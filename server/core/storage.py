"""Хранение загруженных изображений на диске.

Файлы получают случайные имена (UUID4), исходное имя не используется.
Запись идёт во временный файл с последующим переименованием, чтобы при
обрыве процесса не оставалось «полуфайлов». Чтение защищено от выхода
за пределы каталога функцией ``safe_join``.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from .security import safe_join

# Расширения ограничены белым списком, MIME-тип задаётся явно:
# полагаться на реестр Windows в mimetypes нельзя (там нет webp).
IMAGE_MIME_TYPES: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}

STATIC_MIME_TYPES: dict[str, str] = {
    "html": "text/html; charset=utf-8",
    "css": "text/css; charset=utf-8",
    "js": "text/javascript; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "svg": "image/svg+xml",
    "ico": "image/x-icon",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "woff2": "font/woff2",
}


def content_type_for(name: str) -> str:
    """Определяет MIME-тип по расширению файла.

    Args:
        name: Имя файла.

    Returns:
        MIME-тип или ``application/octet-stream``.
    """
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return STATIC_MIME_TYPES.get(extension, "application/octet-stream")


class Storage:
    """Кладёт файлы под случайными именами и отдаёт их обратно.

    Attributes:
        root: Каталог для загруженных изображений.
    """

    def __init__(self, root: Path):
        """Создаёт каталог, если его ещё нет.

        Args:
            root: Путь к каталогу загрузок.
        """
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, extension: str) -> str:
        """Сохраняет данные и возвращает сгенерированное имя файла.

        Args:
            data: Содержимое изображения.
            extension: Расширение без точки (jpg, png, gif, webp).

        Returns:
            Имя файла вида ``<uuid>.<ext>``.

        Raises:
            ValueError: если расширение не входит в белый список.
        """
        if extension not in IMAGE_MIME_TYPES:
            raise ValueError(f"Неподдерживаемое расширение: {extension}")
        filename = f"{uuid.uuid4().hex}.{extension}"
        path = self.root / filename
        # Запись во временный файл и переименование исключают появление
        # «полуфайла», если процесс прервётся посередине.
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(data)
        temporary.replace(path)
        return filename

    def read(self, name: str) -> tuple[bytes, str] | None:
        """Читает файл по имени.

        Args:
            name: Имя файла без каталога.

        Returns:
            Пару «данные, MIME-тип» или None, если файла нет либо имя
            недопустимо.
        """
        path = safe_join(self.root, name)
        if path is None or not path.is_file():
            return None
        return path.read_bytes(), content_type_for(name)

    def delete(self, name: str) -> None:
        """Удаляет файл, игнорируя ошибки (файла может уже не быть).

        Args:
            name: Имя файла без каталога.
        """
        path = safe_join(self.root, name)
        if path is not None and path.is_file():
            try:
                path.unlink()
            except OSError:
                pass
