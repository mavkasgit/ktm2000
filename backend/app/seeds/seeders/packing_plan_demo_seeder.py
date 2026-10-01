from __future__ import annotations

"""Демо-данные «Участков» на основе реального упаковочного плана.

Фикстура ниже — срез реального ``Упаковочный план.xlsx`` (лист ``totalplan``):
38 реальных строк с артикулами, цветами, раскроем и упаковочными операциями.
Файл xlsx остаётся локальным (``.gitignore``), поэтому строки зафиксированы
здесь как код-данные — по образцу ADR-0004 для канона справочников.

Прогон идёт доменным путём, тем же, что и в UI: импорт упаковочного плана →
change set → approve → release batch → ``work_tasks``, затем поверх — дневные
планы. Прямой записи в таблицы нет, поэтому инварианты (норма длин, маршрут,
``work_task`` только на производственных секциях) сохраняются теми же
проверками, что и в приложении.

Запуск: ``npm run db:seed:packing-demo`` (см. ``backend/scripts/seed_packing_demo.py``).
"""

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.daily_plan import DailyPlan
from app.models.imports import ImportBatchMode
from app.models.internal_plan import SectionPlanLine
from app.models.product import Product, ProductLength, ProductType
from app.models.production_plan import PlanPosition, PlanPositionStatus
from app.models.release_batch import ReleaseBatchType
from app.models.route import RouteRuleProfile, RouteStage
from app.models.section import Section
from app.models.user import User
from app.models.work_task import WorkTask, WorkTaskStatus
from app.seeds.canon.registry import build_plant_config
from app.services.action_journal_service import action_journal_service
from app.services.shopfloor_service import complete_task
from app.services.material_operations import completed_operations_through_stage
from app.stock import QualityState, Reason, StockCommand, StockCommandService
from app.stock.models import StockBalance
from app.stock.services import (
    StockProjectionManager,
    completed_operations_match_clause,
    dimensions_match_clause,
)
from app.transfers.services import transfer_send
from app.seeds.seeders.cleanup_seeder import clear_generated_production_data
from app.services.daily_plan_service import TERMINAL_TASK_STATUSES, create_plan
from app.services.plan_generation import create_release_batch, release_batch
from app.services.plan_import_service import create_excel_import_change_set
from app.services.production_plan_service import apply_change_set, approve_plan_position
from app.core.config import settings


PACKING_SECTION_CODE = "PACKING"
DEMO_PLAN_MARKER = "DEMO"

# Участки, на которых демо-данные должны быть живыми. Позиции плана делятся
# между ними по кругу, у каждого своя глубина прогона — так на всех трёх есть и
# активные задания, и «в ожидании» от предыдущей стадии.
DEMO_SECTION_CODES = ("SAWING", "PACKING", "ANODIZING")

# Профиль маршрута, по которому демо-позиции собирают этапы. Шаблон листа
# демо — «Упаковочная карта РП», и разбирать его операции должен тот же профиль,
# что и живой импорт: иначе позиции уедут на шаблонный маршрут с заглушками.
DEMO_ROUTE_PROFILE_CODE = "packaging_map_rp"

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


def _plan_workbook(rows: tuple[dict[str, object], ...]) -> bytes:
    """Собрать «Упаковочный план» в памяти — тот же вход, что у xlsx-импорта."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "totalplan"
    for _ in range(3):
        ws.append([])
    ws.append(list(_PLAN_HEADERS))
    for row in rows:
        ws.append(
            [
                row["sku"],
                "ТЗ",
                row["name"],
                0,
                row["color"],
                row["input_quantity"],
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


async def _ensure_products(db: AsyncSession, rows: tuple[dict[str, object], ...]) -> dict[str, int]:
    """Upsert артикулов плана вместе с их каноном длин (вход + выход раскроя)."""
    stats = {"products": 0, "lengths": 0}
    for row in rows:
        sku = str(row["sku"])
        product = await db.scalar(select(Product).where(Product.sku == sku))
        if product is None:
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
            stats["products"] += 1
        else:
            # Артикул уже есть в каталоге (в т.ч. выведенный из оборота) —
            # импорт отбрасывает неактивные позиции, поэтому реактивируем.
            product.is_active = True
            product.is_catalog_item = True
        for value, primary in ((row["input_length_m"], True), (row["output_length_m"], False)):
            if await _ensure_length(db, product, round(float(value) * 1000), primary=primary):
                stats["lengths"] += 1
    return stats


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

    Позиции делятся между тремя участками: у каждого своя глубина прогона, так
    что задания есть и в работе, и в ожидании на всех трёх. Стадии до целевой
    проходятся целиком — иначе задания целевого участка остались бы
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
                        defect_quantity=Decimal("0"),
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
                share = Decimal("1") if mode == "done" else Decimal("0.6")
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
                    Decimal("0")
                    if split_arrival
                    else min(
                        _whole_pieces(issued - good),
                        max(_whole_pieces(issued * Decimal("0.01")), Decimal("1")),
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


async def seed_packing_plan_demo(
    db: AsyncSession, *, reset: bool = True, run_route: bool = True
) -> dict:
    """Наполнить «Участки» реальным упаковочным планом: план → релиз → дневные планы.

    ``reset=True`` сносит всю оперативку (как ``db:seed --force``) и собирает
    демо-набор заново, поэтому результат детерминирован и повторяем.

    Прод-окружение запрещено: сид сносит планы, задания и проводки, а на проде
    они живые. Проверка — на входе, до любой записи (канон ``routes_seed``:
    ``settings.ENV in ("prod", "production")``).
    """
    if settings.ENV.strip().lower() in PROD_ENVS:
        raise RuntimeError(
            f"Демо-сид упаковочного плана запрещён в окружении {settings.ENV}: он сносит "
            "производственные планы, задания и проводки. Запускать только в dev/test."
        )
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
    # Глубина прогона по позициям: у каждого участка своя, чтобы задания были
    # активны везде, а нижестоящие участки копили «в ожидании».
    target_order = [sections[code].id for code in DEMO_SECTION_CODES]

    stats.update(await _ensure_products(db, PACKING_PLAN_ROWS))

    # Профиль правил обязателен: без него импорт раскладывает все позиции на
    # шаблонный маршрут, где операции — заглушки без кодов, и доска участка
    # показывает вместо цвета и упаковки позиции пустую операцию.
    profile = await db.scalar(
        select(RouteRuleProfile).where(RouteRuleProfile.code == DEMO_ROUTE_PROFILE_CODE)
    )
    if profile is None:
        raise RuntimeError(
            f"Профиль маршрута «{DEMO_ROUTE_PROFILE_CODE}» не засеян — выполните `npm run db:seed`"
        )

    import_result = await create_excel_import_change_set(
        db,
        filename=f"demo-{DEMO_PLAN_MARKER.lower()}-packing-plan-{date.today().isoformat()}.xlsx",
        content=_plan_workbook(PACKING_PLAN_ROWS),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        sheet_index=0,
        mode=ImportBatchMode.create_plan,
        production_plan_id=None,
        column_mapping=None,
        rule_profile_id=profile.id,
        user=actor,
    )
    change_set_id = int(import_result["change_set_id"])
    plan_id = int(import_result["production_plan_id"])
    await apply_change_set(db, change_set_id)

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
        raise RuntimeError("Импорт упаковочного плана не создал ни одной позиции")
    invalid = [
        (item.source_sku, item.source_row_number, item.validation_errors)
        for item in positions
        if item.validation_errors
    ]
    if invalid:
        raise RuntimeError(f"Позиции не прошли валидацию: {invalid[:5]}")
    for position in positions:
        await approve_plan_position(
            db,
            position.production_plan_id,
            position.id,
            force=True,
            reason=f"{DEMO_PLAN_MARKER}: демо-стенд наполняется принудительным утверждением",
        )

    batch = await create_release_batch(
        db,
        production_plan_id=plan_id,
        positions=[{"plan_position_id": item.id, "release_quantity": str(item.quantity)} for item in positions],
        batch_type=ReleaseBatchType.manual,
        name=f"{DEMO_PLAN_MARKER}: упаковочный план",
    )
    await release_batch(db, int(batch["id"]))
    await db.flush()

    position_ids = [item.id for item in positions]
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
        for section_id in target_order
    }
    if not any(tasks_by_section.values()):
        raise RuntimeError("Релиз не создал заданий на демо-участках")
    if run_route:
        await db.flush()
        stats["route_progress"] = await _run_route_progress(
            db,
            positions=positions,
            target_order=target_order,
            actor_id=actor.id,
            scrap_policy=build_plant_config().production.scrap_policy,
            start=datetime.combine(date.today(), datetime.min.time(), tzinfo=UTC).replace(hour=8),
        )

    # Дневной план не принимает терминальные задания (completed/cancelled) —
    # в реальности в план берут то, что ещё предстоит сделать. Статусы после
    # прогона перечитываем из БД: объекты в сессии устарели.
    plan_ids: list[int] = []
    open_tasks_count: dict[int, int] = {}
    for section_id in target_order:
        open_tasks = list(
            (
                await db.scalars(
                    select(WorkTask)
                    .join(SectionPlanLine, SectionPlanLine.id == WorkTask.section_plan_line_id)
                    .where(
                        SectionPlanLine.plan_position_id.in_(position_ids),
                        WorkTask.section_id == section_id,
                        WorkTask.status.not_in(TERMINAL_TASK_STATUSES),
                    )
                    .order_by(WorkTask.id)
                )
            ).all()
        )
        open_tasks_count[section_id] = len(open_tasks)
        for plan_date, task_ids in _daily_plan_specs(open_tasks, date.today()):
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
            "production_plan_id": plan_id,
            "positions": len(positions),
            "tasks_by_section": {
                sections[code].code: {
                    "total": len(tasks_by_section[sections[code].id]),
                    "open": open_tasks_count[sections[code].id],
                }
                for code in DEMO_SECTION_CODES
            },
            "daily_plans": len(plan_ids),
            "daily_plan_ids": plan_ids,
        }
    )
    return stats
