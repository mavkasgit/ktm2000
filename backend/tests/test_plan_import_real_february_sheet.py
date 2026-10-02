"""Регрессия #279 на РЕАЛЬНОМ файле заказчика — «Упаковочная карта (план РП)».

Правило из #279 (строка-продолжение с заполненной «Длина, м» входит в группу раскроя)
сторожит синтетический тест в ``test_excel_import.py`` — он и работает в CI. Этот тест
проверяет то же правило на настоящем листе «План февраль 26 02»: там строка 57 несёт
вход 2,7 без количества, из-за чего позиция ``ЮП-2630`` распадалась на две, а вторая
приходила без наименования (``product_name_missing``).

Файл в репозитории не хранится: это данные заказчика объёмом 2,2 МБ. Источники:

* хранилище импорта — ``<STORAGE_ROOT>/imports/<sha256>.xls`` (у нас —
  ``data/storage-dev/imports/f52c4369….xls``, 10 листов, лист 7 — февраль);
* ``GET /api/imports/files/{file_id}/download`` — если строка ``import_files`` жива.

Путь по умолчанию — ``data/fixtures/01-09.2026_01_Упаковочная карта (план РП).xlsx.xls``
от корня репозитория; переопределяется переменной ``KTM_PLAN_FIXTURE_XLS``. Файла нет —
тест скипается с явной причиной, а не притворяется зелёным.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest
from app.seeds.import_templates import IMPORT_TEMPLATES
from app.services.excel_import import parse_factory_plan_workbook

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE = (
    REPO_ROOT / "data" / "fixtures" / "01-09.2026_01_Упаковочная карта (план РП).xlsx.xls"
)
FIXTURE = Path(os.environ.get("KTM_PLAN_FIXTURE_XLS", DEFAULT_FIXTURE))
FEBRUARY_SHEET = "План февраль 26 02"
TEMPLATE_CODE = "upakovochnaya_karta_rp"

pytestmark = pytest.mark.skipif(
    not FIXTURE.exists(),
    reason=(
        f"нет локальной фикстуры заказчика {FIXTURE}; возьмите файл из хранилища импорта "
        "(<STORAGE_ROOT>/imports/<sha256>.xls) или из GET /api/imports/files/{id}/download "
        "и положите по этому пути (см. #279)"
    ),
)


def _column_mapping() -> dict:
    for template in IMPORT_TEMPLATES:
        if template["code"] == TEMPLATE_CODE:
            return template["column_mapping"]
    raise AssertionError(f"шаблон {TEMPLATE_CODE} не найден в сидах")


def _parse_february_sheet():
    from io import BytesIO

    from python_calamine import load_workbook

    content = FIXTURE.read_bytes()
    sheet_names = load_workbook(BytesIO(content)).sheet_names
    sheet_index = sheet_names.index(FEBRUARY_SHEET)
    return parse_factory_plan_workbook(
        content,
        FIXTURE.name,
        sheet_index=sheet_index,
        column_mapping=_column_mapping(),
    )


def test_february_sheet_groups_filled_length_continuation() -> None:
    """Строки 56–57 — одна позиция ``ЮП-2630``: 100 × 2,7 → 100 × 0,9 + 100 × 1,8."""
    parsed = _parse_february_sheet()

    positions = [row for row in parsed.parsed_rows if row.source_sku == "ЮП-2630"]
    assert len(positions) == 1, (
        f"ожидалась одна позиция ЮП-2630, получено {[p.source_row_numbers for p in positions]}"
    )

    position = positions[0]
    assert position.source_row_numbers == [56, 57]
    assert position.input_quantity == Decimal(100)
    assert position.input_dimensions == {"length_mm": 2700}
    assert len(position.outputs) == 2
    assert position.warnings == []


def test_february_sheet_keeps_only_real_file_gap_warning() -> None:
    """Единственный ``product_name_missing`` на листе — строка 66 (дыра самого файла)."""
    parsed = _parse_february_sheet()

    missing = [
        row
        for row in parsed.parsed_rows
        if any("product_name_missing" in warning for warning in row.warnings)
    ]
    assert [row.source_row_numbers for row in missing] == [[66]], (
        "строка 57 (ЮП-2630) не должна терять наименование: она — продолжение группы; "
        "строка 66 (ЮП-3178) — дыра исходного файла, разбирается отдельно в #279"
    )
