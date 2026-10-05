"""Контракт демо-сидера «Участков» (``packing_plan_demo_seeder``).

Форма датасета (107 строк первого плана: 55 базовых + 30 подготовки + 6 пар
анодирования + 4 парных артикула + 10 незакрытых + 2 непарных, и 6 строк
второго плана — «Плана подготовительного участка») защищается без БД — по
фикстуре и хелперам: у каждого участка подготовки 8–10 строк, есть обе
операции пресса, внутри каждой группы есть повторяющиеся артикулы, базовые
артикулы уникальны, пары анодирования собраны под слияние, строки парных
артикулов совпадают с нормами ``PAIR_NORMS``, непарный вариант пары подписан
своими наименованиями и отличается количеством (иначе импорт отбросил бы
строку как дубликат), у каждой строки есть группа прогона и состояние,
заголовки листов известны шаблонам импорта, раскрой не длиннее входа, дневные
планы раскладываются без пустых карточек.

Доменный путь (импорт → approve → release → маршрут → задания → дневные
планы) гоняется один раз на срезе ``DEMO_SLICE_ROWS`` (16 строк первого плана)
и ``DEMO_STAGE_SLICE_ROWS`` (4 строки второго), а не на весь датасет: срез
закрывает сверловку, пресс (гребёнку), дробеструй, базовую упаковочную группу,
повтор артикула, пару анодирования, пару артикулов и оба незакрытых
состояния. Полный прогон 107 строк в тестах не нужен.

Тяжёлый доменный прогон делается один раз на модуль (фикстура ``demo_seed``),
а проверки по нему разложены по свойствам: маршрут и прогресс, операции
участков, пара анодирования, норма подвеса, незакрытые позиции, второй план,
дневные планы с повторным прогоном. Свойства, которые проверяет один и тот же
срез, живут в одном тесте — иначе они гоняли бы общий запрос и сид по второму
разу ради того же результата.

Прогон: ``pwsh -NoProfile -File scripts/test-run.ps1 --full tests/test_packing_plan_demo_seeder.py``.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import pytest
import pytest_asyncio
from app.api.routes.production_plans import ALL_POSITIONS_PLANNING_STATUSES
from app.core.config import settings
from app.models.daily_plan import DailyPlan, DailyPlanItem
from app.models.internal_plan import SectionPlanLine
from app.models.product import Product, ProductLength
from app.models.production_plan import PlanPosition, PlanPositionStatus, ProductionPlan
from app.models.route import RouteOperation, RouteRuleProfile, RouteStage
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus
from app.seeds.import_templates import IMPORT_TEMPLATES
from app.seeds.run_seed import run_full_seed
from app.seeds.seeders.packing_plan_demo_seeder import (
    ANOD_PAIR_ROWS,
    DEMO_ANOD_SECTION_CODES,
    DEMO_PLAN_ROWS,
    DEMO_PREP_SECTION_CODES,
    DEMO_PREP_STAGE_PROFILE_CODE,
    DEMO_PREP_STAGE_TEMPLATE_CODE,
    DEMO_ROUTE_PROFILE_CODE,
    DEMO_RUN_SECTION_CODES,
    DEMO_SECTION_CODES,
    LIFECYCLE_APPROVED,
    LIFECYCLE_DRAFT,
    LIFECYCLE_RELEASED,
    PACKING_PLAN_ROWS,
    PAIR_ARTICLE_ROWS,
    PAIR_NORMS,
    PENDING_PLAN_ROWS,
    PREP_PLAN_ROWS,
    PREP_STAGE_PLAN_ROWS,
    UNPAIRED_PAIR_ROWS,
    _daily_plan_specs,
    _lifecycle_of,
    _plan_workbook,
    _prep_stage_workbook,
    _progress_mode,
    _row_group,
    _target_section_for,
    seed_packing_plan_demo,
)
from app.services.daily_plan_service import TERMINAL_TASK_STATUSES
from app.services.excel_import import parse_factory_plan_workbook
from app.services.plan_position_hanger import (
    position_dimensions_for_task,
    resolve_positions_hanger,
)
from app.services.route_builder import _resolve_operations
from app.services.shopfloor.queries_sections import get_section_board
from app.stock import QualityState
from app.stock.models import StockBalance
from app.stock.services import StockProjectionManager
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

#: Базовый блок фикстуры — «Упаковочный план» с уникальными артикулами.
PLAN_ROW_COUNT = 55
#: Блок строк подготовки: сверловка + пресс + дробеструй, по 10 строк на участок.
PREP_ROW_COUNT = 30
#: Пары анодирования: 3 артикула по 2 строки (спанбонд + стрейч).
ANOD_PAIR_COUNT = 6
#: Парные артикулы: 2 реальные пары по 2 строки (компоненты одной пары).
PAIR_ROW_COUNT = 4
#: Незакрытые строки: 10 неутверждённых и 2 утверждённых без релиза. Неутверждённых
#: больше намеренно: экран «План» показывает только позиции в статусе
#: draft/invalid/valid, и две-три строки на всю систему выглядели бы поломкой.
#: Среди них вторая партия тех же артикулов пары — норма подвеса у неё та же, и
#: на экране планировщика это видно, — и распил одного входа на две длины:
#: две строки одного задания, которые на экране обязаны быть связаны.
PENDING_ROW_COUNT = 12
#: Строки распила одного входа: ЮП-2627, вход 100 шт по 2,7 м на две длины.
CUT_SPLIT_SKU = "ЮП-2627"
CUT_SPLIT_INPUT_QUANTITY = 100
CUT_SPLIT_INPUT_LENGTH_M = 2.7
CUT_SPLIT_OUTPUT_LENGTHS_M = (0.9, 1.8)
#: Непарный вариант пары: те же два артикула (ЮП-2604/ЮП-2616) самостоятельными
#: строками со своими наименованиями, а не одним общим, как у пары.
UNPAIRED_ROW_COUNT = 2
#: Всего позиций первого (упаковочного) плана.
TOTAL_ROW_COUNT = (
    PLAN_ROW_COUNT
    + PREP_ROW_COUNT
    + ANOD_PAIR_COUNT
    + PAIR_ROW_COUNT
    + PENDING_ROW_COUNT
    + UNPAIRED_ROW_COUNT
)
#: Строк второго плана — «План подготовительного участка».
STAGE_ROW_COUNT = 6
#: Позиций обоих планов.
ALL_POSITION_COUNT = TOTAL_ROW_COUNT + STAGE_ROW_COUNT
#: Сколько строк блока подготовки приходится на каждый участок подготовки.
PREP_ROWS_PER_SECTION = PREP_ROW_COUNT // len(DEMO_PREP_SECTION_CODES)
#: Артикулов в каждом блоке подготовки. Каталог даёт всего 10 артикулов с
#: нормальной (готовой) длиной вне базовых 55, поэтому на три блока их семь,
#: а три остаются парам анодирования.
PREP_SKUS_PER_SECTION = {"DRILLING": 3, "PRESSING": 2, "SHOT_BLAST": 2}
#: Дневная панель участка: девять дней истории, до двух карточек на дату.
DAILY_PLANS_PER_SECTION = 12
#: Нормальные (готовые) длины каталога — ``product_lengths.raw_length_mm IS NULL``.
FINISHED_LENGTHS = frozenset({0.9, 1.35, 1.8, 2.5, 2.7, 3.0})
#: Длины заготовок (``raw_length_mm`` заполнен): длиной изделия не являются.
BILLET_LENGTHS = frozenset({2.75, 1.83, 3.05, 2.55, 2.76, 2.45, 2.08, 2.51})
#: Статусы, которые доска участка показывает под фильтром «Активные».
ACTIVE_STATUSES = frozenset(
    {WorkTaskStatus.ready, WorkTaskStatus.in_progress, WorkTaskStatus.partially_completed}
)
#: Столбцы листа «Упаковочная карта РП» (шаблон upakovochnaya_karta_rp, A..P).
PLAN_SHEET_COLUMNS = 16
#: Столбцы листа «Плана подготовительного участка» (шаблон plan_prep_stage, A..G).
STAGE_SHEET_COLUMNS = 7
#: Канонический вид выпуска; правила подбора маршрута ищут его регистронезависимо
#: (``_condition_match`` → ``case_sensitive=False``, route_selection.py:619).
OUTPUT_KINDS = ("ГП", "П/ф")
#: Операции второго плана: правила профиля ``prep_stage_plan`` различают их по
#: подстроке, пустая операция даёт маршрут «только дробеструй».
STAGE_OPERATIONS = ("сверло", "окно", "гребенка", "")


def _tasks_with_ids(ids: list[int]) -> list:
    """Заглушки заданий: разбиение дневных планов читает только ``id``."""
    return [SimpleNamespace(id=value) for value in ids]


def _plan_sheet() -> tuple[list[str], list[list[object]]]:
    """Шаблон импорта, собранный сидером: заголовки + строки данных как их увидит xlsx-импорт."""
    book = load_workbook(BytesIO(_plan_workbook(DEMO_PLAN_ROWS)))
    sheet = book["totalplan"]
    raw = [list(row) for row in sheet.iter_rows(values_only=True)]
    header_at = next(
        idx for idx, row in enumerate(raw) if any(cell not in (None, "") for cell in row)
    )
    headers = [str(cell) for cell in raw[header_at]]
    data = [row for row in raw[header_at + 1 :] if any(cell not in (None, "") for cell in row)]
    return headers, data



async def _demo_sections(session) -> dict[str, Section]:
    """Участки демо по коду; падение здесь = не засеян справочник, а не пустой тест."""
    rows = (
        await session.scalars(select(Section).where(Section.code.in_(DEMO_SECTION_CODES)))
    ).all()
    sections = {section.code: section for section in rows}
    assert set(sections) == set(DEMO_SECTION_CODES), f"не засеяны участки демо: {sorted(sections)}"
    return sections


async def _positions(session, plan_id: int) -> list[PlanPosition]:
    return list(
        (
            await session.scalars(
                select(PlanPosition)
                .where(PlanPosition.production_plan_id == plan_id)
                .order_by(PlanPosition.id)
            )
        ).all()
    )

async def _demo_plans(session) -> list[ProductionPlan]:
    """Оба набора демо-плана в порядке сида: упаковочный, затем подготовительный."""
    return list((await session.scalars(select(ProductionPlan).order_by(ProductionPlan.id))).all())


async def _slice_positions(session, plan_index: int = 0) -> list[PlanPosition]:
    """Позиции среза по индексу набора плана — готовый список для проверок."""
    return await _positions(session, (await _demo_plans(session))[plan_index].id)



async def _position_section_ids(session, position_id: int) -> list[int]:
    """Участки, через которые позиция проходит по своему маршруту."""
    return list(
        (
            await session.scalars(
                select(SectionPlanLine.section_id).where(
                    SectionPlanLine.plan_position_id == position_id
                )
            )
        ).all()
    )

async def _expected_color_ops(session) -> dict[str, str]:
    """Операция анодирования, которую правило разбора даёт каждому цвету фикстуры.

    Ожидание берётся у самого правила, а сверяется с тем, что попало в этап
    маршрута. Это не тавтология: дефект был в том, что резолв правила
    отрабатывал, а в маршрут попадала первая операция группы — проверка
    сравнивает результат правила с этапом.
    """
    profile = await session.scalar(
        select(RouteRuleProfile).where(RouteRuleProfile.code == DEMO_ROUTE_PROFILE_CODE)
    )
    mapping: dict[str, str] = {}
    for color in {str(row["color"]) for row in DEMO_PLAN_ROWS}:
        resolved = await _resolve_operations(session, profile.id, {"color": color}, None)
        operation = resolved.get(("ANODIZING", "ANODIZING"))
        assert operation, f"правило разбора не дало операции для цвета {color}"
        mapping[color] = operation
    return mapping


async def _balances_by_key(
    session: AsyncSession, section_id: int, product_ids: Sequence[int | None]
) -> dict[tuple[int | None, dict | None], Decimal]:
    """Остатки склада по ключу ``(артикул, габарит)`` — как их видит выдача."""
    rows = (
        await session.execute(
            select(StockBalance.product_id, StockBalance.dimensions, StockBalance.balance_qty)
            .where(
                StockBalance.location_id == section_id,
                StockBalance.quality_state == QualityState.GOOD,
                StockBalance.product_id.in_([pid for pid in product_ids if pid is not None]),
            )
        )
    ).all()
    totals: dict[tuple[int | None, str], Decimal] = {}
    for product_id, dimensions, quantity in rows:
        key = (product_id, _dimensions_key(dimensions))
        totals[key] = totals.get(key, Decimal(0)) + Decimal(str(quantity))
    return totals


def _dimensions_key(dimensions: dict | None) -> str:
    """Габарит в виде ключа словаря: JSONB-поля не хешируются, а совпадение по
    значению должно быть точным — остаток другого размера выдаче не подойдёт."""
    return json.dumps(dimensions, sort_keys=True, ensure_ascii=False)


async def _target_task(session, position_id: int, section_id: int) -> WorkTask:
    """Задание участка по позиции плана — то, что видно на доске этого участка."""
    task = await session.scalar(
        select(WorkTask)
        .join(SectionPlanLine, SectionPlanLine.id == WorkTask.section_plan_line_id)
        .where(
            SectionPlanLine.plan_position_id == position_id,
            WorkTask.section_id == section_id,
        )
    )
    assert task is not None, f"у позиции {position_id} нет задания на участке {section_id}"
    return task


async def _count(session, model, *where) -> int:
    statement = select(func.count()).select_from(model)
    for clause in where:
        statement = statement.where(clause)
    return await session.scalar(statement) or 0


async def _demo_product_lengths(session, rows: Sequence[Mapping[str, object]]) -> dict[str, float]:
    """Нормативная длина (primary) каждого артикула переданных строк в мм."""
    skus = [str(row["sku"]) for row in rows]
    lengths = (
        await session.execute(
            select(Product.sku, ProductLength.length_mm)
            .join(ProductLength, ProductLength.product_id == Product.id)
            .where(Product.sku.in_(skus), ProductLength.is_primary.is_(True))
        )
    ).all()
    return {sku: float(length) for sku, length in lengths}


def _expected_primary_lengths(rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    """Ожидаемая нормативная длина: вход последней строки с артикулом.

    ``_ensure_products`` переставляет primary на каждой строке, поэтому у
    артикула с несколькими строками побеждает последняя — ровно как в живом
    импорте.
    """
    expected: dict[str, int] = {}
    for row in rows:
        expected[str(row["sku"])] = round(float(row["input_length_m"]) * 1000)
    return expected


def _prep_rows_by_section() -> dict[str, tuple[dict[str, object], ...]]:
    """Строки блока подготовки по участку: тройки разбора раскладываются 0/1/2.

    Порядок блока — контракт (см. ``PREP_PLAN_ROWS``): сверловка, пресс,
    дробеструй по кругу, поэтому шаг три и есть принадлежность участку.
    """
    return {
        "DRILLING": PREP_PLAN_ROWS[0::3],
        "PRESSING": PREP_PLAN_ROWS[1::3],
        "SHOT_BLAST": PREP_PLAN_ROWS[2::3],
    }


def _fold_rows(rows: Sequence[Mapping[str, object]]) -> list[list[Mapping[str, object]]]:
    """Свернуть строки листа в группы — так же, как это делает импорт (ADR-0003).

    Единица импорта — группа строк с объединённой ячейкой входа, а не строка:
    открывающая строка задаёт вход, а каждая следующая без своего входного
    количества становится ещё одним выходом той же позиции. Признак
    продолжения — ``input_continuation``, ровно тот же, что и в сидере.
    """
    groups: list[list[Mapping[str, object]]] = []
    for row in rows:
        if row.get("input_continuation") and groups:
            groups[-1].append(row)
        else:
            groups.append([row])
    return groups


def _opening_rows(rows: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """Открывающая строка каждой группы: позиция импорта создаётся ею."""
    return [group[0] for group in _fold_rows(rows)]


def _released(rows: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """Открывающие строки дошедших до релиза групп: у остальных нет ни строки
    плана, ни задания."""
    return [row for row in _opening_rows(rows) if _lifecycle_of(row) == LIFECYCLE_RELEASED]


def _expected_tasks_by_section(rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    """Сколько позиций упаковочного плана проходит через каждый участок.

    Правила подбора дают сверловку строкам с «сверло», пресс — строкам с
    «окно»/«гребенка» (операции взаимно исключают участки), анодирование и
    дробеструй есть в маршруте у каждой строки, а пилу и упаковку снимает
    спанбонд («П/ф»). Незакрытые строки в расчёт не входят: у них нет заданий.
    """
    live = _released(rows)

    def operation(row: Mapping[str, object]) -> str:
        return str(row["operation"]).strip().lower()

    return {
        "DRILLING": sum("сверл" in operation(row) for row in live),
        "PRESSING": sum(
            ("окн" in operation(row) or "греб" in operation(row)) and "сверл" not in operation(row)
            for row in live
        ),
        "SHOT_BLAST": len(live),
        "ANODIZING": len(live),
        "SAWING": sum(str(row["kind"]).upper() == "ГП" for row in live),
        "PACKING": sum(str(row["kind"]).upper() == "ГП" for row in live),
    }


def _expected_stage_tasks_by_section(rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    """Сколько позиций второго плана проходит через каждый участок.

    Маршрут подготовительного профиля идёт ``RAW_STOCK`` → участок подготовки →
    ``SHOT_BLAST`` → ``PREP_STOCK``: сверловка по «сверло», пресс по «окно»/
    «гребенка», иначе только дробеструй. Ни пила, ни упаковка, ни анодирование
    в этом маршруте не участвуют — профиль их исключает.
    """
    live = _released(rows)

    def operation(row: Mapping[str, object]) -> str:
        return str(row["operation"]).strip().lower()

    return {
        "DRILLING": sum("сверл" in operation(row) for row in live),
        "PRESSING": sum(
            ("окн" in operation(row) or "греб" in operation(row)) and "сверл" not in operation(row)
            for row in live
        ),
        "SHOT_BLAST": len(live),
        "SAWING": 0,
        "PACKING": 0,
        "ANODIZING": 0,
    }


# ─── 0. Срез фикстуры и доменный прогон ─────────────────────────────────────

#: Срез фикстуры первого плана: строки, покрывающие все виды строк —
#: сверловку, пресс (гребёнку), дробеструй, базовую упаковочную группу (пилу),
#: повтор артикула, пару анодирования, обе пары артикулов, оба незакрытых
#: состояния и непарный вариант пары. Полный датасет (107 строк) в тестах не
#: гоняется: форму защищают DB-free проверки, а доменный путь — импорт →
#: approve → release → маршрут → задания → дневные планы — срез. Порядок строк
#: внутри блока подготовки — контракт: тройка «сверловка → пресс → дробеструй»
#: расходится по участкам круговым разбором, а повторный артикул встаёт
#: четвёртым и снова попадает на сверловку — отдельным заданием.
DEMO_SLICE_ROWS: tuple[dict[str, object], ...] = (
    PREP_PLAN_ROWS[0],  # ALS1288, «сверло» → DRILLING
    PREP_PLAN_ROWS[4],  # АТ-6324, «гребенка» → PRESSING / PRESS_COMB
    PREP_PLAN_ROWS[2],  # ALS1290, пустая операция → SHOT_BLAST
    PREP_PLAN_ROWS[3],  # повторный ALS1288 → отдельное задание DRILLING
    PACKING_PLAN_ROWS[1],  # базовая упаковочная группа (ГП) → SAWING
    PACKING_PLAN_ROWS[0],  # одинокая строка артикула пары (2616, 300) → своя норма
    ANOD_PAIR_ROWS[2],  # ЮП-2974 «П/ф» → ANODIZING, бакет «закрыто»
    ANOD_PAIR_ROWS[0],  # ЮП-2256 спанбонд → ANODIZING, бакет «в работе»
    ANOD_PAIR_ROWS[1],  # ЮП-2256 стрейч → ANODIZING, бакет «выдано»
    *PAIR_ARTICLE_ROWS,  # обе пары артикулов: своя норма подвеса у каждой позиции
    *PENDING_PLAN_ROWS,  # неутверждённые и утверждённые без релиза
    *UNPAIRED_PAIR_ROWS,  # непарный вариант пары: свои наименования, та же норма
)

#: Срез второго плана: по строке на каждый вариант маршрута подготовительного
#: профиля (#313) плюс обе незакрытые позиции второго листа.
DEMO_STAGE_SLICE_ROWS: tuple[dict[str, object], ...] = tuple(
    [row for row in PREP_STAGE_PLAN_ROWS if str(row["operation"]).strip()]
    + [
        row
        for row in PREP_STAGE_PLAN_ROWS
        if _lifecycle_of(row) != LIFECYCLE_RELEASED
    ]
)


def _demo_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def demo_engine(
    engine: AsyncEngine, base_test_db_url, module_schema_name: str
) -> AsyncIterator[AsyncEngine]:
    """Engine модуля демо-среза с схемой в ``search_path`` на уровне соединения.

    ``SET search_path``, выполненный в транзакции, откатывается вместе с ней —
    а демо-сид коммитит и откатывает внутри себя. Настройка соединения
    (``server_settings``) переживает любые транзакции, поэтому её и берём.
    Схему к этому моменту создаёт штатный ``engine`` conftest.
    """
    _ = engine
    demo = create_async_engine(
        base_test_db_url.render_as_string(hide_password=False),
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": module_schema_name}},
    )
    try:
        yield demo
    finally:
        await demo.dispose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def demo_seed(demo_engine: AsyncEngine) -> dict:
    """Единственный тяжёлый прогон на модуль: доменный путь на срезе фикстуры.

    Сессия фикстуры коммитит по-настоящему (без внешней транзакции), поэтому
    данные видны читающим сессиям тестов; схема модуля живёт до конца модуля.
    """
    async with _demo_session_factory(demo_engine)() as db:
        await run_full_seed(db, force=True)
        return await seed_packing_plan_demo(
            db,
            reset=True,
            run_route=True,
            rows=DEMO_SLICE_ROWS,
            prep_stage_rows=DEMO_STAGE_SLICE_ROWS,
        )


@pytest_asyncio.fixture
async def demo_db(demo_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Сессия теста к засеянному срезу (своё соединение, свой цикл)."""
    async with _demo_session_factory(demo_engine)() as db:
        yield db


# ─── 1. Фикстура листа ──────────────────────────────────────────────────────


def test_fixture_has_exactly_one_row_per_sku() -> None:
    """Базовые 55 строк — с уникальным артикулом: по одной позиции на артикул,
    чтобы читаемая история пилы/упаковки/анодирования не разъезжалась по дублям."""
    skus = [str(row["sku"]) for row in PACKING_PLAN_ROWS]
    assert len(PACKING_PLAN_ROWS) == PLAN_ROW_COUNT
    duplicates = sorted({sku for sku in skus if skus.count(sku) > 1})
    assert not duplicates, f"артикул повторяется в базовом плане: {duplicates}"


def test_prep_fixture_repeats_a_sku_on_every_prep_section() -> None:
    """У каждого участка подготовки есть артикул в нескольких строках — демо
    показывает, что один артикул стоит в очереди участка несколькими заданиями.
    Строки одного артикула обязаны различаться раскроем или количеством: точные
    дубли импорт склеил бы в одну позицию (fingerprint строки).

    Артикулов в блоке меньше, чем строк, потому что каталог даёт всего 10
    подходящих артикулов вне базовых 55 — повтор здесь не дефект, а суть блока.
    """
    groups = _prep_rows_by_section()
    assert set(groups) == set(DEMO_PREP_SECTION_CODES)
    for code, rows in groups.items():
        assert len(rows) == PREP_ROWS_PER_SECTION, f"участок {code}: строк {len(rows)}"
        assert 8 <= len(rows) <= 10, f"участок {code}: {len(rows)} строк вне 8–10"
        counts = Counter(str(row["sku"]) for row in rows)
        assert len(counts) == PREP_SKUS_PER_SECTION[code], f"участок {code}: артикулов {len(counts)}"
        assert max(counts.values()) > 1, f"участок {code}: нет повторяющихся артикулов"
        repeated = sorted(sku for sku, count in counts.items() if count > 1)
        assert repeated, f"участок {code}: нет повторяющихся артикулов"
        for sku in repeated:
            twins = [row for row in rows if str(row["sku"]) == sku]
            distinct = {(row["output_length_m"], row["output_quantity"]) for row in twins}
            assert len(distinct) == len(twins), (
                f"участок {code}: строки {sku} неотличимы — импорт склеит их в одну позицию"
            )


def test_prep_fixture_declares_both_press_operations() -> None:
    """Пресс различает окно и гребёнку одной колонкой: если в блоке останется
    одна операция, вторая плитка участка будет пустой."""
    press_ops = Counter(str(row["operation"]).strip().lower() for row in _prep_rows_by_section()["PRESSING"])
    assert "окно" in press_ops, f"нет строк с окном: {dict(press_ops)}"
    assert "гребенка" in press_ops, f"нет строк с гребёнкой: {dict(press_ops)}"


def test_fixture_covers_every_demo_section() -> None:
    """Шесть участков доски закрыты фикстурой: три «нижних» — базовым блоком,
    три подготовки — блоком подготовки; пары анодирования целятся в участок из
    этой же шестёрки. Пересечения групп и лишних участков нет."""
    assert set(DEMO_SECTION_CODES) == set(DEMO_RUN_SECTION_CODES) | set(DEMO_PREP_SECTION_CODES)
    assert not set(DEMO_RUN_SECTION_CODES) & set(DEMO_PREP_SECTION_CODES)
    assert len(DEMO_SECTION_CODES) == 6
    assert set(DEMO_PREP_SECTION_CODES) == set(_prep_rows_by_section())
    assert set(DEMO_ANOD_SECTION_CODES) <= set(DEMO_SECTION_CODES)


def test_prep_block_does_not_touch_sawing_or_packing() -> None:
    """Строки подготовки объявлены спанбондом («П/ф»), поэтому пиле и упаковке
    они не добавляют заданий: числа базовых 55 позиций на этих участках не
    разъезжаются от нового блока. Сверловка и пресс, наоборот, получают строки
    блока — иначе участки подготовки остались бы пустыми.

    Предикат участков — тот же, что калибруется доменным прогоном среза
    (``test_slice_seed_walks_the_domain_path`` сравнивает его с БД).
    """
    base = _expected_tasks_by_section(PACKING_PLAN_ROWS)
    with_prep = _expected_tasks_by_section(PACKING_PLAN_ROWS + PREP_PLAN_ROWS)
    assert with_prep["SAWING"] == base["SAWING"]
    assert with_prep["PACKING"] == base["PACKING"]
    assert with_prep["DRILLING"] > base["DRILLING"]
    assert with_prep["PRESSING"] > base["PRESSING"]
    assert with_prep["SHOT_BLAST"] == PLAN_ROW_COUNT + PREP_ROW_COUNT


def test_anod_pair_fixture_is_built_for_merging() -> None:
    """Пары анодирования существуют ровно ради слияния строк на печатном листе:
    внутри пары один артикул, цвет, длина и первичная операция, а различие —
    вид выпуска («П/ф» против «ГП»), из которого выводится упаковочная операция
    (``pack_types``: «ГП» → PACK_STRETCH, «П/ф» → PACK_SPUNBOND). Количества
    разные — при слиянии они суммируются («Спанбонд 300 · Стрейч 200»).
    """
    assert len(ANOD_PAIR_ROWS) == ANOD_PAIR_COUNT
    by_sku: dict[str, list[dict[str, object]]] = {}
    for row in ANOD_PAIR_ROWS:
        by_sku.setdefault(str(row["sku"]), []).append(row)
    assert len(by_sku) == ANOD_PAIR_COUNT // 2, f"пары не по два ряда: {sorted(by_sku)}"
    for sku, rows in by_sku.items():
        assert len(rows) == 2, f"{sku}: строк пары {len(rows)}"
        assert {str(row["kind"]).upper() for row in rows} == {"ГП", "П/Ф"}, (
            f"{sku}: вид выпуска пары {[row['kind'] for row in rows]}"
        )
        for field in ("color", "input_length_m", "output_length_m", "operation"):
            assert len({row[field] for row in rows}) == 1, f"{sku}: поле {field} разъезжается"
        assert {str(row["packing"]) for row in rows} != {""}, f"{sku}: пустая упаковка"
        assert all(float(row["output_quantity"]) > 0 for row in rows)
        assert len({row["output_quantity"] for row in rows}) == 2, (
            f"{sku}: количества пары совпали — слияние нечего показывать"
        )


def test_fixture_blocks_use_real_skus_and_stay_recognizable() -> None:
    """Артикулы блоков — реальные каталожные (``ЮП-…``/``АТ-…``/``ALS…`` с живым
    именем товара), а не выдуманные коды: демо показывает заводскую номенклатур
    и не плодит фейковые карточки товара.

    Пересечение по артикулу теперь разрешено и даже нужно: строки парных
    артикулов и незакрытые строки планируют профили, уже стоящие в базовом
    блоке (в живом плане один профиль планируется несколькими строками). Разбор
    строки на группу идёт по содержимому строки, а не по артикулу, поэтому
    повтор артикула уводит позицию не в чужую группу. Проверяется это отдельно
    (``test_every_row_resolves_to_its_group``), а блоки с единственным
    назначением по-прежнему не пересекаются.
    """
    packing_skus = {str(row["sku"]) for row in PACKING_PLAN_ROWS}
    prep_skus = {str(row["sku"]) for row in PREP_PLAN_ROWS}
    anod_skus = {str(row["sku"]) for row in ANOD_PAIR_ROWS}
    assert not packing_skus & prep_skus, f"базовый и подготовительный блоки делят {sorted(packing_skus & prep_skus)}"
    assert not prep_skus & anod_skus, f"подготовка и пары делят {sorted(prep_skus & anod_skus)}"

    for block in (
        PREP_PLAN_ROWS,
        ANOD_PAIR_ROWS,
        PAIR_ARTICLE_ROWS,
        PENDING_PLAN_ROWS,
        UNPAIRED_PAIR_ROWS,
    ):
        for row in block:
            sku = str(row["sku"])
            assert re.match(r"^(ЮП|АТ|ALS)-?\d", sku), f"{sku}: не каталожный формат артикула"
            assert len(str(row["name"])) >= 5, f"{sku}: пустое имя товара"
    invented = sorted(
        str(row["sku"])
        for row in (
            PREP_PLAN_ROWS
            + ANOD_PAIR_ROWS
            + PAIR_ARTICLE_ROWS
            + PENDING_PLAN_ROWS
            + UNPAIRED_PAIR_ROWS
        )
        if re.fullmatch(r"ЮП-6[123]\d\d", str(row["sku"]))
    )
    assert not invented, f"остались выдуманные артикулы: {invented}"


def test_pair_rows_match_the_registered_pair_norms() -> None:
    """Строки парных артикулов совпадают с нормами ``PAIR_NORMS``.

    Пара в плане — две строки по одному артикулу каждой стороны пары. Норма
    подвеса живёт в паре, поэтому количества строк обязаны быть кратны ей:
    иначе импорт округлит их вниз, фикстура разойдётся с планом, а демо
    покажет чужое количество. Длина строки — общая нормальная длина пары,
    иначе пара не разрешится и норма не доедет ни до одной из позиций.
    """
    assert len(PAIR_ARTICLE_ROWS) == PAIR_ROW_COUNT
    assert len(PAIR_NORMS) == PAIR_ROW_COUNT // 2
    rows_by_sku = {str(row["sku"]): row for row in PAIR_ARTICLE_ROWS}
    assert len(rows_by_sku) == PAIR_ROW_COUNT, "в блоке пар повторяется артикул компонента"
    for sku_a, sku_b, length_m, per_hanger in PAIR_NORMS:
        assert per_hanger > 0, f"пара {sku_a}/{sku_b}: неположительная норма подвеса"
        for sku in (sku_a, sku_b):
            row = rows_by_sku.get(sku)
            assert row is not None, f"{sku}: нет строки пары в фикстуре"
            assert float(row["input_length_m"]) == length_m, (
                f"{sku}: длина строки {row['input_length_m']} не совпадает с нормой пары {length_m}"
            )
            assert int(row["output_quantity"]) % per_hanger == 0, (
                f"{sku}: количество {row['output_quantity']} не кратно норме {per_hanger}"
            )
        # Пара — единая загрузка N×A + N×B (#67): обе стороны везут поровну,
        # иначе подвес одной стороны не добирается, а другой не влезает.
        assert rows_by_sku[sku_a]["output_quantity"] == rows_by_sku[sku_b]["output_quantity"], (
            f"пара {sku_a}/{sku_b}: количества {rows_by_sku[sku_a]['output_quantity']} и "
            f"{rows_by_sku[sku_b]['output_quantity']} разошлись"
        )


def test_pending_pair_rows_are_equal_and_share_the_pair_norm() -> None:
    """Вторая партия той же пары в незакрытых — тоже пара равными долями.

    Строки идут соседями в листе, значит импорт видит в них пару: количества
    обязаны быть равны (#67), а норма — парная, одна на обе стороны.
    """
    sku_a, sku_b, _length_m, per_hanger = PAIR_NORMS[0]
    drafted = [row for row in PENDING_PLAN_ROWS if str(row["sku"]) in (sku_a, sku_b)]
    assert len(drafted) == 2, f"в незакрытых не пара: {[row['sku'] for row in drafted]}"
    quantities = [int(row["output_quantity"]) for row in drafted]
    assert quantities[0] == quantities[1], f"стороны пары разошлись по количеству: {quantities}"
    assert quantities[0] % per_hanger == 0, f"количество {quantities[0]} не кратно норме {per_hanger}"
    released = [row for row in PAIR_ARTICLE_ROWS if str(row["sku"]) in (sku_a, sku_b)]
    assert quantities[0] != int(released[0]["output_quantity"]), (
        "вторая партия совпала с выпущенной — импорт склеит строки по fingerprint"
    )


def test_pair_rows_are_not_glued_into_one_line() -> None:
    """Склейки пары в листе нет (#312): у компонентов разные артикулы, а строки
    базового блока отличаются от строк пары — иначе импорт склеил бы их по
    fingerprint в одну позицию и пара бы не появилась на доске."""
    packing_rows = {str(row["sku"]): row for row in PACKING_PLAN_ROWS}
    for row in PAIR_ARTICLE_ROWS:
        base = packing_rows.get(str(row["sku"]))
        if base is None:
            continue
        assert row != base, f"{row['sku']}: строка пары совпала с базовой строкой"


def test_unpaired_variant_of_the_pair_is_counted_by_its_own_norm() -> None:
    """Непарный вариант пары — те же две строки и та же длина 2,7 м, но каждая
    со своим наименованием и своей нормой подвеса, а не парной.

    В реальном файле заказчика строки 10 и 11 «Плана март 26 03» — одна пара,
    и наименование у них общее: первая строка подписана, вторая приходит с
    пустой ячейкой, по общему наименованию пару и опознают. Парный блок эту
    связь повторяет — ЮП-2604 и ЮП-2616 подписаны одинаково. Непарный блок —
    те же два артикула самостоятельными строками: «Кант универсальный 29мм» и
    «Кант универсальный 26мм» (свои наименования артикулов).

    Длина у непарных строк та же, что у пары: непарность выражает не длина, а
    ключ ``own_norm`` — сидер ставит его ручным override позиции, и резолвер
    (тот же, что считает печать) ставит override выше пары. Проверяется здесь
    то, что видно без БД: норма положительна и не равна парной, длина совпадает
    с парной, а количества кратны парной норме — импорт округляет по ней, пока
    override ещё не поставлен. Само значение нормы сверяется с одиночным
    резолвом артикула в БД-тесте.
    """
    assert len(UNPAIRED_PAIR_ROWS) == UNPAIRED_ROW_COUNT
    sku_a, sku_b, pair_length_m, per_hanger = PAIR_NORMS[0]
    assert {str(row["sku"]) for row in UNPAIRED_PAIR_ROWS} == {sku_a, sku_b}, (
        "непарный вариант собран не из артикулов пары"
    )
    pair_rows = {str(row["sku"]): row for row in PAIR_ARTICLE_ROWS}
    assert pair_rows[sku_a]["name"] == pair_rows[sku_b]["name"], (
        "парный блок потерял общее наименование — связи пары на экране не видно"
    )
    names = {str(row["sku"]): str(row["name"]) for row in UNPAIRED_PAIR_ROWS}
    assert len(set(names.values())) == UNPAIRED_ROW_COUNT, (
        f"у непарных строк общее наименование: {sorted(names.values())}"
    )
    taken = Counter((str(row["sku"]), int(row["output_quantity"])) for row in DEMO_PLAN_ROWS)
    for row in UNPAIRED_PAIR_ROWS:
        sku = str(row["sku"])
        assert names[sku] != pair_rows[sku]["name"], (
            f"{sku}: непарная строка повторяет парное наименование — разницы не видно"
        )
        assert _lifecycle_of(row) == LIFECYCLE_RELEASED, (
            f"{sku}: непарная строка не выпущена — задания у неё не будет, и считать нечего"
        )
        assert float(row["input_length_m"]) == pair_length_m, (
            f"{sku}: длина {row['input_length_m']} разошлась с парной {pair_length_m} — "
            "непарность выражает норма, а не длина"
        )
        own_norm = int(row["own_norm"])
        assert own_norm > 0 and own_norm != per_hanger, (
            f"{sku}: своя норма {own_norm} не отличается от парной {per_hanger}"
        )
        assert int(row["output_quantity"]) % per_hanger == 0, (
            f"{sku}: количество {row['output_quantity']} не кратно парной норме {per_hanger} — "
            "импорт округлит строку и фикстура разойдётся с планом"
        )
        assert taken[(sku, int(row["output_quantity"]))] == 1, (
            f"{sku}: количество {row['output_quantity']} уже занято другой строкой — импорт "
            "отбросит её как дубликат (наименования fingerprint не содержит)"
        )


def test_pending_rows_cover_both_unfinished_states() -> None:
    """Незакрытые строки закрывают оба состояния плана: неутверждённые (ждут
    планировщика) и утверждённые без релиза (ждут запуска). Без них демо
    показывало бы только «всё в работе»."""
    states = Counter(_lifecycle_of(row) for row in PENDING_PLAN_ROWS)
    assert len(PENDING_PLAN_ROWS) == PENDING_ROW_COUNT
    assert states[LIFECYCLE_DRAFT] >= 1, "нет неутверждённых строк"
    assert states[LIFECYCLE_APPROVED] >= 1, "нет утверждённых без релиза"
    assert states[LIFECYCLE_RELEASED] == 0, "в блоке незакрытых есть выпущенная строка"
    packing_rows = {str(row["sku"]): row for row in PACKING_PLAN_ROWS}
    reused = [str(row["sku"]) for row in PENDING_PLAN_ROWS if str(row["sku"]) in packing_rows]
    assert reused, "блок не повторяет артикулы базовых строк — демо плодит фейковые карточки"
    for row in PENDING_PLAN_ROWS:
        assert row != packing_rows.get(str(row["sku"])), (
            f"{row['sku']}: строка совпала с базовой — импорт склеит их по fingerprint"
        )


def test_cut_split_group_is_one_position_with_two_outputs() -> None:
    """Распил — это одна позиция с двумя выходами, а не две позиции (ADR-0003).

    Группа строк в файле заказчика: вход объединён на все строки группы,
    выходы идут построчно. Единица импорта — группа, а не строка, поэтому у
    распила одна позиция с двумя выходами. На пиле у неё одно задание на
    вход, дальше по маршруту оно раздваивается по длинам.

    Признак продолжения группы обязателен: строка со своим входным количеством
    импорт считает самостоятельной операцией, и распил рассыплется на две
    несвязанные позиции — оператор увидит два задания вместо одного.
    """
    parsed = parse_factory_plan_workbook(
        _plan_workbook(PENDING_PLAN_ROWS),
        "demo-packing-plan.xlsx",
        0,
        column_mapping=IMPORT_TEMPLATES[0]["column_mapping"],
    )
    cut_rows = [row for row in PENDING_PLAN_ROWS if str(row["sku"]) == CUT_SPLIT_SKU]
    positions = [row for row in parsed.parsed_rows if row.source_sku == CUT_SPLIT_SKU]

    assert len(positions) == 1, f"{CUT_SPLIT_SKU}: распил дал {len(positions)} позиций вместо одной"
    position = positions[0]
    assert int(position.input_quantity) == CUT_SPLIT_INPUT_QUANTITY
    assert position.input_dimensions == {"length_mm": round(CUT_SPLIT_INPUT_LENGTH_M * 1000)}
    outputs = sorted(
        (entry["dimensions"] or {}).get("length_mm") for entry in position.outputs
    )
    assert outputs == [round(length * 1000) for length in sorted(CUT_SPLIT_OUTPUT_LENGTHS_M)], (
        f"{CUT_SPLIT_SKU}: выходы позиции {outputs}"
    )
    assert len(position.source_row_numbers) == len(cut_rows), (
        f"{CUT_SPLIT_SKU}: в позицию попали не все строки группы — "
        f"{position.source_row_numbers}"
    )
    assert not position.errors, f"{CUT_SPLIT_SKU}: ошибки импорта {position.errors}"
    # Баланс группы импорт проверяет сам и предупреждает о расхождении; мы
    # обязаны привести цифры так, чтобы предупреждения не было.
    assert not position.warnings, f"{CUT_SPLIT_SKU}: предупреждения импорта {position.warnings}"


def test_cut_split_rows_keep_one_input_and_balance_the_material() -> None:
    """Вход у строк распила общий, а баланс материала сходится до метра.

    Баланс обязателен: распил либо съедает заготовку, либо производит её из
    воздуха, и тогда бюджет передачи считается не по тому размеру, который
    реально поедет на следующую стадию.
    """
    cut_rows = [row for row in PENDING_PLAN_ROWS if str(row["sku"]) == CUT_SPLIT_SKU]
    assert len(cut_rows) == len(CUT_SPLIT_OUTPUT_LENGTHS_M), (
        f"{CUT_SPLIT_SKU}: строк распила {len(cut_rows)}"
    )
    for row in cut_rows:
        assert float(row["input_length_m"]) == CUT_SPLIT_INPUT_LENGTH_M
        assert int(row["input_quantity"]) == CUT_SPLIT_INPUT_QUANTITY, (
            f"{CUT_SPLIT_SKU}: у строки распила свой вход — импорт не соберёт группу"
        )
        assert _lifecycle_of(row) == LIFECYCLE_DRAFT, (
            f"{CUT_SPLIT_SKU}: строка распила не неутверждена — на «Плане» её не видно"
        )
    lengths = sorted(float(row["output_length_m"]) for row in cut_rows)
    assert tuple(lengths) == tuple(sorted(CUT_SPLIT_OUTPUT_LENGTHS_M)), (
        f"{CUT_SPLIT_SKU}: выходные длины {lengths}"
    )
    # Ровно одна строка помечена продолжением группы: без этого импорт сделал
    # бы из распила две позиции со своим входом каждая.
    continuations = [row for row in cut_rows if row.get("input_continuation")]
    assert len(continuations) == 1, (
        f"{CUT_SPLIT_SKU}: строк-продолжений группы {len(continuations)}, ожидалась одна"
    )

    input_metres = CUT_SPLIT_INPUT_QUANTITY * CUT_SPLIT_INPUT_LENGTH_M
    output_metres = sum(
        float(row["output_length_m"]) * int(row["output_quantity"]) for row in cut_rows
    )
    assert round(input_metres, 3) == round(output_metres, 3), (
        f"{CUT_SPLIT_SKU}: из {input_metres} м заготовки выходит {output_metres} м"
    )


def test_cut_split_group_does_not_collide_with_the_base_block() -> None:
    """Распил отличается от базовой строки того же артикула.

    Базовый блок уже планирует ЮП-2627 (2,7 → 0,9 м, 200 шт). Распил заводит тот
    же артикул с другим количеством и второй длиной выхода — иначе импорт
    склеит их по fingerprint, и вместо распила в плане останется базовая строка.
    """
    cut_rows = [row for row in PENDING_PLAN_ROWS if str(row["sku"]) == CUT_SPLIT_SKU]
    base_rows = [row for row in PACKING_PLAN_ROWS if str(row["sku"]) == CUT_SPLIT_SKU]
    assert base_rows, f"{CUT_SPLIT_SKU}: нет базовой строки — распил не с чем сравнивать"
    for row in cut_rows:
        assert all(row != base for base in base_rows), (
            f"{CUT_SPLIT_SKU}: строка распила совпала с базовой по fingerprint"
        )


def test_pending_rows_fill_the_planner_screen() -> None:
    """Незакрытых строк должно хватать, чтобы экран «План» не был пустым.

    Экран отдаёт ``GET /production-plans/all-positions``, а тот по контракту
    показывает позиции только в статусах ``draft``/``invalid``/``valid`` —
    рабочий список планировщика. Выпущенные позиции оттуда скрыты намеренно,
    поэтому демо из одних released-строк даёт пустую страницу при полной базе.
    Число сверху — не «сколько строк добавили», а сколько строк реально увидит
    человек.
    """
    visible_statuses = {status.value for status in ALL_POSITIONS_PLANNING_STATUSES}
    rows = DEMO_PLAN_ROWS + PREP_STAGE_PLAN_ROWS
    on_screen = [row for row in rows if _lifecycle_of(row) == LIFECYCLE_DRAFT]
    assert len(on_screen) >= 5, (
        f"на экране «План» окажется {len(on_screen)} строк — демо-стенд выглядит сломанным"
    )
    # Утверждённые без релиза экран не показывает: состояние есть в плане и в
    # сводке плана, но на «Плане» не видно. Если это изменится — покрытие демо
    # надо будет расширить, поэтому фиксируем текущее поведение явно.
    approved = [row for row in rows if _lifecycle_of(row) == LIFECYCLE_APPROVED]
    assert approved, "в демо нет утверждённых без релиза"
    assert "approved" not in visible_statuses, (
        "утверждённые позиции стали видны на «Плане» — покрытие демо надо расширить"
    )


def test_every_row_resolves_to_its_group_and_state() -> None:
    """У каждой строки обоих листов есть группа прогона и состояние из
    ``LIFECYCLES``: сид разбирает лист по этим двум признакам, и строка вне
    списков уронила бы прогон."""
    groups = {_row_group(row) for row in DEMO_PLAN_ROWS}
    assert groups == {"run", "prep", "anod", "pair", "unpaired", "pending"}, (
        f"группы строк: {sorted(groups)}"
    )
    assert {_lifecycle_of(row) for row in DEMO_PLAN_ROWS} <= {
        LIFECYCLE_DRAFT,
        LIFECYCLE_APPROVED,
        LIFECYCLE_RELEASED,
    }
    assert {_lifecycle_of(row) for row in PREP_STAGE_PLAN_ROWS} == {
        LIFECYCLE_DRAFT,
        LIFECYCLE_APPROVED,
        LIFECYCLE_RELEASED,
    }, "второй лист не показывает незакрытые состояния"


def test_prep_stage_rows_cover_every_route_variant() -> None:
    """Второй лист закрывает все три варианта маршрута профиля
    ``prep_stage_plan``: сверловка, пресс (окно и гребёнка) и чистый дробеструй.
    Без одного из них участок подготовки остался бы с пустой плиткой."""
    operations = {str(row["operation"]).strip().lower() for row in PREP_STAGE_PLAN_ROWS}
    assert operations == set(STAGE_OPERATIONS), f"операции второго плана: {sorted(operations)}"
    assert any(_lifecycle_of(row) == LIFECYCLE_RELEASED for row in PREP_STAGE_PLAN_ROWS), (
        "второй план не отдаёт ни одного задания"
    )


def test_new_block_lengths_are_finished_catalog_lengths() -> None:
    """Длина строки и длины раскроя новых блоков — нормальные (готовые) длины
    каталога (``product_lengths.raw_length_mm IS NULL``), а не заготовки.

    Заготовка (2,75 / 1,83 / 3,05 / 2,55 / 2,76 / 2,45 / 2,08 / 2,51) — это
    пруток, а не длина изделия: попав в план, она показала бы «2,75» вместо
    дела. Каталог отдаёт готовые длины 0,9 / 1,35 / 1,8 / 2,5 / 2,7 / 3,0.
    """
    for row in PREP_PLAN_ROWS + ANOD_PAIR_ROWS:
        for field in ("input_length_m", "output_length_m"):
            value = float(row[field])
            assert value not in BILLET_LENGTHS, f"{row['sku']}: заготовка {value} как длина изделия"
            assert value in FINISHED_LENGTHS, f"{row['sku']}: {value} вне готовых длин каталога"



@pytest.mark.parametrize(
    ("field", "check"),
    [
        ("sku", lambda value: isinstance(value, str) and value.strip()),
        ("name", lambda value: isinstance(value, str) and value.strip()),
        ("color", lambda value: isinstance(value, str) and value.strip()),
        ("packing", lambda value: isinstance(value, str) and value.strip()),
        ("input_length_m", lambda value: float(value) > 0),
        ("input_quantity", lambda value: float(value) > 0),
        ("output_length_m", lambda value: float(value) > 0),
        ("output_quantity", lambda value: float(value) > 0),
    ],
)
def test_fixture_rows_carry_importable_values(field: str, check) -> None:
    """Пустое/нулевое поле строки уронит валидацию импорта — доска останется без позиции."""
    broken = [(idx, row[field]) for idx, row in enumerate(DEMO_PLAN_ROWS) if not check(row[field])]
    assert not broken, f"поле {field!r} непригодно в {len(broken)} строках(ах): {broken[:5]}"


def test_fixture_declares_a_known_output_kind() -> None:
    """Вид выпуска выбирает маршрут (спанбонд против готовой продукции); значение
    вне двух доменных — позиция молча уходит в маршрут без упаковки."""
    unknown = sorted(
        {
            str(row["kind"])
            for row in DEMO_PLAN_ROWS
            if str(row["kind"]).strip().lower() not in {kind.lower() for kind in OUTPUT_KINDS}
        }
    )
    assert not unknown, f"вид выпуска вне {OUTPUT_KINDS}: {unknown}"


def test_fixture_cutting_rows_keep_output_not_longer_than_input() -> None:
    """Раскрой режет заготовку: выход длиннее входа — ошибка данных, из-за которой
    бюджет передачи считается по несуществующему размеру."""
    impossible = [
        (row["sku"], row["input_length_m"], row["output_length_m"])
        for row in DEMO_PLAN_ROWS
        if float(row["output_length_m"]) > float(row["input_length_m"])
    ]
    assert not impossible, f"выход длиннее входа: {impossible}"


def test_fixture_cutting_rows_do_not_shrink_piece_count() -> None:
    """Раскрой 2,7 → 0,9 даёт больше кусков, а не меньше: просадка количества на
    режущей позиции обрушила бы выдачу следующей стадии."""
    shrunk = [
        (row["sku"], row["input_quantity"], row["output_quantity"])
        for row in DEMO_PLAN_ROWS
        if float(row["output_length_m"]) < float(row["input_length_m"])
        and float(row["output_quantity"]) < float(row["input_quantity"])
    ]
    assert not shrunk, f"раскрой уменьшает количество: {shrunk}"


# ─── 2. Сборка xlsx для импорта ─────────────────────────────────────────────


def test_plan_workbook_carries_only_headers_known_to_import_template() -> None:
    """Импорт сопоставляет колонки по именам: заголовок, которого нет в шаблоне
    упаковочной карты, молча теряет своё поле, а лишняя колонка сдвигает разбор."""
    headers, data = _plan_sheet()
    template = IMPORT_TEMPLATES[0]["column_mapping"]
    known = {str(cfg.get("header") or "").strip() for cfg in template.values()}
    known |= {
        str(alias).strip()
        for cfg in template.values()
        for alias in (cfg.get("aliases") or [])
    }
    assert len(headers) == PLAN_SHEET_COLUMNS, f"ожидалось {PLAN_SHEET_COLUMNS} колонок: {headers}"
    unknown = [header for header in headers if header.strip() not in known]
    assert not unknown, f"шаблон импорта не знает колонки: {unknown}"
    assert len(data) == TOTAL_ROW_COUNT


def test_plan_workbook_parses_back_into_the_fixture_rows() -> None:
    """Тот же парсер, что и в UI, читает собранный сидером лист в те же позиции:
    сдвиг колонки в шаблоне тихо меняет раскрой позиции.

    Единица сопоставления — не строка фикстуры, а позиция: по ADR-0003 группа
    строк импортируется одной позицией, и строка-продолжение становится её
    вторым выходом. Поэтому строки свёрнуты в группы тем же признаком, по
    которому лист их собирает, — ``input_continuation``.
    """
    parsed = parse_factory_plan_workbook(
        _plan_workbook(DEMO_PLAN_ROWS),
        "demo-packing-plan.xlsx",
        0,
        column_mapping=IMPORT_TEMPLATES[0]["column_mapping"],
    )
    groups: list[list[Mapping[str, object]]] = []
    for source in DEMO_PLAN_ROWS:
        if source.get("input_continuation") and groups:
            groups[-1].append(source)
        else:
            groups.append([source])

    assert [row.source_sku for row in parsed.parsed_rows] == [
        str(group[0]["sku"]) for group in groups
    ], "порядок строк фикстуры доехал до парсера с потерями или перестановкой"

    problems = [
        (row.source_sku, row.errors, row.warnings)
        for row in parsed.parsed_rows
        if row.errors or row.warnings
    ]
    assert not problems, f"парсер пожаловался на строки фикстуры: {problems[:5]}"

    for row, group in zip(parsed.parsed_rows, groups, strict=True):
        source = group[0]
        assert row.payload["color"] == source["color"]
        assert row.payload["operation"] == (source["operation"] or None)
        assert row.payload["packaging"] == source["packing"]
        assert row.payload["output_kind"] == source["kind"]
        assert Decimal(str(row.input_quantity)) == Decimal(str(source["input_quantity"]))
        assert row.input_dimensions == {"length_mm": round(float(source["input_length_m"]) * 1000)}
        # Количество позиции — сумма выходов группы, а габариты — по каждому
        # выходу: у группы строк их столько же, сколько строк в группе.
        assert Decimal(str(row.quantity)) == sum(
            Decimal(str(member["output_quantity"])) for member in group
        )
        assert [entry["dimensions"] for entry in row.outputs] == [
            {"length_mm": round(float(member["output_length_m"]) * 1000)} for member in group
        ]
        assert [Decimal(str(entry["quantity"])) for entry in row.outputs] == [
            Decimal(str(member["output_quantity"])) for member in group
        ]



def _stage_sheet() -> tuple[list[str], list[list[object]]]:
    """Шапка и строки второго листа так, как их увидит xlsx-импорт."""
    book = load_workbook(BytesIO(_prep_stage_workbook(PREP_STAGE_PLAN_ROWS)))
    sheet = book["prepplan"]
    raw = [list(row) for row in sheet.iter_rows(values_only=True)]
    header_at = next(
        idx for idx, row in enumerate(raw) if any(cell not in (None, "") for cell in row)
    )
    headers = [str(cell) for cell in raw[header_at]]
    data = [row for row in raw[header_at + 1 :] if any(cell not in (None, "") for cell in row)]
    return headers, data


def test_prep_stage_workbook_carries_only_headers_of_its_own_template() -> None:
    """Лист второго плана собран по своему шаблону (#313), а не по упаковочной
    карте: заголовок чужого шаблона молча теряет своё поле, а лишняя колонка
    сдвигает разбор и портит габариты позиции."""
    headers, data = _stage_sheet()
    template = next(
        item for item in IMPORT_TEMPLATES if item["code"] == DEMO_PREP_STAGE_TEMPLATE_CODE
    )
    known = {str(cfg.get("header") or "").strip() for cfg in template["column_mapping"].values()}
    assert len(headers) == STAGE_SHEET_COLUMNS, f"ожидалось {STAGE_SHEET_COLUMNS} колонок: {headers}"
    unknown = [header for header in headers if header.strip() not in known]
    assert not unknown, f"шаблон {DEMO_PREP_STAGE_TEMPLATE_CODE} не знает колонки: {unknown}"
    assert headers == [str(cfg["header"]) for cfg in template["column_mapping"].values()]
    assert len(data) == STAGE_ROW_COUNT


def test_prep_stage_workbook_parses_back_into_the_fixture_rows() -> None:
    """Парсер второго шаблона читает собранный лист в те же позиции: длина
    обязана доехать габаритом (без неё позиция не находит остаток сырья), а
    количество — без входа и раскроя."""
    parsed = parse_factory_plan_workbook(
        _prep_stage_workbook(PREP_STAGE_PLAN_ROWS),
        "demo-prep-stage-plan.xlsx",
        0,
        column_mapping=next(
            item["column_mapping"]
            for item in IMPORT_TEMPLATES
            if item["code"] == DEMO_PREP_STAGE_TEMPLATE_CODE
        ),
    )
    assert [row.source_sku for row in parsed.parsed_rows] == [
        str(source["sku"]) for source in PREP_STAGE_PLAN_ROWS
    ], "порядок строк второго плана доехал до парсера с потерями"
    problems = [
        (row.source_sku, row.errors, row.warnings)
        for row in parsed.parsed_rows
        if row.errors or row.warnings
    ]
    assert not problems, f"парсер пожаловался на строки второго плана: {problems[:5]}"
    for row, source in zip(parsed.parsed_rows, PREP_STAGE_PLAN_ROWS, strict=True):
        assert Decimal(str(row.quantity)) == Decimal(str(source["quantity"]))
        assert row.outputs[0]["dimensions"] == {
            "length_mm": round(float(source["length_m"]) * 1000)
        }
        assert row.payload["operation"] == (source["operation"] or None)

# ─── 3. Раскладка демо-прогресса ────────────────────────────────────────────


def test_progress_mode_splits_positions_by_declared_shares() -> None:
    """Доли раскладки — контракт доски: 15 % закрытых, 35 % в работе, хвост выдан."""
    modes = [_progress_mode(index, 100) for index in range(100)]
    assert [modes.count(name) for name in ("done", "partial", "issued")] == [15, 35, 50]


@pytest.mark.parametrize(
    ("index", "total", "expected"),
    [
        (0, 100, "done"),  # самая старая позиция закрыта
        (2, 20, "done"),  # 10 % — внутри закрытого бакета
        (3, 20, "partial"),  # ровно 15 % — граница достаётся следующему бакету
        (9, 20, "partial"),  # 45 % — хвост бакета «в работе»
        (10, 20, "issued"),  # ровно 50 % — граница достаётся выданным
        (19, 20, "issued"),
        (0, 1, "done"),
        (1, 3, "partial"),
        (2, 3, "issued"),
        (4, 5, "issued"),  # короткий план: хвост не выпадает из бакетов
        (0, 0, "done"),  # пустой план не делит на ноль
    ],
)
def test_progress_mode_respects_bucket_edges(index: int, total: int, expected: str) -> None:
    assert _progress_mode(index, total) == expected


# ─── 4. Спецификация дневных планов ──────────────────────────────────────────


def test_daily_plan_specs_schedules_twelve_plans_over_nine_days() -> None:
    """История доски: 12 карточек на 9 дней, две на дату там, где цех делает два
    плана в день, и ни одной карточки вне окна в 9 дней."""
    today = date(2026, 3, 17)
    specs = _daily_plan_specs(_tasks_with_ids(list(range(101, 156))), today)

    assert [plan_date for plan_date, _ in specs] == [
        today - timedelta(days=8),
        today - timedelta(days=8),
        today - timedelta(days=7),
        today - timedelta(days=7),
        today - timedelta(days=6),
        today - timedelta(days=5),
        today - timedelta(days=5),
        today - timedelta(days=4),
        today - timedelta(days=3),
        today - timedelta(days=2),
        today - timedelta(days=1),
        today,
    ]
    # 55 заданий на 12 планов: остаток достаётся первым планам, иначе последние
    # карточки вырождаются в одну большую и несколько пустых.
    assert [len(task_ids) for _, task_ids in specs] == [5] * 7 + [4] * 5


@pytest.mark.parametrize(
    ("count", "expected_plans"),
    [(0, 0), (1, 1), (5, 5), (11, 11), (12, 12), (13, 12), (55, 12), (100, 12)],
)
def test_daily_plan_specs_places_every_task_exactly_once(count: int, expected_plans: int) -> None:
    """Задание принадлежит ровно одному дневному плану (UNIQUE по work_task_id) и
    раздаётся в порядке выдачи: старые карточки — отработавшие, свежие — очередь.
    Заданий меньше, чем слотов, — карточек ровно столько же, сколько заданий."""
    ids = list(range(101, 101 + count))
    specs = _daily_plan_specs(_tasks_with_ids(ids), date(2026, 3, 17))
    assert len(specs) == expected_plans
    assert [task_id for _, task_ids in specs for task_id in task_ids] == ids


@pytest.mark.parametrize("count", [1, 5, 11, 12, 13, 55])
def test_daily_plan_specs_never_yields_an_empty_card(count: int) -> None:
    """Пустая карточка дневного плана — мусор в панели, а не данные: слот без
    заданий пропускается, а не превращается в план на 0 позиций."""
    specs = _daily_plan_specs(_tasks_with_ids(list(range(count))), date(2026, 3, 17))
    empty = [plan_date for plan_date, task_ids in specs if not task_ids]
    assert not empty, f"{len(empty)} из {len(specs)} карточек остались бы без заданий"


# ─── 5. Доменный прогон среза ────────────────────────────────────────────────


def _slice_rows_by_group() -> dict[str, list[dict[str, object]]]:
    """Строки среза по группам прогона — тем же разбором, что и сид
    (``_row_group``). Порядок внутри группы — тот же, что у сида: позиции
    импортируются в порядке строк листа."""
    groups: dict[str, list[dict[str, object]]] = {}
    for row in _opening_rows(DEMO_SLICE_ROWS):
        groups.setdefault(_row_group(row), []).append(row)
    assert sum(len(rows) for rows in groups.values()) == len(_opening_rows(DEMO_SLICE_ROWS))
    assert "pending" in groups, "в срезе нет незакрытых строк"
    return groups


#: Участки кругового разбора каждой группы прогона.
_SLICE_GROUP_CODES = {
    "run": DEMO_RUN_SECTION_CODES,
    "prep": DEMO_PREP_SECTION_CODES,
    "anod": DEMO_ANOD_SECTION_CODES,
    "pair": DEMO_RUN_SECTION_CODES,
    "unpaired": DEMO_RUN_SECTION_CODES,
}


@pytest.mark.slow
@pytest.mark.asyncio
async def test_slice_seed_walks_the_domain_path(demo_seed: dict, demo_db: AsyncSession) -> None:
    """Оба среза проходят доменный путь целиком: упаковочный план даёт
    released-позиции с раскроем фикстуры и задания на участках, которые реально
    есть в их маршрутах, а второй план импортируется своим шаблоном."""
    stats = demo_seed
    # Позиция создаётся на ГРУППУ строк, а не на строку (ADR-0003): распил одного
    # входа на две длины — одна позиция с двумя выходами.
    slice_openers = _opening_rows(DEMO_SLICE_ROWS)
    stage_openers = _opening_rows(DEMO_STAGE_SLICE_ROWS)
    released_count = len(_released(DEMO_SLICE_ROWS)) + len(_released(DEMO_STAGE_SLICE_ROWS))
    assert stats["positions"] == len(slice_openers) + len(stage_openers)

    progress = stats["route_progress"]
    assert progress["skipped"] == []
    assert progress["stages"] == released_count
    assert progress["completed"] + progress["partial"] + progress["issued"] == released_count

    plans = list((await demo_db.scalars(select(ProductionPlan).order_by(ProductionPlan.id))).all())
    assert len(plans) == 2, "демо-стенд должен держать два набора планов"
    assert stats["production_plan_ids"] == [plan.id for plan in plans]
    assert stats["production_plan_id"] == plans[0].id

    positions = await _positions(demo_db, plans[0].id)
    stage_positions = await _positions(demo_db, plans[1].id)
    assert [position.source_sku for position in positions] == [
        str(row["sku"]) for row in slice_openers
    ]
    assert [position.source_sku for position in stage_positions] == [
        str(row["sku"]) for row in stage_openers
    ]

    # Состояние позиции — ровно то, чем помечена строка листа: неутверждённые
    # остались в черновике, утверждённые без релиза — утверждены, остальные
    # выпущены. Это и есть покрытие планировщика, а не только цеха.
    expected_status = {
        LIFECYCLE_DRAFT: PlanPositionStatus.draft,
        LIFECYCLE_APPROVED: PlanPositionStatus.approved,
        LIFECYCLE_RELEASED: PlanPositionStatus.released,
    }
    for row, position in zip(slice_openers, positions, strict=True):
        assert position.status == expected_status[_lifecycle_of(row)], (
            f"{position.source_sku}: статус {position.status} не соответствует "
            f"{_lifecycle_of(row)}"
        )
    for row, position in zip(stage_openers, stage_positions, strict=True):
        assert position.status == expected_status[_lifecycle_of(row)]
    assert stats["positions_by_status"] == {
        LIFECYCLE_DRAFT: sum(
            1 for row in slice_openers + stage_openers if _lifecycle_of(row) == LIFECYCLE_DRAFT
        ),
        LIFECYCLE_APPROVED: sum(
            1
            for row in slice_openers + stage_openers
            if _lifecycle_of(row) == LIFECYCLE_APPROVED
        ),
        LIFECYCLE_RELEASED: released_count,
    }

    # Раскрой и габариты упаковочных позиций доехали из строк листа: количество
    # позиции — сумма выходов группы, габариты — по каждому выходу.
    slice_groups = _fold_rows(DEMO_SLICE_ROWS)
    released = [group for group in slice_groups if _lifecycle_of(group[0]) == LIFECYCLE_RELEASED]
    released_positions = [
        position
        for group, position in zip(slice_groups, positions, strict=True)
        if _lifecycle_of(group[0]) == LIFECYCLE_RELEASED
    ]
    assert [position.quantity for position in released_positions] == [
        sum(Decimal(str(row["output_quantity"])) for row in group) for group in released
    ]
    assert [position.input_quantity for position in released_positions] == [
        Decimal(str(group[0]["input_quantity"])) for group in released
    ]
    assert [position.input_dimensions for position in released_positions] == [
        {"length_mm": round(float(group[0]["input_length_m"]) * 1000)} for group in released
    ]
    assert [[entry["dimensions"] for entry in position.outputs] for position in released_positions] == [
        [{"length_mm": round(float(row["output_length_m"]) * 1000)} for row in group]
        for group in released
    ]

    # Участок получает столько заданий, сколько строк срезов реально проходит
    # через него. Второй план маршрут до отгрузки не строит: у него только
    # участки подготовки.
    sections = await _demo_sections(demo_db)
    expected_by_section = _expected_tasks_by_section(DEMO_SLICE_ROWS)
    for code, counts in _expected_stage_tasks_by_section(DEMO_STAGE_SLICE_ROWS).items():
        expected_by_section[code] += counts
    for code, section in sections.items():
        assert stats["tasks_by_section"][code]["total"] == expected_by_section[code], (
            f"участок {code}: заданий {stats['tasks_by_section'][code]['total']}, "
            f"а через срезы проходит {expected_by_section[code]}"
        )
        assert await _count(
            demo_db, WorkTask, WorkTask.section_id == section.id
        ) == expected_by_section[code]

    # Нормативная длина — вход последней строки артикула (у ALS1288 их две,
    # и у пары ЮП-2256 тоже).
    assert await _demo_product_lengths(demo_db, DEMO_SLICE_ROWS) == _expected_primary_lengths(
        DEMO_SLICE_ROWS
    )

    # Глубина прогона — по бакетам прогресса: старые закрыты, следующие
    # выполнены на 60 %, хвост выдан и не начат. Участок остановки — первый
    # участок круга группы, который есть в маршруте позиции. Неутверждённые
    # строки (незакрытые и непарный вариант пары) в прогон не входят: заданий у
    # них нет, и «skipped» обязан остаться пустым.
    slice_groups = _slice_rows_by_group()
    positions_by_group: dict[str, list[PlanPosition]] = {name: [] for name in slice_groups}
    for row, position in zip(slice_openers, positions, strict=True):
        if _lifecycle_of(row) == LIFECYCLE_RELEASED:
            positions_by_group[_row_group(row)].append(position)
    positions_by_group["prep_stage"] = [
        position
        for row, position in zip(stage_openers, stage_positions, strict=True)
        if _lifecycle_of(row) == LIFECYCLE_RELEASED
    ]
    expected_share = {"done": 1.0, "partial": 0.6, "issued": 0.0}
    for name, rows in slice_groups.items():
        group_positions = positions_by_group[name]
        live_rows = _released(rows)
        if not live_rows:
            # Группы без выпущенных строк: у них нет заданий, и проверять долю
            # прогресса не на чем. Непустой список означал бы, что в прогон
            # попала неутверждённая позиция.
            assert not group_positions, f"группа {name}: в прогон попала невыпущенная позиция"
            continue
        assert len(group_positions) == len(live_rows), f"группа {name}: позиций {len(group_positions)}"
        target_ids = [sections[code].id for code in _SLICE_GROUP_CODES[name]]
        for index, position in enumerate(group_positions):
            route_ids = set(await _position_section_ids(demo_db, position.id))
            target = _target_section_for(index, target_ids, route_ids)
            assert target is not None, f"позиция {position.source_sku} вне участков группы"
            task = await _target_task(demo_db, position.id, target)
            cache = await StockProjectionManager().get_task_cache(demo_db, task.id)
            issued = Decimal(str(cache["issued_quantity"]))
            assert issued > 0, f"задание участка позиции {position.source_sku} не выдано"
            share = float(Decimal(str(cache["completed_quantity"])) / issued)
            assert share == pytest.approx(
                expected_share[_progress_mode(index, len(group_positions))], abs=0.01
            ), f"позиция {position.source_sku}: доля {share}"

    stage_live = positions_by_group["prep_stage"]
    stage_target_ids = [sections[code].id for code in DEMO_PREP_SECTION_CODES]
    for index, position in enumerate(stage_live):
        route_ids = set(await _position_section_ids(demo_db, position.id))
        target = _target_section_for(index, stage_target_ids, route_ids)
        assert target is not None, f"позиция {position.source_sku} вне участков подготовки"
        task = await _target_task(demo_db, position.id, target)
        cache = await StockProjectionManager().get_task_cache(demo_db, task.id)
        assert Decimal(str(cache["issued_quantity"])) > 0, (
            f"задание участка позиции {position.source_sku} не выдано"
        )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_slice_sections_carry_their_own_operations(demo_db: AsyncSession, demo_seed: dict) -> None:
    """Участки среза показывают свои операции: сверловка — DRILL, пресс —
    PRESS_COMB (в срезе строка с гребёнкой), дробеструй — SHOT; повторный
    артикул встаёт на сверловке двумя отдельными заданиями.
    """
    sections = await _demo_sections(demo_db)
    positions = await _slice_positions(demo_db)

    async def operation_codes(position: PlanPosition, section_id: int) -> list[str]:
        return list(
            (
                await demo_db.scalars(
                    select(RouteOperation.operation_code)
                    .join(RouteStage, RouteStage.id == RouteOperation.route_stage_id)
                    .join(SectionPlanLine, SectionPlanLine.route_stage_id == RouteStage.id)
                    .where(
                        SectionPlanLine.plan_position_id == position.id,
                        SectionPlanLine.section_id == section_id,
                    )
                    .order_by(RouteOperation.sequence)
                )
            ).all()
        )

    expected_ops = {"DRILLING": "DRILL", "PRESSING": "PRESS_COMB", "SHOT_BLAST": "SHOT"}
    for code, expected in expected_ops.items():
        codes = {
            operation
            for position in positions
            for operation in await operation_codes(position, sections[code].id)
        }
        assert codes == {expected}, f"участок {code}: операции {codes}"
        live = await _count(
            demo_db,
            WorkTask,
            WorkTask.section_id == sections[code].id,
            WorkTask.status.in_(ACTIVE_STATUSES),
        )
        assert live >= 1, f"на участке {code} нет живого задания"

    # Повтор артикула — два отдельных задания сверловки, а не одно склеенное.
    drill_tasks = [
        await _target_task(demo_db, position.id, sections["DRILLING"].id)
        for position in positions
        if position.source_sku == "ALS1288"
    ]
    assert len({task.id for task in drill_tasks}) == 2, "повтор артикула не дал двух заданий"

    # Дневная панель участка отдаёт те же коды, что этап маршрута.
    board = await get_section_board(demo_db, section_id=sections["DRILLING"].id, limit=100)
    codes_by_task = {row["id"]: row["operation_codes"] for row in board["tasks"]}
    for task in drill_tasks:
        assert codes_by_task.get(task.id) == ["DRILL"], (
            f"доска отдала {codes_by_task.get(task.id)} вместо ['DRILL']"
        )

    # Анодирование — общая стадия всех выпущенных строк: цвет берётся из
    # строки, а не из первой операции группы (тот дефект красил весь цех в
    # одну «Серебро»). Незакрытые строки на анодирование не дошли вовсе.
    expected_color_ops = await _expected_color_ops(demo_db)
    for row, position in zip(_opening_rows(DEMO_SLICE_ROWS), positions, strict=True):
        if _lifecycle_of(row) != LIFECYCLE_RELEASED:
            assert not await _position_section_ids(demo_db, position.id), (
                f"позиция {position.source_sku} не выпущена, а строка маршрута у неё есть"
            )
            continue
        color_op, pack_op = await operation_codes(position, sections["ANODIZING"].id)
        assert color_op == expected_color_ops[str(row["color"])]
        expected_pack = "PACK_STRETCH" if str(row["kind"]).upper() == "ГП" else "PACK_SPUNBOND"
        assert pack_op == expected_pack
    assert len(set(expected_color_ops.values())) > 1, "в срезе один цвет на все позиции"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_slice_anod_pair_lands_on_anodizing_with_both_pack_ops(
    demo_seed: dict, demo_db: AsyncSession
) -> None:
    """Пара анодирования доезжает до ANODIZING двумя заданиями: один артикул,
    один цвет и размер, но разные упаковочные операции — ровно то, что фронт
    сливает в одну строку плана с разбивкой упаковки («Спанбонд 300 · Стрейч
    200»). Обе строки пары незакрыты, поэтому обе стоят в дневном плане
    анодирования.
    """
    _ = demo_seed
    sections = await _demo_sections(demo_db)
    positions = await _slice_positions(demo_db)
    counts = Counter(
        str(row["sku"]) for row in ANOD_PAIR_ROWS if row in DEMO_SLICE_ROWS
    )
    full_pairs = [sku for sku, count in counts.items() if count == 2]
    assert len(full_pairs) == 1, f"в срезе не одна целая пара: {dict(counts)}"
    pair_sku = full_pairs[0]

    pair_positions = [position for position in positions if position.source_sku == pair_sku]
    assert len(pair_positions) == 2, "пара анодирования потеряла строку"

    anod_tasks = [
        await _target_task(demo_db, position.id, sections["ANODIZING"].id)
        for position in pair_positions
    ]
    assert len({task.id for task in anod_tasks}) == 2, "на анодировании не два задания пары"
    assert {task.planned_quantity for task in anod_tasks} == {
        Decimal(300),
        Decimal(200),
    }, "количества пары потерялись"
    assert all(task.planned_quantity > 0 for task in anod_tasks)
    assert len({task.dimensions.get("length_mm") for task in anod_tasks}) == 1, (
        "у пары разные размеры"
    )
    # Обе строки пары незакрыты и потому обе стоят в дневном плане анодирования.
    planned_task_ids = set(
        (
            await demo_db.scalars(
                select(DailyPlanItem.work_task_id)
                .join(DailyPlan, DailyPlan.id == DailyPlanItem.daily_plan_id)
                .where(DailyPlan.section_id == sections["ANODIZING"].id)
            )
        ).all()
    )
    assert {task.id for task in anod_tasks} <= planned_task_ids, (
        "строка пары не попала в дневной план анодирования"
    )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_pair_and_unpaired_positions_carry_their_own_hanger_norms(
    demo_seed: dict, demo_db: AsyncSession
) -> None:
    """Парные позиции делят одну норму подвеса, непарные и одиночные — свои.

    Пара импортируется ДВУМЯ позициями без склейки ``A+B`` (#312), и обе тянут
    одну парную норму из ``product_pairs``. Непарный вариант тех же артикулов
    несёт ручной override позиции (то же поле, что пишет экран «План»), и
    резолвер ставит его выше пары — длина при этом та же (2,7 м), различает
    только override. Наименования: у пары одно общее, у непарных — свои; у
    одинокой строки импорт помечает ``no_paired_row`` и парной нормой её не
    считает.

    Ключ поиска позиции — не SKU: артикул пары встречается в плане несколько
    раз (базовая строка, выпущенная партия, неутверждённая вторая партия), и
    словарь по SKU молча схлопнул бы их в одну позицию.
    """
    assert demo_seed["product_pairs"] == len(PAIR_NORMS)
    positions = await _slice_positions(demo_db)
    resolved = await resolve_positions_hanger(demo_db, positions)

    def _position_for(row: Mapping[str, object]) -> PlanPosition:
        matches = [
            position
            for position in positions
            if position.source_sku == str(row["sku"])
            and position.quantity == Decimal(str(row["output_quantity"]))
        ]
        assert len(matches) == 1, (
            f"{row['sku']}: строка фикстуры на {row['output_quantity']} шт не дала ровно "
            f"позицию (нашлось {len(matches)})"
        )
        return matches[0]

    pair_rows = {str(row["sku"]): row for row in PAIR_ARTICLE_ROWS}
    for sku_a, sku_b, length_m, per_hanger in PAIR_NORMS:
        pair_positions = [_position_for(pair_rows[sku_a]), _position_for(pair_rows[sku_b])]
        assert len({position.id for position in pair_positions}) == 2, (
            f"пара {sku_a}/{sku_b} не разъежалась на две позиции"
        )
        assert all("+" not in position.source_sku for position in pair_positions), (
            "в плане осталась склейка пары"
        )
        for position in pair_positions:
            value = resolved[position.id]
            assert (value.quantity_per_hanger, value.source) == (per_hanger, "manual"), (
                f"{position.source_sku}: норма подвеса {value} вместо парной {per_hanger}"
            )
            assert position.input_dimensions == {"length_mm": round(length_m * 1000)}
            assert int(position.quantity) % per_hanger == 0, (
                f"{position.source_sku}: количество {position.quantity} не кратно паре"
            )

    per_hanger = PAIR_NORMS[0][3]
    partner_sku = PAIR_NORMS[0][1]

    # Непарный вариант: своя норма, свои наименования, длина парная.
    own_positions = [_position_for(row) for row in UNPAIRED_PAIR_ROWS]
    assert all("+" not in position.source_sku for position in own_positions), (
        "в плане осталась склейка пары"
    )
    assert {position.source_name for position in own_positions} == {
        str(row["name"]) for row in UNPAIRED_PAIR_ROWS
    }, "непарные позиции подписаны не своими наименованиями"
    for position, row in zip(own_positions, UNPAIRED_PAIR_ROWS, strict=True):
        value = resolved[position.id]
        assert value.quantity_per_hanger == int(row["own_norm"]) and value.source == "manual", (
            f"{position.source_sku}: норма {value} вместо своей {row['own_norm']} — "
            "строка посчитана парой"
        )
        assert value.quantity_per_hanger != per_hanger

    # Вторая партия той же пары в незакрытых — то же, что выпущенная: норма пары
    # и одно общее наименование на оба артикула.
    pair_skus = {str(row["sku"]) for row in UNPAIRED_PAIR_ROWS}
    pending_pair_rows = [row for row in PENDING_PLAN_ROWS if str(row["sku"]) in pair_skus]
    assert {str(row["sku"]) for row in pending_pair_rows} == pair_skus, (
        "в незакрытых нет обеих сторон пары — сравнивать не с чем"
    )
    pending_pair_positions = [_position_for(row) for row in pending_pair_rows]
    assert {position.status for position in pending_pair_positions} == {PlanPositionStatus.draft}, (
        "вторая партия пары не осталась неутверждённой"
    )
    pair_names = {position.source_name for position in pending_pair_positions}
    assert len(pair_names) == 1 and None not in pair_names, (
        f"у парных строк разошлись наименования {sorted(map(str, pair_names))} — связи пары не видно"
    )
    assert pair_names.isdisjoint({str(row["name"]) for row in UNPAIRED_PAIR_ROWS}), (
        "непарный вариант подписан парным наименованием — разницы не видно"
    )
    for position in pending_pair_positions:
        value = resolved[position.id]
        assert (value.quantity_per_hanger, value.source) == (per_hanger, "manual"), (
            f"{position.source_sku}: парная строка посчитана не парой — {value}"
        )
        assert int(position.quantity) % per_hanger == 0

    # Одинокая строка того же артикула (в базовом блоке реального файла у неё
    # партнёр был, в демо — нет) парой не считается. В чистой БД у артикула нет
    # геометрии, поэтому своя норма здесь пустая — проверяется, что она не
    # парная, а не конкретное число.
    solo_row = next(
        row
        for row in PACKING_PLAN_ROWS
        if str(row["sku"]) == partner_sku and int(row["output_quantity"]) == 300
    )
    solo_position = _position_for(solo_row)
    solo_marker = (solo_position.source_payload or {}).get("product_pair") or {}
    assert solo_marker.get("resolved") is False, solo_marker
    assert solo_marker.get("reason") == "no_paired_row", solo_marker
    solo_value = resolved[solo_position.id]
    assert (solo_value.quantity_per_hanger, solo_value.source) != (per_hanger, "manual"), (
        "одинокая строка посчитана парой"
    )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_pending_positions_stop_before_issuing_work(
    demo_seed: dict, demo_db: AsyncSession
) -> None:
    """Незакрытые позиции показывают незакрытую работу: у них нет ни строки
    внутреннего плана, ни задания, поэтому в дневные планы участков они не
    попадают — иначе доска показывала бы задание, которого никто не отдавал.
    """
    positions = await _slice_positions(demo_db, 0) + await _slice_positions(demo_db, 1)
    # Список, а не словарь по SKU: артикул незакрытой позиции может совпадать с
    # артикулом выпущенной строки того же плана (вторая партия пары), и словарь
    # молча склеил бы их в одну.
    pending = [position for position in positions if position.status != PlanPositionStatus.released]
    assert pending, "в демо нет ни одной незакрытой позиции"

    # Позиция создаётся на группу строк (ADR-0003), поэтому количество
    # незакрытой позиции — сумма выходов группы, а не количество одной строки.
    # Количество строки у двух листов называется по-разному: у упаковочного это
    # ``output_quantity``, у подготовительного — ``quantity``.
    def _planned(group: Sequence[Mapping[str, object]]) -> Decimal:
        return sum(
            Decimal(str(row.get("output_quantity", row.get("quantity")))) for row in group
        )

    expected = {
        (str(group[0]["sku"]), _planned(group)): _lifecycle_of(group[0])
        for group in _fold_rows(PENDING_PLAN_ROWS + PREP_STAGE_PLAN_ROWS)
        if _lifecycle_of(group[0]) != LIFECYCLE_RELEASED
    }
    actual = {(position.source_sku, position.quantity): position.status.value for position in pending}
    assert actual == expected, f"незакрытые позиции разошлись с фикстурой: {sorted(actual)}"

    line_counts = dict(
        (
            await demo_db.execute(
                select(SectionPlanLine.plan_position_id, func.count())
                .where(SectionPlanLine.plan_position_id.in_([p.id for p in pending]))
                .group_by(SectionPlanLine.plan_position_id)
            )
        ).all()
    )
    assert not line_counts, f"у незакрытых позиций есть строки плана: {line_counts}"
    task_count = await _count(
        demo_db,
        WorkTask,
        WorkTask.section_plan_line_id.in_(
            select(SectionPlanLine.id).where(
                SectionPlanLine.plan_position_id.in_([p.id for p in pending])
            )
        ),
    )
    assert task_count == 0, f"у незакрытых позиций есть задания: {task_count}"

    # Маршрут позиции импорт назначает сразу — планировщик видит, куда пойдёт
    # работа, ещё до утверждения. Иначе незакрытая позиция выглядела бы как
    # ошибка импорта, а не как работа, до которой ещё не дошли.
    assert all(position.route_id is not None for position in pending), (
        "у незакрытой позиции нет маршрута — импорт его не назначил"
    )



@pytest.mark.slow
@pytest.mark.asyncio
async def test_pending_positions_have_stock_to_take_into_work(
    demo_seed: dict, demo_db: AsyncSession
) -> None:
    """Под каждую незакрытую позицию на складе готовой продукции лежит остаток
    того же артикула и того же габарита.

    Позиция с нулевым остатком — мёртвая строка плана: взять её в работу нечем.
    Остаток ключуется ``product + section + dimensions`` (ADR-0001), поэтому
    проверяется не «сколько всего на складе», а совпадение по всем трём частям
    ключа — остаток другого размера выдаче тоже не найдётся.
    """
    stock_stats = demo_seed["pending_stock"]
    finished = await demo_db.scalar(
        select(Section).where(Section.code == "FINISHED_STOCK")
    )
    assert finished is not None, "склад готовой продукции не засеян"

    positions = await _slice_positions(demo_db, 0) + await _slice_positions(demo_db, 1)
    pending = [position for position in positions if position.status != PlanPositionStatus.released]
    assert stock_stats["items"] == len(pending)
    assert stock_stats["imported"] == len(pending), "часть остатков не завелась"

    balances = await _balances_by_key(demo_db, finished.id, [p.product_id for p in pending])
    for position in pending:
        key = (position.product_id, _dimensions_key(position_dimensions_for_task(position)))
        assert balances.get(key, Decimal(0)) > 0, (
            f"{position.source_sku}: на ГХП нет остатка под незакрытую позицию "
            f"(габарит {key[1]}) — её нечего будет взять в работу"
        )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_second_plan_builds_prep_stage_routes_up_to_prep_stock(
    demo_seed: dict, demo_db: AsyncSession
) -> None:
    """Второй набор плана импортирован своим шаблоном (#313): маршрут позиции
    заканчивается складом подготовки и не заходит на пилу, упаковку и
    анодирование — профиль ``prep_stage_plan`` их исключает. Задание при этом
    есть только на участках подготовки: склад заданий не порождает.
    """
    assert demo_seed["production_plan_ids"][1] is not None
    stage_positions = await _slice_positions(demo_db, 1)
    profile_id = await demo_db.scalar(
        select(RouteRuleProfile.id).where(RouteRuleProfile.code == DEMO_PREP_STAGE_PROFILE_CODE)
    )
    assert profile_id is not None, "профиль второго плана не засеян"

    section_by_id = {
        section.id: section.code for section in (await demo_db.scalars(select(Section))).all()
    }
    expected_routes = {
        "сверло": ["RAW_STOCK", "DRILLING", "SHOT_BLAST", "PREP_STOCK"],
        "окно": ["RAW_STOCK", "PRESSING", "SHOT_BLAST", "PREP_STOCK"],
        "гребенка": ["RAW_STOCK", "PRESSING", "SHOT_BLAST", "PREP_STOCK"],
        "": ["RAW_STOCK", "SHOT_BLAST", "PREP_STOCK"],
    }
    for row, position in zip(DEMO_STAGE_SLICE_ROWS, stage_positions, strict=True):
        assert position.route_profile_id == profile_id, (
            f"{position.source_sku}: маршрут собран не тем профилем"
        )
        stages = (
            await demo_db.scalars(
                select(RouteStage)
                .where(RouteStage.route_id == position.route_id)
                .order_by(RouteStage.sequence)
            )
        ).all()
        codes = [section_by_id.get(stage.storage_section_id or stage.section_id) for stage in stages]
        assert codes == expected_routes[str(row["operation"]).strip().lower()], (
            f"{position.source_sku}: маршрут {codes}"
        )
        route_codes = expected_routes[str(row["operation"]).strip().lower()]
        assert stages[-1].is_final and section_by_id.get(
            stages[-1].storage_section_id or stages[-1].section_id
        ) == "PREP_STOCK", f"{position.source_sku}: маршрут не заканчивается складом подготовки"
        if _lifecycle_of(row) != LIFECYCLE_RELEASED:
            assert not await _position_section_ids(demo_db, position.id), (
                f"{position.source_sku}: не выпущена, а строка внутреннего плана уже есть"
            )
            continue
        line_ids = list(
            (
                await demo_db.scalars(
                    select(SectionPlanLine.id).where(
                        SectionPlanLine.plan_position_id == position.id
                    )
                )
            ).all()
        )
        assert line_ids, f"{position.source_sku}: у позиции нет строк внутреннего плана"
        task_codes = {
            section_by_id[section_id]
            for section_id in (
                await demo_db.scalars(
                    select(WorkTask.section_id).where(
                        WorkTask.section_plan_line_id.in_(line_ids)
                    )
                )
            ).all()
        }
        # Задания есть только на участках подготовки. Склад сырья в списке —
        # служебное складское задание выдачи, а на складе подготовки заданий
        # не бывает вовсе: туда материал только передаётся.
        assert task_codes & {"SAWING", "PACKING", "ANODIZING", "PREP_STOCK"} == set(), (
            f"{position.source_sku}: задания вне участков подготовки: {task_codes}"
        )
        assert task_codes - {"RAW_STOCK"} == set(DEMO_PREP_SECTION_CODES) & set(route_codes), (
            f"{position.source_sku}: задания {task_codes} не совпали с маршрутом {route_codes}"
        )

@pytest.mark.slow
@pytest.mark.asyncio
async def test_slice_daily_plans_and_rerun_replaces(demo_seed: dict, demo_db: AsyncSession) -> None:
    """Дневные планы собираются из незакрытых заданий среза, а повторный прогон
    заменяет набор, не наслаивая второй."""
    first = demo_seed
    plans = list((await demo_db.scalars(select(DailyPlan))).all())
    expected_plans = {
        code: min(DAILY_PLANS_PER_SECTION, entry["planned"])
        for code, entry in first["tasks_by_section"].items()
    }
    assert len(plans) == first["daily_plans"] == sum(expected_plans.values())

    sections = await _demo_sections(demo_db)
    for code, section in sections.items():
        section_plans = [plan for plan in plans if plan.section_id == section.id]
        assert len(section_plans) == expected_plans[code], f"участок {code}: {len(section_plans)} карточек"
        for plan in section_plans:
            task_ids = (
                await demo_db.scalars(
                    select(DailyPlanItem.work_task_id).where(DailyPlanItem.daily_plan_id == plan.id)
                )
            ).all()
            assert task_ids, f"карточка участка {code} осталась без заданий"
            statuses = set(
                (await demo_db.scalars(select(WorkTask.status).where(WorkTask.id.in_(task_ids)))).all()
            )
            assert not statuses & TERMINAL_TASK_STATUSES, "в план попало закрытое задание"

    items = await _count(demo_db, DailyPlanItem)
    distinct = await demo_db.scalar(select(func.count(func.distinct(DailyPlanItem.work_task_id))))
    assert items == distinct == sum(expected_plans.values())

    # Второй прогон тех же срезов: тот же набор, без второго датасета.
    second = await seed_packing_plan_demo(
        demo_db,
        reset=True,
        run_route=True,
        rows=DEMO_SLICE_ROWS,
        prep_stage_rows=DEMO_STAGE_SLICE_ROWS,
    )
    assert second["positions"] == first["positions"]
    assert second["positions_by_status"] == first["positions_by_status"]
    assert second["tasks_by_section"] == first["tasks_by_section"]
    assert second["daily_plans"] == first["daily_plans"]
    assert second["route_progress"] == first["route_progress"]
    assert second["cleared_daily_plans"] == first["daily_plans"], "прежние карточки не снесены"
    assert second["products"] == 0, "артикулы пересозданы вместо upsert"
    assert second["product_pairs"] == 0, "пары пересозданы вместо upsert"

    skus = [str(row["sku"]) for row in DEMO_SLICE_ROWS + DEMO_STAGE_SLICE_ROWS]
    assert await _count(demo_db, ProductionPlan) == 2
    # Позиция на группу строк, а не на строку (ADR-0003): распил — одна позиция.
    assert await _count(demo_db, PlanPosition) == len(
        _fold_rows(DEMO_SLICE_ROWS)
    ) + len(_fold_rows(DEMO_STAGE_SLICE_ROWS))
    assert await _count(demo_db, DailyPlan) == first["daily_plans"]
    assert await _count(demo_db, Product, Product.sku.in_(skus)) == len(set(skus))


# ─── 6. Запрет запуска в прод-окружении ──────────────────────────────────────


@pytest.mark.parametrize("env_value", ["prod", "production", "PROD", " prod "])
@pytest.mark.asyncio
async def test_demo_seed_refuses_to_run_in_prod_env(demo_db: AsyncSession, monkeypatch, env_value: str) -> None:
    """Сид сносит планы, задания и проводки: на проде он обязан отказать, а ENV
    приходит из переменной окружения и пишется с любым регистром."""
    monkeypatch.setattr(settings, "ENV", env_value)
    with pytest.raises(RuntimeError, match="Демо-сид упаковочного плана запрещён"):
        await seed_packing_plan_demo(
            demo_db,
            reset=True,
            run_route=True,
            rows=DEMO_SLICE_ROWS,
            prep_stage_rows=DEMO_STAGE_SLICE_ROWS,
        )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_slice_prod_guard_fires_before_any_write(
    demo_seed: dict, demo_db: AsyncSession, monkeypatch
) -> None:
    """Проверка окружения — до сноса: под продом засеянный срез должен остаться
    нетронутым (числа строк до и после совпадают)."""
    _ = demo_seed
    models = (ProductionPlan, PlanPosition, WorkTask, DailyPlan, DailyPlanItem, Product)
    before = [await _count(demo_db, model) for model in models]

    monkeypatch.setattr(settings, "ENV", "production")
    with pytest.raises(RuntimeError, match="Демо-сид упаковочного плана запрещён"):
        await seed_packing_plan_demo(
            demo_db,
            reset=True,
            run_route=True,
            rows=DEMO_SLICE_ROWS,
            prep_stage_rows=DEMO_STAGE_SLICE_ROWS,
        )

    after = [await _count(demo_db, model) for model in models]
    assert after == before, "прод-защита сработала не на входе: демо-данные уже тронуты"
    assert before[3] > 0, "у среза не оказалось дневных планов"



