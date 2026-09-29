"""Сигнатура маршрута — упорядоченный набор шагов с признаками этапа.

Сигнатура, а не имя, делает два маршрута одним (ADR-0045, CONTEXT.md
«Сигнатура маршрута»). Имя — подпись для человека: шаблон имени выбрасывает
пустые слоты, поэтому два разных маршрута законно дают одно имя, и тогда
имя — признак коллизии, а не ключ.

Шаг сигнатуры: ``stage_kind``, участок (у транзитного — складской),
операции шага и признаки этапа ``is_significant`` / ``transforms_dimensions``
/ ``is_final``. Признаки включены сознательно: сид-маршруты завода
``dynamic_packaging_map_rp`` и ``universal_rp`` имеют одинаковый набор
участков и пустые коды операций и различаются только значимостью этапа —
сигнатура из одних пар «участок + операция» их не различила бы.

Считается из входа сборки (:class:`~app.services.route_builder.BuiltRouteStep`),
а не из записанных в базу этапов: сверка, читающая обе стороны из базы,
сравнивает базу саму с собой и собственных потерь при записи не заметит.
"""
from __future__ import annotations
import hashlib

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.route import ProductionRoute, RouteStage

if TYPE_CHECKING:
    from app.services.route_builder import BuiltRouteStep

# Поля шага и разделители. Коды участков и операций — заглавные snake-case
# (``SAWING``, ``PACK_STRETCH``), разделителей в них не бывает.
_FIELD_SEP = ":"
_OP_SEP = ","
_STEP_SEP = ">"

#: Префикс кода маршрута, созданного импортом (#230, ADR-0051).
AUTO_CODE_PREFIX = "auto-"
#: Сколько hex-символов хеша сигнатуры входит в код. 16 символов = 64 бита:
#: на масштабе завода (сотни маршрутов) коллизия не наступает, а код
#: остаётся читаемым в списке маршрутов и в сообщениях об ошибках.
_AUTO_CODE_HASH_LEN = 16


def auto_route_code(signature: str) -> str | None:
    """Код маршрута импорта — детерминированная функция его сигнатуры.

    Один и тот же состав даёт один и тот же код, разный состав — разный,
    даже если имя совпало: имя — подпись, а идентичность — пара «код +
    сигнатура» (#230, ADR-0051). Формула обязана совпадать с бэкфиллом
    ревизии ``071`` (``'auto-' || substr(sha256(signature), 1, 16)``),
    иначе прод не узнал бы в своих маршрутах своих же.

    ``None`` — сигнатуры нет (маршрут без этапов): кода нет, и тождество
    по-прежнему держится на имени (ADR-0045).
    """
    if not signature:
        return None
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
    return f"{AUTO_CODE_PREFIX}{digest[:_AUTO_CODE_HASH_LEN]}"


@dataclass(frozen=True, slots=True)
class RouteSignatureStep:
    """Один шаг сигнатуры — этап маршрута с его признаками."""

    stage_kind: str
    section_code: str
    operation_codes: tuple[str, ...]
    is_significant: bool
    transforms_dimensions: bool
    is_final: bool
    # Подписи для человека: участок и операции. В тождество маршрута они
    # НЕ входят (``encode`` их не читает) — вердикт считается только по
    # кодам, поэтому переименование участка или операции расхождения не
    # создаёт, а карточку не обесценивает.
    section_name: str | None = None
    operation_names: tuple[str, ...] = ()

    def encode(self) -> str:
        return _FIELD_SEP.join((
            self.stage_kind,
            self.section_code,
            _OP_SEP.join(self.operation_codes),
            _flag(self.is_significant),
            _flag(self.transforms_dimensions),
            _flag(self.is_final),
        ))

    def as_dict(self) -> dict:
        return {
            "stage_kind": self.stage_kind,
            "section_code": self.section_code,
            "operation_codes": list(self.operation_codes),
            "is_significant": self.is_significant,
            "transforms_dimensions": self.transforms_dimensions,
            "is_final": self.is_final,
            "section_name": self.section_name,
            "operation_names": list(self.operation_names),
        }


def _flag(value: bool) -> str:
    return "1" if value else "0"


def signature_steps_from_built_steps(steps: Sequence[BuiltRouteStep]) -> list[RouteSignatureStep]:
    """Шаги сигнатуры из входа сборки маршрута.

    Шаги одного участка подряд — это один этап маршрута: та же группировка,
    что и при записи этапов импортом и сидом. Признаки этапа собираются
    из шагов группы: этап значим, если значим хотя бы один его шаг.
    """
    grouped: list[list] = []
    for step in sorted(steps, key=lambda item: item.sequence):
        if grouped and grouped[-1][0].section_code == step.section_code:
            grouped[-1].append(step)
        else:
            grouped.append([step])

    return [
        RouteSignatureStep(
            stage_kind=group[0].stage_kind,
            section_code=group[0].section_code or "",
            operation_codes=tuple(step.operation_code or "" for step in group),
            is_significant=any(step.is_significant for step in group),
            transforms_dimensions=any(step.transforms_dimensions for step in group),
            is_final=any(step.is_final for step in group),
            section_name=group[0].section_name,
            operation_names=tuple(step.operation_name for step in group),
        )
        for group in grouped
    ]


def encode_signature(steps: Iterable[RouteSignatureStep]) -> str:
    """Сигнатура маршрута — строка шагов в порядке этапов."""
    return _STEP_SEP.join(step.encode() for step in steps)


def signature_from_built_steps(steps: Sequence[BuiltRouteStep]) -> str:
    """Сигнатура собранного маршрута — из входа сборки."""
    return encode_signature(signature_steps_from_built_steps(steps))


def signature_steps_from_stages(stages: Sequence[RouteStage]) -> list[RouteSignatureStep]:
    """Шаги сигнатуры по записанным этапам маршрута.

    Транзитный этап представляет складской участок, производственный —
    свой. Пустая сигнатура (``""``) — у маршрута без этапов.
    """
    return [
        RouteSignatureStep(
            stage_kind=stage.stage_kind,
            section_code=(
                stage.storage_section.code if stage.storage_section is not None
                else stage.section.code if stage.section is not None else ""
            ),
            operation_codes=tuple(op.operation_code or "" for op in stage.operations),
            is_significant=stage.is_significant,
            transforms_dimensions=stage.transforms_dimensions,
            is_final=stage.is_final,
            # Имя участка — текущее из справочника (``Section.name`` не
            # денормализовано в этапе), имя операции — снимок на момент
            # записи маршрута (``RouteOperation.operation_name``).
            section_name=(
                stage.storage_section.name if stage.storage_section is not None
                else stage.section.name if stage.section is not None else None
            ),
            operation_names=tuple(op.operation_name for op in stage.operations),
        )
        for stage in sorted(stages, key=lambda item: item.sequence)
    ]


async def load_route_stages(db: AsyncSession, route_id: int) -> list[RouteStage]:
    """Этапы маршрута с операциями и участками, в порядке этапов."""
    stages = (
        await db.execute(
            select(RouteStage)
            .where(RouteStage.route_id == route_id)
            .options(
                selectinload(RouteStage.operations),
                selectinload(RouteStage.section),
                selectinload(RouteStage.storage_section),
            )
            .order_by(RouteStage.sequence)
        )
    ).scalars().all()
    return list(stages)


async def signature_for_route_stages(db: AsyncSession, route_id: int) -> str:
    """Сигнатура маршрута по тому, что записано в его этапах."""
    return encode_signature(signature_steps_from_stages(await load_route_stages(db, route_id)))


async def route_signature_conflicts(
    db: AsyncSession,
    route: ProductionRoute,
    expected_signature: str,
) -> bool:
    """Расходится ли сигнатура маршрута с ожидаемой (#215, ADR-0045).

    Совпадение имени — не тождество: маршрут, найденный по имени, подходит
    только если сигнатуры совпадают. Ожидаемая сигнатура приходит из входа
    сборки, фактическая — сохранённая (#214), а у маршрута без неё —
    посчитанная по этапам.

    Отсутствие сигнатуры (нет и сохранённой, и этапов) — не конфликт:
    сравнивать не с чем, и маршрут переиспользуется как раньше.
    """
    if not expected_signature:
        return False
    actual = route.route_signature
    if not actual:
        # Сигнатура маршрута без сохранённой — по его этапам, и сверять
        # надо шаги (`RouteSignatureStep`), а не сами `RouteStage`:
        # `encode_signature` ждёт шаги, и на этапах падал
        # `AttributeError: 'RouteStage' object has no attribute 'encode'`.
        # Вызывающий резолв глотал это общим `except Exception`, и конфликт
        # молча не проверялся вовсе.
        stages = await load_route_stages(db, route.id)
        actual = (
            encode_signature(signature_steps_from_stages(stages)) if stages else None
        )
    return actual is not None and actual != expected_signature


async def refresh_route_signature(db: AsyncSession, route: ProductionRoute) -> None:
    """Пересчитать сигнатуру маршрута по его этапам и сохранить её.

    Маршрут без этапов получает ``None``, а не пустую строку: ``NULL`` —
    признак «сигнатуры нет» (так же фильтрует backfill миграции 066), и
    сверка отдаёт по нему вердикт «неизвестно», а не «расходится».
    """
    stages = signature_steps_from_stages(await load_route_stages(db, route.id))
    route.route_signature = encode_signature(stages) if stages else None
    await db.flush()