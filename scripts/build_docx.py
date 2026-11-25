#!/usr/bin/env python3
"""Сборка пояснительной записки в DOCX по требованиям ГОСТ 7.32.

Документ пересобирается одной командой:
    python scripts/build_docx.py

Форматирование: A4, поля 30/15/20/20 мм, Times New Roman 14,
интервал 1,5, отступ первой строки 1,25 см, нумерация страниц внизу
по центру, титульный лист без номера, оглавление — поле TOC.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from docx import Document  # noqa: E402
from docx.enum.section import WD_ORIENT  # noqa: E402
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL  # noqa: E402
from docx.enum.text import (  # noqa: E402
    WD_ALIGN_PARAGRAPH,
    WD_LINE_SPACING,
    WD_TAB_ALIGNMENT,
    WD_TAB_LEADER,
)
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Cm, Pt, RGBColor  # noqa: E402

from scripts.doc_content import BLOCKS  # noqa: E402

OUTPUT = PROJECT_ROOT / "docs" / "Курсовая_ПЗ.docx"
FONT = "Times New Roman"
MONO_FONT = "Courier New"
INK = RGBColor(0, 0, 0)


# ------------------------------------------------------------------ утилиты
def set_run_font(run, name: str = FONT, size: float = 14,
                 bold: bool | None = None, italic: bool | None = None) -> None:
    """Задаёт шрифт для run, включая кириллический диапазон."""
    run.font.name = name
    run.font.size = Pt(size)
    run.font.color.rgb = INK
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    rpr = run._element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.append(fonts)
    for attribute in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        fonts.set(qn(attribute), name)


def set_paragraph_mark(paragraph, name: str = MONO_FONT,
                       size: float = 9.0) -> None:
    """Задаёт шрифт маркера абзаца.

    Без этого высота строки в листинге определяется шрифтом Normal
    (14 pt), и код выглядит разреженным, хотя интервал объявлен
    одинарным. Маркер 9 pt делает строки компактными.
    """
    ppr = paragraph._p.get_or_add_pPr()
    rpr = OxmlElement("w:rPr")
    fonts = OxmlElement("w:rFonts")
    for attribute in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        fonts.set(qn(attribute), name)
    rpr.append(fonts)
    for tag in ("w:sz", "w:szCs"):
        element = OxmlElement(tag)
        element.set(qn("w:val"), str(int(size * 2)))
        rpr.append(element)
    ppr.append(rpr)


def shade(paragraph, fill: str) -> None:
    """Заливка абзаца (используется для листингов)."""
    ppr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    ppr.append(shd)


def add_field(paragraph, instruction: str) -> None:
    """Вставляет простое поле Word (PAGE, TOC)."""
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)


def add_page_number(section) -> None:
    """Номер страницы в нижнем колонтитуле по центру."""
    footer = section.footer
    paragraph = footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.first_line_indent = Cm(0)
    run = paragraph.add_run()
    set_run_font(run, size=12)
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = "PAGE"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)


def add_toc(document: Document,
            entries: list[tuple[int, str, int]] | None = None) -> None:
    """Вставляет поле оглавления.

    Если передан список ``entries`` (уровень, заголовок, страница), он
    записывается как кэшированный результат поля: оглавление видно сразу,
    а Word при обновлении (F9) пересчитает номера страниц.
    """
    if not entries:
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.first_line_indent = Cm(0)
        fld = OxmlElement("w:fldSimple")
        fld.set(qn("w:instr"), r'TOC \o "1-2" \h \z \u')
        fld.set(qn("w:dirty"), "true")
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = "Оглавление обновляется в Word: выделите поле и нажмите F9."
        run.append(text)
        fld.append(run)
        paragraph._p.append(fld)
    else:
        # Поле из нескольких абзацев: begin/instr/separate, затем записи
        # оглавления и end. Такой вид Word понимает как TOC с результатом.
        first = document.add_paragraph()
        first.paragraph_format.first_line_indent = Cm(0)
        run = first.add_run()
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = r'TOC \o "1-2" \h \z \u'
        separate = OxmlElement("w:fldChar")
        separate.set(qn("w:fldCharType"), "separate")
        run._r.append(begin)
        run._r.append(instr)
        run._r.append(separate)

        for level, title, page in entries:
            entry = document.add_paragraph()
            entry.paragraph_format.first_line_indent = Cm(0)
            entry.paragraph_format.left_indent = Cm(0 if level == 1 else 0.75)
            entry.paragraph_format.space_after = Pt(2)
            entry.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            entry.paragraph_format.tab_stops.add_tab_stop(
                Cm(16.3), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
            entry_run = entry.add_run(f"{title}\t{page}")
            set_run_font(entry_run, size=12, bold=(level == 1))

        last = document.add_paragraph()
        last.paragraph_format.first_line_indent = Cm(0)
        end_run = last.add_run()
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        end_run._r.append(end)

    settings = document.settings.element
    update = OxmlElement("w:updateFields")
    update.set(qn("w:val"), "true")
    settings.append(update)


# ------------------------------------------------------------------ стили
def setup_styles(document: Document) -> None:
    """Настраивает базовые стили документа."""
    normal = document.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(14)
    normal.font.color.rgb = INK
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.first_line_indent = Cm(1.25)
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    rpr = normal.element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.append(fonts)
    for attribute in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        fonts.set(qn(attribute), FONT)

    for name, size, before, after in (("Heading 1", 14, 0, 12),
                                      ("Heading 2", 14, 12, 6),
                                      ("Heading 3", 14, 10, 4)):
        style = document.styles[name]
        style.font.name = FONT
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = INK
        style.paragraph_format.first_line_indent = Cm(1.25)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
        style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        style.paragraph_format.keep_with_next = True
        style.element.get_or_add_rPr()
        rpr = style.element.rPr
        fonts = rpr.find(qn("w:rFonts"))
        if fonts is None:
            fonts = OxmlElement("w:rFonts")
            rpr.append(fonts)
        for attribute in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            fonts.set(qn(attribute), FONT)


def setup_page(document: Document) -> None:
    """А4 и поля по ГОСТ 7.32."""
    section = document.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.left_margin = Cm(3.0)
    section.right_margin = Cm(1.5)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.header_distance = Cm(1.0)
    section.footer_distance = Cm(1.0)
    section.different_first_page_header_footer = True
    add_page_number(section)


# ------------------------------------------------------------------ блоки
def title_page(document: Document) -> None:
    """Титульный лист по шаблону."""
    def line(text: str, *, bold: bool = False, size: float = 14,
             before: float = 0, after: float = 0,
             align=WD_ALIGN_PARAGRAPH.CENTER, italic: bool = False):
        paragraph = document.add_paragraph()
        paragraph.alignment = align
        paragraph.paragraph_format.first_line_indent = Cm(0)
        paragraph.paragraph_format.space_before = Pt(before)
        paragraph.paragraph_format.space_after = Pt(after)
        paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        run = paragraph.add_run(text)
        set_run_font(run, size=size, bold=bold, italic=italic)
        return paragraph

    line("МИНИСТЕРСТВО НАУКИ И ВЫСШЕГО ОБРАЗОВАНИЯ", size=13)
    line("РОССИЙСКОЙ ФЕДЕРАЦИИ", size=13)
    line("Тверской государственный технический университет", size=13)
    line("(ТвГТУ)", size=13)
    line("Кафедра [название кафедры — уточнить]", size=13, before=12)
    line("", before=40)
    line("КУРСОВАЯ РАБОТА", bold=True, size=18)
    line("по дисциплине «Операционные системы и сети»", size=14, before=6)
    line("", before=24)
    line("на тему: «Разработка клиент-серверного приложения", bold=True, size=14)
    line("для публикации изображений и обмена сообщениями", bold=True, size=14)
    line("с собственной реализацией протокола HTTP", bold=True, size=14)
    line("поверх TCP-сокетов»", bold=True, size=14)
    line("", before=36)

    for text in ("Выполнили:", "студенты группы ПИН.РИС-24.06",
                 "Дутикова Ксения Дмитриевна", "Панов Артём Андреевич"):
        line(text, align=WD_ALIGN_PARAGRAPH.RIGHT, size=13)
    line("", before=18)
    line("Проверил:", align=WD_ALIGN_PARAGRAPH.RIGHT, size=13)
    line("Прохныч А. Н.", align=WD_ALIGN_PARAGRAPH.RIGHT, size=13)
    line("", before=140)
    line("Тверь", size=14)
    line("2026", size=14)

    document.add_page_break()


def heading(document: Document, text: str, level: int) -> None:
    """Заголовок раздела или подраздела."""
    style = {1: "Heading 1", 2: "Heading 2", 3: "Heading 3"}[level]
    paragraph = document.add_paragraph(style=style)
    if level == 1:
        paragraph.paragraph_format.page_break_before = True
        paragraph.paragraph_format.space_after = Pt(12)
    run = paragraph.add_run(text.upper() if level == 1 else text)
    set_run_font(run, size=14, bold=True)
    # По ГОСТ заголовок приложения выравнивается по центру.
    if level == 1 and text.upper().startswith("ПРИЛОЖЕНИЕ"):
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.first_line_indent = Cm(0)


def body(document: Document, text: str) -> None:
    """Обычный абзац с отступом первой строки."""
    paragraph = document.add_paragraph()
    run = paragraph.add_run(text)
    set_run_font(run, size=14)


def bullets(document: Document, items: list[str]) -> None:
    """Перечень с маркером-тире по ГОСТ."""
    for index, item in enumerate(items):
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.left_indent = Cm(1.25)
        paragraph.paragraph_format.first_line_indent = Cm(0)
        paragraph.paragraph_format.space_after = Pt(2 if index < len(items) - 1 else 6)
        run = paragraph.add_run("– " + item)
        set_run_font(run, size=14)


def picture(document: Document, path: Path, caption: str,
            width_cm: float) -> None:
    """Рисунок по центру и подпись под ним."""
    if not path.exists():
        print(f"  ! нет файла {path}, рисунок пропущен")
        return
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.first_line_indent = Cm(0)
    paragraph.paragraph_format.space_before = Pt(6)
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.paragraph_format.keep_with_next = True
    paragraph.add_run().add_picture(str(path), width=Cm(width_cm))

    caption_paragraph = document.add_paragraph()
    caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption_paragraph.paragraph_format.first_line_indent = Cm(0)
    caption_paragraph.paragraph_format.space_after = Pt(12)
    caption_paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    run = caption_paragraph.add_run(caption)
    set_run_font(run, size=12)


def table_block(document: Document, number: int, caption: str,
                headers: list[str], rows: list[list[str]],
                widths: list[float] | None) -> None:
    """Таблица с подписью сверху и повторяющейся шапкой."""
    caption_paragraph = document.add_paragraph()
    caption_paragraph.paragraph_format.first_line_indent = Cm(0)
    caption_paragraph.paragraph_format.space_before = Pt(6)
    caption_paragraph.paragraph_format.space_after = Pt(4)
    caption_paragraph.paragraph_format.keep_with_next = True
    run = caption_paragraph.add_run(f"Таблица {number} – {caption}")
    set_run_font(run, size=12)

    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    for index, text in enumerate(headers):
        cell = table.rows[0].cells[index]
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        paragraph = cell.paragraphs[0]
        paragraph.paragraph_format.first_line_indent = Cm(0)
        paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        paragraph.paragraph_format.space_before = Pt(2)
        paragraph.paragraph_format.space_after = Pt(2)
        run = paragraph.add_run(text)
        set_run_font(run, size=12, bold=True)

    for row in rows:
        cells = table.add_row().cells
        for index, text in enumerate(row):
            cell = cells[index]
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.first_line_indent = Cm(0)
            paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            paragraph.paragraph_format.space_before = Pt(2)
            paragraph.paragraph_format.space_after = Pt(2)
            run = paragraph.add_run(text)
            set_run_font(run, size=12)

    if widths:
        # Ширину нужно задать и колонке (w:gridCol), и каждой ячейке (w:tcW):
        # иначе LibreOffice и Word подбирают ширины автоматически и таблица
        # становится вдвое выше из-за узких колонок.
        for index, width in enumerate(widths):
            table.columns[index].width = Cm(width)
            for cell in table.columns[index].cells:
                cell.width = Cm(width)

    # Шапка повторяется на новой странице, строки не разрываются.
    for row_index, row in enumerate(table.rows):
        tr_pr = row._tr.get_or_add_trPr()
        cant_split = OxmlElement("w:cantSplit")
        tr_pr.append(cant_split)
        if row_index == 0:
            header = OxmlElement("w:tblHeader")
            header.set(qn("w:val"), "true")
            tr_pr.append(header)

    spacer = document.add_paragraph()
    spacer.paragraph_format.space_after = Pt(6)
    spacer.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    spacer_run = spacer.add_run("")
    set_run_font(spacer_run, size=6)


def listing_block(document: Document, number: int, caption: str,
                  code: str) -> None:
    """Листинг: подпись, серый фон, Courier New 9, одинарный интервал."""
    caption_paragraph = document.add_paragraph()
    caption_paragraph.paragraph_format.first_line_indent = Cm(0)
    caption_paragraph.paragraph_format.space_before = Pt(6)
    caption_paragraph.paragraph_format.space_after = Pt(3)
    caption_paragraph.paragraph_format.keep_with_next = True
    run = caption_paragraph.add_run(f"Листинг {number} – {caption}")
    set_run_font(run, size=12)

    paragraph = document.add_paragraph()
    # Код не выравнивается по ширине: иначе пробелы растягиваются
    # и листинг читается как «разреженный».
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.paragraph_format.first_line_indent = Cm(0)
    paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(8)
    # Длинный листинг может перейти на следующую страницу: принудительное
    # «не разрывать» оставляло бы полупустые страницы.
    paragraph.paragraph_format.keep_together = False
    shade(paragraph, "F4F2F5")
    set_paragraph_mark(paragraph)
    # Нормализуем переводы строк: python-docx превращает \r в <w:br/>,
    # поэтому \r\n давал бы двойной разрыв и разреженный листинг.
    normalized = code.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    for index, line in enumerate(lines):
        run = paragraph.add_run(line)
        set_run_font(run, name=MONO_FONT, size=9)
        if index < len(lines) - 1:
            run.add_break()


def reference(document: Document, text: str) -> None:
    """Позиция списка литературы с висячим отступом."""
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.first_line_indent = Cm(0)
    paragraph.paragraph_format.left_indent = Cm(0.75)
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    run = paragraph.add_run(text)
    set_run_font(run, size=14)


# ------------------------------------------------------------------ сборка
def build(toc_entries: list[tuple[int, str, int]] | None = None) -> Path:
    document = Document()
    setup_page(document)
    setup_styles(document)

    properties = document.core_properties
    properties.title = ("Разработка клиент-серверного приложения для публикации "
                        "изображений и обмена сообщениями")
    properties.author = "Дутикова К. Д., Панов А. А."
    properties.subject = "Курсовая работа по дисциплине «Операционные системы и сети»"
    properties.comments = "Собрано скриптом scripts/build_docx.py"

    title_page(document)
    toc_title = document.add_paragraph()
    toc_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    toc_title.paragraph_format.first_line_indent = Cm(0)
    toc_title.paragraph_format.space_after = Pt(12)
    toc_title.paragraph_format.keep_with_next = True
    toc_run = toc_title.add_run("СОДЕРЖАНИЕ")
    set_run_font(toc_run, size=14, bold=True)
    add_toc(document, toc_entries)

    for block in BLOCKS:
        kind = block[0]
        if kind == "h1":
            heading(document, block[1], 1)
        elif kind == "h2":
            heading(document, block[1], 2)
        elif kind == "h3":
            heading(document, block[1], 3)
        elif kind == "p":
            body(document, block[1])
        elif kind == "ul":
            bullets(document, block[1])
        elif kind == "figure":
            _, number, relative, caption, width = block
            caption_text = f"Рисунок {number} – {caption}"
            picture(document, PROJECT_ROOT / relative, caption_text, width)
        elif kind == "table":
            _, number, caption, headers, rows, widths = block
            table_block(document, number, caption, headers, rows, widths)
        elif kind == "listing":
            _, number, caption, code = block
            listing_block(document, number, caption, code)
        elif kind == "reference":
            reference(document, block[1])
        else:
            raise ValueError(f"Неизвестный блок: {kind}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document.save(OUTPUT)
    return OUTPUT


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    toc_entries = None
    toc_file = PROJECT_ROOT / "docs" / "toc_pages.json"
    if toc_file.exists():
        try:
            raw = json.loads(toc_file.read_text(encoding="utf-8"))
            toc_entries = [(int(item["level"]), str(item["title"]),
                            int(item["page"])) for item in raw]
        except (ValueError, KeyError, TypeError):
            print("Файл toc_pages.json повреждён — будет пустое поле TOC")
            toc_entries = None

    path = build(toc_entries)
    print(f"Документ собран: {path}")
    print("Откройте его в Word и обновите оглавление (F9), если поле не "
          "обновилось автоматически.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
