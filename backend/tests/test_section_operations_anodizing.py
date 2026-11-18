"""T-378: операции анодирования — коды веера ClassicELOX и ``updated_at``.

Спека: ``ekranchik-modern/docs/specs/0003-color-dictionary-and-third-party.md``.

Шов — справочник операций участка в БД после сида (``POST /api/routes-seed``):
его читает синк цветов Экранчика, и он же питает выбор операции строки плана.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.models.route import SectionOperation
from app.models.section import Section
from sqlalchemy import func, select, update

from tests.test_routes_seed import _seed_default_sections

#: Двенадцать цветов веера: код операции, название, hex (T-378).
FAN_COLORS: list[tuple[str, str, str]] = [
    ("C0", "Серебро", "#C2CAD3"),
    ("C35", "Чёрный", "#4E4E52"),
    ("S120-0", "Золото", "#E1DDB0"),
    ("S120-2", "Старое золото", "#AD9E77"),
    ("C31", "Светлая шампань", "#CFD4D5"),
    ("C32", "Тёмная шампань", "#AEA895"),
    ("C33", "Светлая бронза", "#716C62"),
    ("C34", "Тёмная бронза", "#595655"),
    ("C41", "Медь", "#A0837E"),
    ("C44", "Тёмная медь", "#715C5F"),
    ("C51", "Нержавеющая сталь", "#A9968E"),
    ("C54", "Тёмный титан", "#766D6D"),
]

#: Старые операции остаются на месте: их коды не переименовываются (T-378).
LEGACY_CODES = {
    "ANOD_01",
    "ANOD_02",
    "ANOD_03",
    "ANOD_05",
    "ANOD_06",
    "ANOD_07",
    "ANOD_08",
}


async def _anodizing_operations(session) -> dict[str, SectionOperation]:
    rows = await session.scalars(
        select(SectionOperation)
        .join(Section, Section.id == SectionOperation.section_id)
        .where(Section.code == "ANODIZING")
    )
    return {op.operation_code: op for op in rows}


async def _seed_operations(client) -> None:
    response = await client.post("/api/routes-seed")
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_updated_at_is_filled_and_refreshes_on_edit(client, session) -> None:
    """Метка изменения операции заполнена, при чтении не меняется, при правке — обновляется.

    Синк цветов решает «чья правка новее» по этой метке, поэтому:
    - она есть у каждой операции сразу после создания;
    - чтение её не двигает;
    - любая правка операции делает её свежее прежней.
    """
    section = Section(
        code="ANODIZING",
        name="Анодирование",
        sort_order=50,
        type="production",
        is_active=True,
    )
    session.add(section)
    await session.flush()
    operation = SectionOperation(
        section_id=section.id,
        operation_code="C31",
        operation_name="Светлая шампань",
        group_code="ANODIZING",
        group_name="Анодирование",
        icon_color="#CFD4D5",
    )
    session.add(operation)
    await session.commit()
    await session.refresh(operation)

    created_stamp = operation.updated_at
    assert created_stamp is not None

    # Чтение метку не двигает.
    read_back = await session.scalar(
        select(SectionOperation.updated_at).where(SectionOperation.id == operation.id)
    )
    assert read_back == created_stamp

    # Старая метка — как будто операцию правили давно; правка обязана её обновить.
    stale = datetime(2000, 1, 1, tzinfo=UTC)
    await session.execute(
        update(SectionOperation)
        .where(SectionOperation.id == operation.id)
        .values(updated_at=stale)
    )
    await session.commit()
    await session.refresh(operation)
    assert operation.updated_at == stale

    operation.operation_name = "Светлая шампань, матовая"
    await session.commit()
    await session.refresh(operation)

    assert operation.updated_at is not None
    assert operation.updated_at > stale, "правка операции обязана обновить updated_at"


@pytest.mark.asyncio
async def test_seed_creates_the_fan_codes_and_keeps_legacy_ones(
    client, session
) -> None:
    """Сид заводит 12 цветов веера прямыми кодами и не трогает старые ANOD_0x."""
    await _seed_default_sections(session)
    await _seed_operations(client)

    operations = await _anodizing_operations(session)

    for code, name, icon_color in FAN_COLORS:
        operation = operations.get(code)
        assert operation is not None, f"операция {code} не заведена сидом"
        assert operation.operation_name == name
        assert operation.icon_color == icon_color
        assert operation.group_code == "ANODIZING"

    assert set(operations) >= LEGACY_CODES, "старые операции ANOD_0x исчезли из сида"
    assert operations["ANOD_01"].operation_name == "Серебро"
    assert operations["ANOD_06"].operation_name == "Шампань"
    assert "ANOD_04" not in operations

    # (section_id, operation_code) уникален: повторный сид не плодит дублей.
    await _seed_operations(client)
    duplicates = await session.execute(
        select(SectionOperation.operation_code)
        .join(Section, Section.id == SectionOperation.section_id)
        .where(Section.code == "ANODIZING")
        .group_by(SectionOperation.operation_code)
        .having(func.count() > 1)
    )
    assert duplicates.all() == []
    assert set(await _anodizing_operations(session)) == set(operations)

    # Сид не только заводит, но и обновляет существующие операции: правка
    # справочника руками возвращается к объявленному значению, а не остаётся.
    edited = operations["C31"]
    edited.operation_name = "Светлая шампань, правка руками"
    await session.commit()
    await _seed_operations(client)
    restored = (await _anodizing_operations(session))["C31"]
    await session.refresh(restored)
    assert restored.operation_name == "Светлая шампань"


@pytest.mark.asyncio
async def test_reseed_does_not_make_an_operation_newer(client, session) -> None:
    """Повторный сид не двигает ``updated_at`` неизменившейся операции.

    Метка — аргумент синка «чья правка новее». Если каждый ``db:seed``
    переписывал бы её, синк считал бы справочник KTM свежее любой локальной
    правки в Экранчике и затирал бы её одинаковыми значениями.
    """
    await _seed_default_sections(session)
    await _seed_operations(client)

    stale = datetime(2000, 1, 1, tzinfo=UTC)
    await session.execute(
        update(SectionOperation)
        .where(SectionOperation.operation_code.in_(["C31", "ANOD_06"]))
        .values(updated_at=stale)
    )
    await session.commit()

    await _seed_operations(client)

    reseeded = (await _anodizing_operations(session))["C31"]
    await session.refresh(reseeded)
    assert reseeded.updated_at == stale, "повторный сид не должен двигать updated_at"
