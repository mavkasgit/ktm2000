#!/usr/bin/env python
"""Ремонт оси «пройденные операции» в ledger и балансах (ADR-0061, #272).

Что чинится
-----------
До ADR-0061 признак выводился из справочника УЧАСТКА — объединение
``section_operations.operation_code`` всех секций пройденных этапов. Один
остаток нёс операции, которых материал не проходил: у 2,7 м лежали резы на
0,9/1,35/1,8 м, у чёрного профиля — все цвета анодирования. Теперь источник —
операции ЭТАПА (``route_operations``), но уже записанные оси остались грубыми,
а списание ищет ТОЧНУЮ группу остатка (ADR-0055): на полном участке оно
находит грубую строку и падает. Поэтому оси нужно пересчитать.

Что делает скрипт
-----------------
1. Для каждой плановой проводки (``task_id``/``section_plan_line_id``)
   восстанавливает точный признак по маршруту её задания. Какой этап имелся в
   виду, определяется по записанному грубому значению: у проводки ровно два
   возможных смысла — «до своего этапа» (выпуск, передача) и «до предыдущего»
   (потребление входа, возврат, брак) — и совпадает с прежней, участковой осью
   обычно только один.
2. Приём передачи (``TRANSFER_RECEIVE``) зеркалит отправку той же передачи, а
   компенсация (``reverses_id``) — исходную проводку: так требует
   ``StockCommandService.record()``.
3. Импорт остатков (``source_ref`` с префиксом ``import_remainders:``) и ручные
   правки не трогаются: у них признак пришёл из Excel или выбран оператором, и
   переписать его «по маршруту» — значит соврать.
4. С ``--apply`` значения записываются и балансы пересобираются целиком
   (``rebuild_all_balances``). Проводки, ось которых не совпала ни с одним
   кандидатом, печатаются отдельно и не трогаются: молчаливая правка «наугад»
   запрещена (ADR-0021).

Запуск (из ``backend/``):

    ENV_FILE=../.env.dev python scripts/repair_completed_operations_axis.py
    ENV_FILE=../.env.dev python scripts/repair_completed_operations_axis.py --apply

Идемпотентен: на починенной базе изменений не находит.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.check_canon_drift import describe_target, env_file_problem

if TYPE_CHECKING:
    from app.models import StockTransaction
    from sqlalchemy.ext.asyncio import AsyncSession

IMPORT_SOURCE_REF_PREFIX = "import_remainders:"


@dataclass
class RouteAxis:
    """Признак по этапам маршрута: точный (новый) и прежний (участковый)."""

    new_by_seq: dict[int, set[str]] = field(default_factory=dict)
    old_by_seq: dict[int, set[str]] = field(default_factory=dict)
    sequences: list[int] = field(default_factory=list)

    def cumulative(self, store: dict[int, set[str]], through: int) -> list[str]:
        codes: set[str] = set()
        for seq in self.sequences:
            if seq > through:
                break
            codes.update(store.get(seq, ()))
        return sorted(codes)

    def previous(self, sequence: int) -> int | None:
        earlier = [seq for seq in self.sequences if seq < sequence]
        return earlier[-1] if earlier else None

    def match(self, stored: set[str], preferred: int | None) -> tuple[int | None, list[int]]:
        """Этап, которому соответствует записанная ось, и все совпавшие этапы.

        Сначала проверяется предпочтительный этап (свой или предыдущий — как
        его выбирал вызывающий), затем остальные: значение хранится и в
        прежнем (участковом), и в новом (этапном) виде, поэтому повторный
        прогон скрипта находит своё же значение. Несколько совпавших этапов —
        неоднозначность: её печатают, а не прячут (ADR-0021).
        """
        order = [seq for seq in dict.fromkeys(chain(self.preferred_order(preferred), self.sequences)) if seq]
        hits = [
            seq
            for seq in order
            if stored == set(self.cumulative(self.old_by_seq, seq))
            or stored == set(self.cumulative(self.new_by_seq, seq))
        ]
        return (hits[0] if hits else None), hits

    def preferred_order(self, preferred: int | None) -> list[int]:
        return [seq for seq in (preferred, self.previous(preferred)) if seq] if preferred else []


@dataclass
class Change:
    tx_id: int
    reason: str
    task_id: int | None
    route_id: int | None
    sequence: int | None
    before: list[str]
    after: list[str]


async def _load_axes(db: AsyncSession, route_ids: set[int]) -> dict[int, RouteAxis]:
    """Оси маршрутов: точная (операции этапа) и прежняя (операции участка этапа)."""
    from app.models.route import RouteStage, SectionOperation
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    if not route_ids:
        return {}
    stages = (
        (
            await db.execute(
                select(RouteStage)
                .options(selectinload(RouteStage.operations))
                .where(RouteStage.route_id.in_(route_ids))
                .order_by(RouteStage.route_id, RouteStage.sequence)
            )
        )
        .scalars()
        .all()
    )
    section_ids = {stage.section_id for stage in stages if stage.section_id is not None}
    section_ops: dict[int, set[str]] = defaultdict(set)
    if section_ids:
        rows = (
            await db.execute(
                select(SectionOperation.section_id, SectionOperation.operation_code).where(
                    SectionOperation.section_id.in_(section_ids),
                    SectionOperation.operation_code.isnot(None),
                )
            )
        ).all()
        for section_id, code in rows:
            section_ops[section_id].add(code)

    axes: dict[int, RouteAxis] = {}
    for stage in stages:
        axes.setdefault(stage.route_id, RouteAxis()).sequences.append(stage.sequence)
    for stage in stages:
        axis = axes[stage.route_id]
        axis.new_by_seq.setdefault(stage.sequence, set()).update(
            op.operation_code for op in stage.operations if op.operation_code is not None
        )
        # Прежняя ось брала операции секции этапа; у транзитных этапов
        # `section_id` пуст, и они не давали ничего — как и сейчас.
        if stage.section_id is not None:
            axis.old_by_seq.setdefault(stage.sequence, set()).update(
                section_ops.get(stage.section_id, set())
            )
    return axes


async def _axis_owner(db: AsyncSession, tx: StockTransaction) -> tuple[int, int] | None:
    """``(route_id, sequence этапа задания)`` для плановой проводки."""
    from app.models.internal_plan import SectionPlanLine
    from app.models.route import RouteStage
    from app.models.work_task import WorkTask

    if tx.task_id is None:
        if tx.section_plan_line_id is None:
            return None
        line = await db.get(SectionPlanLine, tx.section_plan_line_id)
        return (line.route_id, 0) if line is not None else None
    task = await db.get(WorkTask, tx.task_id)
    if task is None or task.section_plan_line_id is None:
        return None
    line = await db.get(SectionPlanLine, task.section_plan_line_id)
    if line is None:
        return None
    stage = await db.get(RouteStage, task.route_stage_id) if task.route_stage_id else None
    return line.route_id, (stage.sequence if stage is not None else 0)


async def run_repair(session: AsyncSession, *, execute: bool) -> int:
    """Пересчитать оси и (с ``execute``) записать их; вернуть код выхода."""
    from app.models import Reason, StockTransaction
    from app.models.route import SectionOperation
    from sqlalchemy import select

    txs = (
        (
            await session.execute(
                select(StockTransaction)
                .where(StockTransaction.completed_operations.isnot(None))
                .order_by(StockTransaction.id)
            )
        )
        .scalars()
        .all()
    )

    def is_import(tx: StockTransaction) -> bool:
        return bool(tx.source_ref and tx.source_ref.startswith(IMPORT_SOURCE_REF_PREFIX))

    manual_reasons = {
        Reason.MANUAL_IN,
        Reason.MANUAL_OUT,
        Reason.ADJUSTMENT_IN,
        Reason.ADJUSTMENT_OUT,
    }
    owners: dict[int, tuple[int, int] | None] = {}
    route_ids: set[int] = set()
    for tx in txs:
        if tx.reverses_id is not None or is_import(tx):
            continue
        owner = await _axis_owner(session, tx)
        owners[tx.id] = owner
        if owner is not None:
            route_ids.add(owner[0])
    axes = await _load_axes(session, route_ids)
    # Справочник участков целиком: тем же множеством кодов проверяет запись
    # ``assert_known_operation_codes``. Страж ниже смотрит только на те
    # значения, которые скрипт действительно пишет.
    all_known_codes = set(
        (
            await session.execute(
                select(SectionOperation.operation_code).where(
                    SectionOperation.operation_code.isnot(None)
                )
            )
        )
        .scalars()
        .all()
    )

    resolved: dict[int, list[str] | None] = {}
    skipped: list[tuple[int, str, str]] = []
    unmatched: list[tuple[int, str]] = []
    ambiguous: list[tuple[int, str, list[int]]] = []

    def resolve_plan_driven(tx: StockTransaction) -> list[str]:
        stored = list(tx.completed_operations or [])
        owner = owners.get(tx.id)
        if owner is None:
            skipped.append((tx.id, tx.reason.value, "нет задания/строки плана"))
            return stored
        route_id, own_sequence = owner
        axis = axes.get(route_id)
        if axis is None or not axis.sequences:
            unmatched.append((tx.id, f"маршрут #{route_id} без этапов"))
            return stored
        sequence, hits = axis.match(set(stored), own_sequence or None)
        if sequence is None:
            unmatched.append((tx.id, f"ось не совпала ни с одним этапом маршрута #{route_id}"))
            return stored
        if len({tuple(axis.cumulative(axis.new_by_seq, seq)) for seq in hits}) > 1:
            # Записанное значение подходит нескольким этапам с РАЗНЫМИ
            # точными осями (причина проводки не различает их: ``SCRAP``
            # пишут и выпуск, и решение по дефекту). Выбрать одну — гадание,
            # запрещённое ADR-0021: строку не трогаем, а печатаем.
            ambiguous.append((tx.id, f"маршрут #{route_id}", hits))
            return stored
        return axis.cumulative(axis.new_by_seq, sequence)

    # Порядок разрешения: сначала обычные плановые проводки, затем приёмы
    # передач (зеркалят отправку) и компенсации (зеркалят исходную).
    receives = [tx for tx in txs if tx.reason == Reason.TRANSFER_RECEIVE and tx.transfer_id]
    compensations = [tx for tx in txs if tx.reverses_id is not None]
    for tx in txs:
        if tx in receives or tx in compensations:
            continue
        if is_import(tx) or tx.reason in manual_reasons:
            skipped.append(
                (tx.id, tx.reason.value, "импорт остатков" if is_import(tx) else "ручная правка")
            )
            resolved[tx.id] = list(tx.completed_operations or [])
            continue
        resolved[tx.id] = resolve_plan_driven(tx)

    # Только ИСХОДНЫЕ отправки: компенсация отменённой передачи — тоже
    # `TRANSFER_SEND` с тем же `transfer_id`, но её `reverses_id` не пуст,
    # в `resolved` она не попала, и она затирала значение исходной отправки
    # пустым списком (строки идут по id, компенсация позже). Приём такой
    # передачи тогда получал пустой признак вместо зеркала отправки —
    # тихо и неверно (ADR-0021).
    sends_by_transfer: dict[int, list[str]] = {}
    for tx in txs:
        if (
            tx.reason == Reason.TRANSFER_SEND
            and tx.transfer_id is not None
            and tx.reverses_id is None
        ):
            sends_by_transfer[tx.transfer_id] = list(resolved.get(tx.id) or [])
    for tx in receives:
        stored = list(tx.completed_operations or [])
        mirror = sends_by_transfer.get(tx.transfer_id)
        if mirror is None:
            unmatched.append((tx.id, "приём передачи без отправки"))
            resolved[tx.id] = stored
        else:
            resolved[tx.id] = mirror

    for tx in compensations:
        stored = list(tx.completed_operations or [])
        source = resolved.get(tx.reverses_id)
        if source is None:
            unmatched.append((tx.id, f"компенсация проводки #{tx.reverses_id} не разрешена"))
            resolved[tx.id] = stored
        else:
            resolved[tx.id] = list(source)

    changes = [
        Change(
            tx_id=tx.id,
            reason=tx.reason.value,
            task_id=tx.task_id,
            route_id=(owners.get(tx.id) or (None, None))[0],
            sequence=(owners.get(tx.id) or (None, None))[1] or None,
            before=list(tx.completed_operations or []),
            after=list(resolved[tx.id] or []),
        )
        for tx in txs
        if resolved.get(tx.id) is not None
        and set(resolved[tx.id] or []) != set(tx.completed_operations or [])
    ]

    print(f"Проводок с признаком: {len(txs)}")
    for change in changes:
        print(
            f"  tx #{change.tx_id} {change.reason} task={change.task_id} "
            f"route={change.route_id} seq={change.sequence}: "
            f"{len(change.before)} -> {len(change.after)} кодов"
        )
        print(f"      было:  {change.before}")
        print(f"      стало: {change.after}")
    print(f"Изменится: {len(changes)}; без изменений: {len(txs) - len(changes)}")
    print(f"Пропущено (импорт/ручное/вне плана): {len(skipped)}")
    for tx_id, reason, why in skipped[:20]:
        print(f"  tx #{tx_id} {reason}: {why}")
    if len(skipped) > 20:
        print(f"  … ещё {len(skipped) - 20}")
    if unmatched:
        print(f"НЕ РАЗОБРАНО: {len(unmatched)} — не тронуты")
        for tx_id, why in unmatched[:20]:
            print(f"  tx #{tx_id}: {why}")
    if ambiguous:
        print(f"НЕОДНОЗНАЧНО: {len(ambiguous)} — не тронуты")
        for tx_id, route, hits in ambiguous[:20]:
            print(f"  tx #{tx_id} {route}: подходят этапы {hits} — этап не определить")

    # Признак без кода в справочнике участков не разрешится ни в подпись
    # ячейки, ни в фильтр: строка остатка отличалась бы от соседней, а в UI
    # была бы неотличима (ADR-0055 п.5). Такую запись не пишем.
    unknown_codes = sorted(
        {code for change in changes for code in change.after} - all_known_codes
    )
    if unknown_codes:
        print(f"КОДОВ ВНЕ СПРАВОЧНИКА: {len(unknown_codes)} — {unknown_codes}")

    if not execute:
        print("\nЭто dry-run: ничего не записано. Повторить с --apply.")
        return 0
    if unknown_codes:
        print("\nЗапись отменена: признак содержит коды вне справочника участков.")
        return 2
    if ambiguous:
        print(
            "\nНеоднозначные строки не переписаны: их этап не определить по "
            "записанному значению (см. список выше)."
        )
    if not changes:
        print("\nНечего записывать.")
        return 0

    for tx in txs:
        target = resolved.get(tx.id)
        if target is not None:
            tx.completed_operations = target
    await session.flush()

    from app.stock.services import StockProjectionManager

    rebuilt = await StockProjectionManager().rebuild_all_balances(session)
    await session.commit()
    print(f"\nЗаписано проводок: {len(changes)}; пересобрано строк баланса: {rebuilt}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI: DSN из env-файла, dry-run по умолчанию."""
    parser = argparse.ArgumentParser(
        description="Ремонт оси «пройденные операции» в ledger и балансах (ADR-0061)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="записать пересчитанные оси и пересобрать балансы (по умолчанию только показать)",
    )
    args = parser.parse_args(argv)

    # До импорта приложения: pydantic отдал бы приоритет окружению процесса.
    from app.core.env_file import apply_env_file, env_file_path

    problem = env_file_problem(env_file_path())
    if problem is not None:
        print(f"Ремонт оси невозможен: {problem}.", file=sys.stderr)
        return 2
    apply_env_file()

    from app.core.config import settings
    from app.core.database import async_session

    print(f"Проверяем БД: {describe_target(settings.DATABASE_URL)}")
    print("Режим: ЗАПИСЬ" if args.apply else "Режим: dry-run (ничего не записывается)")

    async def _run() -> int:
        async with async_session() as session:
            return await run_repair(session, execute=args.apply)

    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
