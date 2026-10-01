"""Контракт демо-сидера «Участков» (`packing_plan_demo_seeder`).

Форма датасета (91 строка: 55 базовых + 30 подготовки + 6 пар анодирования)
защищается без БД — по фикстуре и хелперам: у каждого участка подготовки 8–10
строк, есть обе операции пресса, внутри каждой группы есть повторяющиеся
артикулы, базовые артикулы уникальны, пары анодирования собраны под слияние
(один артикул, цвет и размер, разные вид выпуска и упаковочная операция),
заголовки листа известны шаблону импорта, раскрой не длиннее входа, дневные
планы раскладываются без пустых карточек.

Доменный путь (импорт → approve → release → маршрут → задачи → дневные планы)
гоняется один раз на срез ``DEMO_SLICE_ROWS`` (8 строк), а не на весь датасет:
срез закрывает сверловку, пресс (гребёнка), дробеструй, базовую упаковочную
группу, повтор артикула и пару анодирования. Полный прогон 91 строки в тестах
не нужен.

Прогон: ``pwsh -NoProfile -File scripts/test-run.ps1 --full tests/test_packing_plan_demo_seeder.py``.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import pytest
import pytest_asyncio
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
    DEMO_ROUTE_PROFILE_CODE,
    DEMO_RUN_SECTION_CODES,
    DEMO_SECTION_CODES,
    PACKING_PLAN_ROWS,
    PREP_PLAN_ROWS,
    _daily_plan_specs,
    _plan_workbook,
    _progress_mode,
    _target_section_for,
    seed_packing_plan_demo,
)
from app.services.daily_plan_service import TERMINAL_TASK_STATUSES
from app.services.excel_import import parse_factory_plan_workbook
from app.services.route_builder import _resolve_operations
from app.services.shopfloor.queries_sections import get_section_board
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
#: Всего позиций демо-плана.
TOTAL_ROW_COUNT = PLAN_ROW_COUNT + PREP_ROW_COUNT + ANOD_PAIR_COUNT
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
#: Канонический вид выпуска; правила подбора маршрута ищут его регистронезависимо
#: (``_condition_match`` → ``case_sensitive=False``, route_selection.py:619).
OUTPUT_KINDS = ("ГП", "П/ф")


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


def _expected_tasks_by_section(rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    """Сколько позиций реально проходит через каждый участок — по маршруту.

    Правила подбора дают сверловку строкам с «сверло», пресс — строкам с
    «окно»/«гребенка» (операции взаимно исключают участки), анодирование и
    дробеструй есть в маршруте у каждой строки, а пилу и упаковку снимает
    спанбонд («П/ф»).
    """
    def operation(row: Mapping[str, object]) -> str:
        return str(row["operation"]).strip().lower()

    return {
        "DRILLING": sum("сверл" in operation(row) for row in rows),
        "PRESSING": sum(
            ("окн" in operation(row) or "греб" in operation(row)) and "сверл" not in operation(row)
            for row in rows
        ),
        "SHOT_BLAST": len(rows),
        "ANODIZING": len(rows),
        "SAWING": sum(str(row["kind"]).upper() == "ГП" for row in rows),
        "PACKING": sum(str(row["kind"]).upper() == "ГП" for row in rows),
    }


# ─── 0. Срез фикстуры и доменный прогон ─────────────────────────────────────

#: Срез фикстуры для доменного прогона: восемь строк, покрывающих все виды
#: строк — сверловку, пресс (гребёнка), дробеструй, базовую упаковочную группу
#: (пила), повтор артикула и пару анодирования. Полный датасет (91 строка) в
#: тестах не гоняется: форму датасета защищают DB-free проверки, а доменный
#: путь — импорт → approve → release → маршрут → задачи → дневные планы — срез.
#: Порядок строк внутри блока подготовки — контракт: тройка «сверловка → пресс →
#: дробеструй» расходится по участкам круговым разбором, а повторный артикул
#: встаёт четвёртым и снова попадает на сверловку — отдельным заданием.
#: У пар анодирования порядок задаёт режим прогресса: первая строка среза (чужой
#: артикул) забирает бакет «закрыто», поэтому обе строки пары ЮП-2256 остаются
#: незакрытыми и попадают в дневной план анодирования.
DEMO_SLICE_ROWS: tuple[dict[str, object], ...] = (
    PREP_PLAN_ROWS[0],  # ALS1288, «сверло» → DRILLING
    PREP_PLAN_ROWS[4],  # АТ-6324, «гребенка» → PRESSING / PRESS_COMB
    PREP_PLAN_ROWS[2],  # ALS1290, пустая операция → SHOT_BLAST
    PREP_PLAN_ROWS[3],  # повторный ALS1288 → отдельное задание DRILLING
    PACKING_PLAN_ROWS[1],  # базовая упаковочная группа (ГП) → SAWING
    ANOD_PAIR_ROWS[2],  # ЮП-2974 «П/ф» → ANODIZING, бакет «закрыто»
    ANOD_PAIR_ROWS[0],  # ЮП-2256 спанбонд → ANODIZING, бакет «в работе»
    ANOD_PAIR_ROWS[1],  # ЮП-2256 стрейч → ANODIZING, бакет «выдано»
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
            db, reset=True, run_route=True, rows=DEMO_SLICE_ROWS
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


def test_fixture_blocks_use_real_skus_and_do_not_overlap() -> None:
    """Артикулы блоков — реальные каталожные (``ЮП-…``/``АТ-…``/``ALS…`` с живым
    именем товара), а не выдуманные коды: демо показывает заводской номенклатур
    и не плодит фейковые карточки товара. Блоки не пересекаются ни между собой,
    ни с базовыми 55 строками, иначе позиция уехала бы на чужой участок.
    """
    packing_skus = {str(row["sku"]) for row in PACKING_PLAN_ROWS}
    prep_skus = {str(row["sku"]) for row in PREP_PLAN_ROWS}
    anod_skus = {str(row["sku"]) for row in ANOD_PAIR_ROWS}
    assert not packing_skus & prep_skus, f"базовый и подготовительный блоки делят {sorted(packing_skus & prep_skus)}"
    assert not packing_skus & anod_skus, f"базовый блок и пары делят {sorted(packing_skus & anod_skus)}"
    assert not prep_skus & anod_skus, f"подготовка и пары делят {sorted(prep_skus & anod_skus)}"
    assert len(DEMO_PLAN_ROWS) == TOTAL_ROW_COUNT

    for block in (PREP_PLAN_ROWS, ANOD_PAIR_ROWS):
        for row in block:
            sku = str(row["sku"])
            assert re.match(r"^(ЮП|АТ|ALS)-?\d", sku), f"{sku}: не каталожный формат артикула"
            assert len(str(row["name"])) >= 5, f"{sku}: пустое имя товара"
    invented = sorted(
        str(row["sku"]) for row in (PREP_PLAN_ROWS + ANOD_PAIR_ROWS) if re.fullmatch(r"ЮП-6[123]\d\d", str(row["sku"]))
    )
    assert not invented, f"остались выдуманные артикулы: {invented}"


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


def test_prep_fixture_cuts_into_selling_lengths() -> None:
    """Раскрой идёт в готовые длины каталога, выход не длиннее входа и не теряет
    штук: иначе выдача следующей стадии считалась бы по несуществующему размеру."""
    for row in PREP_PLAN_ROWS + ANOD_PAIR_ROWS:
        output, source = float(row["output_length_m"]), float(row["input_length_m"])
        assert output <= source, f"{row['sku']}: выход {output} длиннее входа {source}"
        if output < source:
            assert output in FINISHED_LENGTHS, f"{row['sku']}: {output} вне готовых длин"
            assert float(row["output_quantity"]) >= float(row["input_quantity"]), (
                f"{row['sku']}: раскрой уменьшил количество"
            )


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
    сдвиг колонки в шаблоне тихо меняет раскрой позиции."""
    parsed = parse_factory_plan_workbook(
        _plan_workbook(DEMO_PLAN_ROWS),
        "demo-packing-plan.xlsx",
        0,
        column_mapping=IMPORT_TEMPLATES[0]["column_mapping"],
    )
    assert [row.source_sku for row in parsed.parsed_rows] == [
        str(source["sku"]) for source in DEMO_PLAN_ROWS
    ], "порядок строк фикстуры доехал до парсера с потерями или перестановкой"

    problems = [
        (row.source_sku, row.errors, row.warnings)
        for row in parsed.parsed_rows
        if row.errors or row.warnings
    ]
    assert not problems, f"парсер пожаловался на строки фикстуры: {problems[:5]}"

    for row, source in zip(parsed.parsed_rows, DEMO_PLAN_ROWS, strict=True):
        assert row.payload["color"] == source["color"]
        assert row.payload["operation"] == (source["operation"] or None)
        assert row.payload["packaging"] == source["packing"]
        assert row.payload["output_kind"] == source["kind"]
        assert Decimal(str(row.quantity)) == Decimal(str(source["output_quantity"]))
        assert Decimal(str(row.input_quantity)) == Decimal(str(source["input_quantity"]))
        assert row.input_dimensions == {"length_mm": round(float(source["input_length_m"]) * 1000)}
        assert row.outputs[0]["dimensions"] == {
            "length_mm": round(float(source["output_length_m"]) * 1000)
        }
        assert Decimal(str(row.outputs[0]["quantity"])) == Decimal(str(source["output_quantity"]))


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
    """Строки среза по группам прогона: базовые (пила/упаковка/анодирование),
    подготовки (сверловка/пресс/дробеструй) и пары анодирования. Порядок внутри
    группы — тот же, что у сида: позиции импортируются в порядке строк листа.
    """
    groups = {
        "run": [row for row in DEMO_SLICE_ROWS if row in PACKING_PLAN_ROWS],
        "prep": [row for row in DEMO_SLICE_ROWS if row in PREP_PLAN_ROWS],
        "anod": [row for row in DEMO_SLICE_ROWS if row in ANOD_PAIR_ROWS],
    }
    total = sum(len(rows) for rows in groups.values())
    assert total == len(DEMO_SLICE_ROWS), "строка среза вне блоков фикстуры"
    return groups


#: Участки кругового разбора каждой группы прогона.
_SLICE_GROUP_CODES = {
    "run": DEMO_RUN_SECTION_CODES,
    "prep": DEMO_PREP_SECTION_CODES,
    "anod": DEMO_ANOD_SECTION_CODES,
}


@pytest.mark.slow
@pytest.mark.asyncio
async def test_slice_seed_walks_the_domain_path(demo_seed: dict, demo_db: AsyncSession) -> None:
    """Срез проходит доменный путь целиком: released-позиции с раскроем фикстуры
    и задания на участках, которые реально есть в их маршрутах."""
    stats = demo_seed
    assert stats["positions"] == len(DEMO_SLICE_ROWS)

    progress = stats["route_progress"]
    assert progress["skipped"] == []
    assert progress["stages"] == len(DEMO_SLICE_ROWS)
    assert progress["completed"] + progress["partial"] + progress["issued"] == len(DEMO_SLICE_ROWS)

    plans = list((await demo_db.scalars(select(ProductionPlan))).all())
    assert len(plans) == 1
    assert stats["production_plan_id"] == plans[0].id

    positions = await _positions(demo_db, plans[0].id)
    assert [position.source_sku for position in positions] == [
        str(row["sku"]) for row in DEMO_SLICE_ROWS
    ]
    assert {position.status for position in positions} == {PlanPositionStatus.released}
    assert [position.quantity for position in positions] == [
        Decimal(str(row["output_quantity"])) for row in DEMO_SLICE_ROWS
    ]
    assert [position.input_quantity for position in positions] == [
        Decimal(str(row["input_quantity"])) for row in DEMO_SLICE_ROWS
    ]
    assert [position.input_dimensions for position in positions] == [
        {"length_mm": round(float(row["input_length_m"]) * 1000)} for row in DEMO_SLICE_ROWS
    ]
    assert [position.outputs[0]["dimensions"] for position in positions] == [
        {"length_mm": round(float(row["output_length_m"]) * 1000)} for row in DEMO_SLICE_ROWS
    ]

    # Участок получает столько заданий, сколько строк среза реально проходит
    # через него: сверловка — «сверло», пресс — окно/гребёнка, анодирование и
    # дробеструй есть у всех, а пилу и упаковку снимает спанбонд («П/ф»).
    sections = await _demo_sections(demo_db)
    expected_by_section = _expected_tasks_by_section(DEMO_SLICE_ROWS)
    for code, section in sections.items():
        assert stats["tasks_by_section"][code]["total"] == expected_by_section[code], (
            f"участок {code}: заданий {stats['tasks_by_section'][code]['total']}, "
            f"а через срез проходит {expected_by_section[code]}"
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
    # участок круга группы, который есть в маршруте позиции.
    slice_groups = _slice_rows_by_group()
    positions_by_group: dict[str, list[PlanPosition]] = {name: [] for name in slice_groups}
    for row, position in zip(DEMO_SLICE_ROWS, positions, strict=True):
        for name, rows in slice_groups.items():
            if row in rows:
                positions_by_group[name].append(position)
                break
    expected_share = {"done": 1.0, "partial": 0.6, "issued": 0.0}
    for name, rows in slice_groups.items():
        group_positions = positions_by_group[name]
        assert len(group_positions) == len(rows), f"группа {name}: позиций {len(group_positions)}"
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


@pytest.mark.slow
@pytest.mark.asyncio
async def test_slice_sections_carry_their_own_operations(demo_db: AsyncSession, demo_seed: dict) -> None:
    """Участки среза показывают свои операции: сверловка — DRILL, пресс —
    PRESS_COMB (в срезе строка с гребёнкой), дробеструй — SHOT; повторный
    артикул встаёт на сверловке двумя отдельными заданиями.
    """
    sections = await _demo_sections(demo_db)
    plans = list((await demo_db.scalars(select(ProductionPlan))).all())
    positions = await _positions(demo_db, plans[0].id)

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

    # Анодирование — общая стадия всех строк: цвет берётся из строки, а не из
    # первой операции группы (тот дефект красил весь цех в одну «Серебро»).
    expected_color_ops = await _expected_color_ops(demo_db)
    for row, position in zip(DEMO_SLICE_ROWS, positions, strict=True):
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
    plans = list((await demo_db.scalars(select(ProductionPlan))).all())
    positions = await _positions(demo_db, plans[0].id)
    counts = Counter(
        str(row["sku"]) for row in ANOD_PAIR_ROWS if row in DEMO_SLICE_ROWS
    )
    full_pairs = [sku for sku, count in counts.items() if count == 2]
    assert len(full_pairs) == 1, f"в срезе не одна целая пара: {dict(counts)}"
    pair_sku = full_pairs[0]

    pair_positions = [position for position in positions if position.source_sku == pair_sku]
    assert len(pair_positions) == 2, "пара анодирования потеряла строку"

    async def anod_codes(position: PlanPosition) -> list[str]:
        return list(
            (
                await demo_db.scalars(
                    select(RouteOperation.operation_code)
                    .join(RouteStage, RouteStage.id == RouteOperation.route_stage_id)
                    .join(SectionPlanLine, SectionPlanLine.route_stage_id == RouteStage.id)
                    .where(
                        SectionPlanLine.plan_position_id == position.id,
                        SectionPlanLine.section_id == sections["ANODIZING"].id,
                    )
                    .order_by(RouteOperation.sequence)
                )
            ).all()
        )

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

    codes_by_position = {position.id: await anod_codes(position) for position in pair_positions}
    color_ops = {codes[0] for codes in codes_by_position.values()}
    pack_ops = {codes[1] for codes in codes_by_position.values()}
    assert len(color_ops) == 1 and color_ops != {""}, f"цветовая операция пары: {color_ops}"
    assert pack_ops == {"PACK_SPUNBOND", "PACK_STRETCH"}, f"упаковки пары: {pack_ops}"

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

    # Второй прогон того же среза: тот же набор, без второго датасета.
    second = await seed_packing_plan_demo(
        demo_db, reset=True, run_route=True, rows=DEMO_SLICE_ROWS
    )
    assert second["positions"] == first["positions"]
    assert second["tasks_by_section"] == first["tasks_by_section"]
    assert second["daily_plans"] == first["daily_plans"]
    assert second["route_progress"] == first["route_progress"]
    assert second["cleared_daily_plans"] == first["daily_plans"], "прежние карточки не снесены"
    assert second["products"] == 0, "артикулы пересозданы вместо upsert"

    skus = [str(row["sku"]) for row in DEMO_SLICE_ROWS]
    assert await _count(demo_db, ProductionPlan) == 1
    assert await _count(demo_db, PlanPosition) == len(DEMO_SLICE_ROWS)
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
        await seed_packing_plan_demo(demo_db, reset=True, run_route=True, rows=DEMO_SLICE_ROWS)


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
        await seed_packing_plan_demo(demo_db, reset=True, run_route=True, rows=DEMO_SLICE_ROWS)

    after = [await _count(demo_db, model) for model in models]
    assert after == before, "прод-защита сработала не на входе: демо-данные уже тронуты"
    assert before[3] > 0, "у среза не оказалось дневных планов"



