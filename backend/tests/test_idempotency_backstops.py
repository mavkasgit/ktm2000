"""Идемпотентность вне ledger: unique-бэкстопы и 409 на гонку (ADR-0022, #135).

- Бэкстоп-существование: две строки с одним ключом в тестовой схеме
  (create_all, минуя миграции) ловятся partial unique-индексом.
- Сервисный уровень: конкурентные подачи с одним ключом на двух реальных
  соединениях — ровно одна строка, проигравший получает
  ``IdempotencyConflict`` (409, KTMException — не ValueError).
- Cross-connection replay: повтор с тем же ключом возвращает запись
  победителя (включая новые replay-ветки attachments/comments).

Тесты гонки используют отдельные соединения из ``engine`` (общая фикстура
``session`` держит всё на одном соединении — там гонка невоспроизводима).
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.database import get_db
from app.core.exceptions import IdempotencyConflict
from app.core.security import create_access_token
from app.main import app
from app.models.attachment import Attachment
from app.models.defect import Defect, DefectDecision, DefectDecisionType
from app.models.entity_comment import EntityComment, EntityType
from app.models.internal_plan import InternalPlan, InternalPlanStatus, SectionPlanLine
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteStage
from app.models.transfer import Transfer
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.shopfloor.operations_defects import create_defect, defect_decide
from app.services.shopfloor.operations_meta import create_attachment, create_comment
from app.stock import Reason, StockCommand, StockCommandService
from app.transfers.services import transfer_send
from tests.stock.test_stock_command import _make_location, _make_product, _make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("_pin_search_path")]

RACE_KEY = "race-key-135"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def _pin_search_path(engine: AsyncEngine, module_schema_name: str):
    """Каждое новое соединение движка сразу получает search_path модуля
    (engine на NullPool — см. tests/stock/test_ledger_idempotency.py)."""

    def _set_path(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute(f'SET search_path TO "{module_schema_name}"')
        cur.close()

    event.listen(engine.sync_engine, "connect", _set_path)
    yield
    event.remove(engine.sync_engine, "connect", _set_path)


def _schema_sql(module_schema_name: str) -> str:
    return f'SET search_path TO "{module_schema_name}"'


async def _bump_user_sequence(session: AsyncSession) -> None:
    """Поднимает users-последовательность выше постоянного пола (900k)."""
    await session.execute(text(
        "SELECT setval(pg_get_serial_sequence('users', 'id'), "
        "GREATEST((SELECT COALESCE(MAX(id), 0) FROM users), 900000) + 1, false)"
    ))


def _factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(bind=engine, expire_on_commit=False)


def _make_defect(session: AsyncSession, *, product_id: int, section_id: int,
                 user_id: int, key: str | None) -> Defect:
    """Минимальный валидный Defect (без flush)."""
    return Defect(
        product_id=product_id, section_id=section_id,
        created_by=user_id, idempotency_key=key,
    )


async def _race_setup(factory: async_sessionmaker, schema: str, tag: str) -> dict:
    """Закоммиченный базовый сетап: пользователь, продукт, участок.

    ``tag`` уникален на тест: строки коммятся мимо savepoint-изоляции и
    живут весь модуль (как в test_ledger_idempotency).
    """
    async with factory() as s:
        await s.execute(text(schema))
        await _bump_user_sequence(s)
        user = await _make_user(s, f"idem135-{tag}")
        product = await _make_product(s, f"IDEM135-{tag}")
        section = await _make_location(
            s, code=f"IDEM135-{tag}", name="Sec", loc_type="laser"
        )
        await s.commit()
        return {"user": user, "product": product, "section": section}


# ─── существование бэкстопов в тестовой схеме (create_all) ─────────────────


async def test_unique_backstop_rejects_duplicate_keys(
    engine: AsyncEngine, module_schema_name: str,
):
    """Partial unique на лёгких таблицах: дубль ключа → IntegrityError,
    NULL-ключи не конфликтуют. transfers/rework_tasks покрыты race-тестами
    и полными топологиями ниже (их минимальные строки требуют задачи)."""
    factory = _factory(engine)
    schema = _schema_sql(module_schema_name)
    fx = await _race_setup(factory, schema, "backstop")
    user, product, section = fx["user"], fx["product"], fx["section"]

    async with factory() as s:
        await s.execute(text(schema))
        await s.commit()

        async def expect_unique_violation(add_row) -> None:
            add_row()  # первая строка с ключом — легитимна
            await s.flush()
            add_row()  # вторая — ловится partial unique
            with pytest.raises(IntegrityError):
                await s.flush()
            await s.rollback()

        def add_attachment(key: str | None) -> None:
            s.add(Attachment(
                original_filename="a.txt", stored_path="/tmp/a.txt",
                size_bytes=1, created_by=user.id, idempotency_key=key,
            ))

        def add_comment(key: str | None) -> None:
            s.add(EntityComment(
                entity_type=EntityType.work_task, entity_id=1, body="b",
                author_id=user.id, idempotency_key=key,
            ))

        def add_defect(key: str | None) -> None:
            s.add(_make_defect(
                s, product_id=product.id, section_id=section.id,
                user_id=user.id, key=key,
            ))

        def add_decision(key: str | None, defect: Defect) -> None:
            s.add(DefectDecision(
                defect_id=defect.id, decision_type=DefectDecisionType.scrap,
                quantity=Decimal("1"), decided_by=user.id, idempotency_key=key,
            ))

        await expect_unique_violation(lambda: add_defect(RACE_KEY))
        await expect_unique_violation(lambda: add_attachment(RACE_KEY))
        await expect_unique_violation(lambda: add_comment(RACE_KEY))
        add_defect(None)
        await s.flush()
        defect_for_decision = (await s.execute(
            select(Defect).order_by(Defect.id.desc()).limit(1)
        )).scalar_one()
        await expect_unique_violation(
            lambda: add_decision(RACE_KEY, defect_for_decision)
        )

        # NULL-ключи: по две строки на таблицу — partial unique молчит.
        add_defect(None)
        add_defect(None)
        add_attachment(None)
        add_attachment(None)
        add_comment(None)
        add_comment(None)
        await s.flush()


# ─── create_defect / defect_decide: гонка + replay ─────────────────────────


async def test_create_defect_race_loser_gets_conflict(
    engine: AsyncEngine, module_schema_name: str,
):
    factory = _factory(engine)
    schema = _schema_sql(module_schema_name)
    fx = await _race_setup(factory, schema, "defect")

    kwargs = dict(
        product_id=fx["product"].id, section_id=fx["section"].id,
        quantity=Decimal("3"), actor_id=fx["user"].id, idempotency_key=RACE_KEY,
    )
    async with factory() as winner:
        await winner.execute(text(schema))
        first = await create_defect(winner, **kwargs)

        async with factory() as loser:
            await loser.execute(text(schema))
            task = asyncio.create_task(create_defect(loser, **kwargs))
            # Проигравший проходит replay-SELECT (INSERT победителя ещё не
            # закоммичен) и зависает на flush unique-индекса.
            await asyncio.sleep(0.5)
            await winner.commit()
            with pytest.raises(IdempotencyConflict) as exc_info:
                await task
            assert exc_info.value.error_code == "defect_idempotency_conflict"
            await loser.rollback()

    async with factory() as check:
        await check.execute(text(schema))
        rows = (await check.execute(
            select(Defect).where(Defect.idempotency_key == RACE_KEY)
        )).scalars().all()
        replay = await create_defect(check, **kwargs)

    assert len(rows) == 1, "гонка не должна создавать дубликаты дефектов"
    assert replay == {"defect_id": first["defect_id"], "item_id": None,
                      "idempotent_replay": True}


async def test_defect_decide_race_loser_gets_conflict(
    engine: AsyncEngine, module_schema_name: str,
):
    """accept_with_deviation без task: решения не пишут ledger — чистая
    гонка на defect_decisions."""
    factory = _factory(engine)
    schema = _schema_sql(module_schema_name)
    fx = await _race_setup(factory, schema, "decide")

    async with factory() as s:
        await s.execute(text(schema))
        s.add(_make_defect(
            s, product_id=fx["product"].id, section_id=fx["section"].id,
            user_id=fx["user"].id, key=None,
        ))
        await s.flush()
        defect_id = (await s.execute(
            select(Defect).order_by(Defect.id.desc()).limit(1)
        )).scalar_one().id
        await s.commit()

    kwargs = dict(
        defect_id=defect_id,
        decision_type=DefectDecisionType.accept_with_deviation,
        quantity=Decimal("1"), actor_id=fx["user"].id, idempotency_key=RACE_KEY,
    )
    async with factory() as winner:
        await winner.execute(text(schema))
        first = await defect_decide(winner, **kwargs)

        async with factory() as loser:
            await loser.execute(text(schema))
            task = asyncio.create_task(defect_decide(loser, **kwargs))
            await asyncio.sleep(0.5)
            await winner.commit()
            with pytest.raises(IdempotencyConflict) as exc_info:
                await task
            assert exc_info.value.error_code == "defect_decision_idempotency_conflict"
            await loser.rollback()

    async with factory() as check:
        await check.execute(text(schema))
        rows = (await check.execute(
            select(DefectDecision).where(DefectDecision.idempotency_key == RACE_KEY)
        )).scalars().all()
        replay = await defect_decide(check, **kwargs)

    assert len(rows) == 1
    assert replay["decision_id"] == first["decision_id"]
    assert replay["idempotent_replay"] is True


# ─── create_attachment / create_comment: гонка + replay ────────────────────


async def test_create_attachment_race_and_replay(
    engine: AsyncEngine, module_schema_name: str,
):
    factory = _factory(engine)
    schema = _schema_sql(module_schema_name)
    fx = await _race_setup(factory, schema, "attach")

    kwargs = dict(
        original_filename="x.txt", stored_path="/tmp/x.txt",
        size_bytes=2, actor_id=fx["user"].id, idempotency_key=RACE_KEY,
    )
    async with factory() as winner:
        await winner.execute(text(schema))
        first = await create_attachment(winner, **kwargs)

        async with factory() as loser:
            await loser.execute(text(schema))
            task = asyncio.create_task(create_attachment(loser, **kwargs))
            await asyncio.sleep(0.5)
            await winner.commit()
            with pytest.raises(IdempotencyConflict) as exc_info:
                await task
            assert exc_info.value.error_code == "attachment_idempotency_conflict"
            await loser.rollback()

    async with factory() as check:
        await check.execute(text(schema))
        rows = (await check.execute(
            select(Attachment).where(Attachment.idempotency_key == RACE_KEY)
        )).scalars().all()
        replay = await create_attachment(check, **kwargs)

    assert len(rows) == 1
    assert replay == {"attachment_id": first["attachment_id"], "idempotent_replay": True}


async def test_create_comment_race_and_replay(
    engine: AsyncEngine, module_schema_name: str,
):
    factory = _factory(engine)
    schema = _schema_sql(module_schema_name)
    fx = await _race_setup(factory, schema, "comment")

    kwargs = dict(
        entity_type=EntityType.work_task, entity_id=1, body="note",
        actor_id=fx["user"].id, idempotency_key=RACE_KEY,
    )
    async with factory() as winner:
        await winner.execute(text(schema))
        first = await create_comment(winner, **kwargs)

        async with factory() as loser:
            await loser.execute(text(schema))
            task = asyncio.create_task(create_comment(loser, **kwargs))
            await asyncio.sleep(0.5)
            await winner.commit()
            with pytest.raises(IdempotencyConflict) as exc_info:
                await task
            assert exc_info.value.error_code == "entity_comment_idempotency_conflict"
            await loser.rollback()

    async with factory() as check:
        await check.execute(text(schema))
        rows = (await check.execute(
            select(EntityComment).where(EntityComment.idempotency_key == RACE_KEY)
        )).scalars().all()
        replay = await create_comment(check, **kwargs)

    assert len(rows) == 1
    assert replay == {"comment_id": first["comment_id"], "idempotent_replay": True}


# ─── transfer_send: гонка + replay ──────────────────────────────────────────


async def _make_two_stage_setup(factory: async_sessionmaker, schema: str, sku: str) -> dict:
    """Топология из двух этапов с transferable-материалом на первом.

    Прямая ORM-расстановка (без API take-to-work): полностью закоммиченный
    сетап для гонки на двух соединениях движка.
    """
    async with factory() as s:
        await s.execute(text(schema))
        await _bump_user_sequence(s)
        user = await _make_user(s, f"{sku}@local")
        product = await _make_product(s, sku)
        stock = await _make_location(s, code=f"{sku}-STK", name="Stock", loc_type="raw_stock")
        sec1 = await _make_location(s, code=f"{sku}-S1", name="S1", loc_type="production")
        sec2 = await _make_location(s, code=f"{sku}-S2", name="S2", loc_type="production")

        route = ProductionRoute(name=f"R-{sku}", is_active=True)
        s.add(route)
        await s.flush()
        stage1 = RouteStage(route_id=route.id, sequence=1, section_id=sec1.id, is_final=False)
        stage2 = RouteStage(route_id=route.id, sequence=2, section_id=sec2.id, is_final=True)
        s.add_all([stage1, stage2])
        await s.flush()

        plan = ProductionPlan(
            plan_no=f"P-{sku}", name="p", status=ProductionPlanStatus.approved,
            period_start=datetime(2026, 6, 1), period_end=datetime(2026, 6, 30),
        )
        s.add(plan)
        await s.flush()
        pos = PlanPosition(
            production_plan_id=plan.id, product_id=product.id,
            source_type=PlanSourceType.manual, source_sku=product.sku,
            source_name=product.name, quantity=Decimal("10"),
            source_payload={}, status=PlanPositionStatus.approved,
            validation_status=PlanPositionValidationStatus.valid,
            validation_errors=[],
            period_start=plan.period_start, period_end=plan.period_end,
            has_pack_ops=False, route_id=route.id, route_assigned_at=None,
        )
        s.add(pos)
        await s.flush()
        internal = InternalPlan(production_plan_id=plan.id, status=InternalPlanStatus.active)
        s.add(internal)
        await s.flush()
        line1 = SectionPlanLine(
            internal_plan_id=internal.id, plan_position_id=pos.id,
            section_id=sec1.id, route_stage_id=stage1.id,
            product_id=product.id, route_id=route.id,
            sequence=1, planned_quantity=Decimal("10"),
        )
        line2 = SectionPlanLine(
            internal_plan_id=internal.id, plan_position_id=pos.id,
            section_id=sec2.id, route_stage_id=stage2.id,
            product_id=product.id, route_id=route.id,
            sequence=2, planned_quantity=Decimal("10"),
        )
        s.add_all([line1, line2])
        await s.flush()
        task1 = WorkTask(
            section_plan_line_id=line1.id, section_id=sec1.id,
            product_id=product.id, route_stage_id=stage1.id,
            planned_quantity=Decimal("10"), status=WorkTaskStatus.ready,
            due_date=plan.period_end,
        )
        task2 = WorkTask(
            section_plan_line_id=line2.id, section_id=sec2.id,
            product_id=product.id, route_stage_id=stage2.id,
            planned_quantity=Decimal("10"), status=WorkTaskStatus.waiting_previous,
            due_date=plan.period_end,
        )
        s.add_all([task1, task2])
        await s.flush()

        # transferable на task1: выданный и завершённый материал.
        svc = StockCommandService()
        await svc.record(s, StockCommand(
            product_id=product.id, from_location_id=None,
            to_location_id=stock.id, quantity=Decimal("10"),
            reason=Reason.MANUAL_IN, created_by=user.id,
        ))
        await svc.record(s, StockCommand(
            product_id=product.id, from_location_id=stock.id,
            to_location_id=sec1.id, quantity=Decimal("10"),
            reason=Reason.TRANSFER_RECEIVE, task_id=task1.id,
            created_by=user.id,
        ))
        await svc.record(s, StockCommand(
            product_id=product.id, from_location_id=sec1.id,
            to_location_id=sec1.id, quantity=Decimal("10"),
            reason=Reason.COMPLETE, task_id=task1.id,
            source_ref="test_seed", created_by=user.id,
        ))
        await s.commit()
        return {
            "user_email": user.email,
            "from_task_id": task1.id, "to_task_id": task2.id,
        }


async def test_transfer_send_race_loser_gets_conflict(
    engine: AsyncEngine, module_schema_name: str,
):
    factory = _factory(engine)
    schema = _schema_sql(module_schema_name)
    setup = await _make_two_stage_setup(factory, schema, "IDEMTR135")

    kwargs = dict(
        from_task_id=setup["from_task_id"], to_task_id=setup["to_task_id"],
        quantity=Decimal("5"), actor_id=None,
        idempotency_key=RACE_KEY,
    )
    # actor_id нужен числом, а объект user не сохранили — читаем по email.
    from app.models.user import User

    async with factory() as s:
        await s.execute(text(schema))
        actor_id = (await s.execute(
            select(User.id).where(User.email == setup["user_email"])
        )).scalar_one()
    kwargs["actor_id"] = actor_id

    async with factory() as winner:
        await winner.execute(text(schema))
        first = await transfer_send(winner, **kwargs)

        async with factory() as loser:
            await loser.execute(text(schema))
            task = asyncio.create_task(transfer_send(loser, **kwargs))
            # Проигравший проходит replay-SELECT и встаёт на FOR UPDATE
            # исходной задачи; после коммита победителя доходит до INSERT
            # Transfer и ловит unique-бэкстоп.
            await asyncio.sleep(0.5)
            await winner.commit()
            with pytest.raises(IdempotencyConflict) as exc_info:
                await task
            assert exc_info.value.error_code == "transfer_idempotency_conflict"
            await loser.rollback()

    async with factory() as check:
        await check.execute(text(schema))
        rows = (await check.execute(
            select(Transfer).where(Transfer.idempotency_key == RACE_KEY)
        )).scalars().all()
        replay = await transfer_send(check, **kwargs)

    assert len(rows) == 1, "гонка не должна создавать дубликаты передач"
    assert rows[0].id == first["transfer_id"]
    assert replay["transfer_id"] == first["transfer_id"]
    assert replay["idempotent_replay"] is True


# ─── API double-click: комментарий с одним ключом ───────────────────────────


@pytest_asyncio.fixture
async def isolated_client(
    engine: AsyncEngine, module_schema_name: str,
) -> AsyncIterator[AsyncClient]:
    """API-клиент, где каждый запрос получает СВОЁ соединение из engine."""
    factory = _factory(engine)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as db:
            await db.execute(text(_schema_sql(module_schema_name)))
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_api_double_click_comment_single_row(
    isolated_client: AsyncClient, engine: AsyncEngine, module_schema_name: str,
):
    """Два параллельных POST /comments с одним ключом дают 201 победителя и
    допустимый 409 конфликта (или оба 201 при replay), оставляя одну запись."""
    factory = _factory(engine)
    schema = _schema_sql(module_schema_name)
    fx = await _race_setup(factory, schema, "apicomment")
    headers = {"Authorization": f"Bearer {create_access_token(subject=fx['user'].email)}"}

    payload = {
        "entity_type": "work_task", "entity_id": 1, "body": "dblclick",
        "idempotency_key": RACE_KEY,
    }
    r1, r2 = await asyncio.gather(
        isolated_client.post("/api/shopfloor/comments", json=payload, headers=headers),
        isolated_client.post("/api/shopfloor/comments", json=payload, headers=headers),
    )

    for resp in (r1, r2):
        assert resp.status_code == 201 or (
            resp.status_code == 409
            and resp.json()["error_code"] == "entity_comment_idempotency_conflict"
        ), resp.text
    assert 201 in (r1.status_code, r2.status_code), "хотя бы одна подача проходит"

    async with factory() as check:
        await check.execute(text(schema))
        rows = (await check.execute(
            select(EntityComment).where(EntityComment.idempotency_key == RACE_KEY)
        )).scalars().all()

    assert len(rows) == 1, "double-click не должен задваивать комментарий"
