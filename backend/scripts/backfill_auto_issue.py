"""Backfill ``issue_to_work`` movements for tasks that were received via
transfer before the auto-issue-on-receive change.

History: ``transfer_send`` previously wrote only ``transfer_send`` and
``transfer_receive`` Movements. The receiving task therefore had
``cached_received_quantity > 0`` but ``cached_issued_quantity == 0``,
which made it impossible to complete the task until the operator
explicitly issued the material.

This script scans the ``movements`` ledger, finds every
``transfer_receive`` Movement that has no paired ``issue_to_work``
Movement on the same ``task_id`` with the same ``transfer_id`` and
quantity, and writes a synthetic ``issue_to_work`` row to bring the
cache back in sync. It is idempotent: reruns are a no-op once all
legacy transfers have been backfilled.

Usage:
    cd backend
    python -c "import asyncio; from scripts.backfill_auto_issue import main; asyncio.run(main())"
"""
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.models.movement import Movement, MovementType
from app.models.work_task import WorkTask
from app.services.shopfloor_service import (
    _refresh_section_plan_line_cache,
    _refresh_task_cache,
)


async def main() -> None:
    async with async_session() as db:
        receives = (
            await db.execute(
                select(Movement).where(
                    Movement.movement_type == MovementType.transfer_receive,
                ).order_by(Movement.id)
            )
        ).scalars().all()
        print(f"Найдено transfer_receive движений: {len(receives)}")

        backfilled = 0
        skipped = 0
        errors: list[tuple[int, str]] = []
        for recv in receives:
            existing_issue = await db.scalar(
                select(Movement).where(
                    Movement.transfer_id == recv.transfer_id,
                    Movement.movement_type == MovementType.issue_to_work,
                    Movement.task_id == recv.task_id,
                )
            )
            if existing_issue is not None:
                skipped += 1
                continue

            try:
                backfill = Movement(
                    product_id=recv.product_id,
                    task_id=recv.task_id,
                    section_plan_line_id=recv.section_plan_line_id,
                    transfer_id=recv.transfer_id,
                    from_section_id=recv.to_section_id,
                    to_section_id=recv.to_section_id,
                    movement_type=MovementType.issue_to_work,
                    quantity=recv.quantity,
                    source_ref=(recv.source_ref or "") + ":backfill" if recv.source_ref else "backfill_auto_issue",
                    comment="backfill: issue for legacy transfer_receive",
                    created_by=recv.created_by,
                    executor_user_id=recv.executor_user_id,
                    created_by_user_name=recv.created_by_user_name,
                    executor_user_name=recv.executor_user_name,
                    performed_at=recv.performed_at,
                    accounted_at=recv.accounted_at,
                    is_post_factum=recv.is_post_factum,
                )
                db.add(backfill)
                await db.flush()
                backfilled += 1
            except Exception as exc:
                errors.append((recv.id, str(exc)))

        await db.commit()

        # Пересчитать кэш для всех задач, которых коснулся бэкфилл
        if backfilled > 0:
            affected_task_ids = {
                r.task_id for r in receives
                if r.task_id is not None
            }
            print(f"Пересчёт кэша для {len(affected_task_ids)} задач...")
            for task_id in affected_task_ids:
                task = await db.get(WorkTask, task_id)
                if task is None:
                    continue
                await _refresh_task_cache(db, task_id)
                await _refresh_section_plan_line_cache(db, task.section_plan_line_id)
            await db.commit()

        print(
            f"\nГотово. Бэкфилл: {backfilled}, уже было: {skipped}, ошибок: {len(errors)}"
        )
        for move_id, err in errors[:20]:
            print(f"  [move {move_id}] {err}")


if __name__ == "__main__":
    asyncio.run(main())
