from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.idempotency import raise_idempotency_conflict_on_violation
from app.models.attachment import Attachment, AttachmentLink
from app.models.entity_comment import EntityComment, EntityType

from .common import _check_idempotency

async def create_comment(
    db: AsyncSession,
    *,
    entity_type: EntityType,
    entity_id: int,
    body: str,
    actor_id: int,
    comment_type: str = "note",
    is_internal: bool = False,
    idempotency_key: str | None = None,
) -> dict:
    if not body.strip():
        raise ValueError("Comment body must not be empty")
    if idempotency_key:
        existing = await _check_idempotency(
            db, idempotency_key=idempotency_key, entity_type=EntityComment
        )
        if existing is not None:
            return {"comment_id": existing.id, "idempotent_replay": True}
    comment = EntityComment(
        entity_type=entity_type,
        entity_id=entity_id,
        comment_type=comment_type,
        body=body,
        is_internal=is_internal,
        idempotency_key=idempotency_key,
        author_id=actor_id,
    )
    db.add(comment)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Гонка идемпотентности (ADR-0022, тикет #135); повтор с тем же
        # ключом попадает в replay-ветку выше.
        raise_idempotency_conflict_on_violation(
            exc, index_name="uq_entity_comments_idempotency_key",
            entity="entity_comment", idempotency_key=idempotency_key,
        )
    return {"comment_id": comment.id}

async def create_attachment(
    db: AsyncSession,
    *,
    original_filename: str,
    stored_path: str,
    size_bytes: int,
    actor_id: int,
    content_type: str | None = None,
    file_sha256: str | None = None,
    metadata_json: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    if not original_filename.strip():
        raise ValueError("original_filename is required")
    if size_bytes <= 0:
        raise ValueError("size_bytes must be > 0")
    if idempotency_key:
        existing = await _check_idempotency(
            db, idempotency_key=idempotency_key, entity_type=Attachment
        )
        if existing is not None:
            return {"attachment_id": existing.id, "idempotent_replay": True}
    attachment = Attachment(
        original_filename=original_filename,
        stored_path=stored_path,
        content_type=content_type,
        size_bytes=size_bytes,
        file_sha256=file_sha256,
        metadata_json=metadata_json or {},
        idempotency_key=idempotency_key,
        created_by=actor_id,
    )
    db.add(attachment)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Гонка идемпотентности (ADR-0022, тикет #135); повтор с тем же
        # ключом попадает в replay-ветку выше.
        raise_idempotency_conflict_on_violation(
            exc, index_name="uq_attachments_idempotency_key",
            entity="attachment", idempotency_key=idempotency_key,
        )
    return {"attachment_id": attachment.id}

async def link_attachment(
    db: AsyncSession,
    *,
    attachment_id: int,
    entity_type: EntityType,
    entity_id: int,
    actor_id: int,
    caption: str | None = None,
) -> dict:
    attachment = await db.get(Attachment, attachment_id)
    if attachment is None:
        raise ValueError("Attachment not found")
    link = AttachmentLink(
        attachment_id=attachment.id,
        entity_type=entity_type,
        entity_id=entity_id,
        caption=caption,
        created_by=actor_id,
    )
    db.add(link)
    await db.flush()
    return {"attachment_link_id": link.id}

