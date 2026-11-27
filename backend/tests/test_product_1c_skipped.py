"""Реестр исключений разбора ОСВ 1С: наполнение (#464).

Проверяют:
- сид идемпотентен: повторный запуск не плодит дубли;
- категории и количества совпадают с решением каталога #461;
- ``name_norm`` хранится в нормализации импорта (``_norm_cell``);
- ручная правка решения не откатывается повторным сидом;
- уникальность кода и требование «хотя бы одно поле» держит база.
"""
from __future__ import annotations

import pytest
from app.models.product_1c_skipped import (
    SKIP_REASON_NO_CATALOG,
    SKIP_REASON_NOT_MES,
    SKIP_REASON_PURCHASED,
    Product1CSkipped,
)
from app.seeds.product_1c_skipped import PRODUCT_1C_SKIPPED
from app.seeds.seeders.product_1c_skipped_seeder import seed_product_1c_skipped
from app.stock.import_1c_osv import _norm_cell
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

EXPECTED_REASONS = {
    SKIP_REASON_NOT_MES: 293,
    SKIP_REASON_PURCHASED: 5,
    SKIP_REASON_NO_CATALOG: 47,
}


async def _counts(db: AsyncSession) -> dict[str, int]:
    rows = (
        await db.execute(
            select(Product1CSkipped.reason, func.count()).group_by(
                Product1CSkipped.reason
            )
        )
    ).all()
    return dict(rows)


async def test_seed_product_1c_skipped_is_idempotent(session: AsyncSession) -> None:
    first = await seed_product_1c_skipped(session)

    assert first == {"created": len(PRODUCT_1C_SKIPPED), "existing": 0}
    assert len(PRODUCT_1C_SKIPPED) == 345

    second = await seed_product_1c_skipped(session)

    assert second == {"created": 0, "existing": 345}
    total = await session.scalar(select(func.count()).select_from(Product1CSkipped))
    assert total == 345


async def test_seed_product_1c_skipped_reasons_and_names(
    session: AsyncSession,
) -> None:
    await seed_product_1c_skipped(session)

    assert await _counts(session) == EXPECTED_REASONS

    rows = (await session.scalars(select(Product1CSkipped))).all()
    assert {row.decided_by for row in rows} == {"каталог"}
    assert all(row.code and row.name_norm and row.note for row in rows)
    # Заметка печатается оператору в предпросмотре: номера задач в ней —
    # служебная ссылка, её место в документации, а не в причине пропуска.
    assert all("#" not in row.note for row in rows)
    # Нормализация — ровно правило импорта, иначе строка 1С не найдётся.
    for row in rows:
        assert row.name_norm == _norm_cell(row.name_norm)


async def test_seed_product_1c_skipped_keeps_human_decision(
    session: AsyncSession,
) -> None:
    await seed_product_1c_skipped(session)
    row = await session.scalar(
        select(Product1CSkipped).where(Product1CSkipped.code == "4196")
    )
    assert row is not None
    row.reason = SKIP_REASON_NO_CATALOG
    row.note = "решили иначе"
    await session.flush()

    result = await seed_product_1c_skipped(session)

    assert result == {"created": 0, "existing": 345}
    assert row.reason == SKIP_REASON_NO_CATALOG
    assert row.note == "решили иначе"


async def test_registry_code_is_unique(session: AsyncSession) -> None:
    session.add(
        Product1CSkipped(code="DUP-464", name_norm="первая", reason="not_mes")
    )
    await session.commit()

    session.add(
        Product1CSkipped(code="DUP-464", name_norm="вторая", reason="purchased")
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_registry_requires_at_least_one_identity(session: AsyncSession) -> None:
    session.add(Product1CSkipped(reason="not_mes"))

    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
