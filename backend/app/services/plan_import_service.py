from __future__ import annotations

import math
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.imports import ImportBatch, ImportBatchMode, ImportFile
from app.models.product import Product, ProductLength, _length_key
from app.services import product_pair_resolver
from app.services.product_pair_resolver import PairHangerValue, ResolvedPair
from app.models.production_plan import (
    PlanChangeAction,
    PlanChangeItem,
    PlanChangeItemStatus,
    PlanChangeSet,
    PlanPositionRouteMatchQuality,
    PlanPositionRouteMatchReason,
    PlanPositionRouteOrigin,
    PlanPosition,
    PlanPositionStatus,
    ProductionPlan,
)
from app.models.route import ProductionRoute, RouteStage, RouteOperation, RouteRuleProfile
from app.models.section import Section
from app.services.excel_import import (
    ParsedWorkbook,
    ParsedPlanRow,
    detect_workbook_format,
    parse_factory_plan_workbook,
    sha256_bytes,
    validate_excel_extension,
)
from app.services.route_selection import load_route_sections, load_selection_rules_for_profile, load_route_selection_batch_cache, select_route_for_payload
from app.domain.dimensions import LENGTH_MM, DimensionsValidationError, canonicalize_dimensions
from app.services.dimension_validation import MissingDimensionsError, resolve_product_dimensions
from app.services.hanger_quantity import adjust_quantity_to_hanger
from app.services.import_normalization import normalize_sku as _normalize_sku
from app.services.plan_position_hanger import PositionHangerValue, position_length_mm, resolve_position_hanger
from app.services.route_builder import build_route_from_profile, load_route_build_batch_cache


#: Допуск silent-подстановки сырья, мм (#156, поправка к ADR-0024 п.7):
#: разница ГП→сырьё в пределах допуска — штатная логика торцовки,
#: warning raw_length_substituted ставится только при большем расхождении,
#: иначе предпросмотр реального плана тонет в предупреждениях.
RAW_LENGTH_SILENT_TOLERANCE_MM = 100
#: Каталог кодов строк импорта плана (спека docs/plan-import-spec.md §3, карта #157).
#: Статус строки (правило ниже, plan_import_row_status): есть errors → invalid,
#: иначе warnings → warning, иначе pending.
#: Новый код — только с явной классификацией error/warning в этом списке:
#: сторож-тест tests/test_plan_import_codes.py сканирует errors.append /
#: warnings.append в plan_import_service.py и excel_import.py и падает на
#: неклассифицированном коде. При добавлении кода обновить список + тест.
PLAN_IMPORT_ERROR_CODES: frozenset[str] = frozenset(
    {
#: Блокируют (invalid).
        "product_not_found",
        "product_inactive",
        "product_pair_not_found",
        "hanger_calc_zero",
#: Подбор маршрута: no_route_candidate и остальные значения selection.error
#: (route_selection.py: error="no_route_candidate" / "route_rule_conflict").
        "no_route_candidate",
        "route_rule_conflict",
        "active_route_has_no_steps",
        "route_contains_inactive_section",
        "duplicate_sku_due_date",
#: Сырьё: нет зарегистрированной длины ≥ длины ГП (возврат
#: _materialize_raw_length_mm; «и т.п.» спеки — новые raw-коды добавлять сюда).
        "raw_length_not_found",
    }
)
#: Точные warning-коды без параметров.
PLAN_IMPORT_WARNING_CODES: frozenset[str] = frozenset(
    {
        "product_name_missing",
        "input_dimensions_unresolved",
        "paired_profile_product_unmapped",
    }
)
#: Warning-коды с параметрами после «:» (префикс до первого «:»).
PLAN_IMPORT_WARNING_PREFIXES: tuple[str, ...] = (
    "raw_length_substituted",
    "paired_hanger_adjusted",
    "hanger_quantity_not_set",
    "invalid_input_length",
    "invalid_output_length",
    "paired_row_auto_included",
    "row_selection_applied",
    "row_selection_auto_included",
#: Баланс группы вход×длина = Σ(выход×длина) (excel_import._check_group_balances):
#: фактический row-warning вне списка спеки §3, зафиксирован здесь же,
#: чтобы сторож ловил действительно новые коды, а не этот известный.
    "plan_group_balance_mismatch",
)


def _plan_import_code_base(code: str) -> str:
#: База кода без параметров: «invalid_output_length:row=5» → «invalid_output_length».
    return code.split(":", 1)[0]


def classify_plan_import_code(code: str) -> str | None:
#: Классификация кода спеки §3: «error» / «warning» / None (неизвестен).
    base = _plan_import_code_base(code)
    if base in PLAN_IMPORT_ERROR_CODES:
        return "error"
    if base in PLAN_IMPORT_WARNING_CODES or base in PLAN_IMPORT_WARNING_PREFIXES:
        return "warning"
    return None


def plan_import_row_status(errors: list[str], warnings: list[str]) -> PlanChangeItemStatus:
#: Правило статуса строки (спека §3): errors → invalid, иначе warnings → warning,
#: иначе pending. Вынесено рядом с каталогом, чтобы изменение правила
#: ревьюилось вместе с классификацией.
    if errors:
        return PlanChangeItemStatus.invalid
    if warnings:
        return PlanChangeItemStatus.warning
    return PlanChangeItemStatus.pending


def plan_import_item_is_duplicate(item: PlanChangeItem) -> bool:
    """Единый предикат дубля (спека §4.3): действие mark_possible_duplicate
    либо код duplicate_sku_due_date. Держит серверный счётчик `duplicates`
    и чип «Дубли» на фронте на одном определении."""
    if item.change_action == PlanChangeAction.mark_possible_duplicate:
        return True
    return "duplicate_sku_due_date" in (item.errors or ())

def _gp_length_for_raw_materialization(row: ParsedPlanRow) -> float | None:
    """Длина ГП, которую несёт строка, — кандидат на материализацию в сырьё.

    План всегда несёт коммерческую длину ГП (ADR-0024 п.1), и её источник —
    вход позиции: «Длина, м» из Excel; при пустой колонке парсер наследует
    длину единственного выхода (ADR-0003, «вход без резки»). Настоящая резка
    (вход 2,7 м → выход 0,9 м) длину ГП не отменяет: на подвес профиль встаёт
    сырьевой длиной, резка — позже (ADR-0024 п.2), поэтому материализуется
    именно вход. Если вход уже сырьевой, «ближайшая сверху» вернёт его же
    (no-op) — отдельного признака «вход без резки» не требуется.

    ``None`` — вход без длины (безразмерные штуки), подбор невозможен.
    """
    input_dims = row.input_dimensions or {}
    input_length = input_dims.get(LENGTH_MM)
    if isinstance(input_length, bool) or not isinstance(input_length, (int, float)):
        return None
    if float(input_length) <= 0:
        return None
    return float(input_length)


def _pick_raw_length_mm(candidates: Iterable[float], gp_length_mm: float) -> float | None:
    """ADR-0024 «ближайшая сверху»: минимальная зарегистрированная сырьевая
    длина ≥ длины ГП. Точное совпадение — частный случай (возвращается сам ГП).
    """
    suitable = [float(length) for length in candidates if float(length) >= gp_length_mm]
    return min(suitable) if suitable else None


def _mm_as_meters(length_mm: float) -> str:
    """Миллиметры → строка в метрах с запятой для операторских текстов: 2750 → «2,75»."""
    meters = (Decimal(str(length_mm)) / Decimal(1000)).normalize()
    return format(meters, "f").replace(".", ",")


def _materialize_raw_length_mm(
    row: ParsedPlanRow,
    warnings: list[str],
    *,
    gp_length_mm: float,
    candidates: Iterable[float],
) -> str | None:
    """Подобрать сырьё и материализовать во вход позиции (ADR-0024).

    Успех — ``None`` (вход переписан на сырьевую длину либо точное совпадение,
    ничего делать не надо); сброс флага ``inferred`` (вход перестаёт быть
    равен выходу). Warning ``raw_length_substituted`` — только при разнице
    больше ``RAW_LENGTH_SILENT_TOLERANCE_MM``; в пределах допуска подстановка
    считается штатной и молчаливой. Нет кандидата — ``raw_length_not_found``.
    """
    picked = _pick_raw_length_mm(candidates, gp_length_mm)
    if picked is None:
        return "raw_length_not_found"
    if picked == gp_length_mm:
        return None
    new_dims = canonicalize_dimensions({**(row.input_dimensions or {}), LENGTH_MM: picked})
    row.input_dimensions = new_dims
    input_info = dict(row.payload.get("input") or {})
    input_info["dimensions"] = new_dims
    input_info["inferred"] = False
    row.payload["input"] = input_info
    if picked - gp_length_mm > RAW_LENGTH_SILENT_TOLERANCE_MM:
        warnings.append(
            f"raw_length_substituted:ГП {_mm_as_meters(gp_length_mm)} м"
            f" → сырьё {_mm_as_meters(picked)} м"
        )
    return None


async def _load_raw_lengths_mm(
    db: AsyncSession, product_id: int, cache: dict[int, list[float]]
) -> list[float]:
    """Зарегистрированные длины артикула (``ProductLength``) по возрастанию."""
    if product_id not in cache:
        rows = (
            await db.scalars(
                select(ProductLength.length_mm).where(ProductLength.product_id == product_id)
            )
        ).all()
        cache[product_id] = sorted({float(length) for length in rows})
    return cache[product_id]


async def preview_excel_sheet(
    db: AsyncSession,
    *,
    filename: str,
    content: bytes,
    sheet_index: int = 0,
    mode: ImportBatchMode = ImportBatchMode.create_plan,
    production_plan_id: int | None = None,
    column_mapping: dict | None = None,
    row_selection: str | None = None,
    rule_profile_id: int | None = None,
    normalize_hanger_quantity: bool = True,
) -> dict:
    """Parse an Excel sheet and return full preview checks without creating DB records."""
    parsed = parse_factory_plan_workbook(
        content,
        filename,
        sheet_index=sheet_index,
        column_mapping=column_mapping,
        row_selection=row_selection,
        normalize_hanger_quantity=normalize_hanger_quantity,
    )
    summary = _summary(parsed.parsed_rows, parsed.warnings, parsed)

    existing_positions: list[PlanPosition] = []
    effective_plan_id = production_plan_id
    if effective_plan_id is None and mode == ImportBatchMode.append_to_plan:
        latest_plan = await db.scalar(
            select(ProductionPlan)
            .where(ProductionPlan.status.notin_(["released", "cancelled"]))
            .order_by(ProductionPlan.created_at.desc())
            .limit(1)
        )
        if latest_plan is not None:
            effective_plan_id = latest_plan.id

    if effective_plan_id is not None and mode != ImportBatchMode.create_plan:
        existing_positions = (
            await db.execute(
                select(PlanPosition).where(
                    PlanPosition.production_plan_id == effective_plan_id,
                    PlanPosition.status != PlanPositionStatus.cancelled,
                )
            )
        ).scalars().all()

    products_by_sku = await _load_products_by_sku(db)
    item_payloads, _route_selection_diagnostics = await _make_change_items(
        db,
        0,  # dry-run preview, no persisted change set
        parsed.parsed_rows,
        products_by_sku,
        mode,
        existing_positions,
        rule_profile_id,
        template_column_mapping=column_mapping,
        normalize_hanger_quantity=parsed.normalize_hanger_quantity,
    )

    # Добавляем quantity_adjusted_total в summary
    quantity_adjusted_total = sum(
        (Decimal(item.after_data.get("quantity", "0")) for item in item_payloads),
        start=Decimal("0"),
    )
    summary["quantity_adjusted_total"] = str(quantity_adjusted_total)

    return {
        "sheet_name": parsed.sheet_name,
        "header_row_number": parsed.header_row_number,
        "total_rows": parsed.total_rows,
        "summary": summary,
        "items": [serialize_item(item) for item in item_payloads],
    }


async def create_excel_import_change_set(
    db: AsyncSession,
    *,
    filename: str,
    content: bytes,
    content_type: str | None,
    sheet_index: int = 0,
    mode: ImportBatchMode = ImportBatchMode.create_plan,
    production_plan_id: int | None = None,
    column_mapping: dict | None = None,
    row_selection: str | None = None,
    template_id: int | None = None,
    rule_profile_id: int | None = None,
    normalize_hanger_quantity: bool = True,
    user = None,
) -> dict:
    extension = validate_excel_extension(filename)
    file_hash = sha256_bytes(content)
    detected_format = detect_workbook_format(content, filename)
    parsed = parse_factory_plan_workbook(
        content,
        filename,
        sheet_index=sheet_index,
        column_mapping=column_mapping,
        row_selection=row_selection,
        normalize_hanger_quantity=normalize_hanger_quantity,
    )

    import_file = await _get_or_create_import_file(
        db,
        filename=filename,
        content=content,
        content_type=content_type,
        extension=extension,
        detected_format=detected_format,
        file_hash=file_hash,
    )

    if production_plan_id is not None:
        production_plan = await db.get(ProductionPlan, production_plan_id)
        if production_plan is None:
            raise ValueError("Production plan not found")
    elif mode == ImportBatchMode.append_to_plan:
        # Find latest non-released/cancelled plan, or create one
        production_plan = await db.scalar(
            select(ProductionPlan)
            .where(ProductionPlan.status.notin_(["released", "cancelled"]))
            .order_by(ProductionPlan.created_at.desc())
            .limit(1)
        )
        if production_plan is None:
            production_plan = await _create_import_plan(db, parsed.sheet_name)
    else:
        production_plan = await _create_import_plan(db, parsed.sheet_name)

    summary = _summary(parsed.parsed_rows, parsed.warnings, parsed)
    import_batch = ImportBatch(
        source_file_id=import_file.id,
        production_plan_id=production_plan.id,
        template_id=template_id,
        rule_profile_id=rule_profile_id,
        mode=mode,
        sheet_name=parsed.sheet_name,
        header_row_number=parsed.header_row_number,
        total_rows=parsed.total_rows,
        parsed_rows=len(parsed.parsed_rows),
        summary=summary,
        rules_snapshot=[],
    )
    db.add(import_batch)
    await db.flush()

    # Persist deterministic rule snapshot used for this import run.
    snapshot_rules = await load_selection_rules_for_profile(db, profile_id=rule_profile_id)
    import_batch.rules_snapshot = [
        {
            "id": rule.id,
            "code": rule.code,
            "name": rule.name,
            "profile_id": rule.profile_id,
            "priority": rule.priority,
            "is_active": rule.is_active,
            "conditions": rule.conditions or [],
            "actions": rule.actions or [],
        }
        for rule in snapshot_rules
    ]

    change_set = PlanChangeSet(
        production_plan_id=production_plan.id,
        import_batch_id=import_batch.id,
        summary=summary,
    )
    db.add(change_set)
    await db.flush()

    # Запись лога аудита (загрузка черновика импорта)
    from app.services.audit_log_service import log_action
    from app.models.audit_log import AuditAction, AuditEntityType
    await log_action(
        db,
        status="success",
        title="Импорт плана (загружен)",
        message=f"Черновик импорта из файла '{filename}' успешно создан (лист: '{parsed.sheet_name}', строк: {len(parsed.parsed_rows)}).",
        user=user,
        action=AuditAction.IMPORT,
        entity_type=AuditEntityType.IMPORT_BATCH,
        entity_id=import_batch.id,
    )

    existing_positions = []
    if production_plan_id is not None and mode != ImportBatchMode.create_plan:
        existing_positions = (
            await db.execute(
                select(PlanPosition).where(
                    PlanPosition.production_plan_id == production_plan_id,
                    PlanPosition.status != PlanPositionStatus.cancelled,
                )
            )
        ).scalars().all()

    products_by_sku = await _load_products_by_sku(db)
    item_payloads, route_selection_diagnostics = await _make_change_items(
        db,
        change_set.id,
        parsed.parsed_rows,
        products_by_sku,
        mode,
        existing_positions,
        rule_profile_id,
        template_id=template_id,
        template_column_mapping=column_mapping,
        normalize_hanger_quantity=parsed.normalize_hanger_quantity,
    )
    for item in item_payloads:
        db.add(item)
    await db.flush()

    # Update batch with diagnostics
    import_batch.route_selection_diagnostics = route_selection_diagnostics

    return {
        "import_file_id": import_file.id,
        "import_batch_id": import_batch.id,
        "production_plan_id": production_plan.id,
        "change_set_id": change_set.id,
        "template_id": import_batch.template_id,
        "rule_profile_id": import_batch.rule_profile_id,
        "rules_snapshot": import_batch.rules_snapshot,
        "route_selection_diagnostics": import_batch.route_selection_diagnostics,
        "sheet_name": parsed.sheet_name,
        "header_row_number": parsed.header_row_number,
        "summary": _item_aggregates(item_payloads, summary),
        "items": [serialize_light_item(item) for item in item_payloads],
        "quantity_adjusted_total": str(sum(
            (Decimal(item.after_data.get("quantity", "0")) for item in item_payloads),
            start=Decimal("0"),
        )),
    }


async def _get_or_create_import_file(
    db: AsyncSession,
    *,
    filename: str,
    content: bytes,
    content_type: str | None,
    extension: str,
    detected_format: str,
    file_hash: str,
) -> ImportFile:
    existing = await db.scalar(select(ImportFile).where(ImportFile.file_sha256 == file_hash))
    if existing is not None:
        return existing

    storage_dir = Path(settings.IMPORT_STORAGE_DIR)
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_path = storage_dir / f"{file_hash}{extension}"
    stored_path.write_bytes(content)

    import_file = ImportFile(
        original_filename=filename,
        stored_path=str(stored_path),
        content_type=content_type,
        file_extension=extension,
        detected_format=detected_format,
        file_sha256=file_hash,
        size_bytes=len(content),
    )
    db.add(import_file)
    await db.flush()
    return import_file


async def _load_products_by_sku(db: AsyncSession) -> dict[str, Product]:
    products = (await db.execute(
        select(Product).options(
            selectinload(Product.processing_flags),
            selectinload(Product.lengths),
        )
    )).scalars().all()
    result: dict[str, Product] = {}
    for product in products:
        for key in _sku_lookup_keys(product.sku):
            result[key] = product
    return result


def _sku_lookup_keys(sku: str) -> set[str]:
    raw = (sku or "").strip()
    if not raw:
        return set()

    keys = {raw.lower(), _normalize_sku(raw)}

    # Heuristic mojibake recovery for legacy CP1251/Latin-1 mismatch.
    try:
        recovered = raw.encode("latin-1").decode("cp1251")
        keys.add(recovered.lower())
        keys.add(_normalize_sku(recovered))
    except Exception:
        pass
    return {k for k in keys if k}


async def _make_change_items(
    db: AsyncSession,
    change_set_id: int,
    parsed_rows: list[ParsedPlanRow],
    products_by_sku: dict[str, Product],
    mode: ImportBatchMode,
    existing_positions: list[PlanPosition],
    rule_profile_id: int | None = None,
    template_id: int | None = None,
    template_column_mapping: dict | None = None,
    normalize_hanger_quantity: bool = True,
) -> tuple[list[PlanChangeItem], dict]:
    available_by_sku = _build_available_inputs_by_sku(parsed_rows)
    by_fingerprint: dict[str, PlanPosition] = {}
    by_row_hash: dict[str, PlanPosition] = {}
    for pos in existing_positions:
        if pos.source_fingerprint:
            by_fingerprint[pos.source_fingerprint] = pos
        if pos.source_row_hash:
            by_row_hash[pos.source_row_hash] = pos

    # Build set of existing fingerprints for duplicate detection
    existing_fingerprints: set[str] = set()
    for pos in existing_positions:
        if pos.status == PlanPositionStatus.cancelled:
            continue
        if pos.source_fingerprint:
            existing_fingerprints.add(pos.source_fingerprint)

    items: list[PlanChangeItem] = []
    matched_fingerprints: set[str] = set()
    
    # Cache product.is_active to prevent autoflush when accessing expired objects
    product_is_active_cache: dict[int, bool] = {}
    for prod in products_by_sku.values():
        try:
            product_is_active_cache[prod.id] = prod.is_active
        except Exception:
            product_is_active_cache[prod.id] = False
    
    # Cache for already created/found routes by route_name -> route_id
    route_cache: dict[str, int] = {}

    # Локальные кэши для устранения N+1 запросов при сопоставлении маршрутов и пар
    pair_cache = {}                   # tuple(component_skus) -> ResolvedPair | None
    pair_n_cache = {}                 # (pair.id, length_key) -> PairHangerValue
    pair_candidates_cache: dict[int, list[float]] = {}  # pair.id -> пересечение длин A∩B (ADR-0024)
    raw_lengths_cache: dict[int, list[float]] = {}  # product.id -> длины ProductLength (ADR-0024)
    select_route_cache = {}           # tuple_key -> RouteSelectionResult
    route_stages_cache = {}           # route.id -> list[RouteStage]
    sections_by_id_cache = {}         # section_id -> Section
    sections_by_code_cache = {}       # section_code -> Section
    existing_route_by_name_cache = {} # built_route.name -> ProductionRoute
    typical_dimensions_cache: dict[int, dict | None] = {}  # product.id -> типовой размер либо None

    # Межстрочные кэши подбора/сборки маршрута (спека §4.1, #163): снимок
    # справочников на батч — правила, активные маршруты, join этапов,
    # участки, группы операций. Семантика не меняется, только чтение.
    batch_profile = await db.get(RouteRuleProfile, rule_profile_id) if rule_profile_id is not None else None
    selection_batch = await load_route_selection_batch_cache(db, rule_profile_id)
    build_batch = (
        await load_route_build_batch_cache(db, batch_profile, selection_cache=selection_batch)
        if batch_profile is not None
        else None
    )

    def make_hashable(val):
        if isinstance(val, dict):
            return tuple((k, make_hashable(v)) for k, v in sorted(val.items()))
        elif isinstance(val, list):
            return tuple(make_hashable(v) for v in val)
        return val

    # Track fingerprints within this import to detect intra-import duplicates.
    # Use row hashes (not just first row number) so real duplicates are detected
    # and repeated references to the same source row are ignored.
    import_fingerprints: dict[str, dict[str, set[str] | set[int]]] = {}

    for row in parsed_rows:
        warnings = list(row.warnings)
        errors = list(row.errors)
        product = None
        for key in _sku_lookup_keys(row.source_sku):
            product = products_by_sku.get(key)
            if product is not None:
                break

        resolved_pair: ResolvedPair | None = None
        pair_n: PairHangerValue | None = None

        if product is None:
            if not row.payload.get("paired_profile"):
                errors.append("product_not_found")
        else:
            # Use cached value to avoid triggering autoflush
            is_active = product_is_active_cache.get(product.id, False)
            if not is_active:
                errors.append("product_inactive")

        if row.payload.get("paired_profile"):
            # Пара резолвится из product_pairs (#148, ADR-0023) через
            # единственный модуль-владелец: точное неупорядоченное
            # совпадение двух SKU-компонентов.
            components = row.payload.get("components") or []
            component_skus = [c.get("sku", "") for c in components if c.get("sku")]
            # Ключ кэша по нормализованным SKU — вариантам с пробелами/NBSP
            # не нужен отдельный запрос резолва.
            component_skus_key = tuple(sorted(_normalize_sku(sku) for sku in component_skus))
            if component_skus_key in pair_cache:
                resolved_pair = pair_cache[component_skus_key]
            else:
                resolved_pair = await product_pair_resolver.resolve_pair_by_component_skus(db, component_skus)
                pair_cache[component_skus_key] = resolved_pair

            if resolved_pair is None:
                errors.append("product_pair_not_found")
                row.payload["techcard_pair"] = {
                    "resolved": False,
                    "reason": "product_pair_not_found",
                    "inputs": [],
                }
                if "paired_profile_product_unmapped" not in warnings:
                    warnings.append("paired_profile_product_unmapped")
            else:
                # ADR-0024: подбор сырьевой длины «ближайшая сверху» по
                # пересечению длин A∩B и материализация ГП→сырьё во входе —
                # до резолва N. Нет кандидата → raw_length_not_found
                # (ошибка справочника, не расчёта), N не резолвим.
                # Кандидаты кэшируются по паре (#163): ими же пользуется
                # resolve_pair_n без перезапроса мимо pair_n_cache.
                raw_failed = False
                pair_id = resolved_pair.pair.id
                if pair_id not in pair_candidates_cache:
                    pair_candidates_cache[pair_id] = (
                        await product_pair_resolver.pair_length_candidates_mm(db, resolved_pair)
                    )
                gp_length_mm = _gp_length_for_raw_materialization(row)
                if gp_length_mm is not None:
                    raw_error = _materialize_raw_length_mm(
                        row, warnings,
                        gp_length_mm=gp_length_mm,
                        candidates=pair_candidates_cache[pair_id],
                    )
                    if raw_error is not None:
                        errors.append(raw_error)
                        raw_failed = True
                if raw_failed:
                    pair_n = PairHangerValue(None, None)
                else:
                    # N пары — единая механика с одиночными: ручная из словаря
                    # пары / авто-расчёт; невозможна → hanger_calc_zero.
                    length_mm = position_length_mm(row)
                    length_key = _length_key(length_mm) if length_mm is not None else None
                    n_cache_key = (resolved_pair.pair.id, length_key)
                    if n_cache_key in pair_n_cache:
                        pair_n = pair_n_cache[n_cache_key]
                    else:
                        pair_n = await product_pair_resolver.resolve_pair_n(
                            db, resolved_pair, length_mm=length_mm,
                            length_candidates_mm=pair_candidates_cache[pair_id],
                        )
                        pair_n_cache[n_cache_key] = pair_n
                    if pair_n.calc_error:
                        errors.append("hanger_calc_zero")

                inputs = []
                for comp_product in (resolved_pair.product_a, resolved_pair.product_b):
                    sku_key = comp_product.sku.lower()
                    available = available_by_sku.get(sku_key, Decimal("0"))
                    inputs.append({
                        "product_id": comp_product.id,
                        "sku": comp_product.sku,
                        "techcard_quantity": (
                            str(pair_n.quantity_per_hanger) if pair_n.quantity_per_hanger is not None else "0"
                        ),
                        "available_quantity": str(available),
                        "unit": comp_product.unit,
                    })
                # Снапшот пары (payload-ключ legacy, структура сохранена —
                # фронтовые читатели ImportDiffTable/PlanHangerDisplay не меняются).
                row.payload["techcard_pair"] = {
                    "resolved": True,
                    "reason": None,
                    "pair_id": resolved_pair.pair.id,
                    "pair_name": f"{resolved_pair.product_a.sku}+{resolved_pair.product_b.sku}",
                    "inputs": inputs,
                }
                warnings = [w for w in warnings if w != "paired_profile_product_unmapped"]

        payload_has_pack_ops = bool(row.payload.get("additional_pack_operations"))

        payload_key = make_hashable(row.payload)
        route_sel_key = (payload_key, product.id if product else None, rule_profile_id, make_hashable(template_column_mapping) if template_column_mapping else None)
        if route_sel_key in select_route_cache:
            selection = select_route_cache[route_sel_key]
        else:
            selection = await select_route_for_payload(
                db, row.payload, product, profile_id=rule_profile_id,
                template_column_mapping=template_column_mapping,
                batch_cache=selection_batch,
            )
            select_route_cache[route_sel_key] = selection

        route = selection.route
        excel_condition_diagnostics = [
            diagnostic
            for diagnostic in selection.condition_diagnostics
            if diagnostic.get("source") == "excel"
        ]

        if route is None:
            # Only add error if we won't build a dynamic route
            if not rule_profile_id:
                errors.append(selection.error or "no_route_candidate")
        else:
            if route.id in route_stages_cache:
                stages = route_stages_cache[route.id]
            else:
                stages = (
                    await db.execute(select(RouteStage).where(RouteStage.route_id == route.id).order_by(RouteStage.sequence))
                ).scalars().all()
                route_stages_cache[route.id] = stages
            if not stages:
                errors.append("active_route_has_no_steps")
            else:
                for stage in stages:
                    effective_section_id = stage.effective_section_id
                    if effective_section_id in sections_by_id_cache:
                        section = sections_by_id_cache[effective_section_id]
                    else:
                        section = await db.get(Section, effective_section_id)
                        sections_by_id_cache[effective_section_id] = section
                    if section is None or not section.is_active:
                        errors.append("route_contains_inactive_section")
                        break

        route_match_quality = None
        route_match_reason = None
        route_assigned_at = None
        if route is not None:
            route_assigned_at = datetime.now(UTC).isoformat()
            route_match_quality = selection.route_match_quality or PlanPositionRouteMatchQuality.exact.value
            route_match_reason = PlanPositionRouteMatchReason.selection_rules.value

        # ADR-0024: та же механика «ближайшая сверху» для одиночных позиций —
        # вход без резки несёт длину ГП, материализуем в сырьевую из длин
        # самого артикула. Без зарегистрированных длин — как раньше, без
        # новой ошибки (негабаритные штучные товары). Порядок «материализация →
        # N», как у пары: норма берётся по сырьевой длине позиции (#170).
        if not row.payload.get("paired_profile") and product is not None:
            single_gp_length_mm = _gp_length_for_raw_materialization(row)
            if single_gp_length_mm is not None:
                single_candidates = await _load_raw_lengths_mm(db, product.id, raw_lengths_cache)
                if single_candidates:
                    single_raw_error = _materialize_raw_length_mm(
                        row, warnings,
                        gp_length_mm=single_gp_length_mm,
                        candidates=single_candidates,
                    )
                    if single_raw_error is not None:
                        errors.append(single_raw_error)

        # Округление количества до кратности подвесам
        effective_quantity = row.quantity
        original_quantity = row.quantity
        quantity_per_hanger: int | None = None
        hanger_count: int | None = None

        if row.payload.get("paired_profile"):
            # N пары (#148): единая механика с одиночными — ручная из
            # словаря пары / авто-расчёт. Инвариант равенства N (#67):
            # пара — единая загрузка N×A + N×B, поэтому quantity_a == quantity_b
            # и количество позиции — то же число: округляем его, как у
            # одиночных, молча (отдельного warning на пару не заводим).
            per_hanger = pair_n.quantity_per_hanger if pair_n is not None else None

            if per_hanger and per_hanger > 0:
                if normalize_hanger_quantity:
                    adjusted = adjust_quantity_to_hanger(row.quantity, per_hanger)
                    if adjusted is not None:
                        effective_quantity = adjusted
                hanger_count = (
                    math.ceil(effective_quantity / per_hanger)
                    if normalize_hanger_quantity
                    else float(effective_quantity / per_hanger)
                )
        else:
            # Норма — тем же резолвером, что чтение и валидация плана (#170):
            # по сырьевой длине позиции, строго по режиму артикула.
            length_mm = (row.input_dimensions or {}).get(LENGTH_MM)
            hanger_value = (
                resolve_position_hanger(
                    product, length_mm=length_mm, payload_quantity_per_hanger=None
                )
                if product is not None
                else PositionHangerValue(None, None)
            )
            product_hanger_qty = hanger_value.quantity_per_hanger
            if product_hanger_qty is not None and product_hanger_qty > 0:
                quantity_per_hanger = product_hanger_qty

                if normalize_hanger_quantity:
                    adjusted = adjust_quantity_to_hanger(row.quantity, product_hanger_qty)
                    if adjusted is not None:
                        effective_quantity = adjusted
                        hanger_count = math.ceil(effective_quantity / product_hanger_qty)
                    else:
                        hanger_count = math.ceil(effective_quantity / product_hanger_qty)
                else:
                    # Округление отключено — считаем подвесы как дробное число
                    hanger_count = float(effective_quantity / product_hanger_qty)
            elif normalize_hanger_quantity:
                # Нормы для сырьевой длины позиции нет — не округляем (Q2=а).
                if product is None:
                    warnings.append("hanger_quantity_not_set:продукт не найден")
                elif length_mm is not None:
                    warnings.append(f"hanger_quantity_not_set:{_mm_as_meters(length_mm)}")
                else:
                    warnings.append(
                        f"hanger_quantity_not_set:quantity_per_hanger не задан для {product.sku}"
                    )

        # Габариты операции (ADR-0003): вход без длины при габаритных выходах —
        # подставляем типовой размер продукта из справочника измерений.
        # Не разрешилось — warning, импорт не падает.
        input_dimensions = row.input_dimensions
        if (
            input_dimensions is None
            and product is not None
            and any(entry.get("dimensions") for entry in row.outputs)
        ):
            if product.id in typical_dimensions_cache:
                input_dimensions = typical_dimensions_cache[product.id]
            else:
                try:
                    input_dimensions = canonicalize_dimensions(
                        await resolve_product_dimensions(db, product.id, None)
                    )
                except (MissingDimensionsError, DimensionsValidationError):
                    input_dimensions = None
                typical_dimensions_cache[product.id] = input_dimensions
            if input_dimensions is None:
                if "input_dimensions_unresolved" not in warnings:
                    warnings.append("input_dimensions_unresolved")
            else:
                input_info = dict(row.payload.get("input") or {})
                input_info["dimensions"] = input_dimensions
                input_info["inferred"] = True
                row.payload["input"] = input_info

        after_data = {
            "product_id": product.id if product else None,
            "source_sku": row.source_sku,
            "source_name": row.source_name,
            "quantity": str(effective_quantity),
            "original_quantity": str(original_quantity),
            "quantity_per_hanger": quantity_per_hanger,
            "hanger_count": hanger_count,
            "input_quantity": (
                format(row.input_quantity.normalize(), "f") if row.input_quantity is not None else None
            ),
            "input_dimensions": input_dimensions,
            "outputs": row.outputs,
            "source_ref": row.source_ref,
            "source_row_numbers": row.source_row_numbers,
            "source_fingerprint": row.source_fingerprint,
            "source_row_hash": row.source_row_hash,
            "source_payload": row.payload,
            "route_id": route.id if route else None,
            "route_name": route.name if route else None,
            "route_source": "auto" if route else "missing",
            "route_origin": PlanPositionRouteOrigin.auto.value if route else None,
            "route_match_quality": route_match_quality,
            "route_match_reason": route_match_reason,
            "route_assigned_at": route_assigned_at,
            "route_manual_confirmed_at": None,
            "route_profile_id": rule_profile_id if rule_profile_id else None,
            "route_selection": {
                "matched_rule_ids": selection.matched_rule_ids,
                "required_sections": selection.required_sections,
                "excluded_sections": selection.excluded_sections,
                "selected_route_id": route.id if route else None,
                "route_match_reason": selection.route_match_reason,
                "excel_column_diagnostics": excel_condition_diagnostics,
                "normalize_applied_actions": selection.normalize_applied_actions,
                "ctx_snapshot": selection.ctx_snapshot,
                "route_select_matched_rule_ids": selection.route_select_matched_rule_ids,
            },
            "has_pack_ops": payload_has_pack_ops,
        }
        
        # Build dynamic route steps for preview
        if batch_profile is not None:
            try:
                # Include product_id in payload for preview so product-based rules work
                preview_payload = row.payload
                if product is not None:
                    preview_payload = {**row.payload, "product_id": product.id}

                built_route = await build_route_from_profile(
                    db, batch_profile, preview_payload, None,
                    product=product, batch=build_batch,
                )

                if not built_route.error:
                    after_data["route_steps"] = [
                        {
                            "sequence": step.sequence,
                            "section_code": step.section_code,
                            "section_name": step.section_name,
                            "operation_code": step.operation_code,
                            "operation_name": step.operation_name,
                            "is_significant": step.is_significant,
                        }
                        for step in built_route.steps
                    ]
                    # Use built route name and assign dynamic route
                    if built_route.name:
                        after_data["route_name"] = built_route.name
                        after_data["route_source"] = "dynamic_build"
                        after_data["route_assigned_at"] = datetime.now(UTC).isoformat()
                        after_data["route_match_quality"] = PlanPositionRouteMatchQuality.exact.value
            except Exception:
                pass  # Silently ignore route building errors for preview
        
        # Build dynamic route and persist as real ProductionRoute (for real import, not preview)
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Route persistence check: rule_profile_id={rule_profile_id}, change_set_id={change_set_id}")
        
        if batch_profile is not None and change_set_id != 0:
            try:
                logger.info(f"Building dynamic route for product {product.id if product else 'None'}")
                logger.info(f"Profile found: {batch_profile is not None}")
                if batch_profile is not None:
                    payload_for_route = {**row.payload, "product_id": product.id} if product else row.payload

                    built_route = await build_route_from_profile(
                        db, batch_profile, payload_for_route, None,
                        product=product, batch=build_batch,
                    )
                    
                    # Log route building result
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.info(f"Built route: name={built_route.name}, error={built_route.error}, steps_count={len(built_route.steps)}")
                    if len(built_route.steps) == 0:
                        logger.warning(f"Built route has NO STEPS! route_sections={built_route.route_sections}, excluded={built_route.excluded_sections}")
                    
                    if not built_route.error and built_route.name:
                        # Cache key includes route name — color/output_kind are encoded in the name.
                        resolved_ops_summary = tuple(
                            (step.section_code, step.operation_code)
                            for step in built_route.steps
                            if step.operation_code
                        )
                        cache_key = (built_route.name, resolved_ops_summary)
                        
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.info(f"Route cache key: ops={resolved_ops_summary}")
                        
                        # Check cache first
                        if cache_key in route_cache:
                            created_route_id = route_cache[cache_key]
                            # Use cached route - steps already exist
                        else:
                            # Lookup existing ProductionRoute
                            if built_route.name in existing_route_by_name_cache:
                                existing_route = existing_route_by_name_cache[built_route.name]
                            else:
                                existing_route = await db.scalar(
                                    select(ProductionRoute).where(
                                        ProductionRoute.name == built_route.name,
                                    )
                                )
                                existing_route_by_name_cache[built_route.name] = existing_route
                            
                            if existing_route is not None:
                                # Route already exists - it should have steps
                                created_route_id = existing_route.id
                                route_cache[cache_key] = created_route_id
                            else:
                                # Create new ProductionRoute with steps
                                created_route = ProductionRoute(
                                    name=built_route.name,
                                    is_active=True,
                                    import_template_id=template_id,
                                )
                                db.add(created_route)
                                await db.flush()
                                # Кэшируем маршрут по имени сразу после создания:
                                # иначе следующая строка этого же импорта с тем же именем
                                # маршрута (но другим ops_summary → иным cache_key) возьмёт
                                # из existing_route_by_name_cache None и попытается создать
                                # дубль → UniqueViolation uq_production_routes_name.
                                existing_route_by_name_cache[built_route.name] = created_route

                                # Create route stages and operations with savepoint protection
                                steps_created_successfully = False
                                try:
                                    async with db.begin_nested():
                                        # Group built_route.steps by section_code
                                        groups = []
                                        current = []
                                        current_section_id = None

                                        for step in sorted(built_route.steps, key=lambda s: s.sequence):
                                            if step.section_code in sections_by_code_cache:
                                                section = sections_by_code_cache[step.section_code]
                                            else:
                                                section = await db.scalar(
                                                    select(Section).where(Section.code == step.section_code).limit(1)
                                                )
                                                sections_by_code_cache[step.section_code] = section
                                            if section is None:
                                                import logging
                                                logger = logging.getLogger(__name__)
                                                logger.warning(f"Section not found for code: {step.section_code}")
                                                continue


                                            same_group = (
                                                section.id == current_section_id
                                            )

                                            step_info = (step, section)
                                            if same_group:
                                                current.append(step_info)
                                            else:
                                                if current:
                                                    groups.append(current)
                                                current = [step_info]
                                                current_section_id = section.id
                                        if current:
                                            groups.append(current)

                                        if not groups:
                                            raise ValueError(f"No steps/stages added for route {built_route.name}. Built route has {len(built_route.steps)} steps.")

                                        stage_seq = 1
                                        for group in groups:
                                            primary_step, primary_section = group[0]
                                            # Маркер трансформации этапа (ADR-0002) —
                                            # из справочника операций участка, не из кода.
                                            from app.services.route_transform import resolve_stage_transforms_dimensions
                                            stage_transforms = await resolve_stage_transforms_dimensions(
                                                db,
                                                section_id=primary_section.id,
                                                operation_codes=[s[0].operation_code for s in group],
                                            )
                                            stage = RouteStage(
                                                route_id=created_route.id,
                                                sequence=stage_seq,
                                                section_id=primary_section.id,
                                                is_significant=primary_step.is_significant,
                                                transforms_dimensions=stage_transforms,
                                                requires_acceptance=True,
                                                allow_parallel=False,
                                                is_final=any(s[0].is_final for s in group),
                                            )
                                            db.add(stage)
                                            await db.flush()

                                            for op_idx, (step, _) in enumerate(group, start=1):
                                                op = RouteOperation(
                                                    route_stage_id=stage.id,
                                                    sequence=op_idx,
                                                    operation_code=step.operation_code,
                                                    operation_name=step.operation_name,
                                                )
                                                db.add(op)
                                            
                                            stage_seq += 1

                                        await db.flush()
                                        steps_created_successfully = True
                                except Exception as step_error:
                                    # Savepoint is automatically rolled back
                                    # Check if stages exist (maybe created by concurrent process)
                                    existing_stages_count = await db.scalar(
                                        select(func.count(RouteStage.id)).where(
                                            RouteStage.route_id == created_route.id
                                        )
                                    )
                                    if existing_stages_count > 0:
                                        steps_created_successfully = True
                                    else:
                                        import logging
                                        logger = logging.getLogger(__name__)
                                        logger.error(f"Failed to create stages for route {built_route.name}: {step_error}", exc_info=True)
                                        raise

                                if steps_created_successfully:
                                    created_route_id = created_route.id
                                    route_cache[cache_key] = created_route_id
                                    # Видимость для построчных селектов (#163):
                                    # живые запросы видели бы созданный маршрут.
                                    # Фактические строки этапов (группы могут
                                    # пропускать шаги без участка) — одним
                                    # запросом на созданный маршрут.
                                    created_section_rows = await load_route_sections(db, [created_route.id])
                                    selection_batch.register_created_route(
                                        created_route,
                                        created_section_rows.get(created_route.id, []),
                                    )
                        
                        # Update after_data with the created route
                        after_data["route_id"] = created_route_id
                        after_data["route_name"] = built_route.name
                        after_data["route_source"] = "dynamic_build"
                        after_data["route_origin"] = PlanPositionRouteOrigin.auto.value
                        after_data["route_assigned_at"] = datetime.now(UTC).isoformat()
                        after_data["route_match_quality"] = PlanPositionRouteMatchQuality.exact.value
            except Exception as route_error:
                # Log route building errors but don't fail the entire import
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Route building failed for row {row.source_sku}: {route_error}", exc_info=True)
        
        # Log final route_id
        import logging
        logging.getLogger(__name__).info(f"Final route_id for row {row.source_sku}: {after_data.get('route_id')}")

        # Detect duplicate within this import using fingerprint (full row match)
        fp = row.source_fingerprint
        if fp not in import_fingerprints:
            import_fingerprints[fp] = {"row_hashes": set(), "row_numbers": set()}
        fp_entry = import_fingerprints[fp]
        row_hashes = fp_entry["row_hashes"]
        row_numbers = fp_entry["row_numbers"]
        if isinstance(row_hashes, set):
            row_hashes.add(row.source_row_hash)
        if isinstance(row_numbers, set):
            # Use only the canonical (first) row number to avoid false positives
            # from paired profile rows which have multiple source_row_numbers.
            canonical_row = row.source_row_numbers[0] if row.source_row_numbers else row.source_row_number
            row_numbers.add(canonical_row)

        change_action = PlanChangeAction.create_position
        before_data = None
        plan_position_id = None

        existing_by_fp = None
        if mode != ImportBatchMode.create_plan:
            existing_by_fp = by_fingerprint.get(row.source_fingerprint)
            if existing_by_fp is not None:
                matched_fingerprints.add(row.source_fingerprint)
                if existing_by_fp.status == PlanPositionStatus.draft:
                    # Сравниваем по original_quantity если есть, иначе по hash
                    existing_original = existing_by_fp.source_payload.get("original_quantity", str(existing_by_fp.quantity))
                    if existing_original == str(row.quantity) and existing_by_fp.source_row_hash == row.source_row_hash:
                        change_action = PlanChangeAction.ignore_unchanged
                    else:
                        change_action = PlanChangeAction.update_draft_position
                        plan_position_id = existing_by_fp.id
                        before_data = {
                            "product_id": existing_by_fp.product_id,
                            "source_sku": existing_by_fp.source_sku,
                            "source_name": existing_by_fp.source_name,
                            "quantity": str(existing_by_fp.quantity),
                            "original_quantity": existing_by_fp.source_payload.get("original_quantity", str(existing_by_fp.quantity)),
                            "source_ref": existing_by_fp.source_ref,
                            "source_row_numbers": [existing_by_fp.source_row_number],
                            "source_fingerprint": existing_by_fp.source_fingerprint,
                            "source_row_hash": existing_by_fp.source_row_hash,
                            "source_payload": existing_by_fp.source_payload,
                            "has_pack_ops": existing_by_fp.has_pack_ops,
                        }
                elif existing_by_fp.status == PlanPositionStatus.released:
                    change_action = PlanChangeAction.mark_possible_duplicate
                    plan_position_id = existing_by_fp.id

        # Duplicate against existing data
        if mode != ImportBatchMode.create_plan and fp in existing_fingerprints:
            if "duplicate_sku_due_date" not in errors:
                errors.append("duplicate_sku_due_date")

        status = plan_import_row_status(errors, warnings)
        if change_action == PlanChangeAction.mark_possible_duplicate and status == PlanChangeItemStatus.pending:
            status = PlanChangeItemStatus.warning

        items.append(
            PlanChangeItem(
                change_set_id=change_set_id,
                source_row_number=row.source_row_numbers[0],
                source_ref=row.source_ref,
                change_action=change_action,
                before_data=before_data,
                after_data=after_data,
                status=status,
                plan_position_id=plan_position_id,
                warnings=warnings,
                errors=errors,
            )
        )

    # Mark intra-import duplicates: fingerprints that appear more than once
    duplicate_pairs: dict[str, list[int]] = {}
    for fp, fp_entry in import_fingerprints.items():
        row_hashes = fp_entry["row_hashes"]
        row_numbers = fp_entry["row_numbers"]
        if isinstance(row_numbers, set) and len(row_numbers) > 1:
            duplicate_pairs[fp] = sorted(row_numbers)

    if duplicate_pairs:
        for item in items:
            if item.after_data:
                fp = item.after_data.get("source_fingerprint")
                if fp and fp in duplicate_pairs and "duplicate_sku_due_date" not in item.errors:
                    item.errors = list(item.errors) + ["duplicate_sku_due_date"]
                    item.status = PlanChangeItemStatus.invalid
                    # Store duplicate info for frontend display
                    item.after_data["duplicate_rows"] = duplicate_pairs[fp]
                    item.after_data["duplicate_type"] = "within_import"

    # Mark duplicates against existing positions with row info
    if mode != ImportBatchMode.create_plan:
        for item in items:
            if item.after_data and "duplicate_sku_due_date" in item.errors:
                # Already marked as intra-import duplicate
                if item.after_data.get("duplicate_type"):
                    continue
                # Find existing position with matching fingerprint
                fp = item.after_data.get("source_fingerprint")
                if fp and fp in existing_fingerprints:
                    # Find the existing position with matching fingerprint
                    for pos in existing_positions:
                        if pos.status == PlanPositionStatus.cancelled:
                            continue
                        if pos.source_fingerprint == fp:
                            item.after_data["duplicate_existing_id"] = pos.id
                            item.after_data["duplicate_existing_row"] = pos.source_row_number
                            item.after_data["duplicate_existing_payload"] = pos.source_payload
                            item.after_data["duplicate_type"] = "against_existing"
                            break

    if mode == ImportBatchMode.replace_draft_from_same_source:
        for fp, pos in by_fingerprint.items():
            if fp not in matched_fingerprints and pos.status == PlanPositionStatus.draft:
                items.append(
                    PlanChangeItem(
                        change_set_id=change_set_id,
                        source_row_number=pos.source_row_number,
                        source_ref=pos.source_ref,
                        change_action=PlanChangeAction.cancel_draft_position,
                        before_data={
                            "product_id": pos.product_id,
                            "source_sku": pos.source_sku,
                            "source_name": pos.source_name,
                            "quantity": str(pos.quantity),
                            "source_ref": pos.source_ref,
                            "source_row_numbers": [pos.source_row_number],
                            "source_fingerprint": pos.source_fingerprint,
                            "source_row_hash": pos.source_row_hash,
                            "source_payload": pos.source_payload,
                            "has_pack_ops": pos.has_pack_ops,
                        },
                        after_data={},
                        status=PlanChangeItemStatus.pending,
                        plan_position_id=pos.id,
                        warnings=[],
                        errors=[],
                    )
                )

    route_selection_diagnostics = {
        "template_id": template_id,
        "profile_id": rule_profile_id,
        "total_rows": len(parsed_rows),
        "matched_count": sum(1 for item in items if item.after_data and item.after_data.get("route_id")),
        "unmatched_count": sum(1 for item in items if item.after_data and not item.after_data.get("route_id")),
        "normalize_actions_count": sum(
            len((item.after_data or {}).get("route_selection", {}).get("normalize_applied_actions", []))
            for item in items
        ),
        "ctx_samples": [
            (item.after_data or {}).get("route_selection", {}).get("ctx_snapshot")
            for item in items
            if (item.after_data or {}).get("route_selection", {}).get("ctx_snapshot")
        ][:5],
        "excel_diagnostics": {
            "conditions_evaluated": sum(
                len((item.after_data or {}).get("route_selection", {}).get("excel_column_diagnostics", []))
                for item in items
            ),
            "header_mismatch_count": sum(
                1
                for item in items
                for diagnostic in ((item.after_data or {}).get("route_selection", {}).get("excel_column_diagnostics", []))
                if "excel_header_mismatch" in (diagnostic.get("issues") or [])
            ),
            "fallback_used_count": sum(
                1
                for item in items
                for diagnostic in ((item.after_data or {}).get("route_selection", {}).get("excel_column_diagnostics", []))
                if diagnostic.get("resolved_by") in {"header_fallback", "explicit_header"}
            ),
        },
    }

    return items, route_selection_diagnostics


def serialize_item(item: PlanChangeItem) -> dict:
    return {
        "id": item.id,
        "source_row_number": item.source_row_number,
        "source_ref": item.source_ref,
        "source_sku": item.after_data.get("source_sku") if item.after_data else None,
        "change_action": item.change_action.value,
        "status": item.status.value,
        "warnings": item.warnings,
        "errors": item.errors,
        "after_data": item.after_data,
        "plan_position_id": item.plan_position_id,
    }

def serialize_light_item(item: PlanChangeItem) -> dict:
    """Лёгкая строка create-ответа (спека §4.3): без after_data целиком."""
    after = item.after_data or {}
    row_numbers = after.get("source_row_numbers") or (
        [item.source_row_number] if item.source_row_number is not None else []
    )
    return {
        "item_id": item.id,
        "source_row_numbers": row_numbers,
        "source_sku": after.get("source_sku"),
        "source_name": after.get("source_name"),
        "quantity": after.get("quantity"),
        "status": item.status.value,
        "change_action": item.change_action.value,
        "codes": list(item.errors or []) + list(item.warnings or []),
    }


def _item_aggregates(items: list[PlanChangeItem], summary: dict) -> dict:
    """Агрегаты уровня строк поверх parse-summary (спека §4.3).

    `errors` пересчитывается по строкам: включает коды, добавленные после
    парсинга (дубли, автовключения), — именно их показывает диалог.
    `duplicates` считает все дубли, включая внутриимпортные (код
    duplicate_sku_due_date без смены change_action): серверный чип «Дубли»
    в диалоге должен совпадать с таблицей.
    """
    error_counter = Counter(code for item in items for code in (item.errors or []))
    enriched = dict(summary)
    enriched["total"] = len(items)
    enriched["valid"] = sum(1 for item in items if item.status == PlanChangeItemStatus.pending)
    enriched["warning"] = sum(1 for item in items if item.status == PlanChangeItemStatus.warning)
    enriched["invalid"] = sum(1 for item in items if item.status == PlanChangeItemStatus.invalid)
    enriched["duplicates"] = sum(1 for item in items if plan_import_item_is_duplicate(item))
    enriched["errors"] = dict(error_counter)
    return enriched


def _summary(
    rows: list[ParsedPlanRow],
    workbook_warnings: list[str],
    parsed_workbook: ParsedWorkbook | None = None,
) -> dict:
    warning_counter = Counter(warning for row in rows for warning in row.warnings)
    error_counter = Counter(error for row in rows for error in row.errors)
    summary = {
        "total_positions": len(rows),
        "paired_profile_positions": sum(1 for row in rows if row.payload.get("paired_profile")),
        "warning_count": sum(warning_counter.values()) + len(workbook_warnings),
        "error_count": sum(error_counter.values()),
        "warnings": dict(warning_counter),
        "errors": dict(error_counter),
        "workbook_warnings": workbook_warnings,
        "quantity_total": str(sum((row.quantity for row in rows), start=rows[0].quantity * 0) if rows else 0),
    }
    if parsed_workbook is not None:
        summary["row_selection"] = parsed_workbook.row_selection
        summary["selected_row_numbers"] = parsed_workbook.selected_row_numbers
        summary["auto_included_row_numbers"] = parsed_workbook.auto_included_row_numbers
    return summary


def _build_available_inputs_by_sku(rows: list[ParsedPlanRow]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for row in rows:
        components = row.payload.get("components") or []
        if isinstance(components, list) and components:
            for component in components:
                sku = str(component.get("sku") or "").strip()
                if not sku:
                    continue
                key = sku.lower()
                current = totals.get(key, Decimal("0"))
                totals[key] = current + row.quantity
            continue

        key = row.source_sku.lower()
        current = totals.get(key, Decimal("0"))
        totals[key] = current + row.quantity
    return totals


def _make_plan_no(sheet_name: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    safe_sheet = "".join(ch for ch in sheet_name if ch.isalnum() or ch in " _-")[:30] or "Excel"
    return f"План-{safe_sheet}-{stamp}"


async def _create_import_plan(db: AsyncSession, sheet_name: str) -> ProductionPlan:
    """Новый план импорта: имя всегда «Import {лист}»."""
    plan_no = _make_plan_no(sheet_name)
    plan_name = f"Import {sheet_name}"
    production_plan = ProductionPlan(plan_no=plan_no, name=plan_name)
    db.add(production_plan)
    await db.flush()
    return production_plan
