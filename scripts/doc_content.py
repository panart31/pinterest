"""Содержание пояснительной записки: объединение частей и нумерация.

Токены вида {fig:name}, {tab:name} и {lst:name} заменяются на номера
в порядке появления. Благодаря этому ссылки в тексте всегда совпадают
с фактическими подписями.
"""

from __future__ import annotations

import re

from scripts.doc_part1 import BLOCKS as PART1
from scripts.doc_part2 import BLOCKS as PART2
from scripts.doc_part3 import BLOCKS as PART3

PARTS = PART1 + PART2 + PART3
TOKEN = re.compile(r"\{(fig|tab|lst):([a-z0-9_]+)\}")


def build_blocks() -> list[tuple]:
    """Нумерует рисунки, таблицы и листинги и подставляет ссылки."""
    counters = {"fig": 0, "tab": 0, "lst": 0}
    numbers: dict[tuple[str, str], int] = {}

    for block in PARTS:
        kind = block[0]
        if kind == "figure":
            counters["fig"] += 1
            numbers[("fig", block[1])] = counters["fig"]
        elif kind == "table":
            counters["tab"] += 1
            numbers[("tab", block[1])] = counters["tab"]
        elif kind == "listing":
            counters["lst"] += 1
            numbers[("lst", block[1])] = counters["lst"]

    def substitute(text: str) -> str:
        return TOKEN.sub(
            lambda match: str(numbers[(match.group(1), match.group(2))]),
            text)

    result: list[tuple] = []
    for block in PARTS:
        kind = block[0]
        if kind in ("h1", "h2", "h3", "p"):
            result.append((kind, substitute(block[1])))
        elif kind == "ul":
            result.append((kind, [substitute(item) for item in block[1]]))
        elif kind == "figure":
            result.append(("figure", numbers[("fig", block[1])], block[2],
                           substitute(block[3]), block[4]))
        elif kind == "table":
            result.append((
                "table",
                numbers[("tab", block[1])],
                substitute(block[2]),
                block[3],
                [[substitute(cell) for cell in row] for row in block[4]],
                block[5],
            ))
        elif kind == "listing":
            result.append(("listing", numbers[("lst", block[1])],
                           substitute(block[2]), block[3]))
        elif kind == "reference":
            result.append(("reference", substitute(block[1])))
        else:
            raise ValueError(f"Неизвестный блок: {kind}")

    leftovers = [block for block in result
                 if TOKEN.search(str(block))]
    if leftovers:
        raise ValueError(f"Не найдены объекты для ссылок: {leftovers[:3]}")
    return result


BLOCKS = build_blocks()
