# Research: Odoo MRP — карточка продукта, BoM, where-used, операции/routing

- **Дата:** 2026-09-05
- **Вопрос (issue [#139](https://github.com/mavkasgit/ktm2000/issues/139)):** как Odoo MRP связывает сырьё и готовую продукцию и что показывает на карточке продукта — структура BoM (типы kit/phantom/ordinary), where-used, отображение операций/routing (Work Centers, Operations в BoM), как выглядит карточка товара в UI, как BoM переиспользуется планированием. Что применимо к странице «Продукты» KTM-2000 (справочник ГП; состав 1–2 компонента; операции на карточке под вопросом; парные подвесы живут на сырье, не на ГП).
- **Карта:** issue [#138](https://github.com/mavkasgit/ktm2000/issues/138) (страница «Продукты»)

## Источники

Первичные (официальная документация Odoo 19 и исходник `odoo/odoo@17.0`):

1. BoM configuration: <https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/manufacturing/basic_setup/bill_configuration.html>
2. Kits: <https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/manufacturing/advanced_configuration/kit_shipping.html>
3. Work centers: <https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/manufacturing/advanced_configuration/using_work_centers.html>
4. Work order dependencies: <https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/manufacturing/advanced_configuration/work_order_dependencies.html>
5. `mrp.bom` / `mrp.bom.line`: <https://github.com/odoo/odoo/blob/17.0/addons/mrp/models/mrp_bom.py>
6. Smart-кнопки продукта: <https://github.com/odoo/odoo/blob/17.0/addons/mrp/models/product.py>
7. Планирование (stock rule → MO): <https://github.com/odoo/odoo/blob/17.0/addons/mrp/models/stock_rule.py>
8. Release notes Odoo 19 (переименование отчёта): <https://www.odoo.com/odoo-19-release-notes>

## Находки

### 1. Связь сырьё ↔ ГП: BoM — отдельная сущность, а не поле продукта

`mrp.bom` — отдельная модель, обязательная ссылка на шаблон продукта: `product_tmpl_id` (required) + опциональная `product_id` (вариант; если пусто — BoM действует на уровне шаблона для всех вариантов). Компоненты — строки `mrp.bom.line` (`product_id` компонента, `product_qty`, `product_uom_id`), у каждой строки есть поле `operation_id` («Consumed in Operation»). Один продукт может иметь несколько BoM (по количеству/вариантам); `_bom_find` выбирает применимую.

У карточки продукта BoM не «вшита» — она доступна **smart-кнопкой** на форме продукта (`bom_count` → список BoM / создание).

### 2. Типы BoM: только два технических значения

В коде (`mrp_bom.py`) selection ровно из двух:

```python
type = fields.Selection([
    ('normal', 'Manufacture this product'),
    ('phantom', 'Kit')], ...)
```

То есть «phantom» в коде — это и есть UI-тип **Kit**; отдельного типа «kit» нет. Документация к ним добавляет третий *поведенческий* случай через Product Type + route («Sell or purchase» — без BoM вовсе). Разница по поведению:

- **Normal (обычная):** компоненты списываются через производственный заказ (MO).
- **Kit/phantom:** MO не создаётся — при продаже/потребности комплект автоматически раскладывается на компоненты (в `ProcurementGroup.run`: `bom_kit.explode(...)` → каждый компонент становится отдельным procurement). Остатки и пополнение живут **на уровне компонентов**, не комплекта; на карточке комплекта Odoo прячет «прогноз» и показывает on-hand, а `action_open_quants` подмешивает кванты компонентов.

Для KTM-2000: «обычная» BoM — аналог состава «из чего сделано»; kit/phantom — про продажу неразобранных комплектов, к справочнику ГП не относится.

### 3. Where-used — smart-кнопка «Used In» на карточке

В `mrp/models/product.py` у `ProductTemplate` и `ProductProduct` есть `used_in_bom_count` («# BoM Where is Used») со счётом BoM, где продукт встречается компонентом, и экшеном `action_used_in_bom()` с доменом `[('bom_line_ids.product_tmpl_id', '=', self.id)]` / `[('bom_line_ids.product_id', '=', product.id)]`. На форме продукта это smart-кнопка, открывающая список BoM-родителей. Дополнительные view-уровни: отчёт **BoM Overview** (Manufacturing → Reporting, бывший «Structure & Cost», переименован в Odoo 16) показывает дерево компонентов + операции + стоимость; для комплекта кванты компонентов подмешиваются в карточку комплекта.

### 4. Операции/routing: живут в BoM, не на продукте

Операции — `mrp.routing.workcenter`, One2many `operation_ids` на BoM: «Each operation is always exclusively linked to one BoM». Work Center — отдельный справочник; операция = операция + work center + длительность. Вкладка Operations на BoM доступна после включения Work Orders в настройках; зависимости операций (`blocked_by_operation_ids`) — отдельная настройка BoM. На карточке **продукта** операций нет — только через smart-кнопку BoM.

### 5. Карточка продукта в UI (Sales/Inventory/MRP)

Единая форма продукта, к которой каждое приложение добавляет smart-кнопки/вкладки. MRP добавляет: `bom_count` (BoM), `used_in_bom_count` (Used In), `mrp_product_qty` («Manufactured», выпуск за 365 дней) и `is_kits` (меняет поведение кнопки остатков для комплектов). Инвентарь добавляет кванты/движения. Т.е. Odoo не показывает BoM-состав прямо на карточке — карточка остаётся компактной, состав уезжает на один клик (кнопка).

### 6. Переиспользование BoM планированием

`stock_rule.py`: при пополнении manufactured-продукта (reordering rules/orderpoints, MTO, MPS) правило `_run_manufacture` находит BoM (`_get_matching_bom`: из procurement → из orderpoint.bom_id → `_bom_find(bom_type='normal')`) и создаёт MO с `bom_id`; сроки берутся из `bom.produce_delay` + `days_to_prepare_mo`. Для kit/phantom вместо MO — explode на компоненты. Т.е. одна и та же BoM обслуживает и планирование (MRP-бег), и карточку (отображение), и себестоимость (BoM Overview).

## Выводы: что берём / что не берём для KTM-2000

**Берём:**

1. **BoM как отдельная связь «компонент + количество» от продукта ГП** — соответствует решению карты: состав на `Product`, 1–2 компонента; не поле-строка в продукте, а ссылочная структура (аналог `mrp.bom.line`: component, qty).
2. **Состав на карточке ГП — компактно, «одним кликом»**: Odoo держит карточку лёгкой и прячет состав за smart-кнопкой/блоком, а не превращает карточку в техкарту. Для KTM: блок «Состав» из 1–2 строк на карточке — даже компактнее Odoo-подхода, оправдано.
3. **Where-used как обратная связь от сырья**: паттерн `used_in_bom_count` / `action_used_in_bom` — это ровно закрытие открытого вопроса карты «где используется (от сырьевого артикула к ГП)». На карточке **сырья** показывать список ГП, в чей состав он входит (у нас состав маленький, обратный индекс тривиален); на карточке ГП не нужен (ГП никуда не входит).
4. **Двусторонняя асимметрия**: Odoo показывает «BoM» на ГП и «Used In» на компоненте — та же асимметрия, что в KTM (состав на ГП, пары/подвес на сырье).
5. **Тип Kit (phantom) — не брать**: у нас нет «продажи неразобранных комплектов»; все связи ГП — производственные (normal). Достаточно одного типа состава.

**Не берём:**

1. **Операции/routing на карточке продукта** — в Odoo операции принадлежат BoM, а не продукту, и на карточку не выносятся. Это аргумент **против** полноценного блока операций на странице «Продукты» KTM: если операции и показывать, то как простой read-only список возможных этапов (существующий `products.py:662+`), без привязки к WC/длительностям — ценность сомнительна, что подтверждает скепсис карты.
2. **Версионирование BoM (PLM `version`)** — решением карты техкарты упразднены; версию состава не проектируем.
3. **By-products, byproduct-BoM, consumption policies (flexible/strict)** — вне домена KTM (партий нет, ADR-0001; ledger отдельно).
4. **Мультивариантность BoM («Apply on Variants»)** — вариантная модель не проектируем; текущих `ProductLength` + `color` достаточно.
5. **MRP-бег по BoM (reordering → MO)** — планирование KTM-2000 идёт из планов/импорта, не от точек перезаказа; BoM на странице «Продукты» используется только для отображения состава.
6. **Kit-поведение остатков (explode квантов на карточке)** — живых остатков на странице «Продукты» нет (решение карты).
