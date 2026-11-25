#!/usr/bin/env python3
"""Обновляет кэш оглавления для пояснительной записки.

Скрипт собирает документ, конвертирует его в PDF через LibreOffice,
находит страницы заголовков и записывает docs/toc_pages.json.
Сборщик build_docx.py при следующем запуске подставит эти номера
в поле TOC как кэшированный результат.

Требуется установленный LibreOffice (soffice). Если его нет,
документ собирается с полем без кэша — Word заполнит его по F9.

Запуск:
    python scripts/update_toc.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from docx import Document  # noqa: E402
from pypdf import PdfReader  # noqa: E402

DOCX = PROJECT_ROOT / "docs" / "Курсовая_ПЗ.docx"
TOC_JSON = PROJECT_ROOT / "docs" / "toc_pages.json"
SOFFICE_CANDIDATES = [
    Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
    Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
]


def find_soffice() -> Path | None:
    return next((path for path in SOFFICE_CANDIDATES if path.exists()), None)


def normalize(text: str) -> str:
    """Убирает пробелы и мягкие переносы для поиска заголовка на странице."""
    return re.sub(r"\s+", "", text).replace("\u00ad", "").lower()


def convert_to_pdf(soffice: Path, folder: Path) -> Path:
    subprocess.run(
        [str(soffice), "--headless", "--convert-to", "pdf",
         "--outdir", str(folder), str(DOCX)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return folder / (DOCX.stem + ".pdf")


def collect_headings() -> list[tuple[int, str]]:
    document = Document(DOCX)
    headings: list[tuple[int, str]] = []
    for paragraph in document.paragraphs:
        if paragraph.style.name == "Heading 1":
            headings.append((1, paragraph.text.strip()))
        elif paragraph.style.name == "Heading 2":
            headings.append((2, paragraph.text.strip()))
    return headings


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    soffice = find_soffice()
    if soffice is None:
        print("LibreOffice не найден — пропускаем обновление оглавления")
        return 1

    headings = collect_headings()
    with tempfile.TemporaryDirectory(prefix="mosaic-toc-") as folder:
        pdf_path = convert_to_pdf(soffice, Path(folder))
        reader = PdfReader(str(pdf_path))
        pages = [normalize(page.extract_text() or "") for page in reader.pages]

    entries = []
    start = 2  # титульный лист и само оглавление не учитываем
    for level, title in headings:
        needle = normalize(title)
        page_number = next(
            (index + 1 for index in range(start, len(pages))
             if needle in pages[index]), None)
        if page_number is None:
            print(f"  ! не найден заголовок: {title}")
            continue
        entries.append({"level": level, "title": title, "page": page_number})
        print(f"  {title[:52]:52s} с. {page_number}")

    TOC_JSON.write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"Записано: {TOC_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
