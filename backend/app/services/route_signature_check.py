"""Проверка сигнатуры маршрута у позиции плана (#214).

Сопоставляет две стороны:

* **ожидаемая** — сигнатура, собранная из входа сборки позиции (профиль
  импорта, payload позиции, артикул). Это то, каким маршрут должен быть;
* **фактическая** — сохранённая сигнатура маршрута у позиции. У маршрута,
  созданного до #214 и ещё не пересчитанного, берётся по записанным этапам.

Вердикт диагностический: расхождение видно, но ничего не блокирует —
импорт, утверждение и выпуск работают как раньде (отказ импорта — #215).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.production_plan import PlanPosition
from app.models.route import ProductionRoute, RouteRuleProfile
from app.services.route_builder import build_route_from_profile
from app.services.route_matcher import _payload_for_dynamic_build
from app.services.route_signature import (
    RouteSignatureStep,
    encode_signature,
    load_route_stages,
    signature_steps_from_built_steps,
    signature_steps_from_stages,
)

SignatureVerdict = Literal["match", "mismatch", "unknown"]


@dataclass(frozen=True, slots=True)
class RouteSignatureComparison:
    """Ожидаемая и фактическая сигнатуры маршрута позиции с вердиктом."""

    verdict: SignatureVerdict
    expected: str | None = None
    expected_steps: tuple[RouteSignatureStep, ...] = ()
    actual: str | None = None
    actual_steps: tuple[RouteSignatureStep, ...] = ()


async def _expected_signature(
    db: AsyncSession,
    position: PlanPosition,
    profile: RouteRuleProfile | None,
    product: Product | None,
) -> tuple[str | None, tuple[RouteSignatureStep, ...]]:
    """Сигнатура, которую собрал бы для позиции её профиль.

    Пустая пара — сравнивать не с чем: у позиции нет профиля или профиль
    ничего не собрал.
    """
    if profile is None or not (profile.route_sections or []):
        return None, ()

    built = await build_route_from_profile(
        db,
        profile,
        _payload_for_dynamic_build(position),
        position,
        product=product,
    )
    if built.error or not built.steps:
        return None, ()
    return built.signature, tuple(signature_steps_from_built_steps(built.steps))


async def _actual_signature(
    db: AsyncSession,
    route_id: int | None,
) -> tuple[str | None, tuple[RouteSignatureStep, ...]]:
    """Сохранённая сигнатура маршрута и его этапы.

    Сохранённая — источник правды; этапы показываются, чтобы оператор видел,
    о чём речь. У маршрута без сохранённой сигнатуры она досчитывается по
    этапам: пересборки этапов при этом не происходит.
    """
    if route_id is None:
        return None, ()
    route = await db.get(ProductionRoute, route_id)
    steps = tuple(signature_steps_from_stages(await load_route_stages(db, route_id)))
    stored = route.route_signature if route is not None else None
    # У маршрута без сохранённой сигнатуры она досчитывается по этапам; у
    # маршрута без этапов сравнивать нечего — это None, а не пустая строка.
    actual = stored or (encode_signature(steps) or None if steps else None)
    return actual, steps


async def compare_position_route_signature(
    db: AsyncSession,
    position: PlanPosition,
    *,
    profile: RouteRuleProfile | None,
    product: Product | None,
    route_id: int | None,
) -> RouteSignatureComparison:
    """Ожидаемая и фактическая сигнатуры маршрута позиции с вердиктом."""
    expected, expected_steps = await _expected_signature(db, position, profile, product)
    actual, actual_steps = await _actual_signature(db, route_id)

    if not expected or actual is None:
        return RouteSignatureComparison(
            verdict="unknown",
            expected=expected,
            expected_steps=expected_steps,
            actual=actual,
            actual_steps=actual_steps,
        )
    return RouteSignatureComparison(
        verdict="match" if expected == actual else "mismatch",
        expected=expected,
        expected_steps=expected_steps,
        actual=actual,
        actual_steps=actual_steps,
    )
