"""`has_packaging` в справочнике участков (`GET /api/sections`).

Колонка «Упаковка» (доска участка и лист печати) применима только к участку,
у которого в справочнике операций есть операция с префиксом `PACK`. Флаг
считается свойством модели `Section.has_packaging` по уже загруженным
операциям участка, поэтому проверяется здесь через публичный контракт —
ответ API, а не через вызов свойства.
"""

from __future__ import annotations

import pytest
from app.models.route import SectionOperation
from app.models.section import Section

# Свой префикс кода, чтобы выборка не задевала участки из сидов и соседних тестов.
CODE_PREFIX = "SEC-PKGFLAG"


async def _seed_section_with_operations(
    session, code: str, operation_codes: list[str], *, is_significant: bool = True
) -> Section:
    section = Section(code=code, name=f"Packaging flag {code}", type="production")
    session.add(section)
    await session.flush()
    for index, operation_code in enumerate(operation_codes):
        session.add(
            SectionOperation(
                section_id=section.id,
                operation_code=operation_code,
                operation_name=f"Операция {operation_code}",
                is_significant=is_significant,
                sort_order=index,
            )
        )
    await session.commit()
    return section


async def _sections_by_code(client) -> dict[str, dict]:
    response = await client.get(f"/api/sections?code={CODE_PREFIX}&limit=50&offset=0")
    assert response.status_code == 200
    return {item["code"]: item for item in response.json()["items"]}


@pytest.mark.asyncio
async def test_has_packaging_true_only_for_sections_with_pack_operations(
    client, session
) -> None:
    await _seed_section_with_operations(session, f"{CODE_PREFIX}-PACK", ["PACK_GLUE"])
    await _seed_section_with_operations(session, f"{CODE_PREFIX}-SAW", ["SAW_2700"])
    await _seed_section_with_operations(session, f"{CODE_PREFIX}-NONE", [])
    # «PACK» внутри кода, но не в начале: префикс, а не подстрока.
    await _seed_section_with_operations(session, f"{CODE_PREFIX}-UNPACK", ["PRE_PACK"])

    by_code = await _sections_by_code(client)

    assert by_code[f"{CODE_PREFIX}-PACK"]["has_packaging"] is True
    assert by_code[f"{CODE_PREFIX}-SAW"]["has_packaging"] is False
    assert by_code[f"{CODE_PREFIX}-UNPACK"]["has_packaging"] is False
    # Участок без операций отдаёт явный `false`, а не отсутствие поля: фронт
    # различает «нет флага» (показывать, fail-open) и «флаг false» (скрыть).
    assert by_code[f"{CODE_PREFIX}-NONE"]["has_packaging"] is False


@pytest.mark.asyncio
async def test_has_packaging_ignores_is_significant(client, session) -> None:
    """Незначимая упаковочная операция всё равно делает колонку применимой.

    Иначе значение ячейки (любой код с префиксом `PACK` в операциях задания)
    могло бы существовать на участке, где колонка скрыта, — данные пропали бы
    вместе с колонкой.
    """
    section = await _seed_section_with_operations(
        session, f"{CODE_PREFIX}-INSIG", ["PACK_STRETCH"], is_significant=False
    )
    assert section.id is not None

    by_code = await _sections_by_code(client)

    assert by_code[f"{CODE_PREFIX}-INSIG"]["has_packaging"] is True
