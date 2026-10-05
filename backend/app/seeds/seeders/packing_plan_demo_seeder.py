from __future__ import annotations

"""Демо-данные «Участков» на основе реального упаковочного плана.

Фикстура ниже — срез реального ``Упаковочный план.xlsx`` (лист ``totalplan``):
55 реальных строк с артикулами, цветами, раскроем и упаковочными операциями.
Второй блок, ``PREP_PLAN_ROWS``, добавляет строки участков подготовки
(сверловка/пресс/дробеструй): у них свои операции, разные длины раскроя и
повторяющиеся артикулы — чтобы доска показала и обе операции пресса, и
несколько заданий одного артикула на участке. Третий блок, ``ANOD_PAIR_ROWS``,
даёт пары анодирования: один артикул двумя строками («П/ф» и «ГП»), которые
различаются только упаковочной операцией — на печатном листе участка они
сходятся в одну строку с разбивкой упаковки.

Четвёртый блок, ``PAIR_ARTICLE_ROWS``, закрывает правило парных артикулов
(#312): пара — не одна склеченная позиция ``A+B``, а две самостоятельные
позиции, у которых норма «количество на подвес» берётся у пары — если обе
строки пары пришли в плане (см. правило соседних строк в
``plan_import_service._pair_partner_row_is_adjacent``). Пятый,
``PENDING_PLAN_ROWS``, оставляет часть строк неутверждёнными и
утверждёнными-без-релиза: без них демо показывает только «всё в работе».
Шестой, ``UNPAIRED_PAIR_ROWS``, повторяет строки 10 и 11 реального «Плана
март 26 03» без пары: те же два артикула едут самостоятельными строками со
своими наименованиями и своей нормой подвеса на той же длине, что и пара.

Прогон идёт доменным путём, тем же, что и в UI: импорт плана → change set →
approve → release batch → ``work_tasks``, затем поверх — дневные планы.
Прямой записи в таблицы нет, поэтому инварианты (норма длин, маршрут,
``work_task`` только на производственных секциях) сохраняются теми же
проверками, что и в приложении.

Планов два, и это не украшение: у каждого свой шаблон импорта и свой профиль
маршрута. Первый — «Упаковочная карта РП» (``packaging_map_rp``, 16 колонок,
маршрут до отгрузки). Второй — «План подготовительного участка»
(#313, ``prep_stage_plan``, 7 колонок, маршрут ``RAW_STOCK`` → участки
подготовки → ``PREP_STOCK``): набор участков, колонок и правил другой, и
живой импорт «Плана подготовительного участка» без него не проверен.

Файл xlsx остаётся локальным (``.gitignore``), поэтому строки зафиксированы
здесь как код-данные — по образцу ADR-0004 для канона справочников.

Запуск: ``npm run db:seed:packing-demo`` (см. ``backend/scripts/seed_packing_demo.py``).
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.dimensions import format_dimensions
from app.models.daily_plan import DailyPlan
from app.models.import_template import ImportTemplate
from app.models.imports import ImportBatchMode
from app.models.internal_plan import SectionPlanLine
from app.models.product import (
    Product,
    ProductLength,
    ProductPair,
    ProductType,
    _length_key,
)
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.release_batch import ReleaseBatchType
from app.models.route import RouteRuleProfile, RouteStage
from app.models.section import Section
from app.models.user import User
from app.models.work_task import WorkTask, WorkTaskStatus
from app.seeds.canon.registry import build_plant_config
from app.seeds.seeders.cleanup_seeder import clear_generated_production_data
from app.services.action_journal_service import action_journal_service
from app.services.daily_plan_service import TERMINAL_TASK_STATUSES, create_plan
from app.services.material_operations import completed_operations_through_stage
from app.services.plan_generation import create_release_batch, release_batch
from app.services.plan_import_service import create_excel_import_change_set
from app.services.plan_position_hanger import position_dimensions_for_task
from app.services.production_plan_service import apply_change_set, approve_plan_position
from app.services.shopfloor_service import complete_task
from app.stock import QualityState, Reason, StockCommand, StockCommandService
from app.stock.import_service import RemainderItem, apply_remainders_import
from app.stock.models import StockBalance
from app.stock.services import (
    StockProjectionManager,
    completed_operations_match_clause,
    dimensions_match_clause,
)
from app.transfers.services import transfer_send

PACKING_SECTION_CODE = "PACKING"
DEMO_PLAN_MARKER = "DEMO"

# Склад готовой продукции: на него сид кладёт остатки под незакрытые позиции,
# чтобы их было что взять в работу после утверждения и релиза.
FINISHED_STOCK_SECTION_CODE = "FINISHED_STOCK"

# Все производственные участки доски, которые демо обязано оживить. Шесть из
# шести: пилу/упаковку/анодирование наполняют базовые строки «Упаковочного
# плана» (``PACKING_PLAN_ROWS``), сверловку/пресс/дробеструй — блок строк
# подготовки (``PREP_PLAN_ROWS``).
DEMO_SECTION_CODES = ("DRILLING", "PRESSING", "SHOT_BLAST", "SAWING", "PACKING", "ANODIZING")

# Участки, между которыми по кругу делятся базовые 55 строк фикстуры. Порядок —
# часть контракта доски: ``_target_section_for`` отсчитывает круг от порядкового
# номера позиции, поэтому его нельзя менять, не переиграв прогресс всех базовых
# позиций (историю 55 заданий тест защищает отдельно).
DEMO_RUN_SECTION_CODES = ("SAWING", "PACKING", "ANODIZING")

# Участки подготовки, между которыми делятся новые строки ``PREP_PLAN_ROWS``.
# Строки блока идут тройками «сверловка → пресс → дробеструй», и при том же
# круговом разборе каждая тройка останавливается на своём участке: сверловка не
# заходит на пресс и наоборот (правила ``drill``/``press_section``), дробеструй
# же есть в маршруте у всех.
DEMO_PREP_SECTION_CODES = ("DRILLING", "PRESSING", "SHOT_BLAST")

# Участок прогона пар анодирования. У пары обе строки (спанбонд и стрейч) должны
# остановиться именно на анодировании: тогда они есть и на доске участка, и в
# его дневном плане, а печатный лист сводит их в одну строку с разбивкой
# упаковки. Круг здесь из одного участка — иначе половина пар уехала бы на пилу.
DEMO_ANOD_SECTION_CODES = ("ANODIZING",)

# Профиль маршрута, по которому демо-позиции собирают этапы. Шаблон листа
# демо — «Упаковочная карта РП», и разбирать его операции должен тот же профиль,
# что и живой импорт: иначе позиции уедут на шаблонный маршрут с заглушками.
DEMO_ROUTE_PROFILE_CODE = "packaging_map_rp"

# Профиль маршрута второго набора плана — «План подготовительного участка»
# (#313). Маршрут заканчивается складом подготовки, поэтому задания сид даёт
# только трём участкам подготовки, а не всему маршруту.
DEMO_PREP_STAGE_PROFILE_CODE = "prep_stage_plan"

# Код шаблона импорта второго плана. У профиля ``prep_stage_plan`` нет связи
# ``import_template_id`` (в сиде профиля нет ``import_template_code``), поэтому
# и шаблон, и профиль демо передаёт в импорт явно.
DEMO_PREP_STAGE_TEMPLATE_CODE = "plan_prep_stage"

# Состояния, в которых сид оставляет позиции плана. ``released`` — обычный
# хвост прогона; два остальных нужны, чтобы доска планирования показывала и
# работу, до которой ещё не дошли: неутверждённые строки и утверждённые без
# релиза. Значение живёт в строке фикстуры (ключ ``lifecycle``) и в лист не
# попадает — это распределение сидера, а не данные шаблона импорта.
LIFECYCLE_DRAFT = "draft"
LIFECYCLE_APPROVED = "approved"
LIFECYCLE_RELEASED = "released"
LIFECYCLES = (LIFECYCLE_DRAFT, LIFECYCLE_APPROVED, LIFECYCLE_RELEASED)

# Окружения, в которых сид, сносящий оперативку, запускать нельзя (канон
# ``routes_seed``: force-защита по ``settings.ENV``).
PROD_ENVS = {"prod", "production"}

# Приватные функции выдачи и поиска склада: в них уже весь разбор «первый этап —
# со склада, остальные — с предыдущей задачи»; дублировать эту логику в сидере
# значило бы завести второе место, где меняются правила выдачи.
from app.api.routes.production_planning import (
    _ensure_task_issued_via_transfer,
    _find_preceding_stock_line,
)

# Раскладка демо-прогресса по позициям плана: первые выполнены полностью,
# следующие — в работе, хвост — выданы и ждут оператора. Доли, а не числа:
# фикстура может меняться, а картина «старые планы закрыты, свежие в работе»
# должна сохраняться.
_PROGRESS_BUCKETS = (("done", 0.15), ("partial", 0.35), ("issued", 0.5))

# Сколько дневных планов приходится на каждый день истории (от самого старого).
# Сумма — число карточек в панели; даты с несколькими планами дают в UI
# номера №1/№2, как в реальном цехе.
_PLANS_PER_DAY = (2, 2, 1, 2, 1, 1, 1, 1, 1)

# Колонки «Упаковочной карты РП» в порядке шаблона ``upakovochnaya_karta_rp``.
_PLAN_HEADERS = [
    "Артикул",
    "пополнение",
    "Наименование",
    "остатки сырья на КТМ",
    "Цвет",
    "кол-во шт. в 2,7",
    "Длина, м",
    "Пробивка/сверловка",
    "Упаковка",
    "Примечание ",
    "Длина после упак, м",
    "кол-во штук готовой продукции",
    "Запад",
    "Восток",
    "Вид конечного продукта",
    "Комментарии",
]

# 38 строк реального упаковочного плана: ЮП/АТ-артикулы, цвета, раскрой
# (2,7 → 2,4 / 1,35 / 0,9) и две упаковочные операции (поф, смотка спанбондом).
PACKING_PLAN_ROWS: tuple[dict[str, object], ...] = (
    {
        "sku": "ЮП-2616",
        "name": "Кант универсальный 47мм 2,7 анод черный мат",
        "color": "черный",
        "input_length_m": 2.7,
        "input_quantity": 300,
        "output_length_m": 2.7,
        "output_quantity": 300,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-3270",
        "name": "Микроплинтус 16-20мм 2,4м анод. черный матовый",
        "color": "черный",
        "input_length_m": 2.4,
        "input_quantity": 2000,
        "output_length_m": 2.4,
        "output_quantity": 2000,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-3233",
        "name": "Микроплинтус 18мм 2,4м анод. черный матовый",
        "color": "черный",
        "input_length_m": 2.4,
        "input_quantity": 3000,
        "output_length_m": 2.4,
        "output_quantity": 3000,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "АТ-4863",
        "name": "РП-АКП-01 2,7 м анод.шампань, матов",
        "color": "шампань",
        "input_length_m": 2.7,
        "input_quantity": 150,
        "output_length_m": 2.7,
        "output_quantity": 150,
        "operation": "окно",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-460",
        "name": "РП-АКП-03 2,7 м анод.медь матов",
        "color": "медь",
        "input_length_m": 2.7,
        "input_quantity": 150,
        "output_length_m": 2.7,
        "output_quantity": 150,
        "operation": "окно",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "АТ-7314",
        "name": "РП-АКП-03-12,5 2,7 м анод.шампань, матов",
        "color": "шампань",
        "input_length_m": 2.7,
        "input_quantity": 300,
        "output_length_m": 2.7,
        "output_quantity": 300,
        "operation": "окно",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "АТ-4892",
        "name": "РП-АКП-09 2,7 м анод.серебро, матов",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 500,
        "output_length_m": 2.7,
        "output_quantity": 500,
        "operation": "окно",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-3485",
        "name": "РП-АКП-11 2,7 м анод.золото Матов",
        "color": "золото",
        "input_length_m": 2.7,
        "input_quantity": 270,
        "output_length_m": 2.7,
        "output_quantity": 270,
        "operation": "окно",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "АТ-6844",
        "name": "РП-АКП-13 2,7 м анод.серебро. матов",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 100,
        "output_length_m": 2.7,
        "output_quantity": 100,
        "operation": "окно",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-2900",
        "name": "РП-АКП-16-10 2,7 м анод серебро матовый",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 500,
        "output_length_m": 2.7,
        "output_quantity": 500,
        "operation": "окно",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-137",
        "name": "РП-АКП-20-12 2,7 м анод черный матовый",
        "color": "черный",
        "input_length_m": 2.7,
        "input_quantity": 300,
        "output_length_m": 2.7,
        "output_quantity": 300,
        "operation": "гребенка",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-3168",
        "name": "Стык 33 мм на клеевой основе 2,7 анод.титан матовый",
        "color": "титан",
        "input_length_m": 2.7,
        "input_quantity": 50,
        "output_length_m": 0.9,
        "output_quantity": 150,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-2083",
        "name": "Стык 38 мм. 2,7   анод.серебро, матовый",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 200,
        "output_length_m": 2.7,
        "output_quantity": 200,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "АТ-7121",
        "name": "Стык с дюбелем 30 мм 2,7   анод. серебро матовы",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 150,
        "output_length_m": 0.9,
        "output_quantity": 350,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-2630",
        "name": "Стык с дюбелем 40мм 2,7 анод.серебро матовый",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 100,
        "output_length_m": 2.7,
        "output_quantity": 100,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-081",
        "name": "Стык Т-образный (гибкий) 13мм 2,7 м   анод.серебро.мат",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 1000,
        "output_length_m": 2.7,
        "output_quantity": 1000,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-3177",
        "name": "Стык Т-образный (укороченная ножка) 14мм  2,7 анод черный  мат",
        "color": "черный",
        "input_length_m": 2.7,
        "input_quantity": 200,
        "output_length_m": 2.7,
        "output_quantity": 200,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-3123",
        "name": "Стык Т-образный (укороченная ножка) 18мм 2,7 анод серебро мат",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 500,
        "output_length_m": 2.7,
        "output_quantity": 500,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-2902",
        "name": "Стык Т-образный 20мм 2,7 анод серебро мат",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 1000,
        "output_length_m": 2.7,
        "output_quantity": 1000,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-3473",
        "name": "Стык Т-образный 26мм 2,7 анод.серебро, матовый",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 500,
        "output_length_m": 2.7,
        "output_quantity": 500,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-3242",
        "name": "Угол 20*20 внешний на клеевой основе  2,7 анод.серебро матовый",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 150,
        "output_length_m": 2.7,
        "output_quantity": 150,
        "operation": "клей",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-2627",
        "name": "Угол 21*21  2,7   анод. серебро мат",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 200,
        "output_length_m": 0.9,
        "output_quantity": 200,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-048",
        "name": "Угол 24*18  2,7   анод.золото, матовый",
        "color": "золото",
        "input_length_m": 2.7,
        "input_quantity": 50,
        "output_length_m": 1.35,
        "output_quantity": 100,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-1401",
        "name": "Уголок 10*10 3,0 анод.черный, матовый",
        "color": "шампань",
        "input_length_m": 3.0,
        "input_quantity": 100,
        "output_length_m": 3.0,
        "output_quantity": 100,
        "operation": "",
        "packing": "гп, этикетка с шк и наименованием на каждый профиль, смотка спанбонд п",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-011",
        "name": "Уголок 20*20 3,0 анод.серебро матовый",
        "color": "серебро",
        "input_length_m": 3.0,
        "input_quantity": 500,
        "output_length_m": 3.0,
        "output_quantity": 500,
        "operation": "",
        "packing": "гп, этикетка с шк и наименованием на каждый профиль, смотка спанбонд п",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-2004",
        "name": "Уголок 25*25 3,0 анод.черный матовый",
        "color": "черный",
        "input_length_m": 3.0,
        "input_quantity": 700,
        "output_length_m": 3.0,
        "output_quantity": 700,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-1629",
        "name": "Уголок 30*30 3,0 анод.серебро матовый",
        "color": "серебро",
        "input_length_m": 3.0,
        "input_quantity": 440,
        "output_length_m": 3.0,
        "output_quantity": 440,
        "operation": "",
        "packing": "гп, этикетка с шк и наименованием на каждый профиль, смотка спанбонд п",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-2012",
        "name": "Угол 40*20 2,7 анод. серебро мат. с резин встав (черная)",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 50,
        "output_length_m": 0.9,
        "output_quantity": 150,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-2878",
        "name": "Угол со скрытым креплением 40*22 2,7 анод.черный матовый",
        "color": "черный",
        "input_length_m": 2.7,
        "input_quantity": 150,
        "output_length_m": 0.9,
        "output_quantity": 150,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-2695",
        "name": "Накладка угла со скрытым креплением 40х22 ЮП-2695 2,75 под анод",
        "color": "черный",
        "input_length_m": 2.7,
        "input_quantity": 150,
        "output_length_m": 0.9,
        "output_quantity": 150,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-1767",
        "name": "Широкий стык 100мм 2,7 анодир. серебро матовое",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 70,
        "output_length_m": 0.9,
        "output_quantity": 210,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-2628",
        "name": "Широкий стык 60мм  2,7   анодир. серебро матовое",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 200,
        "output_length_m": 0.9,
        "output_quantity": 300,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-003",
        "name": "Полоса 20мм 2,7 анод.черный матовый",
        "color": "черный",
        "input_length_m": 2.7,
        "input_quantity": 200,
        "output_length_m": 2.7,
        "output_quantity": 200,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-2464-1",
        "name": "Плинтус потайной 50х15 мм 2,5м анод. черный матовое",
        "color": "черный",
        "input_length_m": 2.5,
        "input_quantity": 700,
        "output_length_m": 2.5,
        "output_quantity": 700,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-1875",
        "name": "Плинтус алюминиевый 60 мм 2,5м анод.черный. мат",
        "color": "черный",
        "input_length_m": 2.5,
        "input_quantity": 2160,
        "output_length_m": 2.5,
        "output_quantity": 2160,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-1880",
        "name": "Плинтус алюминиевый 80 мм 2,5м анод.черный. Мат",
        "color": "черный",
        "input_length_m": 2.5,
        "input_quantity": 1970,
        "output_length_m": 2.5,
        "output_quantity": 1970,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ALS1360",
        "name": "Плинтус алюм под светодиодную ленту JD 22-60мм led 2,5м анод черный матовый в компл рассеив 1шт.",
        "color": "черный",
        "input_length_m": 2.5,
        "input_quantity": 120,
        "output_length_m": 2.5,
        "output_quantity": 120,
        "operation": "рассеиватель",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-3688",
        "name": "Плинтус алюм потайной SSZ-50мм 2,5м анодированный черный матовый",
        "color": "черный",
        "input_length_m": 2.5,
        "input_quantity": 560,
        "output_length_m": 2.5,
        "output_quantity": 560,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-3361",
        "name": "Плинтус алюминиевый SSZ-80мм 2,5м анод серебро мат в компл с крепежом 5шт",
        "color": "серебро",
        "input_length_m": 2.5,
        "input_quantity": 300,
        "output_length_m": 2.5,
        "output_quantity": 300,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-3690",
        "name": "Плинтус алюминиевый SSZ-60мм 2,5м анод серебро мат в компл с крепежом 5шт",
        "color": "серебро",
        "input_length_m": 2.5,
        "input_quantity": 700,
        "output_length_m": 2.5,
        "output_quantity": 700,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-2183",
        "name": "РП-АКП-08 2,7 м анод серебро матовый",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 100,
        "output_length_m": 2.7,
        "output_quantity": 100,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "АТ-4893",
        "name": "РП-АКП-11 2,7 м анод.золото. Матов",
        "color": "золото",
        "input_length_m": 2.7,
        "input_quantity": 150,
        "output_length_m": 2.7,
        "output_quantity": 150,
        "operation": "окно",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "АТ-7262",
        "name": "РП-АКП- ECO 2,7 м анод.серебро, матов",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 500,
        "output_length_m": 2.7,
        "output_quantity": 500,
        "operation": "окно",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "АТ-4888",
        "name": "РП-АКП-21 (гибкий) 2,5 м анод.серебро, матов",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 150,
        "output_length_m": 2.7,
        "output_quantity": 150,
        "operation": "гребенка",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-3167",
        "name": "Стык 36 мм на клеевой основе 0,9   анод.золото матовый",
        "color": "золото",
        "input_length_m": 2.7,
        "input_quantity": 50,
        "output_length_m": 0.9,
        "output_quantity": 150,
        "operation": "клей",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-2910",
        "name": "Стык Т-образный 23мм разносторонний 2,7 анод серебро матовый",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 300,
        "output_length_m": 2.7,
        "output_quantity": 300,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/Ф",
    },
    {
        "sku": "ЮП-009",
        "name": "Уголок 15*15 3,0 анод.серебро матовый",
        "color": "серебро",
        "input_length_m": 3.0,
        "input_quantity": 500,
        "output_length_m": 3.0,
        "output_quantity": 500,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/Ф",
    },
    {
        "sku": "ЮП-3019",
        "name": "Угол 24*10 2,7 анод. серебро матовый",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 150,
        "output_length_m": 0.9,
        "output_quantity": 250,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-2082",
        "name": "Угол 25*25 0,9   анодированный серебро, матовый",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 50,
        "output_length_m": 0.9,
        "output_quantity": 150,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-2397",
        "name": "Швеллер 10*10*10 3,0 анод.черный матовый",
        "color": "черный",
        "input_length_m": 3.0,
        "input_quantity": 100,
        "output_length_m": 3.0,
        "output_quantity": 100,
        "operation": "",
        "packing": "гп, этикетка с шк и наименованием на каждый профиль, смотка спанбонд п",
        "kind": "ГП",
    },
    {
        "sku": "ALS798",
        "name": "Плинтус алюминиевый 17 мм 2,5м анод.серебро матовый",
        "color": "серебро",
        "input_length_m": 2.5,
        "input_quantity": 300,
        "output_length_m": 2.5,
        "output_quantity": 300,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ALS1103",
        "name": "Плинтус алюминиевый 40 мм 2,5м анод. серебро матовый",
        "color": "серебро",
        "input_length_m": 2.5,
        "input_quantity": 500,
        "output_length_m": 2.5,
        "output_quantity": 500,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/Ф",
    },
    {
        "sku": "ALS1320",
        "name": "Плинтус алюм под светодиодную ленту JD 21-60мм led 2,5м анод черный матовый",
        "color": "черный",
        "input_length_m": 2.5,
        "input_quantity": 500,
        "output_length_m": 2.5,
        "output_quantity": 500,
        "operation": "Без рассеивателя",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/Ф",
    },
    {
        "sku": "ЮП-2975",
        "name": "Плинтус алюм под светодиодную ленту JD 22-80мм led 2,5м анод серебро матовый в компл рассеив 1шт",
        "color": "серебро",
        "input_length_m": 2.5,
        "input_quantity": 300,
        "output_length_m": 2.5,
        "output_quantity": 300,
        "operation": "Без рассеивателя",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/Ф",
    },
    {
        "sku": "ALS917",
        "name": "Алюминиевая декоративная вставка 5,3*6 ZU2.0-5.5 T1.8L 2,7м анодированный черный матовый",
        "color": "черный",
        "input_length_m": 2.7,
        "input_quantity": 150,
        "output_length_m": 2.7,
        "output_quantity": 150,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
)


# Строки участков подготовки. Блок собран тремя под-кортежами (по одной
# первичной операции на участок) и перемешан тройками ниже: разбор по кругу
# (``_target_section_for``) останавливает каждую тройку на её участке, поэтому
# 10 строк сверловки действительно становятся 10 заданиями сверловки, а не
# «уезжают» на соседний участок. Артикулы внутри блока повторяются (несколько
# строк на один артикул) — так на доске видно несколько заданий одного
# артикула; строки различаются количеством и/или раскроем, иначе импорт счёл бы
# их дублями.
#
# Артикулы — реальные каталожные, и длина строки взята как **нормальная
# (готовая) длина этого товара** из каталога: ``product_lengths.raw_length_mm IS
# NULL``. Заготовка (строка, где ``raw_length_mm`` заполнен и равен длине:
# 2750/1830/3050/2550/2760) длиной изделия не является и в фикстуру не идёт —
# иначе в плане стояло бы «2,75» вместо дела. Каталог даёт всего 10 подходящих
# артикулов вне базовых 55, поэтому блоки подготовки делят семь из них, а три
# остаются парам анодирования.
#
# «Пробивка/сверловка»: «сверло» → DRILLING (DRILL), «окно»/«гребенка» →
# PRESSING (PRESS_WINDOW/PRESS_COMB), пустая → маршрут без первичной операции,
# но с SHOT_BLAST (дробеструй есть у всех демо-артикулов).
_PREP_DRILL_ROWS: tuple[dict[str, object], ...] = (
    {
        "sku": "ALS1288",
        "name": "Профиль торцевой",
        "color": "серебро",
        "input_length_m": 1.8,
        "input_quantity": 300,
        "output_length_m": 1.8,
        "output_quantity": 300,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "П/ф",
    },
    {
        "sku": "ALS1288",
        "name": "Профиль торцевой",
        "color": "серебро",
        "input_length_m": 1.8,
        "input_quantity": 150,
        "output_length_m": 1.8,
        "output_quantity": 150,
        "operation": "сверло",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ALS1288",
        "name": "Профиль торцевой",
        "color": "серебро",
        "input_length_m": 1.8,
        "input_quantity": 500,
        "output_length_m": 1.8,
        "output_quantity": 500,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "П/ф",
    },
    {
        "sku": "ALS1288",
        "name": "Профиль торцевой",
        "color": "серебро",
        "input_length_m": 1.8,
        "input_quantity": 220,
        "output_length_m": 0.9,
        "output_quantity": 440,
        "operation": "сверло",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "АТ-6323",
        "name": "Профиль для стеновой панели соединительный",
        "color": "черный",
        "input_length_m": 1.8,
        "input_quantity": 200,
        "output_length_m": 1.8,
        "output_quantity": 200,
        "operation": "сверло",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "АТ-6323",
        "name": "Профиль для стеновой панели соединительный",
        "color": "черный",
        "input_length_m": 1.8,
        "input_quantity": 700,
        "output_length_m": 0.9,
        "output_quantity": 1400,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "П/ф",
    },
    {
        "sku": "АТ-6323",
        "name": "Профиль для стеновой панели соединительный",
        "color": "черный",
        "input_length_m": 1.8,
        "input_quantity": 260,
        "output_length_m": 1.35,
        "output_quantity": 350,
        "operation": "сверло",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "АТ-6323",
        "name": "Профиль для стеновой панели соединительный",
        "color": "черный",
        "input_length_m": 1.8,
        "input_quantity": 120,
        "output_length_m": 1.8,
        "output_quantity": 120,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-2081",
        "name": "Универсальный стык",
        "color": "золото",
        "input_length_m": 1.35,
        "input_quantity": 400,
        "output_length_m": 1.35,
        "output_quantity": 400,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-2081",
        "name": "Универсальный стык",
        "color": "золото",
        "input_length_m": 1.35,
        "input_quantity": 220,
        "output_length_m": 0.9,
        "output_quantity": 330,
        "operation": "сверло",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
)

_PREP_PRESS_ROWS: tuple[dict[str, object], ...] = (
    {
        "sku": "АТ-6324",
        "name": "Профиль для стеновой панели торцевой",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 240,
        "output_length_m": 2.7,
        "output_quantity": 240,
        "operation": "окно",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "П/ф",
    },
    {
        "sku": "АТ-6324",
        "name": "Профиль для стеновой панели торцевой",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 180,
        "output_length_m": 2.7,
        "output_quantity": 180,
        "operation": "гребенка",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "АТ-6324",
        "name": "Профиль для стеновой панели торцевой",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 600,
        "output_length_m": 1.8,
        "output_quantity": 900,
        "operation": "окно",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "П/ф",
    },
    {
        "sku": "АТ-6324",
        "name": "Профиль для стеновой панели торцевой",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 350,
        "output_length_m": 1.35,
        "output_quantity": 700,
        "operation": "гребенка",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "АТ-6324",
        "name": "Профиль для стеновой панели торцевой",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 280,
        "output_length_m": 2.7,
        "output_quantity": 280,
        "operation": "окно",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-2972",
        "name": "Круглая труба 16мм",
        "color": "черный",
        "input_length_m": 3.0,
        "input_quantity": 900,
        "output_length_m": 2.7,
        "output_quantity": 1000,
        "operation": "гребенка",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-2972",
        "name": "Круглая труба 16мм",
        "color": "черный",
        "input_length_m": 3.0,
        "input_quantity": 450,
        "output_length_m": 3.0,
        "output_quantity": 450,
        "operation": "окно",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-2972",
        "name": "Круглая труба 16мм",
        "color": "черный",
        "input_length_m": 3.0,
        "input_quantity": 160,
        "output_length_m": 0.9,
        "output_quantity": 530,
        "operation": "гребенка",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-2972",
        "name": "Круглая труба 16мм",
        "color": "черный",
        "input_length_m": 3.0,
        "input_quantity": 300,
        "output_length_m": 1.8,
        "output_quantity": 500,
        "operation": "окно",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-2972",
        "name": "Круглая труба 16мм",
        "color": "черный",
        "input_length_m": 3.0,
        "input_quantity": 520,
        "output_length_m": 3.0,
        "output_quantity": 520,
        "operation": "гребенка",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
)

_PREP_SHOT_ROWS: tuple[dict[str, object], ...] = (
    {
        "sku": "ALS1290",
        "name": "Профиль угловой",
        "color": "золото",
        "input_length_m": 0.9,
        "input_quantity": 260,
        "output_length_m": 0.9,
        "output_quantity": 260,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ALS1290",
        "name": "Профиль угловой",
        "color": "золото",
        "input_length_m": 0.9,
        "input_quantity": 190,
        "output_length_m": 0.9,
        "output_quantity": 190,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "П/ф",
    },
    {
        "sku": "ALS1290",
        "name": "Профиль угловой",
        "color": "золото",
        "input_length_m": 0.9,
        "input_quantity": 520,
        "output_length_m": 0.9,
        "output_quantity": 520,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ALS1290",
        "name": "Профиль угловой",
        "color": "золото",
        "input_length_m": 0.9,
        "input_quantity": 310,
        "output_length_m": 0.9,
        "output_quantity": 310,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "П/ф",
    },
    {
        "sku": "ALS1290",
        "name": "Профиль угловой",
        "color": "золото",
        "input_length_m": 0.9,
        "input_quantity": 140,
        "output_length_m": 0.9,
        "output_quantity": 140,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-3077",
        "name": "ЮП-3077",
        "color": "шампань",
        "input_length_m": 2.7,
        "input_quantity": 420,
        "output_length_m": 2.7,
        "output_quantity": 420,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-3077",
        "name": "ЮП-3077",
        "color": "шампань",
        "input_length_m": 2.7,
        "input_quantity": 880,
        "output_length_m": 2.7,
        "output_quantity": 880,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-3077",
        "name": "ЮП-3077",
        "color": "шампань",
        "input_length_m": 2.7,
        "input_quantity": 150,
        "output_length_m": 1.35,
        "output_quantity": 300,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-3077",
        "name": "ЮП-3077",
        "color": "шампань",
        "input_length_m": 2.7,
        "input_quantity": 230,
        "output_length_m": 0.9,
        "output_quantity": 690,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-3077",
        "name": "ЮП-3077",
        "color": "шампань",
        "input_length_m": 2.7,
        "input_quantity": 640,
        "output_length_m": 2.7,
        "output_quantity": 640,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "П/ф",
    },
)

# Перемешивание тройками — часть контракта: ровно так позиции блока разойдутся
# по трём участкам подготовки при круговом разборе.
PREP_PLAN_ROWS: tuple[dict[str, object], ...] = tuple(
    row
    for triple in zip(_PREP_DRILL_ROWS, _PREP_PRESS_ROWS, _PREP_SHOT_ROWS, strict=True)
    for row in triple
)


# Пары анодирования: один и тот же реальный артикул двумя строками, чтобы на
# печатном листе участка они сошлись в одну строку с разбивкой упаковки
# («Спанбонд 300 · Стрейч 200»). Длина пары — нормальная (готовая) длина
# артикула из каталога (``raw_length_mm IS NULL``), раскроя у пары нет: обе
# строки одного размера. Строки пары совпадают артикулом, цветом,
# длиной и первичной операцией, а различаются видом выпуска: «П/ф» → спанбонд,
# «ГП» → стрейч. Упаковочная операция выводится именно из вида выпуска —
# правило ``pack_types`` (``selection_rules.py``, ``lookup_field=output_kind``:
# «ГП» → ``PACK_STRETCH``, «П/ф» → ``PACK_SPUNBOND``); колонку «Упаковка» здесь
# никто не читает, поэтому в ней стоит реальный текст настоящего плана для этого
# же вида выпуска. Вид выпуска задаёт и маршрут: «ГП» заходит на пилу/упаковку,
# «П/ф» — нет, но анодирование есть в обоих.
_ANOD_SPUNBOND_ROWS: tuple[dict[str, object], ...] = (
    {
        "sku": "ЮП-2256",
        "name": "РП-АКП-18-10",
        "color": "золото",
        "input_length_m": 2.7,
        "input_quantity": 300,
        "output_length_m": 2.7,
        "output_quantity": 300,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-2974",
        "name": "РП-АКП-10-12,5мм",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 500,
        "output_length_m": 2.7,
        "output_quantity": 500,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-2976",
        "name": "Потайной профиль 8мм",
        "color": "медь",
        "input_length_m": 2.5,
        "input_quantity": 150,
        "output_length_m": 2.5,
        "output_quantity": 150,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
)

_ANOD_STRETCH_ROWS: tuple[dict[str, object], ...] = (
    {
        "sku": "ЮП-2256",
        "name": "РП-АКП-18-10",
        "color": "золото",
        "input_length_m": 2.7,
        "input_quantity": 200,
        "output_length_m": 2.7,
        "output_quantity": 200,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-2974",
        "name": "РП-АКП-10-12,5мм",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 350,
        "output_length_m": 2.7,
        "output_quantity": 350,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-2976",
        "name": "Потайной профиль 8мм",
        "color": "медь",
        "input_length_m": 2.5,
        "input_quantity": 260,
        "output_length_m": 2.5,
        "output_quantity": 260,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
)

# Строки пары идут подряд (спанбонд, стрейч) — так их и читает человек в фикстуре.
ANOD_PAIR_ROWS: tuple[dict[str, object], ...] = tuple(
    row
    for pair in zip(_ANOD_SPUNBOND_ROWS, _ANOD_STRETCH_ROWS, strict=True)
    for row in pair
)

# Парные артикулы: две пары из реального справочника пар. После снятия склейки
# (#312) пара — не одна позиция ``A+B``, а две самостоятельные позиции, по
# одной строке листа на компонент: утверждаются, выпускаются и идут по
# маршруту раздельно. Норма «количество на подвес» берётся у пары, поэтому
# печатный лист участка сводит обе позиции в один подвес («24×ЮП-2695 +
# 24×ЮП-2878»), хотя работают они раздельно.
#
# Норму пары берёт только позиция, которая пришла в паре: строка второго
# компонента на ту же нормальную длину соседним номером строки листа
# (``plan_import_service._pair_partner_row_is_adjacent``). Пара — не свойство
# артикула, а факт плана: одинокая строка артикула пары (базовая ``ЮП-2616``
# на 300 шт в ``PACKING_PLAN_ROWS`` — её партнёра в демо нет) считается
# обычной позицией по собственной норме артикула.
#
# Пары и ручные нормы — из миграции 058 (``product_pairs.quantity_per_hanger``):
# ЮП-2604↔ЮП-2616 с N 30 и ЮП-2695↔ЮП-2878 с N 24. Нормы в справочнике жили
# на сырьевой длине 2750 мм; демо планирует те же артикулы на их общей
# нормальной длине 2,7 м, поэтому демо-норма пишется на тот же ключ, что и
# длина строки (ADR-0028: пара нормируется одной общей длиной).
#
# Количества строк кратны N — иначе импорт округлил бы их вниз и фикстура
# разошлась бы с планом. От строк базового блока те же артикулы отличаются
# количеством: одинаковые строки импорт склеил бы по fingerprint в одну
# позицию.
#
# Количества обеих сторон пары РАВНЫ (#67: пара — единая загрузка
# ``N×A + N×B``): подвес заполняется парой целиком, поэтому 210/180 — это
# план, в котором одна сторона пары заведомо не влезает в свои подвесы.
PAIR_ARTICLE_ROWS: tuple[dict[str, object], ...] = (
    {
        "sku": "ЮП-2604",
        # Настоящего файла каталога в репозитории нет, и имя ЮП-2604
        # демо берёт у партнёра по паре — ровно так же этот артикул назван в
        # e2e пары 2604/2616 (frontend/e2e/pair-article-cycle.spec.ts).
        "name": "Кант универсальный 47мм 2,7 анод черный мат",
        "color": "черный",
        "input_length_m": 2.7,
        "input_quantity": 210,
        "output_length_m": 2.7,
        "output_quantity": 210,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-2616",
        "name": "Кант универсальный 47мм 2,7 анод черный мат",
        "color": "черный",
        "input_length_m": 2.7,
        "input_quantity": 210,
        "output_length_m": 2.7,
        "output_quantity": 210,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
    },
    {
        "sku": "ЮП-2878",
        "name": "Угол со скрытым креплением 40*22 2,7 анод.черный матовый",
        "color": "черный",
        "input_length_m": 2.7,
        "input_quantity": 240,
        "output_length_m": 0.9,
        "output_quantity": 240,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
    {
        "sku": "ЮП-2695",
        "name": "Накладка угла со скрытым креплением 40х22 ЮП-2695 2,75 под анод",
        "color": "черный",
        "input_length_m": 2.7,
        "input_quantity": 240,
        "output_length_m": 0.9,
        "output_quantity": 240,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
    },
)

#: Ручные нормы подвеса демо-пар: (артикул A, артикул B, длина строки, N).
#: Ключ ``N`` — длина в метрах, она же длина строки пары в листе.
PAIR_NORMS: tuple[tuple[str, str, float, int], ...] = (
    ("ЮП-2604", "ЮП-2616", 2.7, 30),
    ("ЮП-2695", "ЮП-2878", 2.7, 24),
)

# Строки, оставленные в незакрытых состояниях: план цеха должен показывать не
# только «всё в работе», но и работу, до которой ещё не дошли — неутверждённые
# позиции и утверждённые без релиза. Артикулы намеренно повторяют строки
# базового блока: в живом плане один профиль планируется несколькими строками,
# и повтор артикула на доске — обычное дело. От базовой строки новая отличается
# количеством, иначе импорт склеил бы их по fingerprint.
#
# Неутверждённых строк заметно больше, чем утверждённых без релиза, и это не
# прихоть фикстуры: рабочий список планировщика на экране «План» — это позиции
# в статусе ``draft``/``invalid``/``valid`` (``/production-plans/all-positions``),
# всё остальное оттуда скрыто. С двумя-тремя такими строками экран выглядит
# сломанным — план есть, а показывать нечего.
#
# ``lifecycle`` читает сидер (см. ``LIFECYCLE_*``) и в лист не попадает.
PENDING_PLAN_ROWS: tuple[dict[str, object], ...] = (
    {
        "sku": "ЮП-460",
        "name": "РП-АКП-03 2,7 м анод.медь матов",
        "color": "медь",
        "input_length_m": 2.7,
        "input_quantity": 200,
        "output_length_m": 2.7,
        "output_quantity": 200,
        "operation": "окно",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
        "lifecycle": LIFECYCLE_DRAFT,
    },
    {
        "sku": "АТ-7314",
        "name": "РП-АКП-03-12,5 2,7 м анод.шампань, матов",
        "color": "шампань",
        "input_length_m": 2.7,
        "input_quantity": 450,
        "output_length_m": 2.7,
        "output_quantity": 450,
        "operation": "окно",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
        "lifecycle": LIFECYCLE_DRAFT,
    },
    {
        "sku": "АТ-4863",
        "name": "РП-АКП-01 2,7 м анод.шампань, матов",
        "color": "шампань",
        "input_length_m": 2.7,
        "input_quantity": 260,
        "output_length_m": 2.7,
        "output_quantity": 260,
        "operation": "окно",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
        "lifecycle": LIFECYCLE_DRAFT,
    },
    {
        "sku": "АТ-4892",
        "name": "РП-АКП-09 2,7 м анод.серебро, матов",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 620,
        "output_length_m": 2.7,
        "output_quantity": 620,
        "operation": "окно",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
        "lifecycle": LIFECYCLE_DRAFT,
    },
    {
        "sku": "ЮП-3168",
        "name": "Стык 33 мм на клеевой основе 2,7 анод.титан матовый",
        "color": "титан",
        "input_length_m": 2.7,
        "input_quantity": 80,
        "output_length_m": 0.9,
        "output_quantity": 240,
        "operation": "",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
        "lifecycle": LIFECYCLE_DRAFT,
    },
    {
        "sku": "АТ-7121",
        "name": "Стык с дюбелем 30 мм 2,7   анод. серебро матовы",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 240,
        "output_length_m": 0.9,
        "output_quantity": 480,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "ГП",
        "lifecycle": LIFECYCLE_DRAFT,
    },
    {
        "sku": "ЮП-3485",
        "name": "РП-АКП-11 2,7 м анод.золото Матов",
        "color": "золото",
        "input_length_m": 2.7,
        "input_quantity": 330,
        "output_length_m": 2.7,
        "output_quantity": 330,
        "operation": "окно",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
        "lifecycle": LIFECYCLE_APPROVED,
    },
    {
        "sku": "ЮП-2083",
        "name": "Стык 38 мм. 2,7   анод.серебро, матовый",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 260,
        "output_length_m": 2.7,
        "output_quantity": 260,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
        "lifecycle": LIFECYCLE_APPROVED,
    },
    # Парная строка в неутверждённых: те же два артикула первой пары, вторая
    # партия. Так видно, что норма подвеса у пары одна и на экране планировщика
    # тоже: обе строки несут N этой пары, хотя пара в ``PAIR_NORMS`` заведена
    # один раз. Количества кратны N и равны между собой (#67: пара — единая
    # загрузка ``N×A + N×B``); от выпущенной партии отличаются, иначе импорт
    # склеил бы строки по fingerprint.
    {
        "sku": "ЮП-2604",
        "name": "Кант универсальный 47мм 2,7 анод черный мат",
        "color": "черный",
        "input_length_m": 2.7,
        "input_quantity": 270,
        "output_length_m": 2.7,
        "output_quantity": 270,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
        "lifecycle": LIFECYCLE_DRAFT,
    },
    {
        "sku": "ЮП-2616",
        "name": "Кант универсальный 47мм 2,7 анод черный мат",
        "color": "черный",
        "input_length_m": 2.7,
        "input_quantity": 270,
        "output_length_m": 2.7,
        "output_quantity": 270,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
        "lifecycle": LIFECYCLE_DRAFT,
    },
    # Распил одного входа на две длины: строки 35–36 июньского плана. По
    # ADR-0003 группа строк — это ОДНА позиция плана: вход объединён на всю
    # группу, выходы идут построчно. Здесь вход один — 100 шт по 2,7 м, —
    # а выходов два: 0,9 м и 1,8 м. Баланс материала сходится ровно:
    # 100 × 2,7 = 270 м, из них 0,9 × 100 = 90 м и 1,8 × 100 = 180 м.
    # На пиле у такой позиции одно задание на вход, дальше по маршруту оно
    # раздваивается по двум длинам — отдельных позиций здесь не создаётся.
    # Это не пара: `product_pairs` артикула ЮП-2627 не касается.
    {
        "sku": "ЮП-2627",
        "name": "Угол 21*21  2,7   анод. серебро мат",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 100,
        "output_length_m": 0.9,
        "output_quantity": 100,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
        "lifecycle": LIFECYCLE_DRAFT,
    },
    {
        "sku": "ЮП-2627",
        "name": "Угол 21*21  2,7   анод. серебро мат",
        "color": "серебро",
        "input_length_m": 2.7,
        "input_quantity": 100,
        # Продолжение группы: своего входного количества у строки в файле нет,
        # вход объединён на группу (ADR-0003, #279).
        "input_continuation": True,
        "output_length_m": 1.8,
        "output_quantity": 100,
        "operation": "сверло",
        "packing": "поф, красная этикетка РП 23*150 на каждый профиль и белая этикетка 58*",
        "kind": "ГП",
        "lifecycle": LIFECYCLE_DRAFT,
    },
)

# Непарный вариант той же пары: строки 10 и 11 «Плана март 26 03» реального
# файла заказчика (``excel/01-09.2026_01_Упаковочная карта (план РП).xlsx.xls``),
# реализованные без пары. В файле это одна пара: первая строка (ЮП-2616) несёт
# наименование, вторая (ЮП-2604) приходит с пустой ячейкой — строки объединены
# общим наименованием, и по нему пару и опознают. Здесь те же две строки едут
# самостоятельными артикулами, у каждой своё наименование: «Кант универсальный
# 26мм» — так ЮП-2616 назван в файле, когда планируется сам по себе (строки
# 119–125, «составная часть для ЮП 3098/3158»), «Кант универсальный 29мм» —
# карточка каталога ЮП-2604 (в самом файле этот артикул наименования не получает
# вовсе: он там всегда вторая строка пары).
#
# Непарность — не только в наименовании, и длина тут ни при чём: обе строки идут
# на той же 2,7 м, что и пара. Считаются они своей нормой, а не парной, через
# ключ ``own_norm``: сидер ставит её ручным override позиции — тем же полем
# ``source_payload.quantity_per_hanger``, которое пишет экран «План» в поле
# «Кол-во на подвес», и той же рукой, что UI (пока позиция черновик, до релиза).
# Норма «количество на подвес» у артикула пары иначе берётся из ``product_pairs``
# (на подвесе едут оба компонента, #312), и на 2,7 м любая строка ЮП-2604
# считалась бы парой — override резолвер ставит выше пары
# (``plan_position_hanger``: позиция с положительным override считается
# одиночной), поэтому строка считает сама по себе.
#
# ``own_norm`` — та норма, с которой строка поехала бы без пары: 60 у ЮП-2604 и
# 62 у ЮП-2616. Числа не выдуманы — это авто-расчёт артикула на этой длине по
# геометрии карточки заказчика (79,3 × 26,05 и 67,2 × 26,15 мм). В чистой БД демо
# заводит артикулы само и геометрии у них нет, поэтому фикстура задаёт норму явно
# — как её задал бы планировщик в поле «Кол-во на подвес». Количества кратны 30
# (парной норме, по которой считает импорт: строки идут соседями и до override он
# видит их парой): 240 — это 4 подвеса по норме 60 у ЮП-2604 и 4 подвеса по норме
# 62 у ЮП-2616 (240 на 62 не делится — импорт и печать считают подвесы вверх).
#
# Строки выпущены (в отличие от парных строк второй партии в ``PENDING_PLAN_ROWS``
# с общим наименованием): задание непарной строки тоже непарное — своя норма,
# свой счёт подвесов, и на печати участка такая строка стоит отдельно, а не
# внутри группы пары.
#
# Количества не совпадают ни с одной другой строкой этих артикулов: fingerprint
# (SKU, количество, цвет, длины, операция, упаковка, вид выпуска) наименование не
# включает, и строка с тем же количеством была бы отброшена импортом как
# дубликат, а не добавлена второй позицией.
UNPAIRED_PAIR_ROWS: tuple[dict[str, object], ...] = (
    {
        "sku": "ЮП-2604",
        "name": "Кант универсальный 29мм",
        "color": "черный",
        "input_length_m": 2.7,
        "input_quantity": 240,
        "output_length_m": 2.7,
        "output_quantity": 240,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
        "own_norm": 60,
        "lifecycle": LIFECYCLE_RELEASED,
    },
    {
        "sku": "ЮП-2616",
        "name": "Кант универсальный 26мм",
        "color": "черный",
        "input_length_m": 2.7,
        "input_quantity": 240,
        "output_length_m": 2.7,
        "output_quantity": 240,
        "operation": "",
        "packing": "смотка спанбондом поштучно в пачке 10 штук",
        "kind": "П/ф",
        "own_norm": 62,
        "lifecycle": LIFECYCLE_RELEASED,
    },
)

# Полный вход демо-импорта первого плана: базовый «Упаковочный план» + строки
# подготовки + пары анодирования + парные артикулы + незакрытые строки +
# непарный вариант пары.
DEMO_PLAN_ROWS: tuple[dict[str, object], ...] = (
    PACKING_PLAN_ROWS
    + PREP_PLAN_ROWS
    + ANOD_PAIR_ROWS
    + PAIR_ARTICLE_ROWS
    + PENDING_PLAN_ROWS
    + UNPAIRED_PAIR_ROWS
)

# Второй набор плана — лист «Плана подготовительного участка» (#313). Шаблон
# короче: у него одна длина и одно количество (без входа и раскроя), зато
# своя колонка операций, из которой правила профиля собирают три варианта
# маршрута: сверловка, пресс (окно/гребенка) и чистый дробеструй.
_PREP_STAGE_HEADERS = [
    "Артикул",
    "Наименование",
    "Цвет",
    "Операция",
    "Длина, м",
    "Кол-во, шт",
    "Примечание",
]

# Шесть строк — по две на каждый вариант маршрута подготовительного профиля.
# Артикулы и длины те же, что у строк блока подготовки первого плана: в цехе
# это те же профисы, просто план ведётся другим листом и до отгрузки не идёт.
PREP_STAGE_PLAN_ROWS: tuple[dict[str, object], ...] = (
    {
        "sku": "ALS1288",
        "name": "Профиль торцевой",
        "color": "серебро",
        "operation": "сверло",
        "length_m": 1.8,
        "quantity": 300,
        "lifecycle": LIFECYCLE_RELEASED,
    },
    {
        "sku": "ЮП-2081",
        "name": "Универсальный стык",
        "color": "золото",
        "operation": "сверло",
        "length_m": 1.35,
        "quantity": 220,
        "lifecycle": LIFECYCLE_RELEASED,
    },
    {
        "sku": "АТ-6324",
        "name": "Профиль для стеновой панели торцевой",
        "color": "серебро",
        "operation": "окно",
        "length_m": 2.7,
        "quantity": 240,
        "lifecycle": LIFECYCLE_RELEASED,
    },
    {
        "sku": "ЮП-2972",
        "name": "Круглая труба 16мм",
        "color": "черный",
        "operation": "гребенка",
        "length_m": 3.0,
        "quantity": 450,
        "lifecycle": LIFECYCLE_RELEASED,
    },
    {
        # Пустая операция — вариант «только дробеструй»: маршрут без сверловки
        # и без пресса. Позиция остаётся неутверждённой, как свежий импорт.
        "sku": "ALS1290",
        "name": "Профиль угловой",
        "color": "золото",
        "operation": "",
        "length_m": 0.9,
        "quantity": 260,
        "lifecycle": LIFECYCLE_DRAFT,
    },
    {
        # Утверждён без релиза: позиция есть, задания ещё не создавались.
        "sku": "ЮП-3077",
        "name": "ЮП-3077",
        "color": "шампань",
        "operation": "",
        "length_m": 2.7,
        "quantity": 420,
        "lifecycle": LIFECYCLE_APPROVED,
    },
)

# Группы прогона: строки одной группы делят круг участков и попадают в дневные
# планы одних и тех же участков. Разбор строки в группу идёт по её содержимому,
# а не по артикулу: артикул намеренно повторяется между блоками (пары
# анодирования против базовых строк, незакрытые строки против тех же базовых
# артикулов, непарный вариант пары против парного), и разбор по SKU отправлял бы
# их в чужую группу.
_ROW_GROUPS: tuple[tuple[str, tuple[dict[str, object], ...]], ...] = (
    ("prep", PREP_PLAN_ROWS),
    ("anod", ANOD_PAIR_ROWS),
    ("pair", PAIR_ARTICLE_ROWS),
    ("unpaired", UNPAIRED_PAIR_ROWS),
    ("pending", PENDING_PLAN_ROWS),
    ("run", PACKING_PLAN_ROWS),
)

#: Круг участков каждой группы прогона. Парные артикулы идут по кругу нижних
#: участков, а незакрытые строки никуда не едут: у них нет заданий, и круг для
#: них не спрашивается.
_GROUP_TARGET_SECTIONS: dict[str, tuple[str, ...]] = {
    "run": DEMO_RUN_SECTION_CODES,
    "prep": DEMO_PREP_SECTION_CODES,
    "anod": DEMO_ANOD_SECTION_CODES,
    "pair": DEMO_RUN_SECTION_CODES,
    "unpaired": DEMO_RUN_SECTION_CODES,
    "pending": DEMO_RUN_SECTION_CODES,
    "prep_stage": DEMO_PREP_SECTION_CODES,
}

#: Какие группы планируются в дневные планы участка. Пила и упаковка берут и
#: базовые строки, и парные артикулы; анодирование — ещё и пары анодирования
#: (они существуют ради слияния на печати). Участки подготовки берут блок
#: подготовки первого плана и второй план целиком. Непарный вариант пары в
#: списках есть для полноты: его строки неутверждённые, заданий у них нет, и в
#: дневные планы они не попадают.
_SECTION_GROUPS: dict[str, tuple[str, ...]] = {
    "SAWING": ("run", "pair", "unpaired"),
    "PACKING": ("run", "pair", "unpaired"),
    "ANODIZING": ("run", "anod", "pair", "unpaired"),
    "DRILLING": ("prep", "prep_stage"),
    "PRESSING": ("prep", "prep_stage"),
    "SHOT_BLAST": ("prep", "prep_stage"),
}


def _row_group(row: Mapping[str, object]) -> str:
    """Группа прогона строки листа по блоку фикстуры, которому она принадлежит."""
    for name, block in _ROW_GROUPS:
        if row in block:
            return name
    raise RuntimeError(
        f"Строка демо-плана вне блоков фикстуры: {dict(row)!r}. Добавь её в один из "
        f"{[name for name, _ in _ROW_GROUPS]} — иначе позиция не попадёт ни в одну группу."
    )


def _lifecycle_of(row: Mapping[str, object]) -> str:
    """Состояние, в котором сид оставляет позицию строки. По умолчанию — релиз."""
    value = str(row.get("lifecycle") or LIFECYCLE_RELEASED)
    if value not in LIFECYCLES:
        raise RuntimeError(f"Неизвестное состояние строки {row.get('sku')!r}: {value!r}")
    return value


def _plan_workbook(rows: Iterable[Mapping[str, object]]) -> bytes:
    """Собрать «Упаковочный план» в памяти — тот же вход, что у xlsx-импорта."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "totalplan"
    for _ in range(3):
        ws.append([])
    ws.append(list(_PLAN_HEADERS))
    for row in rows:
        # Строка-продолжение группы (ADR-0003): входного количества в файле у
        # неё нет — вход объединён на всю группу, а сама строка несёт ещё один
        # выход. Импорт по этому признаку собирает группу в ОДНУ позицию с
        # несколькими выходами; с собственным количеством в каждой строке он
        # сделал бы из распила две самостоятельные операции.
        is_continuation = bool(row.get("input_continuation"))
        ws.append(
            [
                row["sku"],
                "ТЗ",
                row["name"],
                0,
                row["color"],
                "" if is_continuation else row["input_quantity"],
                row["input_length_m"],
                row["operation"],
                row["packing"],
                "",
                row["output_length_m"],
                row["output_quantity"],
                row["output_quantity"],
                0,
                row["kind"],
                "",
            ]
        )
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def _prep_stage_workbook(rows: Iterable[Mapping[str, object]]) -> bytes:
    """Собрать «План подготовительного участка» в памяти — тот же вход, что и у
    живого xlsx-импорта этого шаблона: три пустые строки, затем шапка из семи
    колонок. Длина обязательна — без неё позиция остаётся без габаритов."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "prepplan"
    for _ in range(3):
        ws.append([])
    ws.append(list(_PREP_STAGE_HEADERS))
    for row in rows:
        ws.append(
            [
                row["sku"],
                row["name"],
                row["color"],
                row["operation"],
                row["length_m"],
                row["quantity"],
                f"{DEMO_PLAN_MARKER}: {row.get('note', '')}".strip(),
            ]
        )
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


async def _ensure_length(db: AsyncSession, product: Product, length_mm: float, *, primary: bool) -> bool:
    """Добавить длину в канон продукта; ``primary`` переносит нормативную отметку
    на неё (в БД она одна на продукт), поэтому старая снимается."""
    target = await db.scalar(
        select(ProductLength).where(
            ProductLength.product_id == product.id, ProductLength.length_mm == length_mm
        )
    )
    if target is None:
        target = ProductLength(
            product_id=product.id,
            length_mm=length_mm,
            raw_length_mm=length_mm if primary else None,
            is_primary=False,
        )
        db.add(target)
        await db.flush()
        created = True
    else:
        created = False
    if not primary:
        return created
    current = await db.scalar(
        select(ProductLength).where(
            ProductLength.product_id == product.id, ProductLength.is_primary.is_(True)
        )
    )
    if current is not None and current.id != target.id:
        current.is_primary = False
        # Частичный уникальный индекс проверяется на каждую строку сразу, поэтому
        # снятие отметки должно уйти в БД до её установки на целевой длине.
        await db.flush()
    target.is_primary = True
    target.raw_length_mm = length_mm
    await db.flush()
    return created


async def _upsert_product(db: AsyncSession, row: Mapping[str, object]) -> tuple[Product, bool]:
    """Заводит артикул строки в каталоге. ``True`` — артикул создан заново."""
    sku = str(row["sku"])
    product = await db.scalar(select(Product).where(Product.sku == sku))
    if product is not None:
        # Артикул уже есть в каталоге (в т.ч. выведенный из оборота) —
        # импорт отбрасывает неактивные позиции, поэтому реактивируем.
        product.is_active = True
        product.is_catalog_item = True
        return product, False
    product = Product(
        sku=sku,
        name=str(row["name"]),
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
        is_catalog_item=True,
        alloy="6063",
        color=str(row["color"]),
    )
    db.add(product)
    await db.flush()
    return product, True


async def _ensure_products(db: AsyncSession, rows: Iterable[Mapping[str, object]]) -> dict[str, int]:
    """Upsert артикулов плана вместе с их каноном длин (вход + выход раскроя)."""
    stats = {"products": 0, "lengths": 0}
    for row in rows:
        product, created = await _upsert_product(db, row)
        stats["products"] += int(created)
        for value, primary in ((row["input_length_m"], True), (row["output_length_m"], False)):
            if await _ensure_length(db, product, round(float(value) * 1000), primary=primary):
                stats["lengths"] += 1
    return stats


async def _ensure_prep_stage_products(
    db: AsyncSession, rows: Iterable[Mapping[str, object]]
) -> dict[str, int]:
    """Upsert артикулов подготовительного плана: у них одна длина, а не вход и
    выход, поэтому канон длин трогается один раз на строку."""
    stats = {"products": 0, "lengths": 0}
    for row in rows:
        product, created = await _upsert_product(db, row)
        stats["products"] += int(created)
        if await _ensure_length(db, product, round(float(row["length_m"]) * 1000), primary=True):
            stats["lengths"] += 1
    return stats


async def _ensure_product_pairs(db: AsyncSession) -> tuple[int, int]:
    """Завести демо-пары в ``product_pairs`` с ручной нормой на общей длине.

    Пара в справочнике пар — то, из-за чего позиции пары перестают быть
    независимыми: норма «количество на подвес» берётся у пары, и обе позиции
    печатаются одним подвесом. Заводить пару нужно до импорта — иначе строки
    пары импортируются как обычные одиночные артикулы и норма не доедет.

    Артикулы и их нормальная длина заводятся здесь же, а не только строкой
    плана: пара в справочнике неполна без обеих сторон, а срез фикстуры
    (тесты) может вообще не содержать строк пары.

    Если пара уже есть (импорт каталога), демо дописывает свою норму в неё, а
    не плодит вторую: ``product_pairs`` запрещает две записи на одну пару, а
    резолвер берёт первую по порядку строк. Норма пишется на ключе длины
    строки пары (``_length_key``), а не на сырьевой 2750 мм из миграции 058:
    пара нормируется той длиной, на которой план совпадает с нормальными
    длинами обоих артикулов (ADR-0028).
    """
    rows_by_sku = {str(row["sku"]): row for row in PAIR_ARTICLE_ROWS}
    pairs = products = 0
    for sku_a, sku_b, length_m, per_hanger in PAIR_NORMS:
        pair_products: list[Product] = []
        for sku in (sku_a, sku_b):
            row = rows_by_sku.get(sku)
            if row is None:
                raise RuntimeError(
                    f"Артикул {sku} есть в PAIR_NORMS, но нет в PAIR_ARTICLE_ROWS"
                )
            product, created = await _upsert_product(db, row)
            products += int(created)
            await _ensure_length(
                db, product, round(float(row["input_length_m"]) * 1000), primary=True
            )
            pair_products.append(product)
        # Канонический порядок пары — product_a_id < product_b_id (ADR-0023).
        first, second = sorted(pair_products, key=lambda product: product.id)
        pair = await db.scalar(
            select(ProductPair).where(
                ProductPair.product_a_id == first.id,
                ProductPair.product_b_id == second.id,
            )
        )
        if pair is None:
            pair = ProductPair(product_a_id=first.id, product_b_id=second.id, quantity_per_hanger={})
            db.add(pair)
            await db.flush()
            pairs += 1
        norms = dict(pair.quantity_per_hanger or {})
        norms[_length_key(round(length_m * 1000))] = {"auto": None, "manual": per_hanger}
        pair.quantity_per_hanger = norms
        await db.flush()
    return pairs, products


async def _import_pending_stock(
    db: AsyncSession,
    *,
    positions: Sequence[PlanPosition],
    section: Section,
    actor: User,
) -> dict[str, int]:
    """Заводит остатки на складе готовой продукции под незакрытые позиции.

    Позиция с нулевым остатком — мёртвая строка плана: взять её в работу нечем,
    и демо-стенд на таком плане обрывается на первом же клике оператора. Поэтому
    для всех позиций, оставленных в состояниях ``draft``/``approved``, сид
    импортирует остаток доменным путём остатков — тем же, что и форма «Импорт
    остатков», а не прямыми проводками: остаток должен попасть и в проводки, и в
    историю импортов остатков.

    Остаток ложится на свой артикул и свой габарит позиции: баланс ключуется
    ``product + section + dimensions`` (ADR-0001), и остаток другого размера
    выдаче не найдётся.
    """
    if not positions:
        return {"items": 0, "imported": 0}
    items: list[RemainderItem] = []
    for index, position in enumerate(positions, start=1):
        dimensions = position_dimensions_for_task(position)
        items.append(
            RemainderItem(
                source_row_number=index,
                sku=position.source_sku,
                quantity=float(position.quantity),
                comment=f"{DEMO_PLAN_MARKER}: остаток под незакрытую позицию #{position.id}",
                product_id=position.product_id,
                product_name=position.source_name,
                status="valid",
                errors=[],
                raw_values=[],
                dimensions=dimensions,
                dimensions_label=format_dimensions(dimensions),
            )
        )
    result = await apply_remainders_import(
        db,
        location_id=section.id,
        items=items,
        user=actor,
        skip_invalid=False,
        sheet_name=f"{DEMO_PLAN_MARKER}: остатки незакрытых позиций",
    )
    if not result.success:
        raise RuntimeError(
            f"Импорт остатков под незакрытые позиции не прошёл: {result.errors[:5]}"
        )
    return {"items": len(items), "imported": result.imported_count}


def _daily_plan_specs(tasks: list[WorkTask], today: date) -> list[tuple[date, list[int]]]:
    """Разложить задания участка по истории дневных планов.

    Пересечение невозможно: ``daily_plan_items`` держит UNIQUE по
    ``work_task_id``, то есть задание принадлежит ровно одному дневному плану.
    Поэтому каждый план требует своей порции разных заданий, а не повторов.

    Даты идут от прошлого к сегодняшнему, и задания раздаются в том же порядке:
    так старые планы получают уже отработавшие позиции (их проценты высокие), а
    свежие — выданные и ждущие. Несколько планов на одну дату дают в UI номера
    №1 и №2, как в реальном цехе.
    """
    ids = [task.id for task in tasks]
    if not ids:
        return []
    total_plans = sum(_PLANS_PER_DAY)
    base, remainder = divmod(len(ids), total_plans)
    specs: list[tuple[date, list[int]]] = []
    cursor = 0
    plan_slots = [offset for offset, per_day in enumerate(_PLANS_PER_DAY) for _ in range(per_day)]
    for index, offset in enumerate(plan_slots):
        # Остаток от деления раздаётся первым планам по общему счётчику: так
        # порции выравниваются. Задание меньше, чем планов, даёт порции нулевой
        # длины — такие слоты пропускаем, иначе на доске появятся пустые карточки.
        size = base + (1 if index < remainder else 0)
        chunk = ids[cursor : cursor + size]
        if chunk:
            specs.append((today - timedelta(days=len(_PLANS_PER_DAY) - 1 - offset), chunk))
        cursor += size
    return specs


def _progress_mode(index: int, total: int) -> str:
    """Раскладка позиций по бакетам прогресса (доли в ``_PROGRESS_BUCKETS``)."""
    ratio = index / total if total else 0.0
    edge = 0.0
    for name, share in _PROGRESS_BUCKETS:
        edge += share
        if ratio < edge:
            return name


def _whole_pieces(value: Decimal) -> Decimal:
    """Целые штуки из расчётной доли, округление по полу.

    Производство считает трубы и заготовки штуками, долей штуки не существует:
    дробь в ``complete``/``scrap`` уезжает в ledger, в остаток склада и в
    колонку «передать» (там она видна оператору как «619.2 шт»). По полу, а
    не по умолчанию: нельзя выпустить больше, чем реально выдано, иначе
    годные уедут за остаток выдачи.
    """
    return value.to_integral_value(rounding=ROUND_FLOOR)


async def _position_task_rows(
    db: AsyncSession, position_id: int
) -> list[tuple[WorkTask, SectionPlanLine, RouteStage, Section]]:
    """Все задания позиции по маршруту, в порядке стадий (только производственные)."""
    rows = (
        await db.execute(
            select(WorkTask, SectionPlanLine, RouteStage, Section)
            .join(SectionPlanLine, SectionPlanLine.id == WorkTask.section_plan_line_id)
            .join(RouteStage, RouteStage.id == WorkTask.route_stage_id)
            .join(Section, Section.id == WorkTask.section_id)
            .where(SectionPlanLine.plan_position_id == position_id, WorkTask.status != WorkTaskStatus.cancelled)
            .order_by(SectionPlanLine.sequence)
        )
    ).all()
    return [tuple(row) for row in rows]



async def _ensure_source_stock(
    db: AsyncSession, line: SectionPlanLine, task: WorkTask, actor_id: int, action_id: int
) -> bool:
    """Заложить сырьё на склад перед первой производственной стадией позиции.

    Склад ищется той же функцией, что и в выдаче, иначе остаток уедет на
    участок, а выдача упадёт «недостаточно сырья». Габарит обязан совпадать с
    габаритом задания: StockLedger ищет баланс по точному JSON-ключу.

    Признак «пройденные операции» (ADR-0055) — та же ось, только точная:
    демо-сырьё закладывается в ту же ops-группу, из которой его потом
    заберёт ``transfer_send`` с фейкового складского задания (write-off
    по признаку СПГ, а не «хоть с какой строки»). Признак берётся из
    маршрута складской строки до её этапа включительно — ровно то, что
    выведет ``record()`` для TRANSFER_SEND этого задания. Остаток читается
    по полному ключу баланса (габарит × признак операций × GOOD), иначе
    ``db.scalar`` поднял бы ``MultipleResultsFound`` на артикуле, у
    которого на участке лежит и сырьё, и подготовленное.
    """
    source = await _find_preceding_stock_line(
        db, plan_position_id=line.plan_position_id, before_sequence=line.sequence
    )
    if source is None:
        return False
    stock_line, stock_section = source
    dimensions = task.dimensions
    stock_stage = await db.get(RouteStage, stock_line.route_stage_id)
    stock_ops = (
        await completed_operations_through_stage(
            db,
            route_id=stock_line.route_id,
            through_sequence=stock_stage.sequence if stock_stage else 0,
        )
        if stock_stage is not None
        else None
    )
    balance = await db.scalar(
        select(func.coalesce(func.sum(StockBalance.balance_qty), 0)).where(
            StockBalance.product_id == task.product_id,
            StockBalance.location_id == stock_section.id,
            StockBalance.quality_state == QualityState.GOOD,
            dimensions_match_clause(StockBalance.dimensions, dimensions),
            completed_operations_match_clause(StockBalance.completed_operations, stock_ops),
        )
    )
    balance = Decimal(balance or 0)
    if balance >= task.planned_quantity:
        return False
    await StockCommandService().record(
        db,
        StockCommand(
            product_id=task.product_id,
            quantity=task.planned_quantity - balance,
            reason=Reason.MANUAL_IN,
            to_location_id=stock_section.id,
            quality_state=QualityState.GOOD,
            created_by=actor_id,
            comment="Демо-сырьё упаковочного плана",
            dimensions=dimensions,
            # Вне плана ``record()`` признак не выводит — задаём явно, иначе
            # демо-сырьё легло бы в NULL-группу и выдача его не нашла бы.
            completed_operations=stock_ops,
            action_id=action_id,
        ),
    )
    return True


def _target_section_for(
    index: int,
    target_order: list[int],
    route_section_ids: set[int],
) -> int | None:
    """Демо-участок, на котором останавливается прогон позиции.

    Позиции делятся между участками по кругу, но маршрут решает: спанбонд
    («П/ф») не заходит на пилу и упаковку, и назначать ему такой участок
    нельзя — иначе позиция осталась бы недоигранной. Берём первый участок
    круга, который есть в маршруте позиции. ``index`` — порядковый номер
    позиции, ``target_order`` — участки демо по кругу.
    """
    for offset in range(len(target_order)):
        candidate = target_order[(index + offset) % len(target_order)]
        if candidate in route_section_ids:
            return candidate
    return None


async def _run_route_progress(
    db: AsyncSession,
    positions: list[PlanPosition],
    target_order: list[int],
    actor_id: int,
    scrap_policy,
    start: datetime,
) -> dict[str, object]:
    """Прогнать позиции по маршруту до назначенного участка.

    Позиции делятся между участками своей группы (``target_order``): у каждого
    своя глубина прогона, так что задания есть и в работе, и в ожидании. Стадии
    до целевой проходятся целиком — иначе задания целевого участка остались бы
    ``waiting_previous`` и не попали бы в доску под фильтром «Активные».
    """
    stats: dict[str, object] = {"stages": 0, "completed": 0, "partial": 0, "issued": 0, "skipped": []}
    action = await action_journal_service.log(db, action_type="seed_demo_packing_plan")
    total = len(positions)
    for index, position in enumerate(positions):
        rows = await _position_task_rows(db, position.id)
        target_section_id = _target_section_for(index, target_order, {row[3].id for row in rows})
        if target_section_id is None:
            stats["skipped"].append(f"{position.source_sku}#pos{position.id}: нет демо-участка в маршруте")
            continue
        stop_index = next((i for i, row in enumerate(rows) if row[3].id == target_section_id), None)
        mode = _progress_mode(index, total)
        try:
            carry: Decimal | None = None
            for stage_index, (task, line, stage, _section) in enumerate(rows[: stop_index + 1]):
                performed_at = start + timedelta(minutes=index * 15 + stage_index * 3)
                accounted_at = performed_at + timedelta(minutes=1)
                key = f"{DEMO_PLAN_MARKER.lower()}:pos{position.id}:stage{stage.sequence}"
                # Объём выдачи берётся из факта предыдущей стадии: план по нормам
                # может требовать больше, чем реально прошло, и выдача «впрок»
                # упала бы на отрицательном остатке участка-источника.
                quantity = task.planned_quantity if carry is None else min(carry, task.planned_quantity)
                if stage_index == 0:
                    await _ensure_source_stock(db, line, task, actor_id, action.id)
                    await _ensure_task_issued_via_transfer(
                        db,
                        task=task,
                        line=line,
                        quantity=quantity,
                        prev_task=None,
                        actor_id=actor_id,
                        comment="Демо-выдача упаковочного плана",
                        source_ref=DEMO_PLAN_MARKER,
                        operation_key=key,
                        executor_user_id=actor_id,
                        performed_at=performed_at,
                        accounted_at=accounted_at,
                    )
                    stats["stages"] += 1
                # Для последующих стадий выдача уже выполнена в конце
                # предыдущей итерации — вместе с габаритом выхода. Повторный
                # вызов искал бы остаток по входному размеру и падал на
                # позициях с раскроем.
                if stage_index < stop_index:
                    # Промежуточные стадии проходятся без брака намеренно: брак
                    # уменьшает передачу, а статус ``completed`` требует
                    # transferred >= planned. С копеечным браком задание зависало
                    # в ``in_progress`` с полным визуалом «всё сделано» и плитка
                    # участка врала («в работе 38» при нулевой очереди). Возврат
                    # невыбранного в запас — отдельная доменная операция, а не
                    # побочка демо-прогона. Брак остаётся на упаковке, где он
                    # виден в колонках и означает «в работе».
                    good = quantity
                    await complete_task(
                        db,
                        task_id=task.id,
                        good_quantity=good,
                        defect_quantity=Decimal(0),
                        actor_id=actor_id,
                        defect_reason="demo_defect",
                        comment="Демо-выполнение упаковочного плана",
                        idempotency_key=f"{key}:complete",
                        executor_user_id=actor_id,
                        performed_at=performed_at,
                        accounted_at=accounted_at,
                        scrap_policy=scrap_policy,
                    )
                    if stage_index + 1 <= stop_index:
                        # Трансформирующая стадия (пила) с раскроем отдаёт дальше
                        # выходы, а не вход: габарит и количество берутся из
                        # ``outputs``, иначе бюджет передачи считается по
                        # несуществующему размеру и отправка отклоняется.
                        outgoing = (task.outputs or [{}])[0]
                        next_task = rows[stage_index + 1][0]
                        # Отправлять надо фактически произведённое: у стадии с
                        # раскроем выход считается пропорционально нетто-входу,
                        # поэтому заявленный объём на копейку больше и отправка
                        # упирается в бюджет передачи.
                        produced = (
                            await StockProjectionManager().get_task_cache(db, task.id)
                        )["completed_quantity"]
                        carry = min(produced, next_task.planned_quantity)
                        await transfer_send(
                            db,
                            from_task_id=task.id,
                            to_task_id=next_task.id,
                            quantity=carry,
                            dimensions=outgoing.get("dimensions") or task.dimensions,
                            actor_id=actor_id,
                            comment="Демо-передача по маршруту",
                            idempotency_key=f"{key}:send",
                            executor_user_id=actor_id,
                            performed_at=performed_at,
                            accounted_at=accounted_at,
                        )
                    continue
                if mode == "issued":
                    stats["issued"] += 1
                    continue
                # Штук у нас не бывает: годные и брак — целые. Доля от плана
                # округляется по полу (не выдаём больше выпущенного) и не в
                # ноль — нулевая порция не проходит `complete_task`. Иначе
                # 0.6·1032 = 619.2 уезжает в ledger, в остаток склада и в
                # колонку «передать» готовой продукции.
                issued = Decimal(
                    str((await StockProjectionManager().get_task_cache(db, task.id))["issued_quantity"])
                )
                share = Decimal(1) if mode == "done" else Decimal("0.6")
                good = min(_whole_pieces(issued * share), _whole_pieces(issued))
                # На позициях с раскроем материал приходит на участок с
                # габаритом выхода (например 0,9 м), а задание остаётся с
                # входным (2,7 м): брак списывается по габариту задания, и на
                # таком размере остатка нет — проводка падала бы с «недостаточно
                # сырья». Там брак не закладываем.
                split_arrival = any(
                    (group.get("dimensions") or {}) != (task.dimensions or {})
                    for group in (rows[stop_index - 1][0].outputs if stop_index else [])
                )
                # Брак ~1 % выданного, но не меньше штуки: он виден в колонках
                # доски и означает «в работе». Больше остатка годных — нельзя.
                defect = (
                    Decimal(0)
                    if split_arrival
                    else min(
                        _whole_pieces(issued - good),
                        max(_whole_pieces(issued * Decimal("0.01")), Decimal(1)),
                    )
                )
                await complete_task(
                    db,
                    task_id=task.id,
                    good_quantity=good,
                    defect_quantity=defect,
                    actor_id=actor_id,
                    defect_reason="demo_defect",
                    comment="Демо-выполнение упаковки",
                    idempotency_key=f"{key}:complete",
                    executor_user_id=actor_id,
                    performed_at=performed_at,
                    accounted_at=accounted_at,
                    scrap_policy=scrap_policy,
                )
                stats["completed" if mode == "done" else "partial"] += 1
        except ValueError as exc:
            stats["skipped"].append(f"{position.source_sku}#pos{position.id}: {exc}")
    return stats


def _merge_route_progress(*parts: dict[str, object]) -> dict[str, object]:
    """Свести отчёты прогонов по группам позиций в один.

    Прогон идёт двумя вызовами (базовые строки и строки подготовки), но
    потребителю счётчики нужны общие: сколько стадий закрыто, что «в работе», а
    что выдано. Списки ``skipped`` склеиваются — молча терять пропущенную
    позицию нельзя.
    """
    merged: dict[str, object] = {
        "stages": 0,
        "completed": 0,
        "partial": 0,
        "issued": 0,
        "skipped": [],
    }
    for part in parts:
        for key in ("stages", "completed", "partial", "issued"):
            merged[key] = int(merged[key]) + int(part.get(key) or 0)
        merged["skipped"] = list(merged["skipped"]) + list(part.get("skipped") or [])
    return merged


@dataclass(slots=True)
class _PlanDemo:
    """Собранный план демо: позиции по группам прогона и по состоянию строк."""

    plan_id: int
    positions: list[PlanPosition]
    by_status: dict[str, list[PlanPosition]]
    groups: dict[str, list[PlanPosition]]


async def _import_plan_demo(
    db: AsyncSession,
    *,
    filename: str,
    content: bytes,
    column_mapping: Mapping[str, object] | None,
    profile_id: int,
    actor: User,
) -> int:
    """Импортировать лист в НОВЫЙ план и применить change set.

    ``production_plan_id=None`` вместе с ``mode=create_plan`` — единственный
    способ получить отдельный план на каждый набор строк: импорт сам создаёт
    план и никогда не сливает лист в чужой.
    """
    result = await create_excel_import_change_set(
        db,
        filename=filename,
        content=content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        sheet_index=0,
        mode=ImportBatchMode.create_plan,
        production_plan_id=None,
        column_mapping=dict(column_mapping) if column_mapping else None,
        rule_profile_id=profile_id,
        user=actor,
    )
    await apply_change_set(db, int(result["change_set_id"]))
    return int(result["production_plan_id"])


def _fold_row_groups(rows: Sequence[Mapping[str, object]]) -> list[list[Mapping[str, object]]]:
    """Свернуть строки листа в группы — так же, как это делает импорт (ADR-0003).

    Единица импорта — группа строк с объединённой ячейкой входа, а не строка:
    открывающая строка задаёт вход, а каждая следующая без своего входного
    количества становится ещё одним выходом той же позиции. Признак
    продолжения — ``input_continuation`` в строке фикстуры; именно по нему лист
    остаётся без входного количества в этой строке.

    Группы идут в порядке строк, поэтому ``zip(groups, positions)`` сопоставляет
    их с позициями импорта один в один.
    """
    groups: list[list[Mapping[str, object]]] = []
    for row in rows:
        if row.get("input_continuation") and groups:
            groups[-1].append(row)
        else:
            groups.append([row])
    return groups


async def _build_plan_demo(
    db: AsyncSession,
    *,
    plan_rows: Sequence[Mapping[str, object]],
    group_of_row: Callable[[Mapping[str, object]], str],
    filename: str,
    content: bytes,
    column_mapping: Mapping[str, object] | None,
    profile_id: int,
    actor: User,
    sections: Mapping[str, Section],
    run_route: bool,
    start: datetime,
    scrap_policy,
) -> _PlanDemo:
    """Собрать один план демо целиком: импорт → состояния → релиз → маршрут.

    Единица сопоставления — позиция, и она соответствует **группе** строк
    листа, а не строке (ADR-0003): строки с объединённым входом импортируются
    одной позицией с несколькими выходами. Поэтому строки свёрнуты в группы
    тем же признаком, по которому лист их собирает, — ``input_continuation``.
    Состояние и группа прогона берутся у открывающей строки группы. Расхождение
    числа позиций с числом групп означало бы, что импорт склеил или потерял
    строки, и продолжать нельзя.
    """
    row_groups = _fold_row_groups(plan_rows)
    plan_id = await _import_plan_demo(
        db,
        filename=filename,
        content=content,
        column_mapping=column_mapping,
        profile_id=profile_id,
        actor=actor,
    )
    positions = list(
        (
            await db.scalars(
                select(PlanPosition)
                .where(
                    PlanPosition.production_plan_id == plan_id,
                    PlanPosition.status != PlanPositionStatus.cancelled,
                )
                .order_by(PlanPosition.id)
            )
        ).all()
    )
    if not positions:
        raise RuntimeError(f"Импорт {filename} не создал ни одной позиции")
    if len(positions) != len(row_groups):
        raise RuntimeError(
            f"Импорт {filename} создал {len(positions)} позиций на {len(row_groups)} групп "
            f"строк листа ({len(plan_rows)} строк): строки склеились или потерялись, "
            "состояния и группы разъедутся"
        )
    invalid = [
        (item.source_sku, item.source_row_number, item.validation_errors)
        for item in positions
        if item.validation_errors
    ]
    if invalid:
        raise RuntimeError(f"Позиции не прошли валидацию: {invalid[:5]}")

    # Состояние и группа прогона — по открывающей строке: продолжение группы
    # отдельной операцией не является (ADR-0003).
    lifecycles = [_lifecycle_of(group[0]) for group in row_groups]
    by_status: dict[str, list[PlanPosition]] = {name: [] for name in LIFECYCLES}
    groups: dict[str, list[PlanPosition]] = {}
    for group, position, state in zip(row_groups, positions, lifecycles, strict=True):
        by_status[state].append(position)
        # Задание есть только у выпущенной позиции, поэтому в группах
        # прогона (а через них — в дневных планах) остаются выпущенные.
        if state == LIFECYCLE_RELEASED:
            groups.setdefault(group_of_row(group[0]), []).append(position)

    # Своя норма подвеса — до утверждения и релиза, как её ставит планировщик
    # на экране «План» (там её и разрешено менять: у выпущенной позиции поле
    # закрыто). Дальше строка едет по маршруту уже со своей нормой, а не с
    # парной.
    for group, position in zip(row_groups, positions, strict=True):
        row = group[0]
        own_norm = row.get("own_norm")
        if own_norm is None:
            continue
        if int(own_norm) <= 0:
            raise RuntimeError(f"{position.source_sku}: неположительная своя норма {own_norm!r}")
        payload = dict(position.source_payload or {})
        payload["quantity_per_hanger"] = int(own_norm)
        # Присваивание, а не мутация: JSONB in-place правки не видит.
        position.source_payload = payload

    for position, state in zip(positions, lifecycles, strict=True):
        # Неутверждённые строки сид оставляет в ``draft`` — ровно то состояние,
        # в котором позиция ждёт решения планировщика.
        if state == LIFECYCLE_DRAFT:
            continue
        await approve_plan_position(
            db,
            position.production_plan_id,
            position.id,
            force=True,
            reason=f"{DEMO_PLAN_MARKER}: демо-стенд наполняется принудительным утверждением",
        )

    # Утверждённые без релиза позиции в батч не входят: у них не будет ни
    # ``SectionPlanLine``, ни задания — это и есть «утверждено, но не взято в
    # работу».
    releasable = [
        {"plan_position_id": position.id, "release_quantity": str(position.quantity)}
        for position, state in zip(positions, lifecycles, strict=True)
        if state == LIFECYCLE_RELEASED
    ]
    batch = await create_release_batch(
        db,
        production_plan_id=plan_id,
        positions=releasable,
        batch_type=ReleaseBatchType.manual,
        name=f"{DEMO_PLAN_MARKER}: {filename.rsplit('.', 1)[0]}",
    )
    await release_batch(db, int(batch["id"]))
    await db.flush()

    if run_route:
        for group_name, group_positions in groups.items():
            if not group_positions:
                continue
            _ROUTE_PROGRESS_PARTS.append(
                await _run_route_progress(
                    db,
                    positions=group_positions,
                    target_order=[
                        sections[code].id for code in _GROUP_TARGET_SECTIONS[group_name]
                    ],
                    actor_id=actor.id,
                    scrap_policy=scrap_policy,
                    start=start,
                )
            )
    return _PlanDemo(
        plan_id=plan_id,
        positions=positions,
        by_status=by_status,
        groups=groups,
    )


#: Отчёты прогонов маршрута текущего прогона сида. Список модульный, потому
#: что отчёты собирают планы по очереди, а потребителю нужен один счётчик
#: (``_merge_route_progress``). Сид однопоточный и параллельных прогонов не
#: бывает: список очищается на входе ``seed_packing_plan_demo``.
_ROUTE_PROGRESS_PARTS: list[dict[str, object]] = []


async def seed_packing_plan_demo(
    db: AsyncSession,
    *,
    reset: bool = True,
    run_route: bool = True,
    rows: Iterable[Mapping[str, object]] | None = None,
    prep_stage_rows: Iterable[Mapping[str, object]] | None = None,
) -> dict:
    """Наполнить «Участки» двумя планами: упаковочным и подготовительным.

    ``reset=True`` сносит всю оперативку (как ``db:seed --force``) и собирает
    демо-набор заново, поэтому результат детерминирован и повторяем.

    Плана два, и у каждого свой шаблон импорта:

    * упаковочный — «Упаковочная карта РП» (``DEMO_PLAN_ROWS``), маршрут до
      отгрузки, все шесть участков демо;
    * подготовительный — «План подготовительного участка» (#313,
      ``PREP_STAGE_PLAN_ROWS``), маршрут ``RAW_STOCK`` → участки подготовки →
      ``PREP_STOCK``.

    ``rows`` и ``prep_stage_rows`` — строки листов соответствующих планов; по
    умолчанию вся фикстура. Тесты передают срезы, чтобы прогнать доменный путь
    целиком (импорт → approve → release → маршрут → задания → дневные планы)
    на десятке строк вместо всего датасета. Строка вне блоков фикстуры —
    ошибка: её позиция не попадёт ни в одну группу (``_row_group``).

    Состояние позиции задаёт сама строка (ключ ``lifecycle``): ``draft`` — не
    утверждена, ``approved`` — утверждена без релиза, ``released`` — ушла в
    работу. Без первых двух демо показывало бы только «всё в работе».

    Прод-окружение запрещено: сид сносит планы, задания и проводки, а на проде
    они живые. Проверка — на входе, до любой записи (канон ``routes_seed``:
    ``settings.ENV in ("prod", "production")``).
    """
    if settings.ENV.strip().lower() in PROD_ENVS:
        raise RuntimeError(
            f"Демо-сид упаковочного плана запрещён в окружении {settings.ENV}: он сносит "
            "производственные планы, задания и проводки. Запускать только в dev/test."
        )
    plan_rows: tuple[Mapping[str, object], ...] = (
        DEMO_PLAN_ROWS if rows is None else tuple(rows)
    )
    stage_rows: tuple[Mapping[str, object], ...] = (
        PREP_STAGE_PLAN_ROWS if prep_stage_rows is None else tuple(prep_stage_rows)
    )
    if not plan_rows and not stage_rows:
        raise RuntimeError("Список строк демо-плана пуст")
    _ROUTE_PROGRESS_PARTS.clear()
    stats: dict[str, object] = {}
    if reset:
        stats["cleared_rows"] = sum((await clear_generated_production_data(db)).values())
        # clear_generated_production_data не трогает дневные планы, а их состав
        # ссылается на work_tasks каскадом — без сноса повторный прогон падал бы
        # на UNIQUE(work_task_id).
        stats["cleared_daily_plans"] = (await db.execute(delete(DailyPlan))).rowcount or 0

    actor = await db.scalar(select(User).order_by(User.id).limit(1))
    if actor is None:
        raise RuntimeError("Нет пользователей — выполните `npm run db:seed`")
    sections = {
        code: await db.scalar(select(Section).where(Section.code == code))
        for code in DEMO_SECTION_CODES
    }
    missing = [code for code, section in sections.items() if section is None]
    if missing:
        raise RuntimeError(f"Справочник участков не засеян ({missing}) — выполните `npm run db:seed`")

    stats["products"] = 0
    stats["lengths"] = 0
    if plan_rows:
        plan_stats = await _ensure_products(db, plan_rows)
        stats["products"] += plan_stats["products"]
        stats["lengths"] += plan_stats["lengths"]
        # Пары заводятся всегда, даже если срез фикстуры строк пары не содержит:
        # демо-справочник пар должен быть одинаковым при любом срезе.
        pairs, pair_products = await _ensure_product_pairs(db)
        stats["product_pairs"] = pairs
        stats["products"] += pair_products
    if stage_rows:
        stage_stats = await _ensure_prep_stage_products(db, stage_rows)
        stats["products"] += stage_stats["products"]
        stats["lengths"] += stage_stats["lengths"]

    # Профили правил обязательны: без них импорт раскладывает все позиции на
    # шаблонный маршрут, где операции — заглушки без кодов, и доска участка
    # показывает вместо цвета и упаковки позиции пустую операцию.
    profiles = {
        code: await db.scalar(select(RouteRuleProfile).where(RouteRuleProfile.code == code))
        for code in (DEMO_ROUTE_PROFILE_CODE, DEMO_PREP_STAGE_PROFILE_CODE)
    }
    missing_profiles = [code for code, profile in profiles.items() if profile is None]
    if missing_profiles:
        raise RuntimeError(
            f"Профили маршрута не засеяны ({missing_profiles}) — выполните `npm run db:seed`"
        )

    # Дата в имени файла — человекочитаемая метка локального дня снятия демо,
    # а не инстант: в проде контейнер UTC, а смена шкалы развела бы имя файла и
    # остальные демо-метки.
    day = date.today().isoformat()  # noqa: DTZ011 — метка, не инстант
    # Демо-время операций: 08:00 UTC текущего дня. Дату берём в UTC, а не
    # `date.today()`: смешение локальной даты с `tzinfo=UTC` давало 08:00 UTC
    # «вчерашней» даты на хостах восточнее UTC.
    progress_start = datetime.now(UTC).replace(hour=8, minute=0, second=0, microsecond=0)
    scrap_policy = build_plant_config().production.scrap_policy

    plans: list[_PlanDemo] = []
    if plan_rows:
        plans.append(
            await _build_plan_demo(
                db,
                plan_rows=plan_rows,
                group_of_row=_row_group,
                filename=f"demo-{DEMO_PLAN_MARKER.lower()}-packing-plan-{day}.xlsx",
                content=_plan_workbook(plan_rows),
                column_mapping=None,
                profile_id=profiles[DEMO_ROUTE_PROFILE_CODE].id,
                actor=actor,
                sections=sections,
                run_route=run_route,
                start=progress_start,
                scrap_policy=scrap_policy,
            )
        )
    if stage_rows:
        # У профиля ``prep_stage_plan`` нет связи с шаблоном импорта, поэтому
        # маппинг колонок передаём явно: заголовки «Операция»/«Кол-во, шт» не
        # разбираются дефолтными синонимами. Берём его из строки ``import_templates``,
        # а не из сид-константы — демо должно работать ровно с тем, что создал
        # ``npm run db:seed``, иначе расхождение справочника останется незамеченным.
        template = await db.scalar(
            select(ImportTemplate).where(ImportTemplate.code == DEMO_PREP_STAGE_TEMPLATE_CODE)
        )
        if template is None or not template.column_mapping:
            raise RuntimeError(
                f"Шаблон импорта «{DEMO_PREP_STAGE_TEMPLATE_CODE}» не засеян или пуст — "
                "выполните `npm run db:seed`"
            )
        plans.append(
            await _build_plan_demo(
                db,
                plan_rows=stage_rows,
                group_of_row=lambda _row: "prep_stage",
                filename=f"demo-{DEMO_PLAN_MARKER.lower()}-prep-stage-plan-{day}.xlsx",
                content=_prep_stage_workbook(stage_rows),
                column_mapping=template.column_mapping,
                profile_id=profiles[DEMO_PREP_STAGE_PROFILE_CODE].id,
                actor=actor,
                sections=sections,
                run_route=run_route,
                start=progress_start,
                scrap_policy=scrap_policy,
            )
        )

    stats["route_progress"] = _merge_route_progress(*_ROUTE_PROGRESS_PARTS)

    # Остатки под незакрытые позиции. Импорт остатков коммитит сессию сам, поэтому
    # он идёт после сборки планов и до чтения заданий — дальше все объекты
    # перечитываются из БД заново.
    pending_positions = [
        position
        for plan in plans
        for name in (LIFECYCLE_DRAFT, LIFECYCLE_APPROVED)
        for position in plan.by_status[name]
    ]
    finished_stock = await db.scalar(
        select(Section).where(Section.code == FINISHED_STOCK_SECTION_CODE)
    )
    if finished_stock is None:
        raise RuntimeError(
            f"Склад готовой продукции «{FINISHED_STOCK_SECTION_CODE}» не засеян — "
            "выполните `npm run db:seed`"
        )
    stats["pending_stock"] = await _import_pending_stock(
        db,
        positions=pending_positions,
        section=finished_stock,
        actor=actor,
    )
    await db.flush()

    position_ids = [position.id for plan in plans for position in plan.positions]
    groups_by_name: dict[str, list[PlanPosition]] = {}
    for plan in plans:
        for name, group_positions in plan.groups.items():
            groups_by_name.setdefault(name, []).extend(group_positions)

    all_section_ids = [sections[code].id for code in DEMO_SECTION_CODES]
    tasks_by_section: dict[int, list[WorkTask]] = {
        section_id: list(
            (
                await db.scalars(
                    select(WorkTask)
                    .join(SectionPlanLine, SectionPlanLine.id == WorkTask.section_plan_line_id)
                    .where(
                        SectionPlanLine.plan_position_id.in_(position_ids),
                        WorkTask.section_id == section_id,
                    )
                    .order_by(WorkTask.id)
                )
            ).all()
        )
        for section_id in all_section_ids
    }
    if not any(tasks_by_section.values()):
        raise RuntimeError("Релиз не создал заданий на демо-участках")

    # Дневной план не принимает терминальные задания (completed/cancelled) —
    # в реальности в план берут то, что ещё предстоит сделать. Статусы после
    # прогона перечитываем из БД: объекты в сессии устарели.
    plan_ids: list[int] = []
    planned_tasks_count: dict[int, int] = {}
    for section_code, group_names in _SECTION_GROUPS.items():
        section_id = sections[section_code].id
        group_position_ids = [
            position.id for name in group_names for position in groups_by_name.get(name, [])
        ]
        open_tasks = list(
            (
                await db.scalars(
                    select(WorkTask)
                    .join(SectionPlanLine, SectionPlanLine.id == WorkTask.section_plan_line_id)
                    .where(
                        SectionPlanLine.plan_position_id.in_(group_position_ids),
                        WorkTask.section_id == section_id,
                        WorkTask.status.not_in(TERMINAL_TASK_STATUSES),
                    )
                    .order_by(WorkTask.id)
                )
            ).all()
        )
        planned_tasks_count[section_id] = len(open_tasks)
        # Дата дневного плана — локальный бизнес-день демо (колонка `Date`,
        # инстанта нет). Тест зеркалит эту же шкалу и обязан меняться вместе с
        # ней (`tests/test_packing_plan_demo_seeder.py`).
        for plan_date, task_ids in _daily_plan_specs(open_tasks, date.today()):  # noqa: DTZ011 — бизнес-день демо
            created = await create_plan(
                db,
                section_id=section_id,
                plan_date=plan_date,
                work_task_ids=task_ids,
                created_by=actor.id,
            )
            plan_ids.append(int(created["id"] if isinstance(created, dict) else created.id))
    await db.commit()

    stats.update(
        {
            "production_plan_id": plans[0].plan_id if plans else None,
            "production_plan_ids": [plan.plan_id for plan in plans],
            "positions": sum(len(plan.positions) for plan in plans),
            "positions_by_status": {
                name: sum(len(plan.by_status[name]) for plan in plans) for name in LIFECYCLES
            },
            "tasks_by_section": {
                sections[code].code: {
                    "total": len(tasks_by_section[sections[code].id]),
                    "planned": planned_tasks_count[sections[code].id],
                }
                for code in DEMO_SECTION_CODES
            },
            "daily_plans": len(plan_ids),
            "daily_plan_ids": plan_ids,
        }
    )
    return stats
