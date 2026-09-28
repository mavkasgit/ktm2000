"""Контракт демо-сидера «Участков» (`packing_plan_demo_seeder`).

Сид собирает доску участков из реального ``Упаковочный план.xlsx``: фикстура строк →
xlsx-шаблон импорта → план → релиз → задания на трёх участках → дневные планы.
Тесты защищают то, что видит потребитель: 55 позиций плана с уникальным артикулом,
раскладку демо-прогресса, двенадцать дневных планов на участок, живую очередь на
всех трёх участках и то, что повторный прогон не оставляет второго набора данных.

Прогон: ``pwsh -NoProfile -File scripts/test-run.ps1 --full tests/test_packing_plan_demo_seeder.py``.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

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
    DEMO_ROUTE_PROFILE_CODE,
    DEMO_SECTION_CODES,
    PACKING_PLAN_ROWS,
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

PLAN_ROW_COUNT = 55
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
    book = load_workbook(BytesIO(_plan_workbook(PACKING_PLAN_ROWS)))
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
    for color in {str(row["color"]) for row in PACKING_PLAN_ROWS}:
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


async def _demo_product_lengths(session) -> dict[str, float]:
    """Нормативная длина (primary) каждого артикула фикстуры в мм."""
    skus = [str(row["sku"]) for row in PACKING_PLAN_ROWS]
    lengths = (
        await session.execute(
            select(Product.sku, ProductLength.length_mm)
            .join(ProductLength, ProductLength.product_id == Product.id)
            .where(Product.sku.in_(skus), ProductLength.is_primary.is_(True))
        )
    ).all()
    return {sku: float(length) for sku, length in lengths}


# ─── 1. Фикстура листа ──────────────────────────────────────────────────────


def test_fixture_has_exactly_one_row_per_sku() -> None:
    """55 строк с уникальным артикулом: в производственном плане повтор артикула
    недопустим — импорт склеит такие строки, и позиция потеряет раскрой."""
    skus = [str(row["sku"]) for row in PACKING_PLAN_ROWS]
    assert len(PACKING_PLAN_ROWS) == PLAN_ROW_COUNT
    duplicates = sorted({sku for sku in skus if skus.count(sku) > 1})
    assert not duplicates, f"артикул повторяется в плане: {duplicates}"


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
    broken = [(idx, row[field]) for idx, row in enumerate(PACKING_PLAN_ROWS) if not check(row[field])]
    assert not broken, f"поле {field!r} непригодно в {len(broken)} строках(ах): {broken[:5]}"


def test_fixture_declares_a_known_output_kind() -> None:
    """Вид выпуска выбирает маршрут (спанбонд против готовой продукции); значение
    вне двух доменных — позиция молча уходит в маршрут без упаковки."""
    unknown = sorted(
        {
            str(row["kind"])
            for row in PACKING_PLAN_ROWS
            if str(row["kind"]).strip().lower() not in {kind.lower() for kind in OUTPUT_KINDS}
        }
    )
    assert not unknown, f"вид выпуска вне {OUTPUT_KINDS}: {unknown}"


def test_fixture_cutting_rows_keep_output_not_longer_than_input() -> None:
    """Раскрой режет заготовку: выход длиннее входа — ошибка данных, из-за которой
    бюджет передачи считается по несуществующему размеру."""
    impossible = [
        (row["sku"], row["input_length_m"], row["output_length_m"])
        for row in PACKING_PLAN_ROWS
        if float(row["output_length_m"]) > float(row["input_length_m"])
    ]
    assert not impossible, f"выход длиннее входа: {impossible}"


def test_fixture_cutting_rows_do_not_shrink_piece_count() -> None:
    """Раскрой 2,7 → 0,9 даёт больше кусков, а не меньше: просадка количества на
    режущей позиции обрушила бы выдачу следующей стадии."""
    shrunk = [
        (row["sku"], row["input_quantity"], row["output_quantity"])
        for row in PACKING_PLAN_ROWS
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
    assert len(data) == PLAN_ROW_COUNT


def test_plan_workbook_parses_back_into_the_fixture_rows() -> None:
    """Тот же парсер, что и в UI, читает собранный сидером лист в те же позиции:
    сдвиг колонки в шаблоне тихо меняет раскрой позиции."""
    parsed = parse_factory_plan_workbook(
        _plan_workbook(PACKING_PLAN_ROWS),
        "demo-packing-plan.xlsx",
        0,
        column_mapping=IMPORT_TEMPLATES[0]["column_mapping"],
    )
    assert [row.source_sku for row in parsed.parsed_rows] == [
        str(source["sku"]) for source in PACKING_PLAN_ROWS
    ], "порядок строк фикстуры доехал до парсера с потерями или перестановкой"

    problems = [
        (row.source_sku, row.errors, row.warnings)
        for row in parsed.parsed_rows
        if row.errors or row.warnings
    ]
    assert not problems, f"парсер пожаловался на строки фикстуры: {problems[:5]}"

    for row, source in zip(parsed.parsed_rows, PACKING_PLAN_ROWS, strict=True):
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


# ─── 5. Интеграционный прогон сидера ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_demo_seed_releases_all_plan_positions(session) -> None:
    """Импорт+релиз дают 55 released-позиций с раскроем фикстуры и задание на
    каждом из трёх демо-участков."""
    await run_full_seed(session, force=True)
    stats = await seed_packing_plan_demo(session, reset=True, run_route=False)

    plans = list((await session.scalars(select(ProductionPlan))).all())
    assert len(plans) == 1
    assert stats["production_plan_id"] == plans[0].id

    positions = await _positions(session, plans[0].id)
    assert len(positions) == PLAN_ROW_COUNT
    assert {position.status for position in positions} == {PlanPositionStatus.released}
    assert [position.source_sku for position in positions] == [
        str(row["sku"]) for row in PACKING_PLAN_ROWS
    ]
    assert [position.quantity for position in positions] == [
        Decimal(str(row["output_quantity"])) for row in PACKING_PLAN_ROWS
    ]
    assert [position.input_quantity for position in positions] == [
        Decimal(str(row["input_quantity"])) for row in PACKING_PLAN_ROWS
    ]
    assert [position.input_dimensions for position in positions] == [
        {"length_mm": round(float(row["input_length_m"]) * 1000)} for row in PACKING_PLAN_ROWS
    ]
    assert [position.outputs[0]["dimensions"] for position in positions] == [
        {"length_mm": round(float(row["output_length_m"]) * 1000)} for row in PACKING_PLAN_ROWS
    ]

    # Участок получает столько заданий, сколько позиций реально проходит через
    # него по своему маршруту: спанбонд («П/ф») не заходит на пилу и упаковку,
    # (конкретные числа — в вычисляемом ожидании ниже, а не в тексте).
    sections = await _demo_sections(session)
    skipped_by_route = sum(
        1 for row in PACKING_PLAN_ROWS if str(row["kind"]).upper() != "ГП"
    )
    for code, section in sections.items():
        expected = (
            PLAN_ROW_COUNT - skipped_by_route
            if code in ("SAWING", "PACKING")
            else PLAN_ROW_COUNT
        )
        assert stats["tasks_by_section"][code]["total"] == expected, (
            f"участок {code}: заданий {stats['tasks_by_section'][code]['total']}, "
            f"а через него проходит {expected} позиций"
        )
        assert await _count(
            session, WorkTask, WorkTask.section_id == section.id
        ) == expected, f"на участке {code} не все позиции получили задание"

    # Нормативная длина артикула — входная: по ней считается геометрия выдачи.
    assert await _demo_product_lengths(session) == {
        str(row["sku"]): round(float(row["input_length_m"]) * 1000) for row in PACKING_PLAN_ROWS
    }

@pytest.mark.asyncio
async def test_demo_board_carries_each_position_own_operations(session) -> None:
    """Демо-доска показывает операции позиции, а не заглушку шаблонного маршрута.

    Без профиля правил импорт кладёт все позиции на шаблонный маршрут, где у этапа
    анодирования одна операция без кода: в колонке «Операция» весь цех выглядит
    одинаковым, а «Упаковка» пустая.
    """
    await run_full_seed(session, force=True)
    await seed_packing_plan_demo(session, reset=True, run_route=False)

    sections = await _demo_sections(session)
    plans = list((await session.scalars(select(ProductionPlan))).all())
    positions = await _positions(session, plans[0].id)

    codes_by_sku: dict[str, list[str]] = {}
    for position in positions:
        ops = list(
            (
                await session.scalars(
                    select(RouteOperation)
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
        codes_by_sku[position.source_sku] = [op.operation_code for op in ops]

    # У каждой позиции две операции участка: цвет анодирования и упаковка.
    assert all(len(codes) == 2 for codes in codes_by_sku.values()), (
        f"этап анодирования без двух операций: {codes_by_sku}"
    )
    assert all(code for codes in codes_by_sku.values() for code in codes), (
        f"в этапе анодирования остались операции без кода: {codes_by_sku}"
    )

    # Позиция получает операцию своего цвета, а не первую в группе: при
    # неверном group_code правила резолв терялся и всем 55 позициям доставалась
    # одна и та же «Серебро» — префикс «ANOD_» такой дефект не поймал бы.
    expected_color_ops = await _expected_color_ops(session)
    for row, position in zip(PACKING_PLAN_ROWS, positions, strict=True):
        color_op, pack_op = codes_by_sku[position.source_sku]
        assert color_op == expected_color_ops[str(row["color"])], (
            f"цвет {row['color']} → {color_op}, а операция группы {expected_color_ops[str(row['color'])]}"
        )
        expected_pack = "PACK_STRETCH" if str(row["kind"]).upper() == "ГП" else "PACK_SPUNBOND"
        assert pack_op == expected_pack, f"{row['kind']} → {pack_op}"

    # Разные цвета демо обязаны давать разные операции, иначе проверка выше
    # прошла бы на одной сплошной «Серебро».
    assert len(set(expected_color_ops.values())) > 1, (
        f"в фикстуре один цвет на все позиции: {expected_color_ops}"
    )


    # То же самое с другой стороны — глазами доски: она отдаёт оба кода
    # операции этапа, из них и собираются колонки «Операция» и «Упаковка».
    board = await get_section_board(session, section_id=sections["ANODIZING"].id, limit=500)
    codes_by_task = {row["id"]: row["operation_codes"] for row in board["tasks"]}

    pairs = set()
    for position in positions:
        task = await _target_task(session, position.id, sections["ANODIZING"].id)
        codes = codes_by_task.get(task.id) or []
        assert codes == codes_by_sku[position.source_sku], (
            f"доска отдала {codes} вместо {codes_by_sku[position.source_sku]} "
            f"для {position.source_sku}"
        )
        pairs.add(tuple(codes))

    assert len(pairs) > 1, "демо-доска не должна быть одноцветной"



@pytest.mark.asyncio
async def test_demo_seed_fills_daily_plans_on_every_demo_section(session) -> None:
    """Каждый участок открывает 12 карточек на 9 дней; задания не терминальные и
    не попадают в два плана сразу."""
    await run_full_seed(session, force=True)
    stats = await seed_packing_plan_demo(session, reset=True, run_route=False)

    sections = await _demo_sections(session)
    plans = list((await session.scalars(select(DailyPlan))).all())
    assert len(plans) == stats["daily_plans"] == 36
    assert {plan.section_id for plan in plans} == {section.id for section in sections.values()}

    today = date.today()
    history_window = {today - timedelta(days=offset) for offset in range(8, -1, -1)}
    for code, section in sections.items():
        section_plans = [plan for plan in plans if plan.section_id == section.id]
        assert len(section_plans) == 12, f"участок {code}: {len(section_plans)} карточек"
        assert {plan.plan_date for plan in section_plans} == history_window
        for plan in section_plans:
            items = (
                await session.scalars(
                    select(DailyPlanItem.work_task_id).where(
                        DailyPlanItem.daily_plan_id == plan.id
                    )
                )
            ).all()
            assert items, f"карточка {plan.plan_date} участка {code} осталась без заданий"
            statuses = set(
                (
                    await session.scalars(
                        select(WorkTask.status).where(WorkTask.id.in_(items))
                    )
                ).all()
            )
            assert not statuses & TERMINAL_TASK_STATUSES, (
                f"в план попало закрытое задание: {sorted(status.value for status in statuses & TERMINAL_TASK_STATUSES)}"
            )

    items = await _count(session, DailyPlanItem)
    distinct = await session.scalar(
        select(func.count(func.distinct(DailyPlanItem.work_task_id)))
    )
    # Задание на участок одно, сколько бы участков позиция ни проходила:
    # всего их столько, сколько позиций прошло через свой маршрут.
    expected_tasks = sum(entry["total"] for entry in stats["tasks_by_section"].values())
    assert items == distinct == expected_tasks, (
        "каждое задание должно стоять ровно в одной карточке"
    )


@pytest.mark.asyncio
async def test_route_run_leaves_a_live_queue_on_all_three_sections(session) -> None:
    """Прогон по маршруту: ни одной позиции не пропущено, на каждом участке есть и
    активные задания, и очередь «в ожидании» — демо показывает работу цеха."""
    await run_full_seed(session, force=True)
    stats = await seed_packing_plan_demo(session, reset=True, run_route=True)

    progress = stats["route_progress"]
    assert progress["skipped"] == []
    assert progress["stages"] == PLAN_ROW_COUNT
    assert progress["completed"] + progress["partial"] + progress["issued"] == PLAN_ROW_COUNT

    sections = await _demo_sections(session)
    positions = await _positions(session, stats["production_plan_id"])
    with_waiting = 0
    for code, section in sections.items():
        statuses = set(
            (
                await session.scalars(
                    select(WorkTask.status).where(WorkTask.section_id == section.id)
                )
            ).all()
        )
        assert statuses & ACTIVE_STATUSES, (
            f"доска участка {code} без активных заданий: {sorted(s.value for s in statuses)}"
        )
        if WorkTaskStatus.waiting_previous in statuses:
            with_waiting += 1
    assert with_waiting >= 2, (
        "очередь предыдущей стадии должна копиться минимум на двух участках из трёх"
    )

    # Глубина прогона по позициям: старые закрыты, следующие выполнены на 60 %,
    # хвост выдан и не начат. Участок остановки — тот же, что выбрал сид: он
    # берёт первый участок круга, который реально есть в маршруте позиции.
    target_ids = [sections[code].id for code in DEMO_SECTION_CODES]
    shares = []
    for index in (3, 17, 40):
        route_ids = set(await _position_section_ids(session, positions[index].id))
        target = _target_section_for(index, target_ids, route_ids)
        assert target is not None, f"позиция {index} не заходит ни на один демо-участок"
        code = DEMO_SECTION_CODES[target_ids.index(target)]
        task = await _target_task(session, positions[index].id, target)
        cache = await StockProjectionManager().get_task_cache(session, task.id)
        issued = Decimal(str(cache["issued_quantity"]))
        assert issued > 0, f"задание участка {code} позиции {index} не выдано"
        shares.append(float(Decimal(str(cache["completed_quantity"])) / issued))
    assert shares[0] == pytest.approx(1.0, abs=0.01)
    assert shares[1] == pytest.approx(0.6, abs=0.01)
    assert shares[2] == pytest.approx(0.0, abs=0.01)


@pytest.mark.asyncio
async def test_rerun_with_reset_replaces_previous_demo(session) -> None:
    """Повторный прогон с reset пересобирает демо, а не наслаивает второй набор:
    прежние дневные планы сносятся, артикулы не дублируются."""
    await run_full_seed(session, force=True)
    first = await seed_packing_plan_demo(session, reset=True, run_route=True)
    second = await seed_packing_plan_demo(session, reset=True, run_route=True)

    assert second["positions"] == first["positions"] == PLAN_ROW_COUNT
    assert second["tasks_by_section"] == first["tasks_by_section"]
    assert second["daily_plans"] == first["daily_plans"] == 36
    assert second["route_progress"] == first["route_progress"]
    assert second["cleared_daily_plans"] == 36, "прежние карточки не снесены — будет конфликт UNIQUE"
    assert second["products"] == 0, "артикулы пересозданы вместо upsert"

    sections = await _demo_sections(session)
    skus = [str(row["sku"]) for row in PACKING_PLAN_ROWS]
    assert await _count(session, ProductionPlan) == 1
    assert await _count(session, PlanPosition) == PLAN_ROW_COUNT
    assert await _count(session, DailyPlan) == 36
    # В карточки попадают только незакрытые задания, поэтому состав планов
    # определяется прогоренной глубиной, а не числом позиций.
    planned_tasks = sum(entry["open"] for entry in second["tasks_by_section"].values())
    assert await _count(session, DailyPlanItem) == planned_tasks
    assert await _count(session, Product, Product.sku.in_(skus)) == PLAN_ROW_COUNT
    for code, section in sections.items():
        assert await _count(
            session, WorkTask, WorkTask.section_id == section.id
        ) == second["tasks_by_section"][code]["total"], f"участок {code} получил второй набор заданий"
        assert await _count(
            session, DailyPlan, DailyPlan.section_id == section.id
        ) == 12, f"участок {code} получил второй набор карточек"


# ─── 6. Запрет запуска в прод-окружении ──────────────────────────────────────


@pytest.mark.parametrize("env_value", ["prod", "production", "PROD", " prod "])
@pytest.mark.asyncio
async def test_demo_seed_refuses_to_run_in_prod_env(session, monkeypatch, env_value: str) -> None:
    """Сид сносит планы, задания и проводки: на проде он обязан отказать, а ENV
    приходит из переменной окружения и пишется с любым регистром."""
    monkeypatch.setattr(settings, "ENV", env_value)
    with pytest.raises(RuntimeError, match="Демо-сид упаковочного плана запрещён"):
        await seed_packing_plan_demo(session, reset=True, run_route=True)


@pytest.mark.asyncio
async def test_prod_guard_fires_before_any_write(session, monkeypatch) -> None:
    """Проверка окружения — до сноса: под продом демо-набор должен остаться нетронутым."""
    await run_full_seed(session, force=True)
    await seed_packing_plan_demo(session, reset=True, run_route=False)
    sections = await _demo_sections(session)
    models = (ProductionPlan, PlanPosition, WorkTask, DailyPlan, DailyPlanItem, Product)
    before = [await _count(session, model) for model in models]
    before_work_tasks = {
        code: await _count(session, WorkTask, WorkTask.section_id == section.id)
        for code, section in sections.items()
    }

    monkeypatch.setattr(settings, "ENV", "production")
    with pytest.raises(RuntimeError):
        await seed_packing_plan_demo(session, reset=True, run_route=True)

    after = [await _count(session, model) for model in models]
    assert after == before, "прод-защита сработала не на входе: демо-данные уже тронуты"
    assert before[3] == 36
    for code, section in sections.items():
        assert await _count(
            session, WorkTask, WorkTask.section_id == section.id
        ) == before_work_tasks[code], f"участок {code} потерял задания до срабатывания защиты"
        assert await _count(
            session, DailyPlan, DailyPlan.section_id == section.id
        ) == 12, f"участок {code} потерял карточки до срабатывания защиты"
