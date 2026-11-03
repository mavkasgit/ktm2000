"""Сквозные HTTP-сценарии выдачи с автоподбором источника (#282).

Проверяется **контракт**, а не ядро: предпросмотр и запуск идут через
``POST /api/production-planning/rows/{id}/issue-preview`` и
``POST /api/production-planning/rows/take-to-work``, отмена — через
``GET|POST /api/transfers/issues/{issue_no}/cancel[-preview]``. Ядро подбора
(``test_source_selection.py``) и гонка двух выдач (``test_issue_race.py``)
покрыты предыдущими сменами; здесь — то, что видит оператор:

* предпросмотр не мутирует БД, порядок = ``order``, ``null`` против ``"0"``
  различимы, снятая галочка пересчитывает набор и живёт ровно один вызов,
  подсказки только по включённым складам, лишнее поле в теле → 422;
* одна выдача = N передач в системном порядке, итог ``issue_summary``,
  три стратегии недостачи, групповой запуск только ``auto`` с одним общим
  итогом, повтор с тем же ``idempotency_key`` не плодит вторую выдачу;
* выдача, прыгнувшая через этап, помечает промежуточные задания
  «Пропущено» **своим** номером, а отмена снимает только свои пропуски;
* отмена выдачи целиком: предпросмотр — имена вместо id, компенсирующие
  проводки с ``reverses_id``, возврат балансов, повторная отмена — отказ.

Паттерн сетапа — ``test_take_to_work_source_allocation``: та же схема на
модуль, тот же ``client`` (маршрут коммитит сессию до ответа), те же
``_auth_headers``. Все id и заголовки захватываются ДО запросов: отказный
роут откатывает savepoint и этим экспайрит ORM-объекты общей сессии —
обращение к такому объекту после отказа даёт ``MissingGreenlet`` вместо
полезного ассерта.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select

from app.models.action_journal import Action
from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.section import Section
from app.models.transfer import Transfer, TransferStatus
from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock.models import QualityState, Reason, StockBalance, StockTransaction
from tests.helpers.transfers import _make_dim_route_fixture, _seed_balance
from tests.test_integrity_invariants import (
    _auth_headers,
    _make_user,
    assert_no_invariants_violations,
    assert_no_stock_ledger_invariants_violations,
)

# Маршрут фикстуры: raw_stock(seq1, ISSUE_RAW) → production(seq2, P1_OP)
#   → production(seq3, P2_OP, final). Вход seq2 = «ISSUE_RAW», вход seq3 =
#   «ISSUE_RAW + P1_OP» — тот же резолв адреса, что у ``source_selection``.
RAW_OPS = ["ISSUE_RAW"]
PREP_OPS = ["ISSUE_RAW", "P1_OP"]
PREVIEW = "/api/production-planning/rows/{position_id}/issue-preview"
TAKE = "/api/production-planning/rows/take-to-work"


# ─── Хелперы сетапа (плоские id, никаких ORM-объектов в ассертах) ──────────


async def _warehouse(session, code: str, *, name: str) -> int:
    """Склад-хранилище вне маршрута: подбор ходит по всем складам (#282)."""
    section = Section(code=code, name=name, type="wip_stock", is_active=True, sort_order=80)
    session.add(section)
    await session.flush()
    return section.id


async def _seed(session, *, product_id: int, location_id: int, qty: Decimal, ops, user_id: int, **kw) -> None:
    await _seed_balance(
        session,
        user_id=user_id,
        location_id=location_id,
        product_id=product_id,
        qty=qty,
        ops=ops,
        **kw,
    )
    await session.flush()


async def _rows(session, product_id: int, location_id: int) -> list[StockBalance]:
    return list(
        (
            await session.execute(
                select(StockBalance)
                .where(StockBalance.product_id == product_id, StockBalance.location_id == location_id)
                .order_by(StockBalance.id)
            )
        ).scalars().all()
    )


async def _balance_id(session, product_id: int, location_id: int, *, ops) -> int:
    for balance in await _rows(session, product_id, location_id):
        if sorted(balance.completed_operations or []) == sorted(ops):
            return balance.id
    raise AssertionError(f"остаток с признаком {ops} не посеян")


async def _balance_qty(session, product_id: int, location_id: int) -> Decimal:
    total = await session.scalar(
        select(func.coalesce(func.sum(StockBalance.balance_qty), 0)).where(
            StockBalance.product_id == product_id, StockBalance.location_id == location_id
        )
    )
    return Decimal(total or 0)


async def _snapshot(session, product_id: int) -> dict:
    """Снимок всего, что предпросмотр теоретически может задеть."""
    return {
        "txs": await session.scalar(select(func.count(StockTransaction.id))),
        "actions": await session.scalar(select(func.count(Action.id))),
        "balances": await session.scalar(
            select(func.count(StockBalance.id)).where(StockBalance.product_id == product_id)
        ),
        "qty": await session.scalar(
            select(func.coalesce(func.sum(StockBalance.balance_qty), 0)).where(
                StockBalance.product_id == product_id
            )
        ),
        "transfers": await session.scalar(select(func.count(Transfer.id))),
    }


async def _preview(client, position_id: int, **payload) -> dict:
    resp = await client.post(PREVIEW.format(position_id=position_id), json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _take(client, headers: dict, *, position_ids, release_quantity=None, issue=None, **extra):
    body = {"position_ids": [int(p) for p in position_ids], **extra}
    if release_quantity is not None:
        body["release_quantity"] = str(release_quantity)
    if issue is not None:
        body["issue"] = issue
    resp = await client.post(TAKE, json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _transfers(session, issue_no: str | None = None) -> list[Transfer]:
    stmt = select(Transfer).order_by(Transfer.id)
    if issue_no is not None:
        stmt = stmt.where(Transfer.issue_no == issue_no)
    return list((await session.execute(stmt)).scalars().all())


async def _sends(session) -> list[StockTransaction]:
    return list(
        (
            await session.execute(
                select(StockTransaction)
                .where(StockTransaction.reason == Reason.TRANSFER_SEND)
                .order_by(StockTransaction.id)
            )
        ).scalars().all()
    )


def _by_order(body: dict) -> list[dict]:
    return sorted(body["candidates"], key=lambda c: c["order"])


def _assert_no_ids_in(text: str, forbidden: list[int], *, allow: list[int]) -> None:
    """В операторском тексте нет числовых id — только имена и количества.

    ``allow`` — числа, которые в тексте законны (количества, номера этапов).
    Любое другое число, совпадающее с id склада/артикула/позиции, — протёкший
    технический идентификатор.
    """
    allowed = {str(a) for a in allow} | {"0"}
    forbidden_ids = {str(f) for f in forbidden}
    offenders = {t for t in re.findall(r"\d+", text) if t in forbidden_ids} - allowed
    assert not offenders, f"в тексте протекли числовые id: {offenders} — {text!r}"


async def _two_warehouse_setup(session, sku: str, *, prep_qty=Decimal(40), raw_qty=Decimal(100)) -> dict:
    """Склад-заготовка (→ этап 2) + «Хранилище Б» (→ этап 3): два источника.

    Системный порядок вычерпывает сначала Б (его признак ближе к концу
    маршрута), поэтому одна выдача = две передачи.
    """
    user = await _make_user(session, f"{sku}@local")
    headers = _auth_headers(user)
    fx = await _make_dim_route_fixture(session, sku=sku, qty=Decimal(100))
    product_id = fx["product"].id
    raw_id = fx["sections"][0].id
    raw_name = fx["sections"][0].name
    position_id = fx["position"].id
    whb_id = await _warehouse(session, f"{sku}-WHB", name="Хранилище Б")
    await _seed(session, product_id=product_id, location_id=whb_id, qty=prep_qty, ops=PREP_OPS, user_id=user.id)
    await _seed(session, product_id=product_id, location_id=raw_id, qty=raw_qty, ops=RAW_OPS, user_id=user.id)
    await session.commit()
    return {
        "headers": headers,
        "product_id": product_id,
        "position_id": position_id,
        "raw_id": raw_id,
        "raw_name": raw_name,
        "whb_id": whb_id,
        "user_id": user.id,
    }


# ─── Предпросмотр: только чтение, порядок, галочка, подсказки, 422 ──────────


async def test_issue_preview_is_read_only_and_orders_candidates(client, session) -> None:
    """Preview не мутирует БД и отдаёт строки ровно в поле ``order``.

    Три склада: «Хранилище Б» вычерпывается целиком (``remaining_after`` =
    ``"0"``), склад-заготовка берётся частично (``"80"``), третий склад, до
    которого очередь не дошла — ``null`` (прочерк). «Ноль», «прочерк» и
    «цифра» — три разных состояния; UI обязан различать их по типу значения,
    а не по подписи.
    """
    ctx = await _two_warehouse_setup(session, "ISSPV")
    third_id = await _warehouse(session, "ISSPV-WHC", name="Хранилище В")
    await _seed(
        session,
        product_id=ctx["product_id"],
        location_id=third_id,
        qty=Decimal(50),
        ops=RAW_OPS,
        user_id=ctx["user_id"],
    )
    await session.commit()

    before = await _snapshot(session, ctx["product_id"])
    body = await _preview(client, ctx["position_id"], release_quantity="60")
    after = await _snapshot(session, ctx["product_id"])

    assert body["required"] == "60"
    assert body["collected"] == "60"
    assert body["deficit"] == "0"
    assert after == before, "предпросмотр не имеет права писать проводки, передачи и journal-действия"

    rows = _by_order(body)
    assert [c["order"] for c in rows] == [0, 1, 2]
    assert rows[0]["location_name"] == "Хранилище Б"
    assert rows[0]["take"] == "40" and rows[0]["remaining_after"] == "0"
    assert rows[1]["take"] == "20" and rows[1]["remaining_after"] == "80"
    assert rows[2]["take"] == "0" and rows[2]["remaining_after"] is None
    assert rows[2]["included"] is True
    # адресат выдачи — этап, вход которого равен признаку операций склада
    assert [c["target_sequence"] for c in rows] == [3, 2, 2]
    await assert_no_invariants_violations(session, context="issue preview read-only")


async def test_excluded_warehouse_recalculates_and_lives_one_call(client, session) -> None:
    """Снятая галочка пересчитывает набор и не переживает один вызов.

    «Хранилище Б» (40 шт. с признаком подготовки) снято — 60 целиком берутся
    со склада-заготовки, а Б остаётся в списке с ``included: false`` и
    прочерком. Повторный вызов без галочки обязан вернуть исходный план:
    сервер ничего не запоминает (#282).
    """
    ctx = await _two_warehouse_setup(session, "ISSEX")
    whb_balance = await _balance_id(session, ctx["product_id"], ctx["whb_id"], ops=PREP_OPS)

    full = await _preview(client, ctx["position_id"], release_quantity="60")
    excluded = await _preview(
        client, ctx["position_id"], release_quantity="60", excluded_balance_ids=[whb_balance]
    )
    again = await _preview(client, ctx["position_id"], release_quantity="60")

    assert again == full, "снятая галочка живёт ровно один вызов"

    rows = _by_order(excluded)
    assert excluded["collected"] == "60" and excluded["deficit"] == "0"
    off = [c for c in rows if c["balance_id"] == whb_balance]
    assert len(off) == 1, "снятый склад остаётся видимым в списке"
    assert off[0]["included"] is False
    assert off[0]["take"] == "0" and off[0]["remaining_after"] is None
    live = [c for c in rows if c["included"]]
    assert live[0]["take"] == "60" and live[0]["remaining_after"] == "40"
    assert await _balance_qty(session, ctx["product_id"], ctx["whb_id"]) == Decimal(40), "preview ничего не списал"


async def test_hints_cover_only_included_warehouses(client, session) -> None:
    """Подсказки «брак» и «есть другой размер» — только по включённым складам.

    Склад снят галочкой целиком (единственный годный остаток на нём) — его
    брак и его чужой размер перестают быть аргументом оператору.
    """
    user = await _make_user(session, "ISSHINT@local")
    fx = await _make_dim_route_fixture(session, sku="ISSHINT", qty=Decimal(100), length_mm=2750)
    product_id = fx["product"].id
    raw_id = fx["sections"][0].id
    raw_name = fx["sections"][0].name
    position_id = fx["position"].id
    await _seed(
        session, product_id=product_id, location_id=raw_id, qty=Decimal(100),
        ops=RAW_OPS, user_id=user.id, dimensions={"length_mm": 2750},
    )
    await _seed(
        session, product_id=product_id, location_id=raw_id, qty=Decimal(30),
        ops=RAW_OPS, user_id=user.id, dimensions={"length_mm": 3000},
    )
    # Брак не является источником, но даёт подсказку; ledger-приход браком —
    # не предмет этого теста, поэтому строка ложится остатком напрямую.
    session.add(StockBalance(
        product_id=product_id, location_id=raw_id, quality_state=QualityState.SCRAP,
        dimensions={"length_mm": 2750}, completed_operations=RAW_OPS, balance_qty=Decimal(20),
        refreshed_at=datetime.now(UTC),
    ))
    await session.commit()

    good_balance = await _balance_id(session, product_id, raw_id, ops=RAW_OPS)
    body = await _preview(client, position_id, release_quantity="60")
    kinds = {h["kind"] for h in body["hints"]}
    assert kinds == {"defect", "other_size"}, body["hints"]
    assert {h["location_name"] for h in body["hints"]} == {raw_name}
    assert body["required_dimensions_label"] == "2,75 м"

    off = await _preview(
        client, position_id, release_quantity="60", excluded_balance_ids=[good_balance]
    )
    assert off["hints"] == [], "у снятого склада подсказок нет"
    assert off["collected"] == "0" and off["deficit"] == "60"


async def test_issue_preview_rejects_unknown_field(client, session) -> None:
    """``extra="forbid"``: лишнее поле в теле — 422, а не молчаливый игнор.

    Порядок и количества считает сервер: если бы клиент мог передать своё
    «take» или «location_id», окно научилось бы добавлять склад, который
    система не позвала (#282 — так нельзя).
    """
    user = await _make_user(session, "ISSFORBID@local")
    headers = _auth_headers(user)
    fx = await _make_dim_route_fixture(session, sku="ISSFORBID", qty=Decimal(100))
    await _seed(
        session, product_id=fx["product"].id, location_id=fx["sections"][0].id,
        qty=Decimal(100), ops=RAW_OPS, user_id=user.id,
    )
    position_id = fx["position"].id
    await session.commit()

    resp = await client.post(
        PREVIEW.format(position_id=position_id),
        json={"release_quantity": "10", "take_quantity_by_location": {"1": 5}},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


# ─── Взятие в работу с выдачей: N передач, стратегии, группа, replay ────────


async def test_take_to_work_issue_creates_n_transfers_in_system_order(client, session) -> None:
    """Одна выдача = две передачи: «Хранилище Б» вычерпан, остальное — склад.

    Контракт п.5 тикета: у каждой передачи свой ``transfer_no``, у всех один
    общий ``issue_no``, итог ``issue`` несёт required/collected/deficit и
    передачи в системном порядке.
    """
    ctx = await _two_warehouse_setup(session, "ISSN")
    body = await _take(
        client, ctx["headers"],
        position_ids=[ctx["position_id"]],
        release_quantity="60",
        issue={"shortage_strategy": "partial", "idempotency_key": "issn-1"},
    )
    result = body["results"][0]
    assert result["status"] == "success", result
    summary = result["issue"]
    assert summary["issue_no"].startswith("ISS-")
    assert (summary["required"], summary["collected"], summary["deficit"]) == ("60", "60", "0")

    transfers = summary["transfers"]
    assert [t["from_location_name"] for t in transfers] == ["Хранилище Б", ctx["raw_name"]]
    assert [t["quantity"] for t in transfers] == ["40", "20"]
    assert [t["target_sequence"] for t in transfers] == [3, 2]
    assert len({t["transfer_no"] for t in transfers}) == 2, "N передач, а не одна сваленная"

    issue_no = summary["issue_no"]
    rows = await _transfers(session, issue_no)
    assert len(rows) == 2
    assert {t.issue_no for t in rows} == {issue_no}
    assert all(t.status == TransferStatus.accepted for t in rows), "материал на участке = авто-приём"
    assert await _balance_qty(session, ctx["product_id"], ctx["whb_id"]) == Decimal(0)
    assert await _balance_qty(session, ctx["product_id"], ctx["raw_id"]) == Decimal(80)
    sends = await _sends(session)
    assert [Decimal(s.quantity) for s in sends] == [Decimal(40), Decimal(20)]
    assert all(s.source_ref == f"issue:{issue_no}" for s in sends)
    await assert_no_invariants_violations(session, context="n transfers")
    await assert_no_stock_ledger_invariants_violations(session, context="n transfers")


async def test_take_to_work_fail_strategy_refuses_without_trace(client, session) -> None:
    """``fail``: отказ русским текстом, в БД не остаётся ни запуска, ни выдачи.

    Отказ обязан назвать склады и дефицит, а не «balance 47»; savepoint
    запускателя откатывает и релиз позиции — иначе оператор увидел бы
    «не удалось» поверх уже созданного внутреннего плана.
    """
    user = await _make_user(session, "ISSFAIL@local")
    headers = _auth_headers(user)
    fx = await _make_dim_route_fixture(session, sku="ISSFAIL", qty=Decimal(100))
    product_id = fx["product"].id
    position_id = fx["position"].id
    raw_id = fx["sections"][0].id
    raw_name = fx["sections"][0].name
    whb_id = await _warehouse(session, "ISSFAIL-WHB", name="Хранилище Б")
    await _seed(session, product_id=product_id, location_id=whb_id, qty=Decimal(20), ops=PREP_OPS, user_id=user.id)
    await _seed(session, product_id=product_id, location_id=raw_id, qty=Decimal(30), ops=RAW_OPS, user_id=user.id)
    await session.commit()

    body = await _take(
        client, headers,
        position_ids=[position_id],
        release_quantity="100",
        issue={"shortage_strategy": "fail", "idempotency_key": "issfail-1"},
    )
    result = body["results"][0]
    assert result["status"] == "failed", result
    reason = result["reason"]
    assert "Нужно 100" in reason and "не хватает 50" in reason, reason
    assert "Хранилище Б" in reason and raw_name in reason, reason
    _assert_no_ids_in(reason, [product_id, raw_id, whb_id, position_id], allow=[100, 50, 20, 30])

    assert await _transfers(session) == [], "отказ не оставляет передач"
    assert await _sends(session) == [], "отказ не оставляет проводок"
    lines = await session.scalar(
        select(func.count(SectionPlanLine.id)).where(SectionPlanLine.plan_position_id == position_id)
    )
    assert lines == 0, "неудачная выдача откатывает запуск позиции целиком"
    position = await session.get(PlanPosition, position_id)
    assert position.status == PlanPositionStatus.approved, "позиция не ушла в released"
    assert await _balance_qty(session, product_id, raw_id) == Decimal(30)
    assert body["issue_summary"] is None


async def test_take_to_work_partial_strategy_collects_available_and_reports_deficit(client, session) -> None:
    """``partial`` собирает сколько есть, а дефицит — итог, а не ошибка."""
    user = await _make_user(session, "ISSPART@local")
    headers = _auth_headers(user)
    fx = await _make_dim_route_fixture(session, sku="ISSPART", qty=Decimal(100))
    product_id = fx["product"].id
    position_id = fx["position"].id
    raw_id = fx["sections"][0].id
    await _seed(session, product_id=product_id, location_id=raw_id, qty=Decimal(30), ops=RAW_OPS, user_id=user.id)
    await session.commit()

    body = await _take(
        client, headers,
        position_ids=[position_id],
        release_quantity="100",
        issue={"shortage_strategy": "partial", "idempotency_key": "isspart-1"},
    )
    summary = body["results"][0]["issue"]
    assert (summary["required"], summary["collected"], summary["deficit"]) == ("100", "30", "70")
    assert len(summary["transfers"]) == 1
    assert summary["transfers"][0]["quantity"] == "30"
    assert await _balance_qty(session, product_id, raw_id) == Decimal(0)
    await assert_no_invariants_violations(session, context="partial deficit")


async def test_take_to_work_negative_remainder_drains_warehouse_into_minus(client, session) -> None:
    """``negative_remainder``: последняя передача добирает дефицит складом в минус.

    Проводка обязана пройти с ``allow_negative`` (#133): 100 шт. при 30 на
    складе → баланс ``-70``, а не отказ и не «выдали 30».
    """
    user = await _make_user(session, "ISSNEG@local")
    headers = _auth_headers(user)
    fx = await _make_dim_route_fixture(session, sku="ISSNEG", qty=Decimal(100))
    product_id = fx["product"].id
    position_id = fx["position"].id
    raw_id = fx["sections"][0].id
    await _seed(session, product_id=product_id, location_id=raw_id, qty=Decimal(30), ops=RAW_OPS, user_id=user.id)
    await session.commit()

    body = await _take(
        client, headers,
        position_ids=[position_id],
        release_quantity="100",
        issue={"shortage_strategy": "negative_remainder", "idempotency_key": "issneg-1"},
    )
    summary = body["results"][0]["issue"]
    assert (summary["collected"], summary["deficit"]) == ("100", "0")
    assert summary["transfers"][0]["quantity"] == "100"
    assert await _balance_qty(session, product_id, raw_id) == Decimal(-70), "осознанный минус склада"
    sends = await _sends(session)
    assert len(sends) == 1 and Decimal(sends[0].quantity) == Decimal(100)
    await assert_no_stock_ledger_invariants_violations(session, context="negative remainder")


async def test_group_take_to_work_runs_auto_only_with_single_summary(client, session) -> None:
    """Групповой запуск: только ``auto``, один общий итог с ``issue_no = null``.

    Галочки принадлежат позиции, поэтому в группе они запрещены (422), а
    сводка по всему запуску одна: «собрано X из Y, дефицит Z» сразу по всем
    позициям (#282).
    """
    a = await _two_warehouse_setup(session, "ISSGRP-A")
    b = await _two_warehouse_setup(session, "ISSGRP-B")

    rejected = await client.post(
        TAKE,
        json={"position_ids": [a["position_id"], b["position_id"]],
              "issue": {"auto": False, "excluded_balance_ids": [1]}},
        headers=a["headers"],
    )
    assert rejected.status_code == 422, rejected.text

    body = await _take(client, a["headers"], position_ids=[a["position_id"], b["position_id"]],
                       issue={"auto": True})
    summary = body["issue_summary"]
    assert summary is not None
    assert summary["issue_no"] is None, "в группе один общий итог, а не номер одной из выдач"
    assert (summary["required"], summary["collected"], summary["deficit"]) == ("200", "200", "0")
    # Каждая позиция вычерпывает свои два склада: 4 передачи на две позиции.
    assert len(summary["transfers"]) == 4
    assert len({t["transfer_no"] for t in summary["transfers"]}) == 4
    per_issue = [r["issue"]["issue_no"] for r in body["results"]]
    assert all(i and i.startswith("ISS-") for i in per_issue)
    assert len(set(per_issue)) == 2, "у позиций разные номера выдачи"
    assert len(await _transfers(session)) == 4
    await assert_no_invariants_violations(session, context="group issue")


async def test_take_to_work_idempotent_repeat_does_not_duplicate_issue(client, session) -> None:
    """Повтор того же запуска с тем же ``idempotency_key`` не плодит выдачу.

    Инвариант: ни новых передач, ни новых проводок. Контракт роута при этом
    — «позиция уже в работе» (``already_started``), а не второй итог:
    повторный запуск позиции блокируется раньше, чем подбор успевает
    списать склад второй раз.
    """
    ctx = await _two_warehouse_setup(session, "ISSIDEM")
    first = await _take(
        client, ctx["headers"],
        position_ids=[ctx["position_id"]],
        release_quantity="60",
        issue={"shortage_strategy": "partial", "idempotency_key": "issidem-1"},
    )
    issue_no = first["results"][0]["issue"]["issue_no"]
    transfers_before = len(await _transfers(session))
    sends_before = len(await _sends(session))

    repeat = await _take(
        client, ctx["headers"],
        position_ids=[ctx["position_id"]],
        release_quantity="60",
        issue={"shortage_strategy": "partial", "idempotency_key": "issidem-1"},
    )
    result = repeat["results"][0]
    assert result["status"] in {"already_started", "success"}, result
    replay_issue = (result["issue"] or {}).get("issue_no")
    assert replay_issue in (None, issue_no), "повтор не может выдать другой номер выдачи"
    assert len(await _transfers(session)) == transfers_before
    assert len(await _sends(session)) == sends_before, "идемпотентный повтор не списывает склад дважды"


# ─── Пропущенные этапы: свои против чужих ──────────────────────────────────


async def test_cancel_issue_restores_only_its_own_skipped_stages(client, session) -> None:
    """Выдача на этап 3 помечает этап 2 «Пропущено» своим номером.

    Отмена обязана снять **только** пропуски этого ``issue_no``: пропуск с
    чужим номером и ручной пропуск (``skipped_by_issue_no IS NULL``, #207)
    обязаны остаться нетронутыми. Колонка заведена ровно ради этого —
    реализация, снимающая «все skipped подряд», валит именно этот тест.
    """
    ctx = await _two_warehouse_setup(session, "ISSSKIP")
    body = await _take(
        client, ctx["headers"],
        position_ids=[ctx["position_id"]],
        release_quantity="40",
        issue={"shortage_strategy": "partial", "idempotency_key": "issskip-1"},
    )
    issue_no = body["results"][0]["issue"]["issue_no"]
    skipped = body["results"][0]["issue"]["skipped_stages"]
    assert [s["sequence"] for s in skipped] == [2], skipped
    our_task_id = skipped[0]["task_id"]

    # Чужие пропуски — на заданиях другой позиции этого же модуля: у неё
    # своя выдача не запускалась, поэтому её пропуски не принадлежат ISS_NO.
    other = await _make_dim_route_fixture(session, sku="ISSSKIP-B", qty=Decimal(10))
    other_position_id = other["position"].id
    await _take(client, ctx["headers"], position_ids=[other_position_id])
    other_task_ids = [
        t.id
        for t in (
            await session.execute(
                select(WorkTask)
                .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
                .where(SectionPlanLine.plan_position_id == other_position_id)
                .order_by(WorkTask.id)
            )
        ).scalars().all()
    ]
    assert other_task_ids, "на второй позиции есть задания, чтобы повесить чужой пропуск"
    foreign_numbered, foreign_manual = other_task_ids[0], other_task_ids[-1]
    task = await session.get(WorkTask, foreign_numbered)
    task.status = WorkTaskStatus.skipped
    task.skip_reason = "Чужая выдача"
    task.skipped_by_issue_no = "ISS-FOREIGN-1"
    task = await session.get(WorkTask, foreign_manual)
    task.status = WorkTaskStatus.skipped
    task.skip_reason = "Материал подготовлен заранее"
    task.skipped_by_issue_no = None
    await session.commit()

    ours = await session.get(WorkTask, our_task_id)
    assert ours.status == WorkTaskStatus.skipped and ours.skipped_by_issue_no == issue_no

    resp = await client.post(
        f"/api/transfers/issues/{issue_no}/cancel",
        params={"comment": "подбор нужно пересобрать"},
        headers=ctx["headers"],
    )
    assert resp.status_code == 200, resp.text

    ours = await session.get(WorkTask, our_task_id)
    assert ours.status != WorkTaskStatus.skipped, "свой пропуск снят"
    assert ours.skipped_by_issue_no is None and ours.skip_reason is None

    manual = await session.get(WorkTask, foreign_manual)
    assert manual.status == WorkTaskStatus.skipped
    assert manual.skipped_by_issue_no is None
    assert manual.skip_reason == "Материал подготовлен заранее", "ручной пропуск не принадлежит выдаче"

    foreign = await session.get(WorkTask, foreign_numbered)
    assert foreign.status == WorkTaskStatus.skipped
    assert foreign.skipped_by_issue_no == "ISS-FOREIGN-1", "чужой пропуск не принадлежит этой отмене"
    await assert_no_invariants_violations(session, context="cancel restores own skips")


# ─── Отмена выдачи целиком ─────────────────────────────────────────────────


async def test_issue_cancel_preview_reports_names_not_ids(client, session) -> None:
    """``cancel-preview`` — «вернём 40 на „Хранилище Б“, 20 на „RAW“, …».

    В ``summary`` и ``reason`` оператору нечего сказать про ``balance 47``:
    только имена складов и количества.
    """
    ctx = await _two_warehouse_setup(session, "ISSCPRV")
    body = await _take(
        client, ctx["headers"],
        position_ids=[ctx["position_id"]],
        release_quantity="60",
        issue={"shortage_strategy": "partial", "idempotency_key": "isscprv-1"},
    )
    issue_no = body["results"][0]["issue"]["issue_no"]
    transfer_ids = [t.id for t in await _transfers(session, issue_no)]

    resp = await client.get(
        f"/api/transfers/issues/{issue_no}/cancel-preview", headers=ctx["headers"]
    )
    assert resp.status_code == 200, resp.text
    preview = resp.json()
    assert preview["issue_no"] == issue_no
    assert preview["can_cancel"] is True and preview["reason"] is None
    assert len(preview["returns"]) == len(transfer_ids) == 2
    assert {r["location_name"] for r in preview["returns"]} == {"Хранилище Б", ctx["raw_name"]}
    assert {Decimal(r["quantity"]) for r in preview["returns"]} == {Decimal(40), Decimal(20)}

    summary = preview["summary"]
    assert "вернём" in summary and "Хранилище Б" in summary, summary
    _assert_no_ids_in(
        summary,
        [ctx["product_id"], ctx["raw_id"], ctx["whb_id"], ctx["position_id"], *transfer_ids],
        allow=[1, 2, 3, 40, 20, 60, 100, 80],
    )

    unknown = await client.get(
        "/api/transfers/issues/ISS-000000000000000000/cancel-preview", headers=ctx["headers"]
    )
    assert unknown.status_code == 404
    assert "не найдена" in unknown.json()["detail"]


async def test_cancel_issue_reverses_ledger_and_refuses_repetition(client, session) -> None:
    """Отмена выдачи: компенсирующие проводки, возврат балансов, журнал действий.

    Каждая передача откатывается своим ``transfer_send`` Action (ADR-0019),
    поэтому у компенсации есть ``reverses_id`` и собственный ``action_id``.
    Повторная отмена обязана отказаться, а не вернуть склад второй раз.
    """
    ctx = await _two_warehouse_setup(session, "ISSCANC")
    body = await _take(
        client, ctx["headers"],
        position_ids=[ctx["position_id"]],
        release_quantity="60",
        issue={"shortage_strategy": "partial", "idempotency_key": "isscanc-1"},
    )
    issue_no = body["results"][0]["issue"]["issue_no"]
    product_id = ctx["product_id"]
    before = await _snapshot(session, product_id)

    resp = await client.post(
        f"/api/transfers/issues/{issue_no}/cancel",
        params={"comment": "артикул не тот"},
        headers=ctx["headers"],
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["issue_no"] == issue_no
    assert len(payload["cancelled_transfers"]) == 2

    for transfer in await _transfers(session, issue_no):
        assert transfer.status == TransferStatus.cancelled

    reversals = list(
        (
            await session.execute(
                select(StockTransaction)
                .where(StockTransaction.reverses_id.is_not(None))
                .order_by(StockTransaction.id)
            )
        ).scalars().all()
    )
    assert len(reversals) >= 2, "возврат материала обязан быть зеркальной проводкой"
    assert all(t.action_id is not None for t in reversals), "компенсация оформлена действием журнала"
    assert await _balance_qty(session, product_id, ctx["whb_id"]) == Decimal(40)
    assert await _balance_qty(session, product_id, ctx["raw_id"]) == Decimal(100)
    after_cancel = await _snapshot(session, product_id)
    assert after_cancel["actions"] > before["actions"], "отмена оформлена действиями журнала"
    assert after_cancel["txs"] == before["txs"] + len(reversals), (
        "отмена пишет ровно компенсирующие проводки, без лишних движений"
    )
    await assert_no_invariants_violations(session, context="issue cancelled")
    await assert_no_stock_ledger_invariants_violations(session, context="issue cancelled")

    again = await client.post(
        f"/api/transfers/issues/{issue_no}/cancel",
        params={"comment": "ещё раз"},
        headers=ctx["headers"],
    )
    assert again.status_code == 400, again.text
    assert "уже отменена" in again.json()["detail"]
    assert (await _snapshot(session, product_id))["txs"] == after_cancel["txs"], (
        "повторная отмена не добавляет ни одной проводки"
    )


async def test_issue_cancel_without_executed_work_is_allowed_despite_auto_accept(client, session) -> None:
    """Авто-приёмка сама по себе не блокирует полную отмену (ADR-0071).

    ``_record_issue_transfer`` выставляет ``accepted`` сразу при создании
    передачи. Если читать запрет «часть принята → не отменить» буквально по
    статусу, отменить выдачу было бы нельзя никогда: система сама создавала
    бы основание для отказа. Основание — фактическое действие получателя.
    """
    ctx = await _two_warehouse_setup(session, "ISSAUTO")
    body = await _take(
        client, ctx["headers"],
        position_ids=[ctx["position_id"]],
        release_quantity="60",
        issue={"shortage_strategy": "partial", "idempotency_key": "issauto-1"},
    )
    issue_no = body["results"][0]["issue"]["issue_no"]
    rows = await _transfers(session, issue_no)
    assert rows and all(t.status == TransferStatus.accepted for t in rows), "приёмка автоматическая"

    preview = await client.get(
        f"/api/transfers/issues/{issue_no}/cancel-preview", headers=ctx["headers"]
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_cancel"] is True, (
        "авто-приёмка без фактического действия получателя — не основание отказа"
    )
    cancel = await client.post(
        f"/api/transfers/issues/{issue_no}/cancel", headers=ctx["headers"]
    )
    assert cancel.status_code == 200, cancel.text
    assert await _balance_qty(session, ctx["product_id"], ctx["whb_id"]) == Decimal(40)
    assert await _balance_qty(session, ctx["product_id"], ctx["raw_id"]) == Decimal(100)
