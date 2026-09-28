"""Детектор дрейфа канона: «строка канона отсутствует в БД» (ADR-0046, #216).

Скрипт read-only и однонаправленный: отсутствие строки канона — дефект,
лишняя строка в БД (правило, созданное администратором) — нет. Ключи свои
у каждой таблицы: `sections.code`, `section_operations` — пара
`(section_id, operation_code)`, `route_selection_rules.code` (у
административных правил `code IS NULL`).
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import delete, func, select

from app.models.route import (
    RouteOperation,
    RouteSelectionRule,
    RouteStage,
    SectionOperation,
)
from app.models.section import Section
from app.models.spg import SpgSection
from app.seeds.canon import build_plant_config
from app.seeds.run_seed import run_full_seed
from app.services.canon_drift import NULL_CODE_LABEL, check_canon_drift
from scripts.check_canon_drift import (
    describe_target,
    env_file_problem,
    run_check,
)

# Участок, у которого в каноне есть операция: удаление строки участка тянет
# за собой удаление его операций (FK), иначе проверка падала бы на ограничении.
DRIFT_SECTION_CODE = "PACKING"


@pytest_asyncio.fixture
async def seeded(session):
    """БД, полностью просидированная текущим каноном."""
    await run_full_seed(session, force=True)
    return session


async def _section_id(session, code: str) -> int:
    section_id = await session.scalar(select(Section.id).where(Section.code == code))
    assert section_id is not None, f"Участок {code} не просидирован"
    return section_id


async def _drop_section(session, code: str) -> None:
    """Удалить участок вместе со ссылающимися на него строками."""
    section_id = await _section_id(session, code)
    stage_ids = set(
        (
            await session.scalars(
                select(RouteStage.id).where(
                    (RouteStage.section_id == section_id)
                    | (RouteStage.storage_section_id == section_id)
                )
            )
        ).all()
    )
    if stage_ids:
        await session.execute(
            delete(RouteOperation).where(RouteOperation.route_stage_id.in_(stage_ids))
        )
    await session.execute(
        delete(RouteStage).where(
            (RouteStage.section_id == section_id)
            | (RouteStage.storage_section_id == section_id)
        )
    )
    await session.execute(
        delete(SectionOperation).where(SectionOperation.section_id == section_id)
    )
    await session.execute(delete(SpgSection).where(SpgSection.section_id == section_id))
    await session.execute(delete(Section).where(Section.id == section_id))


async def _drop_first_operation(session) -> tuple[str, str]:
    """Удалить одну строку операции участка; вернуть её канон-ключ."""
    canon = build_plant_config()
    section_code, operation_code = next(
        (op.section_code, op.operation_code)
        for op in canon.production.ops
        if op.operation_code is not None
    )
    section_id = await _section_id(session, section_code)
    await session.execute(
        delete(SectionOperation).where(
            (SectionOperation.section_id == section_id)
            & (SectionOperation.operation_code == operation_code)
        )
    )
    return section_code, operation_code


async def _drop_first_rule(session) -> str:
    """Удалить строку канон-правила; вернуть его код."""
    canon = build_plant_config()
    code = canon.routing.selection_rules[0].code
    await session.execute(delete(RouteSelectionRule).where(RouteSelectionRule.code == code))
    return code


async def _add_admin_rule(session, code: str | None) -> None:
    """Правило «из UI»: без канона, код может быть NULL."""
    session.add(
        RouteSelectionRule(
            code=code,
            name="Административное правило",
            priority=900,
            conditions=[],
            actions=[],
        )
    )
    await session.flush()


class TestCleanDatabase:
    """На просидированной БД дрейфа нет."""

    async def test_fully_seeded_database_has_no_drift(self, seeded) -> None:
        report = await check_canon_drift(seeded)
        assert report.missing_sections == ()
        assert report.missing_operations == ()
        assert report.missing_rules == ()

    async def test_fully_seeded_database_exits_zero(self, seeded, capsys) -> None:
        exit_code = await run_check(seeded)
        assert exit_code == 0


class TestMissingCanonRow:
    """Отсутствующая в БД строка канона — дефект."""

    async def test_missing_section_is_reported(self, seeded) -> None:
        await _drop_section(seeded, DRIFT_SECTION_CODE)

        report = await check_canon_drift(seeded)

        assert DRIFT_SECTION_CODE in report.missing_sections
        # Операции отсутствующего участка отдельными строками не докладываются:
        # их отсутствие следует из отсутствия участка.
        assert not any(
            section_code == DRIFT_SECTION_CODE
            for section_code, _ in report.missing_operations
        )

    async def test_missing_section_operation_is_reported(self, seeded) -> None:
        section_code, operation_code = await _drop_first_operation(seeded)

        report = await check_canon_drift(seeded)

        assert (section_code, operation_code) in report.missing_operations

    async def test_missing_selection_rule_is_reported(self, seeded) -> None:
        code = await _drop_first_rule(seeded)

        report = await check_canon_drift(seeded)

        assert code in report.missing_rules

    async def test_missing_row_is_named_in_output_and_exits_nonzero(
        self, seeded, capsys
    ) -> None:
        code = await _drop_first_rule(seeded)

        exit_code = await run_check(seeded)

        assert exit_code != 0
        assert code in capsys.readouterr().out


class TestExtraDatabaseRow:
    """Лишнее в БД — административная правка, не дефект."""

    async def test_admin_rule_without_code_is_not_drift(self, seeded) -> None:
        await _add_admin_rule(seeded, code=None)

        report = await check_canon_drift(seeded)

        assert report.has_drift is False
        assert NULL_CODE_LABEL in report.extra_rules

    async def test_rule_with_code_outside_canon_is_not_drift(self, seeded) -> None:
        await _add_admin_rule(seeded, code="admin_one_off")

        report = await check_canon_drift(seeded)

        assert report.has_drift is False
        assert "admin_one_off" in report.extra_rules


class TestReadOnly:
    """Скрипт только читает: грязная БД от повторного прогона не чинится."""

    async def test_repeated_check_does_not_repair_drift(self, seeded) -> None:
        code = await _drop_first_rule(seeded)
        before = await check_canon_drift(seeded)

        await run_check(seeded)
        after = await check_canon_drift(seeded)

        assert before == after
        assert code in after.missing_rules
        assert await seeded.scalar(
            select(func.count())
            .select_from(RouteSelectionRule)
            .where(RouteSelectionRule.code == code)
        ) == 0


class TestTargetIdentification:
    """Отчёт называет проверяемую базу и не проходит мимо env-файла."""

    def test_target_names_database_without_password(self) -> None:
        target = describe_target(
            "postgresql+asyncpg://ktm2000_user:hunter2@db-host:5432/ktm2000_prod"
        )

        assert "ktm2000_prod" in target
        assert "db-host" in target
        assert "hunter2" not in target

    def test_missing_env_file_is_refused(self, tmp_path) -> None:
        """Нет файла — DSN взялся бы из окружения оболочки: молчалив «OK» нельзя."""
        assert env_file_problem(tmp_path / "absent.env") is not None

    def test_present_env_file_is_accepted(self, tmp_path) -> None:
        env_file = tmp_path / ".env.prod"
        env_file.write_text("DATABASE_URL=x\n", encoding="utf-8")

        assert env_file_problem(env_file) is None
