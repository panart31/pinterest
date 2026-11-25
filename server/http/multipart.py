"""Разбор тела multipart/form-data (RFC 7578).

Формат: части разделяются строкой ``--boundary``; каждая часть состоит
из блока заголовков, пустой строки и данных. Разбор ведётся по байтам,
поэтому бинарные файлы не портятся. Дополнительно поддерживается
расширенное имя файла ``filename*=UTF-8''...``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .request import percent_decode


class MultipartError(ValueError):
    """Тело запроса не является корректным multipart/form-data."""


@dataclass(frozen=True)
class Part:
    """Одна часть multipart-тела.

    Attributes:
        name: Имя поля формы.
        filename: Исходное имя файла или None для обычного поля.
        content_type: MIME-тип части.
        data: Содержимое части в байтах.
    """

    name: str
    filename: str | None
    content_type: str
    data: bytes


def _split_parameters(value: str) -> tuple[str, dict[str, str]]:
    """Делит значение заголовка на основное и параметры ``key=value``.

    Параметры могут содержать точку с запятой внутри кавычек, поэтому
    используется простой автомат, а не ``split(';')``.

    Args:
        value: Значение заголовка Content-Disposition или Content-Type.

    Returns:
        Пару «основное значение (в нижнем регистре), словарь параметров».
    """
    chunks: list[str] = []
    current: list[str] = []
    in_quotes = False
    for char in value:
        if char == '"':
            in_quotes = not in_quotes
            current.append(char)
        elif char == ";" and not in_quotes:
            chunks.append("".join(current))
            current = []
        else:
            current.append(char)
    chunks.append("".join(current))

    main = chunks[0].strip().lower()
    params: dict[str, str] = {}
    for chunk in chunks[1:]:
        key, sep, raw = chunk.strip().partition("=")
        if not sep:
            continue
        raw = raw.strip()
        if len(raw) >= 2 and raw[0] == raw[-1] == '"':
            raw = raw[1:-1]
        params[key.strip().lower()] = raw
    return main, params


def boundary_from_content_type(content_type: str) -> str:
    """Извлекает boundary из Content-Type.

    Args:
        content_type: Значение заголовка, например
            ``multipart/form-data; boundary=----Mosaic``.

    Returns:
        Строка boundary.

    Raises:
        MultipartError: если тип не multipart или boundary отсутствует
            или слишком длинный.
    """
    main, params = _split_parameters(content_type)
    if main != "multipart/form-data":
        raise MultipartError("Ожидался Content-Type multipart/form-data")
    boundary = params.get("boundary", "")
    if not boundary:
        raise MultipartError("В Content-Type отсутствует boundary")
    if len(boundary) > 70 or "\r" in boundary or "\n" in boundary:
        raise MultipartError("Некорректный boundary")
    return boundary


def _decode_filename(raw: str) -> str:
    """Поддерживает расширенную форму ``filename*=UTF-8''имя``.

    Args:
        raw: Значение параметра filename.

    Returns:
        Декодированное имя файла.
    """
    if "''" in raw:
        charset, _, encoded = raw.partition("''")
        if charset.lower() in ("utf-8", "utf8"):
            return percent_decode(encoded)
    return raw


def _parse_part_headers(block: bytes) -> dict[str, str]:
    """Разбирает заголовки одной части.

    Args:
        block: Байты блока заголовков.

    Returns:
        Словарь с именами в нижнем регистре.

    Raises:
        MultipartError: если строка не содержит двоеточия.
    """
    headers: dict[str, str] = {}
    try:
        text = block.decode("utf-8")
    except UnicodeDecodeError:
        text = block.decode("iso-8859-1")
    for line in text.split("\r\n"):
        if not line:
            continue
        name, sep, value = line.partition(":")
        if not sep:
            raise MultipartError("Некорректный заголовок части")
        headers[name.strip().lower()] = value.strip()
    return headers


def parse_multipart(body: bytes, content_type: str,
                    max_parts: int = 32) -> list[Part]:
    """Разбирает тело multipart/form-data на список частей.

    Args:
        body: Тело запроса целиком.
        content_type: Заголовок Content-Type с boundary.
        max_parts: Максимальное число частей (защита от перегрузки).

    Returns:
        Список частей в порядке следования.

    Raises:
        MultipartError: если тело повреждено, boundary нет или частей
            слишком много.
    """
    boundary = boundary_from_content_type(content_type)
    delimiter = b"--" + boundary.encode("latin-1")

    segments = body.split(delimiter)
    if len(segments) < 3:
        raise MultipartError("Тело не содержит ни одной части")

    parts: list[Part] = []
    # Первый сегмент — preamble, последний — epilogue после закрывающего --.
    for segment in segments[1:-1]:
        if segment.startswith(b"--"):
            break
        if not segment.startswith(b"\r\n"):
            raise MultipartError("Часть не начинается с перевода строки")
        segment = segment[2:]
        if segment.endswith(b"\r\n"):
            segment = segment[:-2]

        header_block, sep, data = segment.partition(b"\r\n\r\n")
        if not sep:
            raise MultipartError("В части нет пустой строки после заголовков")
        headers = _parse_part_headers(header_block)

        disposition = headers.get("content-disposition", "")
        _, params = _split_parameters(disposition)
        name = params.get("name")
        if not name:
            raise MultipartError("В части отсутствует параметр name")
        filename = params.get("filename")
        if filename is not None:
            filename = _decode_filename(filename)

        parts.append(Part(
            name=name,
            filename=filename,
            content_type=headers.get("content-type", "application/octet-stream"),
            data=data,
        ))
        if len(parts) > max_parts:
            raise MultipartError("Слишком много частей в форме")

    if not parts:
        raise MultipartError("Форма не содержит полей")
    return parts


def find_part(parts: list[Part], name: str) -> Part | None:
    """Возвращает первую часть с указанным именем поля.

    Args:
        parts: Результат ``parse_multipart``.
        name: Имя поля формы.

    Returns:
        Часть или None, если такого поля нет.
    """
    for part in parts:
        if part.name == name:
            return part
    return None
