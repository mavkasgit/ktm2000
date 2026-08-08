"""Юнит-тесты table-driven upsert хелпера (ADR-0010, Seam 2).

Проверяют внешний контракт `upsert_by_code`:
- insert новой строки и update существующей;
- `field_map` (передача полей из данных в ORM-модель);
- `resolve=`-хук для FK-резолва и производных полей;
- составной ключ (SectionOperation: (section_id, operation_code));
- возврат `dict[key, Model]` с корректными ключами;
- idempotency: повторный вызов не создаёт дублей.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models.route import SectionOperation
from app.models.section import Section
from app.seeds.upsert import upsert_by_code


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


@pytest.mark.asyncio
async def test_insert_new_and_update_existing(session) -> None:
    rows = [
        {"code": "SEC-A", "name": "Секция A", "sort_order": 10, "type": "production"},
        {"code": "SEC-B", "name": "Секция B", "sort_order": 20, "type": "wip_stock"},
    ]
    field_map = {"code": "code", "name": "name", "sort_order": "sort_order", "type": "type"}

    result = await upsert_by_code(session, Section, rows, key_field="code", field_map=field_map)

    assert set(result) == {"SEC-A", "SEC-B"}
    assert await _count(session, Section) == 2

    # Обновление существующей + вставка новой
    rows2 = [
        {"code": "SEC-A", "name": "Секция A v2", "sort_order": 15, "type": "production"},
        {"code": "SEC-C", "name": "Секция C", "sort_order": 30, "type": "production"},
    ]
    result2 = await upsert_by_code(session, Section, rows2, key_field="code", field_map=field_map)

    assert set(result2) == {"SEC-A", "SEC-C"}
    assert await _count(session, Section) == 3

    a = await session.scalar(select(Section).where(Section.code == "SEC-A"))
    assert a is not None
    assert a.name == "Секция A v2"
    assert a.sort_order == 15


@pytest.mark.asyncio
async def test_field_map_passes_selected_fields(session) -> None:
    rows = [{"code": "SEC-D", "name": "Секция D", "sort_order": 40, "type": "production"}]
    field_map = {"code": "code", "name": "name"}

    result = await upsert_by_code(session, Section, rows, key_field="code", field_map=field_map)

    d = result["SEC-D"]
    # Не-mapped поля остаются дефолтными
    assert d.sort_order == 0
    assert d.type == "production"


@pytest.mark.asyncio
async def test_resolve_hook_for_fk(session) -> None:
    section = Section(code="SEC-FK", name="Секция FK", sort_order=10, type="production")
    session.add(section)
    await session.flush()

    op_rows = [
        {"operation_code": "OP_1", "operation_name": "Операция 1"},
    ]
    field_map = {"operation_code": "operation_code", "operation_name": "operation_name"}

    def resolve(_row) -> dict:
        return {"section_id": section.id}

    result = await upsert_by_code(
        session,
        SectionOperation,
        op_rows,
        key_field=("section_id", "operation_code"),
        field_map=field_map,
        resolve=resolve,
    )

    key = (section.id, "OP_1")
    assert set(result) == {key}
    assert result[key].operation_name == "Операция 1"


@pytest.mark.asyncio
async def test_composite_key_and_transforms_dimensions(session) -> None:
    section = Section(code="SEC-CK", name="Секция CK", sort_order=10, type="production")
    session.add(section)
    await session.flush()

    op_rows = [
        {"operation_code": "SAW", "operation_name": "Резка"},
        {"operation_code": "PACK", "operation_name": "Упаковка"},
    ]
    field_map = {"operation_code": "operation_code", "operation_name": "operation_name"}

    def resolve(row) -> dict:
        return {
            "section_id": section.id,
            "transforms_dimensions": row["operation_code"] == "SAW",
        }

    result = await upsert_by_code(
        session,
        SectionOperation,
        op_rows,
        key_field=("section_id", "operation_code"),
        field_map=field_map,
        resolve=resolve,
    )

    assert set(result) == {(section.id, "SAW"), (section.id, "PACK")}
    assert result[(section.id, "SAW")].transforms_dimensions is True
    assert result[(section.id, "PACK")].transforms_dimensions is False


@pytest.mark.asyncio
async def test_idempotent_second_call_no_duplicates(session) -> None:
    rows = [
        {"code": "SEC-I", "name": "Секция I", "sort_order": 10, "type": "production"},
    ]
    field_map = {"code": "code", "name": "name", "sort_order": "sort_order", "type": "type"}

    await upsert_by_code(session, Section, rows, key_field="code", field_map=field_map)
    result2 = await upsert_by_code(session, Section, rows, key_field="code", field_map=field_map)

    assert await _count(session, Section) == 1
    assert set(result2) == {"SEC-I"}
    # Существующая запись обновлена, не создана заново
    i = await session.scalar(select(Section).where(Section.code == "SEC-I"))
    assert i is not None
    assert i.name == "Секция I"
