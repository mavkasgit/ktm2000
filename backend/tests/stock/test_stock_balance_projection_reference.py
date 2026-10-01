"""Независимый референс «проекция баланса == ledger» по каждому сегменту.

ADR-0055 (тикет #243): ключ ``stock_balances`` — пять осей
``(product_id, location_id, quality_state, dimensions,
completed_operations)``, и сверять проекцию с ledger надо посегментно, а не
суммой по локации. Инвариант S1 в ``tests/test_integrity_invariants.py``
делает то же на стороне SQL; здесь — написанный в тесте пересчёт на Python.

Именно «написанный в тесте» важно: эталон, вынесенный в продовый код,
повторит его же дефект. Референс здесь маленький, детерминированный и
читает ровно две таблицы (``stock_transactions`` и ``stock_balances``).

Сверка идёт по множеству ключей целиком, поэтому ловится всё:
- потерянный в проекции сегмент (ось, пропавшая из GROUP BY/WHERE);
- лишняя строка баланса;
- сегмент, разъехавшийся по ключу при совпадающей сумме;
- задвоение строк в одном сегменте (уникальный индекс обязан быть один);
- ``NULL`` («состояние не зафиксировано») и ``[]`` («прошёл маршрут, операций
  не было») как РАЗНЫЕ группы — иначе слияние двух материально разных
  партий прошло бы молча.

Терминальные секции (``type='terminal'``, «Отправлено») из сверки
исключены: проекция баланс в них не материализует (ADR-0055, #136), но
ledger туда пишет — сверять их значит ловить ложное нарушение на каждом
финальном выпуске.
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product, ProductType
from app.models.route import SectionOperation
from app.models.section import Section
from app.models.user import User, UserRole
from app.services.route_storage_classifier import TERMINAL_TYPES
from app.stock.models import QualityState, Reason, StockBalance, StockTransaction
from app.stock.services import StockCommand, StockCommandService
from tests.test_integrity_invariants import assert_no_invariants_violations

pytestmark = pytest.mark.asyncio

Segment = tuple[int, int, str, str | None, str | None]


# ─── референсный пересчёт ───────────────────────────────────────────────────


def _json_key(value) -> str | None:
    """Слепок jsonb-оси для сравнения ключей.

    ``None`` — SQL NULL и jsonb ``'null'`` (asyncpg декодирует оба в Python
    ``None``), то есть «не зафиксировано»; это отдельный ключ, а не пустой
    список. ``sort_keys`` нужен для dimensions: jsonb не хранит порядок
    свойств, и ``{"length_mm": 2700, "width_mm": 10}`` — тот же ключ, что и
    переставленный.
    """
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _segment(
    product_id: int,
    location_id: int,
    quality_state,
    dimensions,
    completed_operations,
) -> Segment:
    return (
        product_id,
        location_id,
        getattr(quality_state, "value", quality_state),
        _json_key(dimensions),
        _json_key(completed_operations),
    )


async def _terminal_location_ids(session: AsyncSession) -> set[int]:
    return set(
        (await session.scalars(
            select(Section.id).where(Section.type.in_(sorted(TERMINAL_TYPES)))
        )).all()
    )


async def ledger_segments(session: AsyncSession) -> dict[Segment, Decimal]:
    """Сумма ledger по каждому пятиосевому ключу, без нулевых групп.

    Каждая проводка даёт две «стороны»: приход на ``to_location`` и расход с
    ``from_location``, качество берётся со своей стороны — так же, как в
    ``StockProjectionManager._recompute_balance``.
    """
    terminal = await _terminal_location_ids(session)
    rows = (await session.execute(select(
        StockTransaction.product_id,
        StockTransaction.from_location_id,
        StockTransaction.to_location_id,
        StockTransaction.from_quality_state,
        StockTransaction.to_quality_state,
        StockTransaction.dimensions,
        StockTransaction.completed_operations,
        StockTransaction.quantity,
    ))).all()

    agg: dict[Segment, Decimal] = {}
    for product_id, from_loc, to_loc, from_qs, to_qs, dims, ops, qty in rows:
        if to_loc is not None and to_loc not in terminal:
            key = _segment(product_id, to_loc, to_qs, dims, ops)
            agg[key] = agg.get(key, Decimal("0")) + qty
        if from_loc is not None and from_loc not in terminal:
            key = _segment(product_id, from_loc, from_qs, dims, ops)
            agg[key] = agg.get(key, Decimal("0")) - qty
    return {key: net for key, net in agg.items() if net != 0}


async def balance_segments(
    session: AsyncSession,
) -> dict[Segment, tuple[Decimal, int]]:
    """Сумма и число строк проекции по каждому пятиосевому ключу.

    Терминал исключён так же, как в ``ledger_segments``: legacy-строка на
    «Отправлено» существует только до ``rebuild_all_balances`` и в сверку
    оперативных остатков не входит.
    """
    terminal = await _terminal_location_ids(session)
    stmt = select(
        StockBalance.product_id,
        StockBalance.location_id,
        StockBalance.quality_state,
        StockBalance.dimensions,
        StockBalance.completed_operations,
        StockBalance.balance_qty,
    )
    if terminal:
        stmt = stmt.where(StockBalance.location_id.not_in(terminal))
    rows = (await session.execute(stmt)).all()

    out: dict[Segment, tuple[Decimal, int]] = {}
    for product_id, location_id, quality_state, dims, ops, qty in rows:
        key = _segment(product_id, location_id, quality_state, dims, ops)
        total, count = out.get(key, (Decimal("0"), 0))
        out[key] = (total + qty, count + 1)
    return out


async def assert_projection_matches_ledger(
    session: AsyncSession, *, context: str | None = None
) -> None:
    """Проекция обязана совпасть с пересчётом из ledger по каждому сегменту."""
    ledger = await ledger_segments(session)
    balance = await balance_segments(session)

    problems: list[str] = []
    for key in sorted(set(ledger) | set(balance), key=repr):
        expected = ledger.get(key)
        actual = balance.get(key)
        if actual is None:
            problems.append(f"нет строки остатка: сегмент {key}, ledger={expected}")
        elif expected is None:
            problems.append(
                f"лишняя строка остатка: сегмент {key}, balance={actual[0]}, "
                f"rows={actual[1]}"
            )
        elif actual != (expected, 1):
            problems.append(
                f"сегмент {key}: ledger={expected}, balance={actual[0]}, "
                f"rows={actual[1]}"
            )

    if problems:
        prefix = f"[{context}] " if context else ""
        raise AssertionError(
            prefix + "пересчёт из ledger != баланс по сегментам:\n  "
            + "\n  ".join(problems)
        )


# ─── фикстуры данных ────────────────────────────────────────────────────────


async def _make_user(session: AsyncSession, username: str) -> User:
    user = User(
        username=username,
        email=f"{username}@local",
        full_name="Projection Ref",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_section(
    session: AsyncSession, *, code: str, loc_type: str
) -> Section:
    section = Section(
        code=code, name=code, type=loc_type, is_active=True, sort_order=0,
    )
    session.add(section)
    await session.flush()
    return section


async def _make_product(session: AsyncSession, sku: str) -> Product:
    product = Product(
        sku=sku, name=sku, type=ProductType.finished_good, unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.flush()
    return product


async def _register_operations(session: AsyncSession, section: Section,
                               *codes: str) -> None:
    """Справочник операций: C3 требует каждый код в ledger знать секциями."""
    for idx, code in enumerate(codes, start=1):
        session.add(SectionOperation(
            section_id=section.id,
            operation_code=code,
            operation_name=code,
            sort_order=idx,
        ))
    await session.flush()


async def _record(session: AsyncSession, **kwargs) -> None:
    cmd = StockCommand(**kwargs)
    await StockCommandService().record(session, cmd)
    await session.commit()


# ─── тесты ───────────────────────────────────────────────────────────────────


async def test_reference_recompute_matches_on_all_axis_combinations(
    session: AsyncSession,
) -> None:
    """Референс совпадает с проекцией на всех комбинациях осей.

    Один артикул, пять групп на одном складе: ``NULL``, ``[]``, список
    операций, тот же список с габаритом и другой список. Рядом — группа
    брака (ось качества), приход на терминал (баланс не материализуется) и
    локация, чьи приход и расход взаимно погасились (строки быть не должно).
    """
    user = await _make_user(session, "proj-ref")
    product = await _make_product(session, "PROJ-REF")
    raw = await _make_section(session, code="PROJ-RAW", loc_type="raw_stock")
    scrap = await _make_section(session, code="PROJ-SCR", loc_type="scrap")
    terminal = await _make_section(session, code="PROJ-TERM", loc_type="terminal")
    other = await _make_section(session, code="PROJ-OTH", loc_type="raw_stock")
    await _register_operations(session, raw, "OP_A", "OP_B")

    dims = {"length_mm": 2700}

    # Пять групп на одном (артикул, локация, качество).
    await _record(session, product_id=product.id, to_location_id=raw.id,
                   quantity=Decimal("100"), reason=Reason.MANUAL_IN,
                   completed_operations=None, created_by=user.id)
    await _record(session, product_id=product.id, to_location_id=raw.id,
                   quantity=Decimal("50"), reason=Reason.MANUAL_IN,
                   completed_operations=[], created_by=user.id)
    await _record(session, product_id=product.id, to_location_id=raw.id,
                   quantity=Decimal("30"), reason=Reason.MANUAL_IN,
                   completed_operations=["OP_A"], created_by=user.id)
    await _record(session, product_id=product.id, to_location_id=raw.id,
                   quantity=Decimal("20"), reason=Reason.MANUAL_IN,
                   dimensions=dims, completed_operations=["OP_A"],
                   created_by=user.id)
    await _record(session, product_id=product.id, to_location_id=raw.id,
                   quantity=Decimal("7"), reason=Reason.MANUAL_IN,
                   completed_operations=["OP_B"], created_by=user.id)

    # Расход из NULL-группы: 100 → 60, остальные группы не тронуты.
    await _record(session, product_id=product.id, from_location_id=raw.id,
                   quantity=Decimal("40"), reason=Reason.MANUAL_OUT,
                   completed_operations=None, created_by=user.id)

    # Ось качества: брак уходит на scrap-локацию со своим quality_state.
    await _record(session, product_id=product.id, from_location_id=raw.id,
                   to_location_id=scrap.id, quantity=Decimal("13"),
                   reason=Reason.SCRAP, to_quality_state=QualityState.SCRAP,
                   completed_operations=[], created_by=user.id)

    # Терминал: ledger пишет, проекция — нет.
    await _record(session, product_id=product.id, to_location_id=terminal.id,
                   quantity=Decimal("11"), reason=Reason.MANUAL_IN,
                   completed_operations=None, created_by=user.id)

    # Приход и расход в ноль: строки баланса не остаётся.
    await _record(session, product_id=product.id, to_location_id=other.id,
                   quantity=Decimal("40"), reason=Reason.MANUAL_IN,
                   completed_operations=None, created_by=user.id)
    await _record(session, product_id=product.id, from_location_id=other.id,
                   quantity=Decimal("40"), reason=Reason.MANUAL_OUT,
                   completed_operations=None, created_by=user.id)

    balance = await balance_segments(session)
    raw_groups = {
        key: value for key, value in balance.items() if key[1] == raw.id
    }
    assert len(raw_groups) == 5, (
        "на одном складе обязаны быть пять разных сегментов одного артикула: "
        f"получено {sorted(raw_groups)}"
    )
    assert {key[3] for key in raw_groups} == {None, _json_key(dims)}
    assert {key[4] for key in raw_groups} == {
        None, _json_key([]), _json_key(["OP_A"]), _json_key(["OP_B"]),
    }
    # NULL и [] — разные группы: 60 и 37, а не 97 одной суммой.
    assert balance[_segment(product.id, raw.id, QualityState.GOOD, None, None)][0] == Decimal("60")
    assert balance[_segment(product.id, raw.id, QualityState.GOOD, None, [])][0] == Decimal("37")

    # Брак и терминал.
    assert balance[_segment(product.id, scrap.id, QualityState.SCRAP, None, [])][0] == Decimal("13")
    assert not [key for key in balance if key[1] == terminal.id]
    # Нулевая группа не оставила ни строки, ни ожидания в ledger.
    assert not [key for key in balance if key[1] == other.id]
    assert not [key for key in await ledger_segments(session) if key[1] == other.id]

    await assert_projection_matches_ledger(session, context="all-axes")
    await assert_no_invariants_violations(session, context="all-axes")


async def test_reference_recompute_matches_on_demo_data(session: AsyncSession) -> None:
    """Референс совпадает на демо-сидере при нескольких группах одного SKU."""
    from app.seeds.seeders import demo_production_seeder
    from app.seeds.seeders.spgs_seeder import seed_spgs
    from tests.test_prep_stock_seed import (
        _build_route_with_sections,
        _seed_default_sections,
        _spg_defs,
    )

    user = await _make_user(session, "proj-ref-demo")
    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, _spg_defs(), sections_map)
    await session.commit()
    await _build_route_with_sections(
        session,
        route_code="dynamic_packaging_map_rp",
        sections=[
            ("WH", "Склад сырья", "raw_stock", False),
            ("DRILLING", "Сверловка", "production", True),
            ("PRESSING", "Пресс", "production", True),
            ("SHOT_BLAST", "Дробеструй", "production", True),
            ("WIP_WH", "Склад пф", "wip_stock", False),
        ],
    )
    stats = await demo_production_seeder.seed_demo_production(session)
    await session.commit()
    assert stats["remainders"] >= 1, "демо-сидер обязан положить остатки"

    # Вторая группа того же артикула на той же локации: признак противоположный
    # уже лежащему, поэтому слияние сразу было бы видно по сумме.
    seeded = (await session.execute(
        select(StockBalance).order_by(StockBalance.id).limit(1)
    )).scalar_one_or_none()
    assert seeded is not None, "после сида должен быть хотя бы один сегмент"
    opposite = None if seeded.completed_operations is not None else []
    await _record(
        session,
        product_id=seeded.product_id,
        to_location_id=seeded.location_id,
        quantity=Decimal("3"),
        reason=Reason.MANUAL_IN,
        completed_operations=opposite,
        created_by=user.id,
    )

    groups = {
        key for key in await balance_segments(session)
        if key[0] == seeded.product_id and key[1] == seeded.location_id
    }
    assert len(groups) >= 2, (
        f"у {seeded.product_id} на локации {seeded.location_id} должна быть "
        f"вторая группа операций, получено {sorted(groups, key=repr)}"
    )

    await assert_projection_matches_ledger(session, context="demo-data")
    await assert_no_invariants_violations(session, context="demo-data")


async def test_reference_detects_lost_segment(session: AsyncSession) -> None:
    """Референс обязан ругаться на потерянный и на испорченный сегмент.

    Контроль «тест не зелёный сам по себе»: сверка ловит и неверную сумму
    (порча строки), и полное отсутствие строки (ось, пропавшая из проекции).
    """
    user = await _make_user(session, "proj-ref-neg")
    product = await _make_product(session, "PROJ-NEG")
    raw = await _make_section(session, code="PROJ-NEG-RAW", loc_type="raw_stock")
    await _register_operations(session, raw, "OP_A")

    await _record(session, product_id=product.id, to_location_id=raw.id,
                   quantity=Decimal("10"), reason=Reason.MANUAL_IN,
                   completed_operations=None, created_by=user.id)
    await _record(session, product_id=product.id, to_location_id=raw.id,
                   quantity=Decimal("5"), reason=Reason.MANUAL_IN,
                   completed_operations=["OP_A"], created_by=user.id)
    await assert_projection_matches_ledger(session, context="negative-setup")

    ops_key = _segment(product.id, raw.id, QualityState.GOOD, None, ["OP_A"])
    row = (await session.execute(
        select(StockBalance).where(
            StockBalance.product_id == product.id,
            StockBalance.location_id == raw.id,
            StockBalance.completed_operations.isnot(None),
        )
    )).scalar_one()
    original = row.balance_qty
    assert original == Decimal("5")

    # 1. Сумма разошлась.
    row.balance_qty = original + Decimal("5")
    await session.flush()
    with pytest.raises(AssertionError, match="ledger=5"):
        await assert_projection_matches_ledger(session, context="corrupted-qty")
    row.balance_qty = original
    await session.flush()
    await assert_projection_matches_ledger(session, context="restored-qty")

    # 2. Строки сегмента нет вовсе — тот случай, который не видит
    #    односторонний LEFT JOIN от stock_balances.
    assert ops_key in await balance_segments(session)
    await session.delete(row)
    await session.flush()
    with pytest.raises(AssertionError, match="нет строки остатка"):
        await assert_projection_matches_ledger(session, context="lost-segment")

    session.add(StockBalance(
        product_id=product.id,
        location_id=raw.id,
        quality_state=QualityState.GOOD,
        dimensions=None,
        completed_operations=["OP_A"],
        balance_qty=original,
    ))
    await session.flush()
    await assert_projection_matches_ledger(session, context="restored-segment")
    await assert_no_invariants_violations(session, context="negative-control")
