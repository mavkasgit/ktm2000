"""Единая политика резолва узла действия (ADR-0021, тикет #130).

Чистая функция ``resolve_action`` — один seam выбора узла ``Action``
для всех компенсаторов. Дискриминированный результат без исключений:

- ``action_id`` передан → строго этот узел (``db.get``) с проверкой
  ``action_type``; чужой тип или отсутствие записи → ``NotFound``;
- иначе фолбэк по паре ``(action_type, ref_id)`` — строгая трихотомия
  по АКТИВНЫМ действиям: 0 → ``NotFound``, ровно 1 → ``Resolved``,
  больше 1 → ``Ambiguous`` со списком id-кандидатов;
- ``ref_id=None`` без ``action_id`` → ``NotFound`` (manual_adjustment,
  import_remainders): фолбэк по паре невозможен по построению.

Угадывание («первый попавшийся», «самый свежий») запрещено: узлы с
неоднозначной парой нереферсибельны до ручного разбора (preview-first).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_journal import Action, ActionStatus
from app.reversal.base import CheckBlocker


@dataclass(frozen=True)
class Resolved:
    """Узел однозначно определён."""

    action: Action


@dataclass(frozen=True)
class Ambiguous:
    """По паре (action_type, ref_id) активно больше одного действия."""

    candidates: list[int]


@dataclass(frozen=True)
class NotFound:
    """Узел не найден: нет записи, чужой action_type либо не заданы
    ни action_id, ни ref_id."""


async def resolve_action(
    db: AsyncSession,
    *,
    action_type: str,
    ref_id: int | None,
    action_id: int | None,
) -> Resolved | Ambiguous | NotFound:
    """Резолв узла действия: id старше пары (тип, ref_id), без угадывания.

    Фолбэк считает только АКТИВНЫЕ действия пары: единственный активный
    резолвится, пара без активных — «не найдено», несколько активных —
    «неоднозначно» с перечнем кандидатов.
    """
    if action_id is not None:
        action = await db.get(Action, action_id)
        if action is None or action.action_type != action_type:
            return NotFound()
        return Resolved(action)
    if ref_id is None:
        # Без обоих адресатов (напр. manual_adjustment) фолбэк по паре
        # невозможен по построению — честный «не найдено».
        return NotFound()
    actives = (
        (
            await db.execute(
                select(Action)
                .where(
                    Action.action_type == action_type,
                    Action.ref_id == ref_id,
                    Action.status == ActionStatus.ACTIVE,
                )
                .order_by(Action.id.asc())
            )
        )
        .scalars()
        .all()
    )
    if not actives:
        return NotFound()
    if len(actives) == 1:
        return Resolved(actives[0])
    return Ambiguous(candidates=[a.id for a in actives])


def ambiguous_detail(
    action_type: str, ref_id: int | None, candidates: list[int]
) -> str:
    """Детали блокера/ошибки ``ambiguous``: перечень id-кандидатов (#130)."""
    ids = ", ".join(f"#{c}" for c in candidates)
    return (
        f"{action_type}: по паре (action_type, ref_id={ref_id}) найдено "
        f"несколько активных действий ({ids}) — откат невозможен "
        f"до ручного разбора"
    )


def not_found_detail(action_type: str, ref_id: int | None, action_id: int | None) -> str:
    """Детали блокера/ошибки ``not_found`` с указанием источника резолва."""
    if action_id is not None:
        return (
            f"{action_type}: действие #{action_id} не найдено "
            f"или относится к другому action_type"
        )
    if ref_id is None:
        return f"{action_type}: у действия нет ref_id"
    return f"{action_type}: действие с ref_id={ref_id} не найдено"


def resolution_blockers(
    res: Resolved | Ambiguous | NotFound,
    *,
    action_type: str,
    ref_id: int | None,
    action_id: int | None,
) -> list[CheckBlocker] | None:
    """Неуспех резолва → блокеры для check()-границы компенсатора;
    ``None`` при ``Resolved`` (блокеров нет)."""
    if isinstance(res, Resolved):
        return None
    if isinstance(res, Ambiguous):
        detail = ambiguous_detail(action_type, ref_id, res.candidates)
        return [CheckBlocker(kind="ambiguous", detail=detail)]
    return [CheckBlocker(kind="not_found", detail=not_found_detail(action_type, ref_id, action_id))]


def require_resolved(
    res: Resolved | Ambiguous | NotFound,
    *,
    action_type: str,
    ref_id: int | None,
    action_id: int | None,
) -> Action:
    """Узел для plan()-границы: ``Resolved`` → action; иначе обычный
    ValueError (внешний контракт плана прежний, ADR-0021 п.4)."""
    if isinstance(res, Ambiguous):
        raise ValueError(ambiguous_detail(action_type, ref_id, res.candidates))
    if isinstance(res, NotFound):
        raise ValueError(not_found_detail(action_type, ref_id, action_id))
    return res.action
