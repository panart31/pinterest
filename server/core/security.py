"""Безопасность: пароли, валидация данных, защита путей, типы изображений.

Модуль не знает ничего о HTTP и БД — это набор чистых функций,
которые удобно покрывать юнит-тестами. Пароли хранятся как PBKDF2-
HMAC-SHA256 с индивидуальной солью; сравнение выполняется за постоянное
время. Имена файлов и пути проверяются отдельно, чтобы исключить
path traversal.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from pathlib import Path

PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
FILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

MIN_PASSWORD = 6
MAX_PASSWORD = 128
MAX_DISPLAY_NAME = 40
DEFAULT_MAX_CAPTION = 500
DEFAULT_MAX_MESSAGE = 2000
DEFAULT_MAX_COMMENT = 500

# Сигнатуры файлов: расширение определяется по содержимому, а не по имени.
_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)
_WEBP_HEAD = b"RIFF"
_WEBP_TAIL = b"WEBP"


class ValidationError(ValueError):
    """Данные не прошли проверку; текст можно показать пользователю."""


def hash_password(password: str) -> tuple[str, str]:
    """Хеширует пароль с новой случайной солью.

    Args:
        password: Пароль в открытом виде.

    Returns:
        Пару (соль, хеш) в hex-виде. Соль уникальна для каждого вызова.
    """
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                PBKDF2_ITERATIONS)
    return salt.hex(), digest.hex()


def burn_password_time(password: str) -> None:
    """Выполняет PBKDF2 с фиктивной солью.

    Вызывается, когда пользователь с таким логином не найден: время
    ответа не должно зависеть от существования учётной записи, иначе
    по задержке можно перебирать логины.

    Args:
        password: Присланный пароль (может быть любым).
    """
    hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                        b"\x00" * SALT_BYTES, PBKDF2_ITERATIONS)


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    """Сравнивает пароль с сохранённым хешем за постоянное время.

    Args:
        password: Введённый пароль.
        salt_hex: Соль из базы в hex-виде.
        hash_hex: Ожидаемый хеш в hex-виде.

    Returns:
        True, если пароль верный; False при неверном пароле или
        повреждённых hex-строках.
    """
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                 PBKDF2_ITERATIONS)
    return hmac.compare_digest(actual, expected)


def clean_text(value: object, *, field: str, max_length: int,
               allow_empty: bool = False) -> str:
    """Убирает управляющие символы и проверяет длину строки.

    Args:
        value: Проверяемое значение.
        field: Название поля для текста ошибки.
        max_length: Максимальная длина после обрезки пробелов.
        allow_empty: Разрешена ли пустая строка.

    Returns:
        Очищенную строку.

    Raises:
        ValidationError: если значение не строка, пустое (при запрете)
            или длиннее лимита.
    """
    if not isinstance(value, str):
        raise ValidationError(f"Поле «{field}» должно быть строкой")
    text = CONTROL_CHARS_RE.sub("", value).strip()
    if not text and not allow_empty:
        raise ValidationError(f"Поле «{field}» не может быть пустым")
    if len(text) > max_length:
        raise ValidationError(
            f"Поле «{field}» длиннее {max_length} символов")
    return text


def validate_username(value: object) -> str:
    """Проверяет логин.

    Args:
        value: Логин из запроса.

    Returns:
        Логин длиной 3–32 символа (латиница, цифры, ``.``, ``-``, ``_``).

    Raises:
        ValidationError: если формат неверен.
    """
    username = clean_text(value, field="логин", max_length=32)
    if not USERNAME_RE.match(username):
        raise ValidationError(
            "Логин должен содержать 3–32 символа: латинские буквы, цифры, "
            "точку, дефис или подчёркивание")
    return username


def validate_password(value: object) -> str:
    """Проверяет длину пароля.

    Args:
        value: Пароль из запроса.

    Returns:
        Пароль без изменений (пробелы не обрезаются).

    Raises:
        ValidationError: если пароль короче 6 или длиннее 128 символов.
    """
    if not isinstance(value, str):
        raise ValidationError("Пароль должен быть строкой")
    if len(value) < MIN_PASSWORD:
        raise ValidationError(f"Пароль должен быть не короче {MIN_PASSWORD} символов")
    if len(value) > MAX_PASSWORD:
        raise ValidationError(f"Пароль должен быть не длиннее {MAX_PASSWORD} символов")
    return value


def validate_display_name(value: object) -> str:
    """Проверяет отображаемое имя.

    Args:
        value: Имя из запроса (кириллица разрешена).

    Returns:
        Очищенную строку до 40 символов.

    Raises:
        ValidationError: если строка пустая или слишком длинная.
    """
    return clean_text(value, field="имя", max_length=MAX_DISPLAY_NAME)


def validate_caption(value: object) -> str:
    """Проверяет подпись к изображению.

    Args:
        value: Подпись; None трактуется как пустая строка.

    Returns:
        Очищенную подпись до 500 символов.

    Raises:
        ValidationError: если подпись длиннее лимита.
    """
    if value is None:
        return ""
    return clean_text(value, field="подпись", max_length=DEFAULT_MAX_CAPTION,
                      allow_empty=True)


def validate_message(value: object) -> str:
    """Проверяет текст сообщения.

    Args:
        value: Текст из запроса.

    Returns:
        Очищенную строку 1–2000 символов.

    Raises:
        ValidationError: если текст пустой или слишком длинный.
    """
    return clean_text(value, field="сообщение", max_length=DEFAULT_MAX_MESSAGE)


def validate_comment(value: object) -> str:
    """Проверяет текст комментария.

    Args:
        value: Текст из запроса.

    Returns:
        Очищенную строку 1–500 символов.

    Raises:
        ValidationError: если текст пустой или слишком длинный.
    """
    return clean_text(value, field="комментарий", max_length=DEFAULT_MAX_COMMENT)


def detect_image_extension(data: bytes) -> str | None:
    """Определяет формат изображения по сигнатуре.

    Проверка по сигнатуре не даёт загрузить исполняемый файл с
    расширением ``.jpg``.

    Args:
        data: Первые байты файла (можно весь файл).

    Returns:
        Расширение без точки (jpg, png, gif, webp) или None.
    """
    if not data:
        return None
    for signature, extension in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return extension
    if len(data) >= 12 and data[:4] == _WEBP_HEAD and data[8:12] == _WEBP_TAIL:
        return "webp"
    return None


def safe_file_name(name: str) -> bool:
    """Проверяет, что имя файла безопасно.

    Args:
        name: Имя без каталога.

    Returns:
        True, если нет разделителей, ``..`` и посторонних символов.
    """
    return bool(FILE_NAME_RE.match(name)) and ".." not in name


def safe_join(base: Path, name: str) -> Path | None:
    """Склеивает каталог и имя файла, не выпуская путь за пределы каталога.

    Args:
        base: Каталог-основа.
        name: Имя файла.

    Returns:
        Абсолютный путь внутри ``base`` или None, если имя подозрительное
        или итоговый путь оказался снаружи (защита от path traversal).
    """
    if not name or not safe_file_name(name):
        return None
    base_resolved = base.resolve()
    candidate = (base_resolved / name).resolve()
    if candidate == base_resolved or base_resolved not in candidate.parents:
        return None
    return candidate
