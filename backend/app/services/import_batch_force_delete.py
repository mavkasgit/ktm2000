"""Принудительное удаление батча импорта «поверх» живых данных.

Задача: оператор видит блокеры удаления (released-позиции, передачи вниз по
цепочке) и всё равно хочет убрать импорт из актуальных данных, зная о
последствиях. Обычный ``delete_import_batch`` в этом случае отвечает 409, а
``delete_production_plan`` — 409 от reversal с дефицитом покрытия: откат
проводок требует вернуть материал на склад, которого там уже нет (демо-данные
созданы без входных остатков).

Поэтому force-путь не «откатывает», а **удаляет поддерево батча целиком**:
позиции, линии, задания, передачи, брак и их проводки ledger. Балансы после
этого пересчитываются из оставшегося ledger — то есть склад возвращается в
состояние «до импорта, до проводов, до передач», как и просит оператор.

История при этом не теряется: записи ``action_journal`` по удалённым заданиям
переводятся в ``purged`` (соглашение ADR-0019 п.7 — записи журнала не
удаляются, это аудит), а одна новая запись ``import_batch_force_delete``
фиксирует, что именно и по чьей причине снесено. Параллельно пишется
``AuditLog`` с полным превью «до».

Что останавливает даже force (это не политика, а целостность):

* передача, один конец которой вне батча — снести её значит испортить чужой
  импорт (``transfer_crosses_batch``);
* проводка батча, компенсирующая чужую проводку — удаление изменит эффект
  чужой операции (``compensates_foreign_transaction``);
* несовпадение ``confirmation``/пустая причина — до любых записей.

Всё остальное оператор подтверждает осознанно: превью с цифрами последствий
и обязательное поле причины.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_journal import Action, ActionStatus
from app.models.audit_log import AuditAction, AuditEntityType
from app.models.imports import ImportBatch
from app.models.internal_plan import SectionPlanLine
from app.models.production_plan import PlanChangeItem, PlanChangeSet, PlanPosition
from app.models.user import User
from app.models.work_task import WorkTask
from app.services.audit_log_service import log_action
from app.services.action_journal_service import action_journal_service
from app.services.material_operations import completed_operation_stages
from app.services.production_plan_service import _delete_batch_and_orphan_file
from app.stock.services import StockProjectionManager
from app.stock.import_service import resolve_operations_dictionary
from app.stock.models import QualityState

#: Коды причин, по которым force невозможен даже с подтверждением оператора.
FORCE_BLOCK_TRANSFER_CROSSES_BATCH = "transfer_crosses_batch"
FORCE_BLOCK_FOREIGN_COMPENSATION = "compensates_foreign_transaction"

#: Минимальная длина причины: «почему снесли производство» — не пустое слово.
MIN_REASON_LENGTH = 3


class BatchForceDeleteBlocked(Exception):
    """Force-удаление невозможно: остаётся чужаяdata в каскаде.

    Роутер мапит в 409 с теми же blockers, что и обычный 409 удаления, плюс
    ``safe_action``, чтобы UI показал экран блокировок, а не «ошибка 500».
    """

    def __init__(self, blockers: list[dict], drafts: int) -> None:
        super().__init__("force delete blocked")
        self.blockers = blockers
        self.drafts = drafts


class _Footprint:
    """Множества id удаляемого поддерева — один источник для превью и каскада.

    Собирается один раз превью и переиспользуется удалением: расхождение между
    «что показали» и «что снесли» — самый дорогой вид бага в админской операции.
    """

    def __init__(self) -> None:
        self.position_ids: list[int] = []
        self.line_ids: list[int] = []
        self.task_ids: list[int] = []
        self.transfer_ids: list[int] = []
        self.defect_ids: list[int] = []
        self.tx_ids: list[int] = []
        self.stock_effects: list[dict] = []

    def counts(self) -> dict:
        return {
            "positions": len(self.position_ids),
            "section_plan_lines": len(self.line_ids),
            "work_tasks": len(self.task_ids),
            "transfers": len(self.transfer_ids),
            "defects": len(self.defect_ids),
            "ledger_entries": len(self.tx_ids),
        }


async def _batch_filename(db: AsyncSession, batch: ImportBatch) -> str:
    from app.models.imports import ImportFile

    file = await db.get(ImportFile, batch.source_file_id)
    return file.original_filename if file is not None else f"batch-{batch.id}"


async def _collect_footprint(db: AsyncSession, batch_id: int) -> _Footprint:
    """Собрать поддерево батча: позиции → линии → задания → передачи → ledger.

    Проводки берём по трём точкам привязки (задание, передача, линия плана):
    учётные проводки плана могут нести ``task_id = NULL``, и по одной колонке
    они бы потерялись.
    """
    from app.models.defect import Defect
    from app.models.product import Product
    from app.models.section import Section
    from app.models.transfer import Transfer
    from app.stock.models import StockTransaction

    fp = _Footprint()
    fp.position_ids = list(
        (
            await db.execute(
                select(PlanPosition.id).where(PlanPosition.import_batch_id == batch_id)
            )
        ).scalars()
    )
    if not fp.position_ids:
        return fp

    line_rows = (
        await db.execute(
            select(SectionPlanLine.id, SectionPlanLine.plan_position_id).where(
                SectionPlanLine.plan_position_id.in_(fp.position_ids)
            )
        )
    ).all()
    fp.line_ids = [line_id for line_id, _ in line_rows]

    if fp.line_ids:
        fp.task_ids = list(
            (
                await db.execute(
                    select(WorkTask.id).where(
                        WorkTask.section_plan_line_id.in_(fp.line_ids)
                    )
                )
            ).scalars()
        )

    if fp.task_ids:
        fp.transfer_ids = list(
            (
                await db.execute(
                    select(Transfer.id).where(
                        or_(
                            Transfer.from_task_id.in_(fp.task_ids),
                            Transfer.to_task_id.in_(fp.task_ids),
                        )
                    )
                )
            ).scalars()
        )
        fp.defect_ids = list(
            (
                await db.execute(
                    select(Defect.id).where(Defect.task_id.in_(fp.task_ids))
                )
            ).scalars()
        )

    tx_filters = []
    if fp.task_ids:
        tx_filters.append(StockTransaction.task_id.in_(fp.task_ids))
    if fp.transfer_ids:
        tx_filters.append(StockTransaction.transfer_id.in_(fp.transfer_ids))
    if fp.line_ids:
        tx_filters.append(StockTransaction.section_plan_line_id.in_(fp.line_ids))
    if not tx_filters:
        return fp

    rows = (
        await db.execute(
            select(
                StockTransaction.id,
                StockTransaction.reverses_id,
                StockTransaction.product_id,
                StockTransaction.from_location_id,
                StockTransaction.to_location_id,
                StockTransaction.from_quality_state,
                StockTransaction.to_quality_state,
                StockTransaction.dimensions,
                StockTransaction.completed_operations,
                StockTransaction.quantity,
                StockTransaction.action_id,
                Product.sku,
            )
            .join(Product, Product.id == StockTransaction.product_id)
            .where(or_(*tx_filters))
            .order_by(StockTransaction.id)
        )
    ).all()

    fp.tx_ids = [int(r.id) for r in rows]
    locations = {
        int(r.id): r.code
        for r in (
            await db.execute(
                select(Section.id, Section.code).where(
                    Section.id.in_(
                        {
                            loc
                            for r in rows
                            for loc in (r.from_location_id, r.to_location_id)
                            if loc is not None
                        }
                        or {0}
                    )
                )
            )
        ).all()
    }
    fp.stock_effects = _aggregate_stock_effects(
        rows, locations, await resolve_operations_dictionary(db) if rows else []
    )
    return fp


def _aggregate_stock_effects(
    rows, locations: dict[int, str], operations: list[dict]
) -> list[dict]:
    """Свод по проводкам батча: чистый эффект на каждый ключ остатка.

    Это ровно то изменение остатка, которое увидит склад после удаления:
    входящие плюсуются, исходящие вычитаются, компенсации (reverses_id)
    сокращают эффект до нуля естественным сложением.

    Ключ повторяет ключ StockBalance, иначе свод врёт: остатки одного
    артикула и участка, но разной длины и разного признака операций —
    разные строки баланса, и сводить их в одну цифру нельзя (ADR-0043 §3).
    Признак операций в свод выводится явно — иначе оператор увидит две
    несопоставимые строки с одинаковыми артикулом, локацией и длиной.

    ``operations`` — справочник ``resolve_operations_dictionary``: по нему
    признак разворачивается в ``completed_stages`` (ADR-0055 §5). Подпись
    в диалоге обязана совпадать с доской остатков («Пресс (окно)», а не
    ``PRESS_WINDOW``), поэтому строки свода несут тот же развитый
    справочником признак, что и строка баланса; пустые состояния различает
    сам ``completed_operations`` (``None`` — «не зафиксировано», ``[]`` —
    «без операций»), у обоих ``completed_stages`` пуст, как и на доске.
    """
    deltas: dict[tuple[str, int, str | None, str | None], Decimal] = {}
    skus: dict[tuple[str, int, str | None, str | None], str] = {}
    dimensions: dict[tuple[str, int, str | None, str | None], dict | None] = {}
    completed_operations: dict[tuple[str, int, str | None, str | None], list | None] = {}
    counts: dict[tuple[str, int, str | None, str | None], int] = {}

    for row in rows:
        sign = Decimal("-1") if row.reverses_id is not None else Decimal("1")
        for location_id, quality_state in (
            (row.to_location_id, row.to_quality_state),
            (row.from_location_id, row.from_quality_state),
        ):
            if location_id is None:
                continue
            key = (
                row.sku,
                int(location_id),
                _dims_signature(row.dimensions),
                _ops_signature(row.completed_operations),
            )
            direction = Decimal("1") if location_id == row.to_location_id else Decimal("-1")
            deltas[key] = deltas.get(key, Decimal("0")) + direction * sign * row.quantity
            skus[key] = row.sku
            dimensions[key] = row.dimensions
            completed_operations[key] = row.completed_operations
            counts[key] = counts.get(key, 0) + 1

    return sorted(
        (
            {
                "product_sku": skus[key],
                "location_id": key[1],
                "location_code": locations.get(key[1], f"section:{key[1]}"),
                "dimensions": dimensions[key],
                "completed_operations": completed_operations[key],
                "completed_stages": completed_operation_stages(
                    completed_operations[key], operations
                ),
                "net_delta": format(deltas[key], "f"),
                "ledger_entries": counts[key],
            }
            for key in deltas
            if deltas[key] != 0
        ),
        key=lambda e: (
            e["product_sku"],
            e["location_code"],
            e["location_id"],
            repr(e["completed_operations"]),
        ),
    )


def _dims_signature(dimensions: dict | None) -> str | None:
    if dimensions is None:
        return None
    return repr(sorted((str(k), str(v)) for k, v in dimensions.items()))


def _ops_signature(ops: list | None) -> str | None:
    """Подпись признака операций для ключа баланса — зеркало ``_dims_signature``.

    ``None`` (состояние не зафиксировано) и ``[]`` (операций не было) —
    разные значения баланса и потому разные подписи (ADR-0043 §2).
    """
    if ops is None:
        return None
    return repr(tuple(str(code) for code in ops))


async def _force_blockers(db: AsyncSession, fp: _Footprint) -> list[dict]:
    """Блокеры целостности, которые force не обходит.

    Оба случая — про границу батча: снести чужое нельзя даже с подтверждением,
    потому что чужая операция после этого перестанет сходиться.
    """
    from app.models.transfer import Transfer
    from app.stock.models import StockTransaction

    blockers: list[dict] = []
    if fp.task_ids:
        from_in = Transfer.from_task_id.in_(fp.task_ids)
        to_in = Transfer.to_task_id.in_(fp.task_ids)
        # Пересечение границы батча = ровно один конец внутри (XOR). Такая
        # передача связывает батч с чужим импортом: снести её — значит
        # испортить чужое, чего подтверждение оператора не разрешает.
        crossing = (
            await db.execute(
                select(Transfer.id, Transfer.transfer_no).where(
                    or_(from_in, to_in), or_(~from_in, ~to_in)
                )
            )
        ).all()
        blockers.extend(
            {
                "position_id": None,
                "reason": f"transfer-crosses-batch #{transfer_id} {transfer_no}",
            }
            for transfer_id, transfer_no in crossing
        )

    if fp.tx_ids:
        foreign = (
            await db.execute(
                select(StockTransaction.id, StockTransaction.reverses_id).where(
                    StockTransaction.id.in_(fp.tx_ids),
                    StockTransaction.reverses_id.is_not(None),
                    StockTransaction.reverses_id.not_in(fp.tx_ids),
                )
            )
        ).all()
        blockers.extend(
            {
                "position_id": None,
                "reason": f"compensates-foreign-tx #{tx_id} of #{source_id}",
            }
            for tx_id, source_id in foreign
        )
    return blockers


async def get_batch_force_delete_preview(db: AsyncSession, batch_id: int) -> dict:
    """Превью force-удаления: что снесётся и как изменятся остатки.

    Тот же контракт, что у ``GET /delete-preview`` плана, плюс ``blockers``
    неоткрутимых случаев — UI обязан показать их до ввода причины.
    """
    batch = await db.get(ImportBatch, batch_id)
    if batch is None:
        raise ValueError("Import batch not found")

    fp = await _collect_footprint(db, batch_id)
    blockers = await _force_blockers(db, fp)
    return {
        "batch_id": batch.id,
        "filename": await _batch_filename(db, batch),
        "production_plan_id": batch.production_plan_id,
        **fp.counts(),
        "stock_effects": fp.stock_effects,
        "blockers": blockers,
    }



def _quality(value) -> QualityState:
    """Значение качества из проводки как enum.

    ORM-чтение отдаёт ``QualityState``, но сессия может вернуть и сырое
    значение базы — приводим оба случая к одному типу, иначе пересчёт
    баланса упадёт на ``str(enum)`` вместо ``enum.value``.
    """
    return value if isinstance(value, QualityState) else QualityState(str(value))

async def force_delete_import_batch(
    db: AsyncSession,
    batch_id: int,
    *,
    confirmation: str,
    reason: str,
    changed_by: int | None = None,
) -> dict:
    """Снести поддерево батча целиком, вернув склад к состоянию до импорта.

    Порядок соответствует направлению FK: сначала листья (брак и его решения),
    затем проводки ledger, затем передачи и задания, и только потом позиции
    плана и сам батч. Балансы пересчитываются последними — уже по
    оставшемуся ledger, поэтому склад совпадает с суммой проводок (S1).
    """
    from app.models.defect import Defect, DefectItem, TransferDiscrepancyDefectItem
    from app.models.internal_plan import InternalPlan, InternalPlanStatus
    from app.models.release_batch import ReleaseBatchPosition
    from app.models.production_plan import PositionStatusHistory
    from app.models.rework_task import ReworkTask
    from app.models.transfer import Transfer, TransferDiscrepancy
    from app.stock.models import StockTransaction

    batch = await db.get(ImportBatch, batch_id)
    if batch is None:
        raise ValueError("Import batch not found")

    filename = await _batch_filename(db, batch)
    clean_reason = reason.strip()
    if confirmation != filename:
        raise ValueError("Confirmation must exactly match the file name")
    if len(clean_reason) < MIN_REASON_LENGTH:
        raise ValueError("Reason must contain at least 3 characters")

    fp = await _collect_footprint(db, batch_id)
    if not fp.position_ids:
        raise ValueError("Import batch has no positions to delete")

    blockers = await _force_blockers(db, fp)
    if blockers:
        from app.services.production_plan_service import (
            _safely_deletable_position_ids,
        )

        raise BatchForceDeleteBlocked(
            blockers, len(await _safely_deletable_position_ids(db, batch_id))
        )

    preview = {
        **fp.counts(),
        "filename": filename,
        "stock_effects": fp.stock_effects,
    }
    # Ключи баланса, которые пересчитаем: обе стороны каждой удаляемой
    # проводки. Ключ повторяет ключ StockBalance целиком (ADR-0043 §3):
    # без признака операций удалённые проводки одного артикула и участка,
    # но разных операций попали бы в один пересчёт, и строки баланса, которых
    # удаление не касается, пересчитывались бы по чужой группе. Габарит и
    # признак операций — dict/list и в set не годятся, поэтому в ключе лежат
    # их стабильные подписи, а значения разбираются через dims_by_signature
    # и ops_by_signature.
    balance_keys: set[tuple[int, int, QualityState, str | None, str | None]] = set()
    dims_by_signature: dict[str | None, dict | None] = {}
    ops_by_signature: dict[str | None, list | None] = {}
    if fp.tx_ids:
        for row in (
            await db.execute(
                select(
                    StockTransaction.product_id,
                    StockTransaction.from_location_id,
                    StockTransaction.to_location_id,
                    StockTransaction.from_quality_state,
                    StockTransaction.to_quality_state,
                    StockTransaction.dimensions,
                    StockTransaction.completed_operations,
                ).where(StockTransaction.id.in_(fp.tx_ids))
            )
        ).all():
            signature = _dims_signature(row.dimensions)
            ops_signature = _ops_signature(row.completed_operations)
            dims_by_signature.setdefault(signature, row.dimensions)
            ops_by_signature.setdefault(ops_signature, row.completed_operations)
            if row.from_location_id is not None:
                balance_keys.add(
                    (
                        int(row.product_id),
                        int(row.from_location_id),
                        _quality(row.from_quality_state),
                        signature,
                        ops_signature,
                    )
                )
            if row.to_location_id is not None:
                balance_keys.add(
                    (
                        int(row.product_id),
                        int(row.to_location_id),
                        _quality(row.to_quality_state),
                        signature,
                        ops_signature,
                    )
                )

    # Действия удаляемых заданий/передач: проводки исчезнут, но журнал —
    # аудит, поэтому записи получают статус purged, а не удаляются.
    ref_ids = list(fp.task_ids) + list(fp.transfer_ids)
    purged_action_ids: list[int] = []
    if ref_ids:
        purged_action_ids = list(
            (
                await db.execute(
                    select(Action.id).where(
                        Action.ref_id.in_(ref_ids), Action.status == ActionStatus.ACTIVE
                    )
                )
            ).scalars()
        )
        if purged_action_ids:
            await db.execute(
                update(Action)
                .where(Action.id.in_(purged_action_ids))
                .values(status=ActionStatus.PURGED)
            )

    if fp.defect_ids:
        await db.execute(
            delete(DefectItem).where(DefectItem.defect_id.in_(fp.defect_ids))
        )
        # Решения по браку удаляем вместе с браком: они не имеют смысла без
        # исходного дефекта, а их FK без ON DELETE CASCADE не дал бы снести его.
        await db.execute(
            delete(Defect).where(Defect.id.in_(fp.defect_ids))
        )
        await db.execute(
            delete(ReworkTask).where(ReworkTask.defect_id.in_(fp.defect_ids))
        )

    if fp.transfer_ids:
        discrepancy_ids = list(
            (
                await db.execute(
                    select(TransferDiscrepancy.id).where(
                        TransferDiscrepancy.transfer_id.in_(fp.transfer_ids)
                    )
                )
            ).scalars()
        )
        if discrepancy_ids:
            await db.execute(
                delete(TransferDiscrepancyDefectItem).where(
                    TransferDiscrepancyDefectItem.transfer_discrepancy_id.in_(
                        discrepancy_ids
                    )
                )
            )
            await db.execute(
                delete(TransferDiscrepancy).where(
                    TransferDiscrepancy.id.in_(discrepancy_ids)
                )
            )

    if fp.tx_ids:
        # Компенсации ссылаются на исходные через reverses_id, поэтому их снос
        # идёт в том же запросе: FK self-reference иначе рвёт удаление.
        await db.execute(
            delete(StockTransaction).where(StockTransaction.id.in_(fp.tx_ids))
        )
    if fp.transfer_ids:
        await db.execute(delete(Transfer).where(Transfer.id.in_(fp.transfer_ids)))
    if fp.task_ids:
        await db.execute(
            delete(ReworkTask).where(ReworkTask.source_task_id.in_(fp.task_ids))
        )
        await db.execute(delete(WorkTask).where(WorkTask.id.in_(fp.task_ids)))
    if fp.line_ids:
        await db.execute(
            delete(SectionPlanLine).where(SectionPlanLine.id.in_(fp.line_ids))
        )
    if fp.position_ids:
        await db.execute(
            delete(ReleaseBatchPosition).where(
                ReleaseBatchPosition.plan_position_id.in_(fp.position_ids)
            )
        )
        await db.execute(
            delete(PositionStatusHistory).where(
                PositionStatusHistory.plan_position_id.in_(fp.position_ids)
            )
        )

    change_set_ids = list(
        (
            await db.execute(
                select(PlanChangeSet.id).where(
                    PlanChangeSet.import_batch_id == batch_id
                )
            )
        ).scalars()
    )
    if change_set_ids:
        await db.execute(
            delete(PlanChangeItem).where(PlanChangeItem.change_set_id.in_(change_set_ids))
        )
        await db.execute(
            delete(PlanChangeSet).where(PlanChangeSet.id.in_(change_set_ids))
        )
    if fp.position_ids:
        await db.execute(
            delete(PlanPosition).where(PlanPosition.id.in_(fp.position_ids))
        )

    user = await db.get(User, changed_by) if changed_by else None
    actor = (user.full_name or user.username) if user is not None else "system"
    history_action = await action_journal_service.log(
        db,
        action_type="import_batch_force_delete",
        ref_id=batch.id,
        actor=actor,
        depends_on=list(dict.fromkeys(purged_action_ids)),
    )
    # ``log`` не берёт reason, а причину операции обязан хранить сам журнал
    # (Action.reason) — иначе в цепочке откатов не видно, чьей рукой снесено.
    history_action.reason = clean_reason
    await db.flush()

    await _delete_batch_and_orphan_file(db, batch_id)
    await db.execute(
        update(InternalPlan).where(
            InternalPlan.production_plan_id == batch.production_plan_id
        ).values(status=InternalPlanStatus.cancelled)
    )

    projection = StockProjectionManager()
    for product_id, location_id, quality_state, signature, ops_signature in balance_keys:
        await projection.recompute_balance_key(
            db,
            product_id,
            location_id,
            quality_state,
            dims_by_signature[signature],
            ops_by_signature[ops_signature],
        )

    now = datetime.now(timezone.utc)
    await log_action(
        db,
        status="success",
        title="Принудительное удаление пакета импорта",
        message=(
            f"Файл «{filename}» удалён вместе с производственными данными: "
            f"позиций {len(fp.position_ids)}, заданий {len(fp.task_ids)}, "
            f"передач {len(fp.transfer_ids)}, проводок {len(fp.tx_ids)}. "
            f"Остатки возвращены к состоянию до импорта. Причина: {clean_reason}."
        ),
        user=user,
        action=AuditAction.DELETE,
        entity_type=AuditEntityType.IMPORT_BATCH,
        entity_id=batch_id,
        changes={
            "before": preview,
            "after": {
                "status": "cancelled",
                "deleted_at": now.isoformat(),
                "deleted_by": changed_by,
                "reason": clean_reason,
                "purged_action_ids": list(dict.fromkeys(purged_action_ids)),
            },
        },
    )
    await db.commit()
    return {
        "deleted": True,
        "mode": "force",
        "batch_id": batch_id,
        "filename": filename,
        **fp.counts(),
        "purged_action_ids": list(dict.fromkeys(purged_action_ids)),
        "history_action_id": history_action.id,
    }
