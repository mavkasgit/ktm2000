from __future__ import annotations

SELECTION_RULES = [
    {
        "code": "core_sections",
        # SHIPMENT/SHIPPED обязательны, и требование рабочее: складские этапы
        # лежат в `storage_section_id`, а `validate_route_match` их учитывает
        # наравне с `section_id` (фикс рядом, в route_validation). Прежняя
        # ошибка «любой маршрут со складами неполон» лечилась чтением
        # `storage_section_id`, а не снятием требования: без этого фикса
        # маршрут без отправки проходил бы approve незаметно.
        "name": "Базовые участки маршрута",
        "profile_code": "packaging_map_rp",
        "priority": 1000,
        "is_active": True,
        "phase": "route_select",
        "conditions": [],
        "actions": [
            {"action": "require_section", "section_code": "RAW_STOCK"},
            {"action": "require_section", "section_code": "ANODIZING"},
            {"action": "require_section", "section_code": "FINISHED_STOCK"},
            {"action": "require_section", "section_code": "SHIPMENT"},
            {"action": "require_section", "section_code": "SHIPPED"},
        ],
    },
    {
        "code": "drill",
        "name": "Операция сверловки",
        "profile_code": "packaging_map_rp",
        "priority": 900,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "сверл"},
        ],
        "actions": [
            {"action": "require_section", "section_code": "DRILLING"},
            {"action": "require_section", "section_code": "PREP_STOCK"},
            {"action": "exclude_section", "section_code": "PRESSING"},
        ],
    },
    {
        "code": "press_section",
        "name": "Пресс: участок маршрута",
        "profile_code": "packaging_map_rp",
        "priority": 850,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "окн"},
            {"source": "payload", "field_path": "operation", "operator": "not_contains", "value": "сверл"},
        ],
        "condition_logic": "and",
        "actions": [
            {"action": "require_section", "section_code": "PRESSING"},
            {"action": "require_section", "section_code": "PREP_STOCK"},
            {"action": "exclude_section", "section_code": "DRILLING"},
        ],
    },
    {
        "code": "press_section_comb",
        "name": "Пресс гребёнка: участок маршрута",
        "profile_code": "packaging_map_rp",
        "priority": 850,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "греб"},
            {"source": "payload", "field_path": "operation", "operator": "not_contains", "value": "сверл"},
        ],
        "condition_logic": "and",
        "actions": [
            {"action": "require_section", "section_code": "PRESSING"},
            {"action": "require_section", "section_code": "PREP_STOCK"},
            {"action": "exclude_section", "section_code": "DRILLING"},
        ],
    },
    {
        "code": "press_types",
        "name": "Пресс: определение типа",
        "profile_code": "packaging_map_rp",
        "priority": 100,
        "is_active": True,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "not_empty", "value": None},
        ],
        "actions": [
            {
                "action": "set_operation_by_mapping",
                "section_code": "PRESSING",
                "group_code": "PRESSING",
                "lookup_field": "operation",
                "mapping": [
                    {"keyword": "окн", "operation_code": "PRESS_WINDOW"},
                    {"keyword": "греб", "operation_code": "PRESS_COMB"},
                ],
            },
        ],
    },
    {
        "code": "drill_types",
        "name": "Сверловка: определение типа",
        "profile_code": "packaging_map_rp",
        "priority": 100,
        "is_active": True,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "сверл"},
        ],
        "actions": [
            {
                "action": "set_operation",
                "section_code": "DRILLING",
                "group_code": "DRILLING",
                "operation_code": "DRILL",
            },
        ],
    },
    {
        "code": "empty_primary",
        "name": "Без первичной операции",
        "profile_code": "packaging_map_rp",
        "priority": 800,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "empty", "value": None},
        ],
        "actions": [
            {"action": "exclude_section", "section_code": "DRILLING"},
            {"action": "exclude_section", "section_code": "PRESSING"},
        ],
    },
    {
        "code": "pack_stretch_branch",
        "name": "Стрейч упаковка — полный маршрут (ГП)",
        "profile_code": "packaging_map_rp",
        "priority": 700,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "output_kind", "operator": "contains", "value": "ГП"},
        ],
        "actions": [
            {"action": "require_section", "section_code": "WIP_STOCK"},
            {"action": "require_section", "section_code": "SAWING"},
            {"action": "require_section", "section_code": "PACKING"},
        ],
    },
    {
        "code": "pack_spunbond_branch",
        "name": "Спанбонд упаковка — без промежуточных этапов (П/ф)",
        "profile_code": "packaging_map_rp",
        "priority": 700,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "output_kind", "operator": "contains", "value": "П/ф"},
        ],
        "actions": [
            {"action": "exclude_section", "section_code": "WIP_STOCK"},
            {"action": "exclude_section", "section_code": "SAWING"},
            {"action": "exclude_section", "section_code": "PACKING"},
        ],
    },
    {
        "code": "product_skip_shot",
        "name": "Продукт без дробеструя",
        "profile_code": "packaging_map_rp",
        "priority": 600,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "product", "field_path": "skip_shot_blast", "operator": "equals", "value": True},
        ],
        "actions": [
            {"action": "exclude_section", "section_code": "SHOT_BLAST"},
        ],
    },
    {
        "code": "product_with_shot",
        "name": "Продукт с дробеструем",
        "profile_code": "packaging_map_rp",
        "priority": 590,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "product", "field_path": "skip_shot_blast", "operator": "not_equals", "value": True},
        ],
        "actions": [
            {"action": "require_section", "section_code": "SHOT_BLAST"},
            {"action": "require_section", "section_code": "PREP_STOCK"},
        ],
    },
    {
        "code": "prep_stock_no_prep_path",
        "name": "Без подготовки — исключить склад подготовки",
        "profile_code": "packaging_map_rp",
        "priority": 580,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "empty", "value": None},
            {"source": "product", "field_path": "skip_shot_blast", "operator": "equals", "value": True},
        ],
        "condition_logic": "and",
        "actions": [
            {"action": "exclude_section", "section_code": "PREP_STOCK"},
        ],
    },

    # Normalize: extract color from source_name when Excel color column is empty
    {
        "code": "anod_color_from_source_name",
        "name": "Анод: цвет из наименования",
        "profile_code": "packaging_map_rp",
        "priority": 200,
        "is_active": True,
        "phase": "normalize",
        "conditions": [
            {"source": "payload", "field_path": "color", "operator": "empty", "value": None},
            {"source": "payload", "field_path": "source_name", "operator": "not_empty", "value": None},
        ],
        "condition_logic": "and",
        "actions": [
            {
                "action": "set_field_from_color_extraction",
                "target_field": "color",
                "source_field": "source_name",
            },
        ],
    },

    # ANOD operation resolution — consolidated color mapping
    {
        "code": "anod_colors",
        "name": "Анод: определение цвета",
        "profile_code": "packaging_map_rp",
        "priority": 100,
        "is_active": True,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "color", "operator": "not_empty", "value": None},
        ],
        "actions": [
            {
                "action": "set_operation_by_mapping",
                "section_code": "ANODIZING",
                "group_code": "ANODIZING",
                "lookup_field": "color",
                "mapping": [
                    {"keyword": "анодсеребро", "operation_code": "ANOD_01"},
                    {"keyword": "анодтитан", "operation_code": "ANOD_08"},
                    {"keyword": "анодчерный", "operation_code": "ANOD_05"},
                    {"keyword": "анодчёрный", "operation_code": "ANOD_05"},
                    {"keyword": "анодшампань", "operation_code": "ANOD_06"},
                    {"keyword": "анодзолото", "operation_code": "ANOD_02"},
                    {"keyword": "анодбронза", "operation_code": "ANOD_03"},
                    {"keyword": "анодмедь", "operation_code": "ANOD_07"},
                    {"keyword": "серебр", "operation_code": "ANOD_01"},
                    {"keyword": "золот", "operation_code": "ANOD_02"},
                    {"keyword": "бронз", "operation_code": "ANOD_03"},
                    {"keyword": "чёрн", "operation_code": "ANOD_05"},
                    {"keyword": "черн", "operation_code": "ANOD_05"},
                    {"keyword": "шампань", "operation_code": "ANOD_06"},
                    {"keyword": "мед", "operation_code": "ANOD_07"},
                    {"keyword": "титан", "operation_code": "ANOD_08"},
                ],
            },
        ],
    },

    # ===== resolve_signatures rules =====
    {
        "code": "output_kind_gp",
        "name": "Вид выпуска: ГП",
        "profile_code": "packaging_map_rp",
        "priority": 100,
        "is_active": True,
        "phase": "resolve_signatures",
        "conditions": [
            {"source": "ctx", "field_path": "included_sections", "operator": "contains", "value": "PACKING"},
            {"source": "ctx", "field_path": "included_sections", "operator": "contains", "value": "WIP_STOCK"},
            {"source": "ctx", "field_path": "included_sections", "operator": "contains", "value": "SAWING"},
        ],
        "condition_logic": "and",
        "actions": [
            {"action": "set_field", "path": "payload.output_kind", "value": "ГП"},
        ],
    },
    {
        "code": "output_kind_pf",
        "name": "Вид выпуска: П/Ф",
        "profile_code": "packaging_map_rp",
        "priority": 90,
        "is_active": True,
        "phase": "resolve_signatures",
        "conditions": [
            {"source": "ctx", "field_path": "included_sections", "operator": "not_contains", "value": "PACKING"},
            {"source": "ctx", "field_path": "included_sections", "operator": "not_contains", "value": "WIP_STOCK"},
            {"source": "ctx", "field_path": "included_sections", "operator": "not_contains", "value": "SAWING"},
        ],
        "condition_logic": "and",
        "actions": [
            {"action": "set_field", "path": "payload.output_kind", "value": "П/Ф"},
        ],
    },
    {
        "code": "shot_op_bez_operatsiy",
        "name": "Дробеструй: без операций",
        "profile_code": "packaging_map_rp",
        "priority": 100,
        "is_active": True,
        "phase": "resolve_signatures",
        "conditions": [
            {"source": "ctx", "field_path": "included_sections", "operator": "not_contains", "value": "SHOT_BLAST"},
        ],
        "actions": [
            {"action": "set_field", "path": "payload.shot_op", "value": "Без операций"},
        ],
    },

    # PACK operation resolution — consolidated packaging type mapping
    {
        "code": "pack_types",
        "name": "Упаковка: определение типа",
        "profile_code": "packaging_map_rp",
        "priority": 100,
        "is_active": True,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "output_kind", "operator": "not_empty", "value": None},
        ],
        "actions": [
            {
                "action": "set_operation_by_mapping",
                "section_code": "ANODIZING",
                "group_code": "PACK",
                "lookup_field": "output_kind",
                "mapping": [
                    {"keyword": "ГП", "operation_code": "PACK_STRETCH"},
                    {"keyword": "П/ф", "operation_code": "PACK_SPUNBOND"},
                ],
            },
        ],
    },

    # ===== Упаковка: вид и сборка (#226) =====
    # «Склейка» и «установка рассеивателя» — это операции участка упаковки, а не
    # отдельный шаг маршрута: строка различает их одной колонкой, поэтому группа
    # операций упаковки и получает дефолтную `PACK` для всех остальных строк.
    # Правила маршрута снимают с таких строк сверловку и пресс — иначе строка
    # без первичной операции уходила бы в цех, которого на плане нет.
    {
        "code": "pack_glue_route",
        "name": "Склейка: участок маршрута",
        "profile_code": "packaging_map_rp",
        "priority": 850,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "клей"},
        ],
        "actions": [
            {"action": "exclude_section", "section_code": "DRILLING"},
            {"action": "exclude_section", "section_code": "PRESSING"},
        ],
    },
    {
        "code": "pack_lens_route",
        # Условие ловит и «рассеиватель», и «Без рассеивателя»: это признак
        # отсутствия, отдельной операции у него нет (#226), но маршрут такой
        # строки — тот же, что у строки без первичной операции.
        "name": "Рассеиватель: участок маршрута",
        "profile_code": "packaging_map_rp",
        "priority": 850,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "рассеивател"},
        ],
        "actions": [
            {"action": "exclude_section", "section_code": "DRILLING"},
            {"action": "exclude_section", "section_code": "PRESSING"},
        ],
    },
    {
        "code": "pack_glue_types",
        "name": "Упаковка: склейка",
        "profile_code": "packaging_map_rp",
        "priority": 100,
        "is_active": True,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "клей"},
        ],
        "actions": [
            {
                "action": "set_operation",
                "section_code": "PACKING",
                "group_code": "PACKING",
                "operation_code": "PACK_GLUE",
            },
        ],
    },
    {
        "code": "pack_lens_types",
        # «Без рассеивателя» содержит слово «рассеиватель», поэтому признак
        # отсутствия отсекается явно: операция под него не назначается.
        "name": "Упаковка: установка рассеивателя",
        "profile_code": "packaging_map_rp",
        "priority": 100,
        "is_active": True,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "рассеивател"},
            {"source": "payload", "field_path": "operation", "operator": "not_contains", "value": "без"},
        ],
        "condition_logic": "and",
        "actions": [
            {
                "action": "set_operation",
                "section_code": "PACKING",
                "group_code": "PACKING",
                "operation_code": "PACK_LENS",
            },
        ],
    },

    # ===== Пила: операция по длине раскроя (#226) =====
    # Длина раскроя лежит в payload-полях `input_length`/`output_length`
    # (колонки G и K «Упаковочной карты РП», import_templates.py:22,26) в
    # метрах строкой. Длину в код операции несёт только рез с ОДНИМ выходом:
    # раскрой в несколько длин (ADR-0003) называет одна `SAW_MULTI` (#277) —
    # длины и их число там живут в выходах позиции, а не в коде операции.
    {
        "code": "saw_length_0900",
        "name": "Пила: резка на 0,9 м",
        "profile_code": "packaging_map_rp",
        "priority": 90,
        "is_active": True,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "output_length", "operator": "equals", "value": "0.9"},
            {"source": "payload", "field_path": "input_length", "operator": "not_empty", "value": None},
            {"source": "payload", "field_path": "input_length", "operator": "not_equals", "value": "0.9"},
            {"source": "payload", "field_path": "outputs.1", "operator": "empty", "value": None},
        ],
        "condition_logic": "and",
        "actions": [
            {
                "action": "set_operation",
                "section_code": "SAWING",
                "group_code": "SAWING",
                "operation_code": "SAW_0900",
            },
        ],
    },
    {
        "code": "saw_length_1350",
        "name": "Пила: резка на 1,35 м",
        "profile_code": "packaging_map_rp",
        "priority": 90,
        "is_active": True,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "output_length", "operator": "equals", "value": "1.35"},
            {"source": "payload", "field_path": "input_length", "operator": "not_empty", "value": None},
            {"source": "payload", "field_path": "input_length", "operator": "not_equals", "value": "1.35"},
            {"source": "payload", "field_path": "outputs.1", "operator": "empty", "value": None},
        ],
        "condition_logic": "and",
        "actions": [
            {
                "action": "set_operation",
                "section_code": "SAWING",
                "group_code": "SAWING",
                "operation_code": "SAW_1350",
            },
        ],
    },
    {
        "code": "saw_length_1800",
        "name": "Пила: резка на 1,8 м",
        "profile_code": "packaging_map_rp",
        "priority": 90,
        "is_active": True,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "output_length", "operator": "equals", "value": "1.8"},
            {"source": "payload", "field_path": "input_length", "operator": "not_empty", "value": None},
            {"source": "payload", "field_path": "input_length", "operator": "not_equals", "value": "1.8"},
            {"source": "payload", "field_path": "outputs.1", "operator": "empty", "value": None},
        ],
        "condition_logic": "and",
        "actions": [
            {
                "action": "set_operation",
                "section_code": "SAWING",
                "group_code": "SAWING",
                "operation_code": "SAW_1800",
            },
        ],
    },
    {
        "code": "saw_length_2700",
        "name": "Пила: резка на 2,7 м",
        "profile_code": "packaging_map_rp",
        "priority": 90,
        "is_active": True,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "output_length", "operator": "equals", "value": "2.7"},
            {"source": "payload", "field_path": "input_length", "operator": "not_empty", "value": None},
            {"source": "payload", "field_path": "input_length", "operator": "not_equals", "value": "2.7"},
            {"source": "payload", "field_path": "outputs.1", "operator": "empty", "value": None},
        ],
        "condition_logic": "and",
        "actions": [
            {
                "action": "set_operation",
                "section_code": "SAWING",
                "group_code": "SAWING",
                "operation_code": "SAW_2700",
            },
        ],
    },
    {
        "code": "saw_multi_length",
        # Раскрой одной заготовки в несколько длин (2,7 → 1,8 + 0,9, #277).
        # Признак — второй выход в payload: 59 таких групп в реальном плане
        # (январь–сентябрь 2026). Длины не перечисляются: их число и значения
        # произвольные, они лежат в `outputs`/`cut_layout`; операция только
        # отделяет раскрой от реза в одну длину и от строки без резки.
        "name": "Пила: резка на несколько длин",
        "profile_code": "packaging_map_rp",
        "priority": 90,
        "is_active": True,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "outputs.1", "operator": "not_empty", "value": None},
        ],
        "condition_logic": "and",
        "actions": [
            {
                "action": "set_operation",
                "section_code": "SAWING",
                "group_code": "SAWING",
                "operation_code": "SAW_MULTI",
            },
        ],
    },
    {
        "code": "saw_cut_any_length",
        # Рез в одну длину ЛЮБОЙ длины (0,45, 2,25, …): приоритет выше правил
        # `saw_length_*`, то есть применяется раньше их — точная длина
        # перекрывает фолбэк последней записью (resolved_operations, порядок
        # «приоритет по убыванию»). Новая стандартная длина — просто ещё одно
        # правило `saw_length_*`, этот фолбэк трогать не нужно.
        # «Выход не равен входу» — сравнение двух полей строки (`value_from`):
        # при равенстве резки нет, и строка остаётся на базовой `SAW`.
        "name": "Пила: резка в размер",
        "profile_code": "packaging_map_rp",
        "priority": 95,
        "is_active": True,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "input_length", "operator": "not_empty", "value": None},
            {"source": "payload", "field_path": "output_length", "operator": "not_empty", "value": None},
            {
                "source": "payload",
                "field_path": "output_length",
                "operator": "not_equals",
                "value_from": "input_length",
            },
            {"source": "payload", "field_path": "outputs.1", "operator": "empty", "value": None},
        ],
        "condition_logic": "and",
        "actions": [
            {
                "action": "set_operation",
                "section_code": "SAWING",
                "group_code": "SAWING",
                "operation_code": "SAW_CUT",
            },
        ],
    },

    # ===== План подготовительного участка (#313) =====
    # Профиль `prep_stage_plan`, шаблон `plan_prep_stage`. Ровно ТРИ варианта
    # маршрута, и вместе они не встречаются:
    #   1) сверло + дробеструй — DRILLING, SHOT_BLAST
    #   2) пресс + дробеструй  — PRESSING, SHOT_BLAST
    #   3) чистый дробеструй    — SHOT_BLAST
    # Старт у всех один — RAW_STOCK, финиш один — PREP_STOCK.
    # Различие несёт колонка «Операция» файла: `exclude_section` снимает
    # участок, которого на строке нет. `require_section` нужен не для
    # подбора (его `build_route_from_profile` не читает), а чтобы
    # `validate_route_match` проверяла требуемое против записанных этапов.
    {
        "code": "prep_core_sections",
        "name": "Подготовка: базовые участки",
        "profile_code": "prep_stage_plan",
        "priority": 1000,
        "is_active": True,
        "phase": "route_select",
        "conditions": [],
        "actions": [
            {"action": "require_section", "section_code": "RAW_STOCK"},
            {"action": "require_section", "section_code": "SHOT_BLAST"},
            {"action": "require_section", "section_code": "PREP_STOCK"},
            # Участки основного маршрута до подготовки не доходят: без
            # исключения строка подготовительного плана матчилась бы на
            # универсальный маршрут `universal_rp`, который содержит их все.
            {"action": "exclude_section", "section_code": "ANODIZING"},
            {"action": "exclude_section", "section_code": "WIP_STOCK"},
            {"action": "exclude_section", "section_code": "SAWING"},
            {"action": "exclude_section", "section_code": "PACKING"},
            {"action": "exclude_section", "section_code": "FINISHED_STOCK"},
            {"action": "exclude_section", "section_code": "SHIPMENT"},
            {"action": "exclude_section", "section_code": "SHIPPED"},
        ],
    },
    {
        # Вариант 1: в колонке «Операция» сверловка. Пресс снимаем — на
        # этой строке его нет.
        "code": "prep_drill_shot",
        "name": "Подготовка: сверло + дробеструй",
        "profile_code": "prep_stage_plan",
        "priority": 900,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "сверл"},
        ],
        "actions": [
            {"action": "require_section", "section_code": "DRILLING"},
            {"action": "exclude_section", "section_code": "PRESSING"},
        ],
    },
    {
        # Вариант 2: пресс. Два правила — по окну и по гребёнке: операции
        # пресса в справочнике разные (`PRESS_WINDOW` / `PRESS_COMB`), и
        # колонка файла различает их так же, как на упаковочной карте.
        # `not_contains "сверл"` — пресс строки со сверловкой не бывает,
        # и без этого проверки обе ветки сошлись бы на одной строке.
        "code": "prep_press_window_shot",
        "name": "Подготовка: пресс (окно) + дробеструй",
        "profile_code": "prep_stage_plan",
        "priority": 890,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "окн"},
            {"source": "payload", "field_path": "operation", "operator": "not_contains", "value": "сверл"},
        ],
        "condition_logic": "and",
        "actions": [
            {"action": "require_section", "section_code": "PRESSING"},
            {"action": "exclude_section", "section_code": "DRILLING"},
        ],
    },
    {
        "code": "prep_press_comb_shot",
        "name": "Подготовка: пресс (гребенка) + дробеструй",
        "profile_code": "prep_stage_plan",
        "priority": 890,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "греб"},
            {"source": "payload", "field_path": "operation", "operator": "not_contains", "value": "сверл"},
        ],
        "condition_logic": "and",
        "actions": [
            {"action": "require_section", "section_code": "PRESSING"},
            {"action": "exclude_section", "section_code": "DRILLING"},
        ],
    },
    {
        # Вариант 3: чистый дробеструй. Колонка «Операция» пуста — дробеструй
        # в маршруте есть всегда (вариант не «без дробеструя», а «без
        # сверла и пресса»), а участки подготовки без вторичной операции
        # не заводятся.
        "code": "prep_shot_only",
        "name": "Подготовка: только дробеструй",
        "profile_code": "prep_stage_plan",
        "priority": 880,
        "is_active": True,
        "phase": "route_select",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "empty", "value": None},
        ],
        "actions": [
            {"action": "exclude_section", "section_code": "DRILLING"},
            {"action": "exclude_section", "section_code": "PRESSING"},
        ],
    },
    {
        # Операция строки — из колонки файла (как `pack_type` в тестах
        # импорта): `resolve_operations` адресует группу своего участка.
        "code": "prep_drill_operation",
        "name": "Подготовка: операция сверловки",
        "profile_code": "prep_stage_plan",
        "priority": 100,
        "is_active": True,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "contains", "value": "сверл"},
        ],
        "actions": [
            {
                "action": "set_operation",
                "section_code": "DRILLING",
                "group_code": "DRILLING",
                "operation_code": "DRILL",
            },
        ],
    },
    {
        # Два вида пресса различаются словом в той же колонке. Промах
        # mapping'а не страшен: у участка PRESSING в справочнике есть
        # группы, и `build_route_from_profile` берёт первую операцию группы
        # (fallback участка).
        "code": "prep_press_operation",
        "name": "Подготовка: операция пресса",
        "profile_code": "prep_stage_plan",
        "priority": 100,
        "is_active": True,
        "phase": "resolve_operations",
        "conditions": [
            {"source": "payload", "field_path": "operation", "operator": "not_contains", "value": "сверл"},
            {"source": "payload", "field_path": "operation", "operator": "not_empty", "value": None},
        ],
        "condition_logic": "and",
        "actions": [
            {
                "action": "set_operation_by_mapping",
                "section_code": "PRESSING",
                "group_code": "PRESSING",
                "lookup_field": "operation",
                "mapping": [
                    {"keyword": "окн", "operation_code": "PRESS_WINDOW"},
                    {"keyword": "греб", "operation_code": "PRESS_COMB"},
                ],
            },
        ],
    },
    {
        # Имя маршрута различает варианты: слоты операций пусты у
        # невключённых участков, а `build_route_name` выбрасывает пустые
        # части. `shot_op` ставит правило ниже — без него все три варианта
        # назывались бы одинаково и делили один маршрут по сигнатуре.
        "code": "prep_shot_signature",
        "name": "Подготовка: подпись дробеструя в имени",
        "profile_code": "prep_stage_plan",
        "priority": 100,
        "is_active": True,
        "phase": "resolve_signatures",
        "conditions": [
            {"source": "ctx", "field_path": "included_sections", "operator": "contains", "value": "SHOT_BLAST"},
        ],
        "actions": [
            {"action": "set_field", "path": "payload.shot_op", "value": "Дробеструй"},
        ],
    },
]
