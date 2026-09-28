"""Дрейф канона: сверка «строка кода-канона присутствует в БД» (ADR-0046).

Однонаправленная сверка ``канон ⊆ БД``: отсутствующая в БД строка канона —
всегда дефект, лишняя строка в БД — административная правка (ADR-0004 §2) и
дефектом не считается. Покрытие — ровно то, что ломает сборку маршрута:
``sections``, ``section_operations``, ``route_selection_rules``.

Модуль **только читает**: сессия используется для SELECT'ов, коммита и
изменений в ней нет. Проверка выполняется на ``AsyncSession``.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import RouteSelectionRule, SectionOperation
from app.models.section import Section
from app.seeds.canon import build_plant_config
from app.seeds.canon.models import PlantConfig

# Правило без кода (создано из UI) в отчёте о лишних строках обозначается так:
# у канона код всегда задан, поэтому ``None`` в лишних — признак правки
# администратора, а не дрейфа.
NULL_CODE_LABEL = "(code IS NULL)"


@dataclass(frozen=True)
class CanonDrift:
    """Результат сверки: чего не хватает в БД и что в БД лишнего.

    ``missing_*`` — дефект, ``extra_*`` — справочная часть отчёта.
    """

    missing_sections: tuple[str, ...] = ()
    missing_operations: tuple[tuple[str, str], ...] = ()
    missing_rules: tuple[str, ...] = ()
    extra_rules: tuple[str, ...] = ()

    @property
    def has_drift(self) -> bool:
        """Есть ли строки канона, отсутствующие в БД."""
        return bool(
            self.missing_sections or self.missing_operations or self.missing_rules
        )

    def render(self) -> str:
        """Человекочитаемый отчёт: чего не хватает и что лишнего."""
        lines: list[str] = []
        for code in self.missing_sections:
            lines.append(f"  раздел «sections»: нет участка с code={code!r}")
        for section_code, operation_code in self.missing_operations:
            lines.append(
                "  раздел «section_operations»: нет операции "
                f"({section_code!r}, {operation_code!r})"
            )
        for code in self.missing_rules:
            lines.append(
                f"  раздел «route_selection_rules»: нет правила с code={code!r}"
            )
        for code in self.extra_rules:
            lines.append(
                f"  лишнее в «route_selection_rules»: {code} — не дефект "
                "(правило создано вне канона)"
            )
        return "\n".join(lines)


async def check_canon_drift(session: AsyncSession) -> CanonDrift:
    """Сверить код-канон с содержимым БД. Только чтение, без коммита.

    Ключи свои у каждой таблицы: ``sections.code``; ``section_operations`` —
    пара ``(section_id, operation_code)``, в отчёте — по ``code`` участка;
    ``route_selection_rules.code`` (``NULL`` у административных правил).
    Операции отсутствующего в БД участка не докладываются: без участка их
    и не может быть, а строкой в отчёте они бы только шумели.
    """
    config = build_plant_config()

    db_sections = set((await session.scalars(select(Section.code))).all())
    missing_sections = tuple(
        sorted({s.code for s in config.production.sections} - db_sections)
    )

    # ``section_operations`` ключуется по id участка, канон знает только code:
    # сопоставляем через ``sections``, ограничиваясь участками, что есть в БД.
    rows = await session.execute(
        select(Section.code, SectionOperation.operation_code)
        .join(Section, Section.id == SectionOperation.section_id)
    )
    db_operations = {(code, operation_code) for code, operation_code in rows.all()}

    canon_operations = {
        (op.section_code, op.operation_code)
        for op in config.production.ops
        if op.operation_code is not None and op.section_code in db_sections
    }
    missing_operations = tuple(sorted(canon_operations - db_operations))

    canon_rule_codes = {r.code for r in config.routing.selection_rules}
    db_rule_codes = set(
        (await session.scalars(select(RouteSelectionRule.code))).all()
    )
    missing_rules = tuple(sorted(canon_rule_codes - db_rule_codes))
    extra_rules = tuple(
        sorted(
            code if code is not None else NULL_CODE_LABEL
            for code in db_rule_codes - canon_rule_codes
        )
    )

    return CanonDrift(
        missing_sections=missing_sections,
        missing_operations=missing_operations,
        missing_rules=missing_rules,
        extra_rules=extra_rules,
    )
