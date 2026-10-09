"""Сторож формы строки доски (ADR-0031, тикет #319).

Форма задания на доске объявлена один раз — ``board_row.SectionBoardTaskOut``
(и базовый ``SourceSignature``) — и собирается одной функцией
``build_board_task_row``. Набор ключей выводится из объявления, а не
дублируется в тесте: удаление ключа из builder'а роняет оба теста ниже, а
не проходит незамеченным.

Второй контракт — «одно представление»: ручка задания отдаёт те же
id/status/planned_quantity/cache, что и строка доски того же задания.
"""

from __future__ import annotations

import pytest
from app.services.shopfloor.board_row import SectionBoardTaskOut
from app.services.shopfloor.queries_details import get_task_details
from app.services.shopfloor.queries_sections import get_section_board

from tests.test_section_board_operation_fallback import (
    _create_task_for_route,
    _setup_press_section_with_null_route_step,
)

pytestmark = pytest.mark.asyncio


def _declared_keys() -> set[str]:
    return set(SectionBoardTaskOut.__required_keys__) | set(
        SectionBoardTaskOut.__optional_keys__
    )


def _assert_matches_interface(row: dict) -> None:
    declared = _declared_keys()
    assert set(row) == declared, (
        "строка доски разошлась с объявленным интерфейсом: "
        f"потеряны {sorted(declared - set(row))}, лишние {sorted(set(row) - declared)}"
    )


async def test_guard_rejects_row_with_any_dropped_key() -> None:
    """Сторож чувствителен к удалению любого ключа строки, а не только хвоста."""
    declared = sorted(_declared_keys())
    for dropped in declared:
        broken = {key: None for key in declared if key != dropped}
        with pytest.raises(AssertionError):
            _assert_matches_interface(broken)


async def test_section_board_row_matches_declared_interface(session) -> None:
    """Живая строка доски несёт ровно объявленный набор ключей."""
    _raw_section, press_section, route, raw_step, press_step = (
        await _setup_press_section_with_null_route_step(session)
    )
    await _create_task_for_route(
        session,
        route,
        raw_step,
        press_step,
        {"operation_code": "PRESS_WINDOW", "color": "silver"},
    )

    board = await get_section_board(session, section_id=press_section.id)

    assert board["tasks"], "доска участка пуста — контракт не проверен"
    for row in board["tasks"]:
        _assert_matches_interface(row)


async def test_task_details_reuses_board_row(session) -> None:
    """Ручка задания отдаёт те же значения строки доски (одно представление)."""
    _raw_section, press_section, route, raw_step, press_step = (
        await _setup_press_section_with_null_route_step(session)
    )
    _product, _pp, _raw_task, press_task = await _create_task_for_route(
        session,
        route,
        raw_step,
        press_step,
        {"operation_code": "PRESS_COMB", "color": "black"},
    )

    board = await get_section_board(session, section_id=press_section.id)
    row = next(task for task in board["tasks"] if task["id"] == press_task.id)

    details = await get_task_details(session, press_task.id)

    for key in ("id", "status", "planned_quantity", "cache"):
        assert details[key] == row[key], f"поле {key} разошлось между ручками"
    assert details["route_step"]["id"] == row["route_step_id"]
    assert details["route_step"]["sequence"] == row["sequence"]
    assert details["route_step"]["operation_code"] == press_step.operations[0].operation_code
