"""История импорта остатков: запись, LIFO по складу, гейты, мягкое удаление.

Покрывает решения гриллинга (#232): ADR-0052 п.2/5/7/8, ADR-0053 п.1/4,
плюс гейт роли из ADR-0052 п.6.
"""
from __future__ import annotations

import pytest
from decimal import Decimal
from sqlalchemy import select

from app.models import Product, ProductType, Section
from app.core.security import create_access_token
from app.models.action_journal import Action
from app.models.user import User, UserRole
from app.reversal import errors
from app.reversal.service import reversal_service
from app.stock.import_history import (
    BLOCK_ALREADY_ROLLED_BACK,
    BLOCK_LEGACY_NO_LOCATION,
    BLOCK_NOT_LAST,
    ImportHistoryError,
    assert_rollback_allowed,
    get_batch,
    get_batch_rows,
    hide_batch,
    import_batch_rollback_blockers,
    list_batches,
)
from app.stock.import_models import (
    StockImportBatch,
    StockImportBatchStatus,
    StockImportRowStatus,
)
from app.stock.import_service import RemainderItem, apply_remainders_import
from app.stock.models import Reason, StockTransaction
from app.stock.services import StockCommand, StockCommandService
from tests.test_integrity_invariants import assert_no_invariants_violations


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(subject=user.email)}"}


async def _product(session, sku: str) -> Product:
    product = Product(sku=sku, name=sku, type=ProductType.finished_good,
                      unit="pcs", is_active=True)
    session.add(product)
    await session.commit()
    return product


async def _section(session, code: str) -> Section:
    section = Section(code=code, name=code, type="raw_stock",
                      is_active=True, sort_order=0)
    session.add(section)
    await session.commit()
    return section


def _items(sku: str, quantity: float, row: int = 2, status: str = "valid",
           errors_: list[str] | None = None) -> list[RemainderItem]:
    return [
        RemainderItem(
            source_row_number=row, sku=sku, quantity=quantity, comment=None,
            product_id=None, product_name=None, status=status,
            errors=errors_ or [], raw_values=[sku, str(quantity)],
        )
    ]


async def _import(session, section, items, *, clear_existing: bool = False,
                  user: User | None = None):
    """Прогнать импорт с подстановкой product_id (как это делает сервис)."""
    for item in items:
        product = await session.scalar(select(Product).where(Product.sku == item.sku))
        item.product_id = product.id if product else None
    return await apply_remainders_import(
        session, section.id, items, clear_existing=clear_existing, user=user
    )



# ─── Запись истории (ADR-0052 п.2, п.8) ───────────────────────────────────────


async def test_import_writes_batch_and_rows(session: AsyncSession) -> None:
    """Импорт остатков оставляет в БД батч и строки, а не анонимный узел."""
    product = await _product(session, "HIST-1")
    section = await _section(session, "HIST-LOC-1")

    result = await _import(session, section, _items(product.sku, 5.0))
    await session.commit()

    assert result.batch_id is not None
    batch = await get_batch(session, result.batch_id)
    assert batch.status == StockImportBatchStatus.APPLIED
    assert batch.location_id == section.id
    assert batch.total_rows == 1
    assert batch.imported_rows == 1
    assert batch.skipped_rows == 0

    rows = await get_batch_rows(session, batch.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.status == StockImportRowStatus.VALID.value
    assert row.product_sku == product.sku
    # Строка обязана быть связана с созданной ею проводкой: без связи нельзя
    # ни объяснить пропуск, ни показать блокировку покрытия (ADR-0052 п.8).
    assert row.current_balance is not None


async def test_invalid_row_is_persisted_without_transaction(session: AsyncSession) -> None:
    """Пропущенная строка остаётся в истории с причиной — иначе через неделю
    нельзя ответить «почему по этому артикулу ноль» (ADR-0052 п.8)."""
    section = await _section(session, "HIST-LOC-INV")
    result = await _import(
        session, section, _items("NO-SUCH-SKU", 3.0, status="invalid",
                                errors_=["sku_not_found"]),
    )
    await session.commit()

    batch = await get_batch(session, result.batch_id)
    assert batch.skipped_rows == 1
    rows = await get_batch_rows(session, batch.id)
    assert len(rows) == 1
    assert rows[0].status == StockImportRowStatus.INVALID.value
    assert "sku_not_found" in rows[0].errors
    assert rows[0].current_balance is None


# ─── LIFO по складу (ADR-0053) ───────────────────────────────────────────────


async def test_only_last_batch_of_location_is_rollbackable(session: AsyncSession) -> None:
    """Два батча одного склада: откатывается только последний."""
    product = await _product(session, "HIST-LIFO")
    section = await _section(session, "HIST-LOC-LIFO")

    first = await _import(session, section, _items(product.sku, 5.0))
    second = await _import(session, section, _items(product.sku, 7.0))
    await session.commit()

    first_batch = await get_batch(session, first.batch_id)
    second_batch = await get_batch(session, second.batch_id)
    await assert_rollback_allowed(db=session, batch=second_batch)  # последний — ок
    with pytest.raises(ImportHistoryError) as exc:
        await assert_rollback_allowed(db=session, batch=first_batch)
    assert exc.value.code == BLOCK_NOT_LAST


async def test_lifo_scope_is_per_location(session: AsyncSession) -> None:
    """Импорт на другой склад не делает батч неоткатываемым (ADR-0053 п.1)."""
    product = await _product(session, "HIST-SCOPE")
    loc_a = await _section(session, "HIST-SCOPE-A")
    loc_b = await _section(session, "HIST-SCOPE-B")

    a = await _import(session, loc_a, _items(product.sku, 5.0))
    await _import(session, loc_b, _items(product.sku, 9.0))
    await session.commit()

    # Ба��ч склада A — последний на складе A, несмотря на более новый батч B.
    await assert_rollback_allowed(
        db=session, batch=await get_batch(session, a.batch_id)
    )


async def test_rolled_back_batch_exposes_lifo_blocker(session: AsyncSession) -> None:
    """Откатанный батч помечен и в UI (can_rollback), и в компенсаторе."""
    product = await _product(session, "HIST-RB")
    section = await _section(session, "HIST-LOC-RB")

    result = await _import(session, section, _items(product.sku, 5.0))
    await session.commit()

    action = await session.get(Action, result.action_id)
    preview = await reversal_service.preview_reverse(session, action.id)
    assert not preview.blockers
    await reversal_service.reverse(
        session, action.id, plan_token=preview.plan_token, actor="tester"
    )
    batch = await get_batch(session, result.batch_id)
    await session.commit()

    views = await list_batches(session)
    view = next(v for v in views if v.batch_id == batch.id)
    assert view.can_rollback is False
    assert view.rollback_blocked_reason == BLOCK_ALREADY_ROLLED_BACK
    assert await import_batch_rollback_blockers(session, action.id)


async def test_non_last_batch_blocked_in_compensator(session: AsyncSession) -> None:
    """Гейт LIFO живёт в компенсаторе, а не только в UI: preview честно
    отказывает (ADR-0053 п.4)."""
    product = await _product(session, "HIST-BLK")
    section = await _section(session, "HIST-LOC-BLK")

    first = await _import(session, section, _items(product.sku, 5.0))
    await _import(session, section, _items(product.sku, 7.0))
    await session.commit()

    first_action = (await get_batch(session, first.batch_id)).action_id
    preview = await reversal_service.preview_reverse(session, first_action)
    assert preview.blockers
    assert any(b.kind == "not_allowed" for b in preview.blockers)
    assert preview.plan_token is None


# ─── Покрытие (ADR-0052 п.4) ─────────────────────────────────────────────────


async def test_rollback_restores_balance_and_keeps_invariants(
    session: AsyncSession,
) -> None:
    """Откат возвращает остаток к состоянию до импорта и не ломает ledger."""
    product = await _product(session, "HIST-BAL")
    section = await _section(session, "HIST-LOC-BAL")

    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id, from_location_id=None,
        to_location_id=section.id, quantity=Decimal("9"),
        reason=Reason.MANUAL_IN, created_by=1,
    ))
    await session.commit()

    result = await _import(session, section, _items(product.sku, 5.0),
                           clear_existing=True)
    await session.commit()
    assert result.success is True

    action = await session.get(Action, result.action_id)
    assert {t.reason for t in (
        await session.execute(
            select(StockTransaction).where(StockTransaction.action_id == action.id)
        )
    ).scalars()} == {Reason.ADJUSTMENT_OUT, Reason.MANUAL_IN}

    preview = await reversal_service.preview_reverse(session, action.id)
    await reversal_service.reverse(
        session, action.id, plan_token=preview.plan_token, actor="tester"
    )
    from app.stock.import_history import mark_rolled_back

    await mark_rolled_back(
        session, await get_batch(session, result.batch_id), user=None
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="hist-rollback")

    batch = await get_batch(session, result.batch_id)
    assert batch.status == StockImportBatchStatus.ROLLED_BACK
    assert batch.rolled_back_at is not None


async def test_rollback_blocked_when_material_consumed(session: AsyncSession) -> None:
    """Израсходованный после импорта материал блокирует откат (ADR-0052 п.4):
    компенсации нечем покрыть, частичный откат запрещён."""
    product = await _product(session, "HIST-COV")
    section = await _section(session, "HIST-LOC-COV")

    result = await _import(session, section, _items(product.sku, 5.0))
    await session.commit()

    # Материал ушёл в производство.
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id, from_location_id=section.id,
        to_location_id=None, quantity=Decimal("5"),
        reason=Reason.MANUAL_OUT, created_by=1,
    ))
    await session.commit()

    action = await session.get(Action, result.action_id)
    preview = await reversal_service.preview_reverse(session, action.id)
    assert any(b.kind == "coverage" for b in preview.blockers)

    # Preview-first: подтверждение не выдаётся, пока есть блокер, поэтому
    # форжированный токен отсекается StalePlanToken — до попытки компенсации.
    with pytest.raises(errors.StalePlanToken):
        await reversal_service.reverse(
            session, action.id, plan_token="forged.token"
        )
    assert preview.plan_token is None
    await assert_no_invariants_violations(session, context="hist-coverage")


# ─── Мягкое удаление (ADR-0052 п.5) ──────────────────────────────────────────


async def test_hide_hides_from_list_but_keeps_ledger(session: AsyncSession) -> None:
    """«Удалить» убирает запись из списка и ничего не делает с проводками."""
    product = await _product(session, "HIST-HIDE")
    section = await _section(session, "HIST-LOC-HIDE")
    result = await _import(session, section, _items(product.sku, 5.0))
    await session.commit()

    txs_before = await session.scalar(
        select(StockTransaction).where(
            StockTransaction.action_id == result.action_id
        ).with_only_columns(StockTransaction.id)
    )
    actions_before = await session.scalar(
        select(Action).where(Action.id == result.action_id).with_only_columns(Action.id)
    )
    assert txs_before is not None and actions_before is not None

    admin = User(
        username="hist-admin", full_name="Hist Admin", role=UserRole.admin,
        is_active=True,
    )
    session.add(admin)
    await session.commit()

    await hide_batch(session, result.batch_id, user=admin, reason="залито не то")

    assert all(v.batch_id != result.batch_id for v in await list_batches(session))
    visible = await list_batches(session, include_hidden=True)
    assert any(v.batch_id == result.batch_id for v in visible)

    batch = await get_batch(session, result.batch_id)
    assert batch.deleted_at is not None and batch.deleted_by == admin.id
    # Узел журнала не удаляется никогда (ADR-0019 §7), проводки — append-only.
    assert await session.get(Action, result.action_id) is not None
    assert await session.get(StockTransaction, txs_before) is not None
    await assert_no_invariants_violations(session, context="hist-hide")


async def test_hide_requires_reason_length(session: AsyncSession) -> None:
    section = await _section(session, "HIST-LOC-REASON")
    product = await _product(session, "HIST-REASON")
    result = await _import(session, section, _items(product.sku, 1.0))
    await session.commit()

    with pytest.raises(ImportHistoryError) as exc:
        await hide_batch(session, result.batch_id, user=None, reason="ну")
    assert exc.value.code == "reason_too_short"


# ─── Бэкфилл и legacy (ADR-0052 п.7) ─────────────────────────────────────────


async def test_action_without_batch_row_is_not_gated(session: AsyncSession) -> None:
    """Узел журнала без строки батча (импорт до миграции, до бэкфилла) гейтом
    LIFO не блокируется: блокировать то, что откатывается и сейчас, незачем."""
    from app.services.action_journal_service import action_journal_service

    action = await action_journal_service.log(session, action_type="import_remainders")
    await session.commit()

    assert await import_batch_rollback_blockers(session, action.id) == []


async def test_legacy_batch_without_location_is_marked(session: AsyncSession) -> None:
    """Бэкфилловый батч: склад не сохранился — это видно в UI, а не выдаётся
    за «склад 0» (ADR-0052 п.7)."""
    from app.services.action_journal_service import action_journal_service

    action = await action_journal_service.log(session, action_type="import_remainders")
    await session.commit()
    batch = StockImportBatch(
        action_id=action.id, file_id=None, location_id=None, legacy=True,
        status=StockImportBatchStatus.APPLIED,
    )
    session.add(batch)
    await session.commit()

    views = await list_batches(session)
    view = next(v for v in views if v.batch_id == batch.id)
    assert view.legacy is True
    assert view.location_id is None
    assert view.can_rollback is False
    assert view.rollback_blocked_reason == BLOCK_LEGACY_NO_LOCATION


# ─── Гейт роли (ADR-0052 п.6) ────────────────────────────────────────────────


async def test_non_admin_cannot_reverse_import_remainders(
    client, session: AsyncSession
) -> None:
    """Админский гейт держится и на общем маршруте /actions/{id}/reverse:
    иначе он обходится за два клика из журнала (ADR-0052 п.6)."""
    from app.services.action_journal_service import action_journal_service

    operator = User(
        username="hist-op", full_name="Hist Op", role=UserRole.operator,
        is_active=True,
        # JWT выдаётся на email: без него субъект пустой и срабатывает
        # dev-bypass, а под ним пользователь — админ, и гейт не проверяется.
        email="hist-op@example.test",
    )
    session.add(operator)
    action = await action_journal_service.log(session, action_type="import_remainders")
    await session.commit()

    resp = await client.post(
        f"/api/actions/{action.id}/preview-reverse",
        headers=_headers(operator),
        json={},
    )
    assert resp.status_code == 403
    assert "администратор" in str(resp.json()["detail"])
