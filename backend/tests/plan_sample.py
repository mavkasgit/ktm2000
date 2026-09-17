"""Сэмпл «Упаковочного плана» для тестов — собирается в памяти.

Историческая фикстура `test.xls` (корень репо) не хранилась в git
(`*.xls` в `.gitignore`), поэтому в чистом клоне тесты падали на
`FileNotFoundError`. Здесь тот же сэмпл строится на лету: матрица
«цвет × пробивка/сверловка × вид продукта» (6 × 4 × 2 = 48 строк),
одна строка — одна позиция (SKU уникален, группировка раскроя не
срабатывает). Шапка — как у настоящего упаковочного плана, чтобы
парсер находил колонки автодетектом (шаблон без column_mapping).

Первый артикул — ЮП-2256 (чёрный, без операции, ГП): на него опирается
регрессия `test_xls_route_selection` про пропуск дробеструя.
"""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

HEADERS = [
    "Артикул",
    "пополнение",
    "Наименование",
    "остатки сырья на КТМ",
    "Цвет",
    "кол-во шт. в 2,7",
    "Длина, м",
    "Пробивка/сверловка",
    "Упаковка",
    "Примечание ",
    "Длина после упак, м",
    "кол-во штук готовой продукции",
    "Запад",
    "Восток",
    "Вид конечного продукта",
]

COLORS = ["черный", "серебро", "золото", "шампань", "медь", "титан"]
OPERATIONS = ["", "окно", "гребенка", "сверло"]
KINDS = ["ГП", "П/ф"]

PACK_GP = (
    "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*30 на пачку из 10 шт"
)
PACK_SPUN = "смотка спанбондом поштучно в пачке 10 штук"

FIRST_SKU = "ЮП-2256"


def build_sample_plan_rows() -> list[list[object]]:
    """Строки плана (без шапки) — по одной на каждую комбинацию матрицы."""
    rows: list[list[object]] = []
    index = 0
    for color in COLORS:
        for operation in OPERATIONS:
            for kind in KINDS:
                index += 1
                sku = FIRST_SKU if index == 1 else f"ЮП-{3000 + index:04d}"
                quantity = 50 + (index % 4) * 50
                is_gp = kind == "ГП"
                rows.append(
                    [
                        sku,
                        "ТЗ",
                        f"Профиль {sku} 2,7 м анод{color} матов",
                        5000,
                        color,
                        quantity,
                        2.7,
                        operation or None,
                        PACK_GP if is_gp else PACK_SPUN,
                        None,
                        2.7,
                        quantity,
                        quantity if is_gp else None,
                        0 if is_gp else quantity,
                        kind,
                    ]
                )
    return rows


def build_sample_plan_workbook(sheet_name: str = "totalplan") -> bytes:
    """Тот же сэмпл как xlsx-байты (3 пустые строки + шапка + данные)."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = sheet_name
    for _ in range(3):
        ws.append([])
    ws.append(list(HEADERS))
    for row in build_sample_plan_rows():
        ws.append(row)
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
