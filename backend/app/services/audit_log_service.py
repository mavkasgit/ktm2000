from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Any, Dict

from app.models.audit_log import AuditLog, AuditAction, AuditEntityType
from app.models.user import User


def compute_changes(before: Dict[str, Any] | None, after: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """
    Вычисляет разницу между двумя состояниями объекта (до и после).
    Возвращает словарь с ключами "before" и "after", содержащими только изменившиеся поля.
    """
    if before is None and after is None:
        return None
    if before is None:
        return {"before": {}, "after": after}
    if after is None:
        return {"before": before, "after": {}}

    changed_before = {}
    changed_after = {}

    all_keys = set(before.keys()).union(after.keys())
    for key in all_keys:
        val_before = before.get(key)
        val_after = after.get(key)
        if val_before != val_after:
            changed_before[key] = val_before
            changed_after[key] = val_after

    if not changed_before and not changed_after:
        return None

    return {"before": changed_before, "after": changed_after}


async def log_action(
    db: AsyncSession,
    status: str,
    title: str,
    message: str,
    user: User | None = None,
    user_id: int | None = None,
    user_name: str | None = None,
    section_id: int | None = None,
    section_name: str | None = None,
    section_code: str | None = None,
    task_ids: List[int] | None = None,
    product_sku: str | None = None,
    operation_name: str | None = None,
    qty_text: str | None = None,
    comment: str | None = None,
    error_details: str | None = None,
    # Новые параметры
    action: AuditAction | str | None = None,
    entity_type: AuditEntityType | str | None = None,
    entity_id: int | None = None,
    changes: Dict[str, Any] | None = None,
) -> AuditLog:
    task_ids_str = None
    if task_ids:
        task_ids_str = ",".join(map(str, task_ids))

    u_id = user.id if user else user_id
    u_name = user.full_name if user else user_name

    # Преобразуем енамы в строки для бд, если переданы енамы
    action_val = action.value if isinstance(action, AuditAction) else action
    entity_type_val = entity_type.value if isinstance(entity_type, AuditEntityType) else entity_type

    log = AuditLog(
        user_id=u_id,
        user_name=u_name,
        status=status,
        title=title,
        message=message,
        section_id=section_id,
        section_name=section_name,
        section_code=section_code,
        task_ids=task_ids_str,
        product_sku=product_sku,
        operation_name=operation_name,
        qty_text=qty_text,
        comment=comment,
        error_details=error_details,
        action=action_val,
        entity_type=entity_type_val,
        entity_id=entity_id,
        changes=changes,
    )
    db.add(log)
    await db.flush()
    return log

