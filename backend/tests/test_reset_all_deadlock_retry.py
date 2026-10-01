"""Регресс на устойчивость полного сброса (`POST /production-plans/reset-all`).

Проверяет сквозь НАСТОЯЩИЙ эндпоинт с НАСТОЯЩИМИ соединениями и настоящими
коммитами (как `test_bulk_approve_commit.py`), потому что дефект жил именно
внутри цикла повтора: откат там переводил ORM-объект `current_user` в
expired, и следующий `log_action` падал `MissingGreenlet` → 500. Заглушка
сессии без ORM-состояния такой дефект воспроизвести не может в принципе,
поэтому здесь только реальный Postgres.

Диагноз конфликта зафиксирован прогоном: `TRUNCATE` против транзакции,
которая просто держит блокировку, даёт не дедлок, а ожидание —
SQLSTATE `55P03` (`canceling statement due to lock timeout`). Настоящий
`40P01` в этой схеме недостижим: `TRUNCATE` берёт блокировки в одном
порядке, и цикла ожидания между двумя такими запросами не возникает.
Поэтому повтор ловит оба кода, а узнаёт их по SQLSTATE, а не по тексту.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import pytest
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.audit_log import AuditLog
from app.models.production_plan import ProductionPlan, ProductionPlanStatus
from app.models.user import User
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

RESET_ALL_URL = "/api/production-plans/reset-all"

# Тот же предел ожидания, что и в бою. Ставится в override, а не подменяется
# во внутренностях: иначе на старом коде, где сброс сам предел не ставит,
# запрос ждал бы снятия блокировки вместо того, чтобы отбиться.
LOCK_TIMEOUT = "2s"


@asynccontextmanager
async def _schema_session(
    engine: AsyncEngine,
    schema: str,
    *,
    session_cls: type[AsyncSession] = AsyncSession,
) -> AsyncIterator[AsyncSession]:
    """Сессия на собственном соединении, коммиты которой НАСТОЯЩИЕ.

    `SET search_path` выполняется первым и коммитится: в Postgres SET без
    LOCAL переживает коммит транзакции и держится до конца сессии, поэтому
    последующие `session.commit()` фиксируют данные по-настоящему, а не
    отпускают savepoint внешней транзакции.
    """
    async with engine.connect() as conn:
        await conn.execute(text(f'SET search_path TO "{schema}"'))
        await conn.commit()
        factory = async_sessionmaker(bind=conn, class_=session_cls, expire_on_commit=False)
        async with factory() as db:
            try:
                yield db
            finally:
                await db.rollback()


async def _seed_admin(engine: AsyncEngine, schema: str, email: str) -> User:
    async with _schema_session(engine, schema) as db:
        user = User(email=email, full_name="Reset Admin", role="admin", is_active=True)
        db.add(user)
        await db.commit()
        return user


async def _seed_plan(engine: AsyncEngine, schema: str, number: str) -> None:
    async with _schema_session(engine, schema) as db:
        db.add(
            ProductionPlan(
                plan_no=number,
                name=f"Reset probe {number}",
                status=ProductionPlanStatus.draft,
            )
        )
        await db.commit()


async def _plan_exists(engine: AsyncEngine, schema: str, number: str) -> bool:
    async with _schema_session(engine, schema) as db:
        stmt = select(ProductionPlan.id).where(ProductionPlan.plan_no == number)
        return (await db.execute(stmt)).first() is not None


async def _latest_audit(engine: AsyncEngine, schema: str):
    """Атрибуция последней записи «Сброс системы» как обычные значения."""
    async with _schema_session(engine, schema) as db:
        stmt = (
            select(AuditLog.user_id, AuditLog.user_name)
            .where(AuditLog.title == "Сброс системы")
            .order_by(AuditLog.id.desc())
        )
        return (await db.execute(stmt)).first()


def _truncate_failing_session_cls(
    errors: list[BaseException],
    attempts: list[int],
) -> type[AsyncSession]:
    """Реальная сессия, у которой выполнение `TRUNCATE` падает заданным списком.

    Подменяется только сам `TRUNCATE`; всё остальное — настоящий эндпоинт,
    настоящая сессия, настоящий откат и настоящий коммит аудита.
    """

    class _FlakyTruncate(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            if str(statement).lstrip().upper().startswith("TRUNCATE TABLE"):
                attempts.append(1)
                if errors:
                    raise errors.pop(0)
            return await super().execute(statement, *args, **kwargs)

    return _FlakyTruncate


async def _call_reset_all(
    engine: AsyncEngine,
    schema: str,
    headers: dict[str, str],
    *,
    session_cls: type[AsyncSession] = AsyncSession,
    lock_timeout: str | None = LOCK_TIMEOUT,
):
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with _schema_session(engine, schema, session_cls=session_cls) as db:
            if lock_timeout is not None:
                await db.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout}'"))
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            return await ac.post(RESET_ALL_URL, headers=headers)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(subject=user.email)}"}


async def _hold_lock_for(engine: AsyncEngine, schema: str, seconds: float) -> None:
    """Фоновая транзакция, которая держит ACCESS SHARE на `production_plans`."""
    async with engine.connect() as conn:
        await conn.execute(text(f'SET search_path TO "{schema}"'))
        await conn.commit()
        held = await conn.begin()
        await conn.execute(text("SELECT 1 FROM production_plans LIMIT 1"))
        try:
            await asyncio.sleep(seconds)
        finally:
            await held.rollback()


@pytest.mark.asyncio
async def test_reset_all_survives_real_lock_contention(
    engine: AsyncEngine, module_schema_name: str
) -> None:
    """Настоящая транзакция держит блокировку — сброс всё равно отвечает 204.

    Это и есть сценарий, ради которого написан повтор. Ошибка приходит из
    Postgres, а не из подмены: конкурент держит ACCESS SHARE на
    `production_plans` дольше `lock_timeout`, поэтому первая попытка
    отбивается настоящим SQLSTATE `55P03`, а вторая — уже после снятия
    блокировки — проходит. Ответ 204 — приоритетный признак: откат в цикле
    повтора не имеет права оставить эндпоинт сломанным.
    """
    schema = module_schema_name
    user = await _seed_admin(engine, schema, "reset-contention@test.local")
    await _seed_plan(engine, schema, "CONTENTION-1")

    # Держим дольше одного предела ожидания, но отпускаем до конца бюджета.
    holder = asyncio.create_task(_hold_lock_for(engine, schema, 3.4))
    await asyncio.sleep(0.3)
    try:
        response = await asyncio.wait_for(
            _call_reset_all(engine, schema, _auth(user)), timeout=60
        )
    finally:
        await holder

    assert response.status_code == 204, (
        f"сброс обязан пережить конкуренцию, а не отдать "
        f"{response.status_code}: {response.text}"
    )
    assert not await _plan_exists(engine, schema, "CONTENTION-1"), "план должен быть удалён"

    audit = await _latest_audit(engine, schema)
    assert audit is not None, "аудит полного сброса обязан быть записан"
    assert audit[0] == user.id, "аудит должен быть атрибутирован пользователю запроса"
    assert audit[1] == "Reset Admin", "аудит должен хранить имя пользователя запроса"


@pytest.mark.asyncio
async def test_reset_all_retries_on_deadlock_sqlstate_with_foreign_message(
    engine: AsyncEngine, module_schema_name: str
) -> None:
    """Дедлок опознаётся по SQLSTATE `40P01`, даже если в тексте его нет.

    Различение по подстроке в тексте пропускает настоящий дедлок с
    нестандартной формулировкой драйвера — а это ровно тот случай, ради
    которого повтор и написан.
    """
    from app.api.routes.production_plans import _TRUNCATE_ATTEMPTS

    schema = module_schema_name
    user = await _seed_admin(engine, schema, "reset-deadlock@test.local")
    await _seed_plan(engine, schema, "DEADLOCK-1")

    attempts: list[int] = []
    errors: list[BaseException] = [
        DBAPIError(
            "TRUNCATE ...",
            {},
            asyncpg.exceptions.DeadlockDetectedError("operation cancelled by the database"),
        )
    ]
    response = await _call_reset_all(
        engine,
        schema,
        _auth(user),
        session_cls=_truncate_failing_session_cls(errors, attempts),
    )

    assert response.status_code == 204, (
        f"ожидался успех после повтора, получено {response.status_code}: {response.text}"
    )
    assert len(attempts) == 2, "повтор по 40P01 обязан состояться ровно один раз"
    assert not await _plan_exists(engine, schema, "DEADLOCK-1")
    assert _TRUNCATE_ATTEMPTS >= 2, "бюджет повторов должен вмещать одну ретраю"


@pytest.mark.asyncio
async def test_reset_all_does_not_retry_error_that_merely_mentions_deadlock(
    engine: AsyncEngine, module_schema_name: str
) -> None:
    """Чужая ошибка со словом «deadlock» в тексте повтором не считается.

    Настоящий отказ обязан дойти до клиента сразу, а не растягиваться на
    пять попыток с паузами.
    """
    from app.api.routes.production_plans import _TRUNCATE_ATTEMPTS

    schema = module_schema_name
    user = await _seed_admin(engine, schema, "reset-nonretry@test.local")
    await _seed_plan(engine, schema, "NOT-RETRY-1")

    attempts: list[int] = []
    errors: list[BaseException] = [
        DBAPIError(
            "TRUNCATE ...",
            {},
            asyncpg.exceptions.SyntaxOrAccessError(
                "deadlock detected is not a valid privilege for this role"
            ),
        )
    ] * (_TRUNCATE_ATTEMPTS + 2)
    response = await _call_reset_all(
        engine,
        schema,
        _auth(user),
        session_cls=_truncate_failing_session_cls(errors, attempts),
    )

    assert response.status_code >= 500, "ошибку нельзя прятать, клиент обязан её увидеть"
    assert len(attempts) == 1, f"повтор тут только для блокировок, попыток было {len(attempts)}"
    assert await _plan_exists(engine, schema, "NOT-RETRY-1"), "прерванный сброс не удаляет данные"


@pytest.mark.asyncio
async def test_reset_all_gives_up_when_contention_persists(
    engine: AsyncEngine, module_schema_name: str
) -> None:
    """Исчерпание бюджета повторов обязано дать отказ, а не тихий «успех».

    Иначе повтор превращается в способ спрятать поломку: оператор увидит
    «сброс прошёл», а данные останутся.
    """
    from app.api.routes.production_plans import _TRUNCATE_ATTEMPTS

    schema = module_schema_name
    user = await _seed_admin(engine, schema, "reset-budget@test.local")
    await _seed_plan(engine, schema, "BUDGET-1")

    attempts: list[int] = []
    errors: list[BaseException] = [
        DBAPIError(
            "TRUNCATE ...",
            {},
            asyncpg.exceptions.LockNotAvailableError("canceling statement due to lock timeout"),
        )
    ] * (_TRUNCATE_ATTEMPTS + 3)
    response = await _call_reset_all(
        engine,
        schema,
        _auth(user),
        session_cls=_truncate_failing_session_cls(errors, attempts),
    )

    assert response.status_code >= 500, "упорный конфликт обязан дойти до клиента"
    assert len(attempts) == _TRUNCATE_ATTEMPTS, "больше попыток, чем объявлено"
    assert await _plan_exists(engine, schema, "BUDGET-1"), "прерванный сброс не удаляет данные"


@pytest.mark.asyncio
async def test_reset_all_bounds_lock_wait_by_its_own_lock_timeout(
    engine: AsyncEngine, module_schema_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сброс сам ограничивает ожидание блокировки, а не висит до её снятия.

    Без `lock_timeout` со стороны сброса запрос, которому встретилась
    забытая транзакция, ждал бы бесконечно: `deadlock_timeout` в Postgres
    срабатывает только на настоящем цикле, а ожидание блокировки — не
    цикл. Здесь предел приходит изнутри сброса (никакого `lock_timeout` в
    override), а блокировку держит транзакция, которая не отпустит её вовсе.
    """
    from app.api.routes import production_plans as pp

    schema = module_schema_name
    user = await _seed_admin(engine, schema, "reset-timeout@test.local")
    await _seed_plan(engine, schema, "TIMEOUT-1")

    monkeypatch.setattr(pp, "_TRUNCATE_LOCK_TIMEOUT", "200ms", raising=False)
    monkeypatch.setattr(pp, "_TRUNCATE_ATTEMPTS", 1, raising=False)

    holder = asyncio.create_task(_hold_lock_for(engine, schema, 5))
    await asyncio.sleep(0.3)
    started = time.monotonic()
    try:
        response = await asyncio.wait_for(
            _call_reset_all(engine, schema, _auth(user), lock_timeout=None), timeout=60
        )
    finally:
        holder.cancel()
    elapsed = time.monotonic() - started

    assert elapsed < 3.0, f"ожидание блокировки не ограничено сбросом: {elapsed:.1f}s"
    assert response.status_code >= 500, "запертый TRUNCATE обязан честно отказать"
    assert await _plan_exists(engine, schema, "TIMEOUT-1")
