"""ADR-0043 / #207: инварианты ``StockCommandService.record()`` для признака
«пройденные операции».

Единственный путь записи в ledger держит три правила:

1. **Форма** — канонический отсортированный список без дублей, ``[]`` ≠ ``None``,
   каждый код существует в справочнике ``section_operations``.
2. **Компенсация зеркалит признак** исходной проводки: не передан — зеркалится
   сам, передан и отличается — отказ.
3. **Плановая проводка не остаётся без признака**: вне плана (ручной приход,
   импорт, сид) ``NULL`` — честное «неизвестно», в плане — признак выводится
   из маршрута позиции либо путь закрыт исключением.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.section import Section
from app.services.material_operations import (
    CompletedOperationsError,
    canonicalize_completed_operations,
)
from app.services.route_storage_classifier import (
    SECTION_TYPE_PRODUCTION,
    SECTION_TYPE_RAW_STOCK,
)
from app.stock import (
    Reason,
    StockCommand,
    StockCommandService,
    StockValidationError,
)
from tests.helpers.completed_operations import build_operation_route


# ─── 1. Форма ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (None, None),
        ([], []),
        (["SHOT"], ["SHOT"]),
        # Канон: сортировка + дедупликация.
        (["SHOT", "ISSUE_RAW", "SHOT"], ["ISSUE_RAW", "SHOT"]),
        # Пробелы по краям не часть кода.
        (["  SHOT "], ["SHOT"]),
    ],
    ids=["none-stays-none", "empty-list-stays-empty", "single", "sorted-deduped", "trimmed"],
)
def test_canonicalize_completed_operations_form(
    values: list[str] | None, expected: list[str] | None
) -> None:
    """Каноническая форма: сортированный список без дублей."""
    assert canonicalize_completed_operations(values) == expected


def test_canonicalize_preserves_empty_list_distinct_from_none() -> None:
    """Пустой список — осмысленное значение, он не схлопывается в ``None``.

    Схлопывание сломало бы зеркало компенсации: откат проводки «материал
    прошёл маршрут, операций не было» записал бы «состояние неизвестно».
    """
    empty = canonicalize_completed_operations([])
    assert empty == []
    assert empty is not None
    assert empty != canonicalize_completed_operations(None)


@pytest.mark.parametrize(
    "values",
    [[1], [None], ["SHOT", 2], ["SHOT", ""], ["   "], [""]],
    ids=["int", "none", "mixed", "empty-string", "blank", "only-empty"],
)
def test_canonicalize_rejects_malformed_elements(values: list) -> None:
    """Не-строки и пустые коды отвергаются: в ledger попадает только список кодов."""
    with pytest.raises(CompletedOperationsError):
        canonicalize_completed_operations(values)


# ─── 2. Компенсация зеркалит признак ─────────────────────────────────────────


async def test_compensation_mirrors_empty_list_of_source(session: AsyncSession) -> None:
    """Компенсация проводки с ``[]`` тоже несёт ``[]``, а не ``None``.

    Маршрут без справочных операций на секциях — плановая проводка пишет
    ``[]``; откат такого материала обязан сохранить это различие.
    """
    fx = await build_operation_route(
        session,
        sku="EMPTYSRC",
        stages=[
            ("Склад сырья", SECTION_TYPE_RAW_STOCK, []),
            ("Пресс", SECTION_TYPE_PRODUCTION, []),
        ],
    )
    press = fx["tasks"][1]
    svc = StockCommandService()
    planned = await svc.record(
        session,
        StockCommand(
            product_id=fx["product"].id,
            to_location_id=press.section_id,
            quantity=Decimal("10"),
            reason=Reason.MANUAL_IN,
            task_id=press.id,
            created_by=fx["user"].id,
        ),
    )
    assert planned.completed_operations == []

    compensation = await svc.record(
        session,
        StockCommand(
            product_id=fx["product"].id,
            from_location_id=press.section_id,
            to_location_id=None,
            quantity=Decimal("10"),
            reason=Reason.MANUAL_IN,
            reverses_id=planned.id,
            created_by=fx["user"].id,
        ),
    )
    assert compensation.completed_operations == []


async def test_compensation_mirrors_null_of_source(session: AsyncSession) -> None:
    """Компенсация внеплановой проводки остаётся ``NULL``.

    ``NULL`` — «состояние неизвестно»; откат ручного прихода не имеет права
    превратить его в «операций не было» (``[]``) или выдумать операции.
    """
    fx = await build_operation_route(
        session,
        sku="NULLSRC",
        stages=[("Пресс", SECTION_TYPE_PRODUCTION, ["PRESS_COMB"])],
    )
    press = fx["tasks"][0]
    svc = StockCommandService()
    source = await svc.record(
        session,
        StockCommand(
            product_id=fx["product"].id,
            to_location_id=press.section_id,
            quantity=Decimal("10"),
            reason=Reason.MANUAL_IN,
            created_by=fx["user"].id,
        ),
    )
    assert source.completed_operations is None

    compensation = await svc.record(
        session,
        StockCommand(
            product_id=fx["product"].id,
            from_location_id=press.section_id,
            to_location_id=None,
            quantity=Decimal("10"),
            reason=Reason.MANUAL_IN,
            reverses_id=source.id,
            created_by=fx["user"].id,
        ),
    )
    assert compensation.completed_operations is None


async def test_compensation_with_different_operations_is_rejected(
    session: AsyncSession,
) -> None:
    """Явно переданный, отличный от исходного признак — отказ, а не тихий дубль."""
    fx = await build_operation_route(
        session,
        sku="MISMATCH",
        stages=[
            ("Склад сырья", SECTION_TYPE_RAW_STOCK, ["ISSUE_RAW"]),
            ("Пресс", SECTION_TYPE_PRODUCTION, ["PRESS_COMB"]),
        ],
    )
    press = fx["tasks"][1]
    svc = StockCommandService()
    planned = await svc.record(
        session,
        StockCommand(
            product_id=fx["product"].id,
            to_location_id=press.section_id,
            quantity=Decimal("10"),
            reason=Reason.MANUAL_IN,
            task_id=press.id,
            created_by=fx["user"].id,
        ),
    )
    assert planned.completed_operations == ["ISSUE_RAW", "PRESS_COMB"]

    with pytest.raises(StockValidationError, match="must mirror completed_operations"):
        await svc.record(
            session,
            StockCommand(
                product_id=fx["product"].id,
                from_location_id=press.section_id,
                to_location_id=None,
                quantity=Decimal("10"),
                reason=Reason.MANUAL_IN,
                completed_operations=["PRESS_COMB"],
                reverses_id=planned.id,
                created_by=fx["user"].id,
            ),
        )


async def test_compensation_may_restate_source_operations(
    session: AsyncSession,
) -> None:
    """Переданный, но РАВНЫЙ исходному признак допустим (канон совпал)."""
    fx = await build_operation_route(
        session,
        sku="SAMEOPS",
        stages=[
            ("Склад сырья", SECTION_TYPE_RAW_STOCK, ["ISSUE_RAW"]),
            ("Пресс", SECTION_TYPE_PRODUCTION, ["PRESS_COMB", "PRESS_WINDOW"]),
        ],
    )
    press = fx["tasks"][1]
    svc = StockCommandService()
    planned = await svc.record(
        session,
        StockCommand(
            product_id=fx["product"].id,
            to_location_id=press.section_id,
            quantity=Decimal("10"),
            reason=Reason.MANUAL_IN,
            task_id=press.id,
            created_by=fx["user"].id,
        ),
    )
    compensation = await svc.record(
        session,
        StockCommand(
            product_id=fx["product"].id,
            from_location_id=press.section_id,
            to_location_id=None,
            quantity=Decimal("10"),
            reason=Reason.MANUAL_IN,
            completed_operations=["PRESS_WINDOW", "PRESS_COMB", "ISSUE_RAW"],
            reverses_id=planned.id,
            created_by=fx["user"].id,
        ),
    )
    assert compensation.completed_operations == ["ISSUE_RAW", "PRESS_COMB", "PRESS_WINDOW"]


# ─── 3. Плановая проводка не остаётся NULL ───────────────────────────────────


async def test_plan_write_without_resolvable_route_is_rejected(
    session: AsyncSession,
) -> None:
    """Плановая проводка, у которой нечего вывести из маршрута, отклоняется.

    Проводка привязана к строке плана, но задания нет — маршрут позиции
    не восстанавливается, и «тихий» ``NULL`` означал бы потерю признака
    в середине маршрута.
    """
    fx = await build_operation_route(
        session,
        sku="NORESOLVE",
        stages=[("Пресс", SECTION_TYPE_PRODUCTION, ["PRESS_COMB"])],
    )
    with pytest.raises(StockValidationError, match="required for plan-driven stock writes"):
        await StockCommandService().record(
            session,
            StockCommand(
                product_id=fx["product"].id,
                to_location_id=fx["sections"][0].id,
                quantity=Decimal("10"),
                reason=Reason.MANUAL_IN,
                section_plan_line_id=fx["plan_lines"][0].id,
                created_by=fx["user"].id,
            ),
        )


async def test_plan_write_without_route_allowed_to_store_null(
    session: AsyncSession,
) -> None:
    """Явное ``allow_unknown_completed_operations`` разрешает записать ``NULL``.

    Это осознанный выход для проводок, чей маршрут не восстановим; по
    умолчанию он закрыт.
    """
    fx = await build_operation_route(
        session,
        sku="ALLOWUNK",
        stages=[("Пресс", SECTION_TYPE_PRODUCTION, ["PRESS_COMB"])],
    )
    tx = await StockCommandService().record(
        session,
        StockCommand(
            product_id=fx["product"].id,
            to_location_id=fx["sections"][0].id,
            quantity=Decimal("10"),
            reason=Reason.MANUAL_IN,
            section_plan_line_id=fx["plan_lines"][0].id,
            allow_unknown_completed_operations=True,
            created_by=fx["user"].id,
        ),
    )
    assert tx.completed_operations is None


async def test_non_plan_write_stores_null(session: AsyncSession) -> None:
    """Внеплановый приход остаётся ``NULL`` — «состояние неизвестно».

    Ручной приход/импорт остатков не имеет маршрута позиции; выдумывать
    для него операции значило бы записать в ledger ложь.
    """
    fx = await build_operation_route(
        session,
        sku="NONPLAN",
        stages=[("Пресс", SECTION_TYPE_PRODUCTION, ["PRESS_COMB"])],
    )
    stock = Section(
        code="NONPLAN-STK",
        name="Stock",
        type=SECTION_TYPE_RAW_STOCK,
        is_active=True,
        sort_order=0,
    )
    session.add(stock)
    await session.flush()

    tx = await StockCommandService().record(
        session,
        StockCommand(
            product_id=fx["product"].id,
            to_location_id=stock.id,
            quantity=Decimal("10"),
            reason=Reason.MANUAL_IN,
            created_by=fx["user"].id,
        ),
    )
    assert tx.completed_operations is None


async def test_plan_write_derives_operations_from_route(
    session: AsyncSession,
) -> None:
    """Плановая проводка без явного признака получает его из маршрута задания."""
    fx = await build_operation_route(
        session,
        sku="DERIVED",
        stages=[
            ("Склад сырья", SECTION_TYPE_RAW_STOCK, ["ISSUE_RAW"]),
            ("Пресс", SECTION_TYPE_PRODUCTION, ["PRESS_COMB", "PRESS_WINDOW"]),
        ],
    )
    press = fx["tasks"][1]
    tx = await StockCommandService().record(
        session,
        StockCommand(
            product_id=fx["product"].id,
            to_location_id=press.section_id,
            quantity=Decimal("10"),
            reason=Reason.MANUAL_IN,
            task_id=press.id,
            created_by=fx["user"].id,
        ),
    )
    assert tx.completed_operations == ["ISSUE_RAW", "PRESS_COMB", "PRESS_WINDOW"]


async def test_unknown_operation_code_is_rejected(session: AsyncSession) -> None:
    """Код, которого нет в справочнике операций секций, в ledger не попадает."""
    fx = await build_operation_route(
        session,
        sku="TYPO",
        stages=[("Пресс", SECTION_TYPE_PRODUCTION, ["PRESS_COMB"])],
    )
    with pytest.raises(StockValidationError, match="unknown operation_code"):
        await StockCommandService().record(
            session,
            StockCommand(
                product_id=fx["product"].id,
                to_location_id=fx["sections"][0].id,
                quantity=Decimal("10"),
                reason=Reason.MANUAL_IN,
                completed_operations=["PRESS_СOMB"],
                created_by=fx["user"].id,
            ),
        )
