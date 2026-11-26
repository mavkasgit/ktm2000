"""Синтетический лист ОСВ 1С для тестов импорта остатков.

Шапка — как в реальной выгрузке: «Конечное сальдо» в колонке 10, подзаголовок
«Количество» там же. Один помощник на тесты маркеров (#468) и будущие срезы,
чтобы копии шапки не расходились.
"""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

OSV_HEADER = (
    "Код",
    "Наименование ТМЦ",
    "Ед. изм.",
    "Цена за ед.",
    "Начальное сальдо",
    None,
    "Оборот по дебету",
    None,
    "Оборот по кредиту",
    None,
    "Конечное сальдо",
    None,
)
OSV_SUBHEADER = (
    None,
    None,
    None,
    None,
    "Количество",
    "Стоимость, руб.",
    "Количество",
    "Стоимость, руб.",
    "Количество",
    "Стоимость, руб.",
    "Количество",
    "Стоимость, руб.",
)


def osv_row(code: object, name: object, unit: object, quantity: object) -> list:
    """Строка ОСВ шириной 12 колонок: количество в «Конечном сальдо» (10)."""
    return [code, name, unit, None, None, None, None, None, None, None, quantity, None]


def make_osv_workbook(
    data_rows: list[list],
    *,
    sheet_title: str = "Склад сырой",
    section_header: str = "Завод КТМ СКЛАД СЫРОЙ",
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title
    for row in [
        ["Оборотно-сальдовая ведомость по счету 10"],
        [],
        [section_header],
        [],
        [],
        [],
        [],
        list(OSV_HEADER),
        list(OSV_SUBHEADER),
        *data_rows,
    ]:
        ws.append(row)
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
