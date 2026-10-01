"""Регресс-тесты fallback-ветки резолва маршрута позиции (правка 6faf3bd).

Контекст: ``_resolve_route_id_for_dynamic_name`` при динамической пересборке
имени маршрута. Если пересобранное имя не нашлось среди ``ProductionRoute``,
функция возвращает ``stored_route_id`` позиции (6faf3bd) — назначение позиции
остаётся действительным.

Контракты, которые защищают тесты:

1. Fallback срабатывает: позиция с ``stored_route_id``, чьё пересобранное имя
   не резолвится ни по одному маршруту, получает ``route_id`` = stored id и
   ``error=None`` (без этого take-to-work отказывал «No route found»).
2. Fallback сохраняет ПЕРЕСОБРАННОЕ имя: страница плана обязана совпадать с
   предпросмотром импорта (контракт закреплён
   `test_route_matcher.py::test_resolve_position_route_rebuilds_dynamic_name_over_wrong_route_id`).
   Плата — в fallback-ветке id и имя указывают на разные строки; решение
   зафиксировано осознанно, см. docstring теста и резолва.
3. Архивированный маршрут (``is_active=False``) не выдаётся за действительное
   назначение: позиция обязана получить ``route_id=None`` и ``error``.
4. Граница фикса: если пересобранное имя СУЩЕСТВУЮЩЕГО маршрута, пересборка
   побеждает устаревший ``stored_route_id`` (контракт плановой страницы
   «имя как в превью импорта»).
"""

from __future__ import annotations

import pytest
from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteOrigin,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
)
from app.models.route import ProductionRoute, RouteRuleProfile, RouteStage
from app.models.section import Section
from app.services.route_builder import build_route_from_profile
from app.services.route_matcher import (
    _payload_for_dynamic_build,
    resolve_position_route,
)
from app.services.route_signature import auto_route_code
from sqlalchemy import select

# Имя маршрута, сохранённое в позиции до правки: содержит цвет, которого нет
# в пересобранном имени (шаблон «{output_kind} - {operations}»).
STORED_ROUTE_NAME = "П/Ф - Серебро - Спанбонд"


async def _make_profile_position(session) -> PlanPosition:
    """Позиция с профилем маршрута и сохранённым, не совпадающим с rebuild именем.

    Возвращает позицию и её ``stored_route_id``. Пересобранное по профилю имя
    намеренно не совпадает с ``STORED_ROUTE_NAME`` и не существует в БД —
    это и есть вход fallback-ветки.
    """
    from tests.test_dynamic_route_generation import (
        _make_profile_with_rules,
        _seed_sections,
    )

    await _seed_sections(session)
    profile_id = await _make_profile_with_rules(session)

    stored_route = ProductionRoute(name=STORED_ROUTE_NAME, is_active=True)
    session.add(stored_route)
    await session.flush()

    position = PlanPosition(
        production_plan_id=1,
        product_id=None,
        source_type=PlanSourceType.excel_import,
        source_sku="ХТ-466-3776",
        quantity=1,
        # Цвет берётся из source_name: rebuild отдаёт «П/Ф - Чёрный»,
        # сохранённый маршрут назван по цвету «Серебро» — расхождение как в проде.
        source_payload={"output_kind": "П/Ф", "source_name": "РП-АКТ-03 2,7 м анодчерный матов"},
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
        route_id=stored_route.id,
        route_profile_id=profile_id,
        route_origin=PlanPositionRouteOrigin.auto,
    )
    return position, stored_route


async def _rebuilt_name(session, position: PlanPosition) -> str:
    """Пересобрать имя маршрута ровно так, как это делает resolve_position_route."""
    profile = await session.get(RouteRuleProfile, position.route_profile_id)
    assert profile is not None
    built = await build_route_from_profile(
        session, profile, _payload_for_dynamic_build(position), position
    )
    assert built.error is None, f"предусловие: сборка маршрута должна удаться, получено {built.error!r}"
    return built.name


async def _assert_fallback_precondition(session, position: PlanPosition, stored_route: ProductionRoute) -> str:
    """Проверить, что тест действительно стоит на fallback-ветке, и вернуть rebuilt-имя.

    Без этой проверки тест молча уехал бы в другую ветку (имя совпало бы с
    существующим маршрутом) и проверял бы не то.
    """
    built_name = await _rebuilt_name(session, position)
    assert built_name != stored_route.name, (
        f"предусловие: rebuilt-имя {built_name!r} должно отличаться от сохранённого {stored_route.name!r}"
    )
    matched = await session.scalar(
        select(ProductionRoute.id).where(ProductionRoute.name == built_name)
    )
    assert matched is None, (
        f"предусловие: маршрута с rebuilt-именем {built_name!r} в БД быть не должно (найден id={matched})"
    )
    return built_name


@pytest.mark.asyncio
async def test_stored_route_id_survives_when_rebuilt_name_matches_nothing(session) -> None:
    """Fallback: невосстановившееся имя не стирает назначение позиции.

    Без 6faf3bd резолв отдавал route_id=None → позиция уходила в
    ``route_not_found``, и take-to-work отказывал с «No route found for
    this position», хотя маршрут был назначен и существовал.
    """
    position, stored_route = await _make_profile_position(session)
    await _assert_fallback_precondition(session, position, stored_route)

    result = await resolve_position_route(session, position)

    assert result.error is None
    assert result.route_id == stored_route.id


@pytest.mark.asyncio
async def test_fallback_keeps_rebuilt_name_for_preview_parity(session) -> None:
    """Fallback сохраняет пересобранное имя — страница плана обязана совпадать
    с предпросмотром импорта.

    В fallback-ветке id и имя описывают разные строки (id сохранённого
    маршрута, имя из пересборки по payload). Это НЕ дефект: контракт
    «план = предпросмотр импорта» закреплён в
    `test_route_matcher.py::test_resolve_position_route_rebuilds_dynamic_name_over_wrong_route_id`,
    и он важнее согласованности пары. Тест фиксирует решение явно, чтобы
    следующий читатель не «починил» его обратно.
    """
    position, stored_route = await _make_profile_position(session)
    built_name = await _assert_fallback_precondition(session, position, stored_route)

    result = await resolve_position_route(session, position)

    assert result.route_id == stored_route.id
    assert result.route_name == built_name
    assert result.route_name != stored_route.name


@pytest.mark.asyncio
async def test_archived_stored_route_is_not_reported_as_valid_assignment(session) -> None:
    """Fallback не должен выдавать архивированный маршрут за действительный.

    Комментарий в коде утверждает «назначение всё равно действительное», но
    ``is_active=False`` — это явный отзыв маршрута. Позиция обязана получить
    ``route_id=None`` и ``error``, иначе take-to-work падает позже и позже
    (production_planning.py:1787 «Route is not active»).
    """
    position, stored_route = await _make_profile_position(session)
    stored_route.is_active = False
    await session.flush()
    await _assert_fallback_precondition(session, position, stored_route)

    result = await resolve_position_route(session, position)

    assert result.route_id is None
    assert result.error == "route_not_found"


@pytest.mark.asyncio
async def test_rebuild_name_wins_over_stale_stored_route_id_when_route_exists(session) -> None:
    """Граница фикса: если rebuilt-имя существует, оно побеждает устаревший stored id.

    Защищает от «лечения» теста 2 обратным правилом (всегда имя сохранённого
    маршрута): пересборка обязана по-прежнему выигрывать у устаревшего
    ``stored_route_id``, как требует плановый экран.
    """
    position, stored_route = await _make_profile_position(session)
    built_name = await _rebuilt_name(session, position)
    assert built_name != stored_route.name

    fresh_route = ProductionRoute(name=built_name, is_active=True)
    session.add(fresh_route)
    await session.flush()

    result = await resolve_position_route(session, position)

    assert result.route_id == fresh_route.id
    assert result.route_name == built_name


async def _make_renamed_import_route(session, position: PlanPosition) -> ProductionRoute:
    """Маршрут импорта с настоящим ``auto-``-кодом, которому сменили состав.

    Код считается из сигнатуры, но ``refresh_route_signature`` код не
    обновляет: отредактированный руками маршрут сохраняет прежний
    ``auto-``-код и продолжает находиться по нему. Именно этот случай
    отличается по сигнатуре, но совпадает по коду.
    """
    built = await _built_route(session, position)
    code = auto_route_code(built.signature)
    assert code is not None, "предусловие: у собранного маршрута есть сигнатура"

    section = await session.scalar(select(Section).where(Section.code == "PACKING"))
    route = ProductionRoute(name=built.name, code=code, is_active=True)
    session.add(route)
    await session.flush()
    # Состав маршрута в БД — один участок, а сигнатура осталась от
    # исходной пересборки: ровно то, что даёт правка маршрута руками.
    stage = RouteStage(route_id=route.id, sequence=1, section_id=section.id, is_final=True)
    session.add(stage)
    await session.flush()
    await session.commit()
    return route


async def _built_route(session, position: PlanPosition):
    profile = await session.get(RouteRuleProfile, position.route_profile_id)
    assert profile is not None
    return await build_route_from_profile(
        session, profile, _payload_for_dynamic_build(position), position
    )


@pytest.mark.asyncio
async def test_route_edited_by_hand_keeps_auto_code_but_signature_is_verified(session) -> None:
    """Маршрут, найденный по коду, проходит сверку сигнатуры (ADR-0051 п.4).

    Ветка кода возвращала ``id`` сразу, без сверки, и позиция получала
    маршрут чужого состава с ``error=None`` — выглядела назначенной и
    проходила дальше. Ровно тот случай, от которого защищает ADR-0045.
    """
    from tests.test_dynamic_route_generation import (
        _make_profile_with_rules,
        _seed_sections,
    )

    await _seed_sections(session)
    profile_id = await _make_profile_with_rules(session)
    position = PlanPosition(
        production_plan_id=1,
        product_id=None,
        source_type=PlanSourceType.excel_import,
        source_sku="ХТ-466-3776",
        quantity=1,
        source_payload={"output_kind": "П/Ф", "source_name": "РП-АКТ-03 2,7 м анодчерный матов"},
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
        route_id=None,
        route_profile_id=profile_id,
        route_origin=PlanPositionRouteOrigin.auto,
    )
    # Позиция в памяти, как в соседних тестах: резолву нужен профиль и
    # payload, а не строка плана в БД.

    edited = await _make_renamed_import_route(session, position)
    assert edited.route_signature is None, (
        "предусловие: у маршрута нет сохранённой сигнатуры — сверка берёт её с этапов"
    )

    result = await resolve_position_route(session, position)

    assert result.route_id != edited.id, "маршрут чужого состава нельзя подставлять"
    assert result.error == "route_signature_conflict"


@pytest.mark.asyncio
async def test_legacy_name_fallback_resolves_oldest_codeless_route(session) -> None:
    """Fallback по имени берёт самый старый маршрут без кода, как сид и импорт.

    Ветка брала ``order_by(id DESC)`` — самый свежий, тогда как сид, импорт и
    ``run_seed`` работают с самым старым. На дублях без кода (маршруты,
    созданные импортом до #230) это тихо разные выборки: позиция получала
    другой маршрут, и результат зависел от того, когда строка создана.
    """
    from tests.test_dynamic_route_generation import (
        _make_profile_with_rules,
        _seed_sections,
    )

    await _seed_sections(session)
    profile_id = await _make_profile_with_rules(session)
    position = PlanPosition(
        production_plan_id=1,
        product_id=None,
        source_type=PlanSourceType.excel_import,
        source_sku="ХТ-466-3776",
        quantity=1,
        source_payload={"output_kind": "П/Ф", "source_name": "РП-АКТ-03 2,7 м анодчерный матов"},
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
        route_id=None,
        route_profile_id=profile_id,
        route_origin=PlanPositionRouteOrigin.auto,
    )
    built = await _built_route(session, position)
    assert built.signature, "предусловие: пересборка даёт сигнатуру"
    assert auto_route_code(built.signature) is not None

    # Два маршрута до #230: кода нет ни у одного, имя общее.
    older = ProductionRoute(name=built.name, code=None, is_active=True)
    session.add(older)
    await session.flush()
    newer = ProductionRoute(name=built.name, code=None, is_active=True)
    session.add(newer)
    await session.commit()
    assert newer.id > older.id

    result = await resolve_position_route(session, position)

    # Ветка кода не сработала: auto-кода в базе нет, только безкодовые.
    assert result.route_id == older.id, (
        f"fallback взял {result.route_id}, ожидался самый старый {older.id}"
    )
