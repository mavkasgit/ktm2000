# Research: SAP — material master, material BOM, routing, production version

- **Дата:** 2026-09-05
- **Вопрос** (тикет [#140](https://github.com/mavkasgit/ktm2000/issues/140)): как SAP организует связь «сырьё → ГП» — material master (просмотры), material BOM (альтернативы/варианты), routing (операции, work centers), production version. Где хранится состав, где операции, показывает ли material master «из чего состоит»/«где используется», как норматив отделяется от факта. Применимость к странице «Продукты» KTM-2000: должен ли список операций быть частью карточки ГП.
- **Карта:** #138 («Продукты»: спека + ADR «Упразднение техкарт»)

## Источники (первичные)

- SAP Learning, курс *Exploring Basic Data for Manufacturing and Product Management in SAP S/4HANA*:
  - Material unit: [Introducing Material](https://learning.sap.com/courses/exploring-basic-data-for-manufacturing-and-product-management-in-sap-s-4hana/introducing-material), [Creating a Material](https://learning.sap.com/courses/exploring-basic-data-for-manufacturing-and-product-management-in-sap-s-4hana/creating-a-material), [Classifying Material](https://learning.sap.com/courses/exploring-basic-data-for-manufacturing-and-product-management-in-sap-s-4hana/classifying-material)
  - BOM unit: [Introducing BOMs](https://learning.sap.com/courses/exploring-basic-data-for-manufacturing-and-product-management-in-sap-s-4hana/introducing-bills-of-material-boms-), [Managing BOMs](https://learning.sap.com/courses/exploring-basic-data-for-manufacturing-and-product-management-in-sap-s-4hana/managing-boms), [Analyzing BOMs](https://learning.sap.com/courses/exploring-basic-data-for-manufacturing-and-product-management-in-sap-s-4hana/analyzing-boms)
  - Work Centers: [Creating Work Centers](https://learning.sap.com/courses/exploring-basic-data-for-manufacturing-and-product-management-in-sap-s-4hana/creating-work-centers)
  - Task Lists: [Working with Task Lists](https://learning.sap.com/courses/exploring-basic-data-for-manufacturing-and-product-management-in-sap-s-4hana/working-with-task-lists), [Creating Product Versions](https://learning.sap.com/courses/exploring-basic-data-for-manufacturing-and-product-management-in-sap-s-4hana/creating-product-versions)
- SAP Learning, курс *Manage Production Orders in SAP S/4HANA Manufacturing*: [Analyzing Master Data Selection](https://learning.sap.com/courses/manage-production-orders-in-sap-s-4hana-manufacturing/analyzing-master-data-selection)
- SAP Help Portal (SPA — текст вытащен через поисковые сниппеты):
  - [Creating Production Versions (in the Routing)](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9c4986bda35f4840ae438960ffbef64d/92d44c57589e42c1b020b1245d61f4a9.html) — «A production version combines an MBOM version with a shop floor routing version and therefore determines which MBOM version is used together with which shop floor routing.»
  - [Material Where-Used List for BOMs](https://help.sap.com/docs/SAP_S4HANA_CLOUD/f369b2eff700401494ba6e7c9a573288/d007975f2bab45af86fa5fa0120f1b29.html)
  - [Planned Cost (preliminary costing of manufacturing orders)](https://help.sap.com/docs/SAP_S4HANA_CLOUD/4032610758dc437089f0c28320eec93f/71a41300c3034964bddb5c9cc34894b7.html)

## Находки

### 1. Material master — это «паспорт» материала, а НЕ носитель состава

Материал организован **просмотрами (views)**, каждый отвечает за свой домен данных, на разных орг. уровнях (client → plant → storage location):

| View | Что держит | Таблица |
|---|---|---|
| Basic Data | номер, описание, базовая ЕИ, техданные | MARA |
| Classification | user-defined классы/атрибуты материала | (классификация) |
| MRP (Materials planning) | plant-specific данные планирования закупок/производства | MARC |
| Work Scheduling | plant-specific данные для планирования производства (в т.ч. unit of issue для BOM) | MARC |
| Accounting | оценка (valuation) | MBEW |

Состав («из чего состоит») в material master **не хранится** — это отдельный master-data объект **material BOM**. Операции — отдельный объект **routing** (task list). Material master лишь ссылается: в MRP-данных указывается production version, которая выбирает пару «BOM × routing».

### 2. Material BOM — где живёт состав

- BOM = «drawings plus a list of all required parts», результат проектирования продукта; возникает везде, «where finished or semi-finished products are built from several components» (в процессных отраслях — recipe/list of ingredients).
- **Потребители BOM**: MRP (разузлование для расчёта количеств), work scheduling (планирование операций), production order management (обеспечение комплектующими), reservations/goods issues, product costing (материальные затраты).
- **Альтернативы**: несколько alternative BOM на один материал (переключение между ними в Fiori-приложении Manage Multilevel Material BOM); group BOM — plant-независимый, потом привязывается к заводам.
- **Варианты**: variant BOM / классы внутри BOM — только если header material конфигурируемый (variant configuration).
- **Item categories** (stock/non-stock/document/variable-size/phantom) определяют, нужен ли материал-вход, ведётся ли складской учёт и т.д.
- Единица/база: базовая ЕИ берётся из material master; если в Work Scheduling view задан unit of issue — используется он, с коэффициентом пересчёта.

### 3. Routing (task list) — где живут операции

- Routing = **шаблон производственного процесса** для production orders: «shows operations in a sequence and acts as a template for production orders».
- Операция отвечает на вопросы: *где* работа выполняется (work center), *сколько времени* (standard values: setup/machine/labor), *какие материалы* нужны на операции (component allocation), *какие инструменты/PRT*.
- **Work center** — отдельный master-data объект: держит standard value keys, default values для операций, данные планирования (queue/move time), costing (cost center + activity types) и capacity. «The system copies the default values to the routing» — рабочие центры поставляют дефолты в операции.
- Последовательности: standard sequence + alternative/parallel sequences (расширенное моделирование).

### 4. Production version — связка BOM × routing

- «A production version **combines an MBOM version with a shop floor routing version** and therefore determines which MBOM version is used together with which shop floor routing» (help.sap.com).
- В S/4HANA production version **обязательна**: «a production order needs a production version, so you MUST define a production version inside your material MRP data». Выбор альтернативы: «The appropriate alternative is selected using the production version in the material master».
- Несколько версий на один материал — например, разные способы изготовления для разных lot-size интервалов (пример из урока: bracket — целая заготовка на NC-машине для крупных партий vs полосы для мелких).
- Ограничения согласованности: lot-size range версии должен лежать внутри диапазонов и BOM, и routing; валидность дат версии — внутри валидности BOM и routing.

### 5. «Из чего состоит» и «где используется» — отдельные отчёты, не поля карточки

- **BOM explosion** (сверху вниз) отвечает «what does this product consist of»: от ГП ко всем компонентам, одно- и многоуровневое.
- **Where-used list** (снизу вверх) отвечает обратное: какие BOM содержат данный компонент — нужно, чтобы понять «the products that are affected by a change to an individual part» (например, при задержке поставки сырья или изменении его стоимости). В Fiori — приложение [Material Where-Used List for BOMs](https://help.sap.com/docs/SAP_S4HANA_CLOUD/f369b2eff700401494ba6e7c9a573288/d007975f2bab45af86fa5fa0120f1b29.html): поиск BOM-хедеров по компоненту с фильтрами (plant, BOM usage, alternative, category).
- Т.е. **в SAP ни направление не хранится денормализованно на карточке** — оба являются запросами по BOM-объекту. (Odoo, в отличие от SAP, денормализует where-used на карточку товара.)

### 6. Норматив vs факт: копия-снимок в заказе

- При создании production order выбирается production version, и **BOM + routing копируются в заказ**: «When creating a production order, a production version with routing and bill of material (BOM) is selected», из planned order — «the production version of the planned order determined by the MRP run is copied to the production order».
- Дальше заказ живёт своей жизнью: компоненты → reservations, операции → подтверждения (confirmations). «Read Master Data» позволяет переподтянуть версию, но **только пока не было material movements и confirmations**.
- Изменение BOM/routing master data **не задним числом** меняет существующие заказы — заказ хранит снимок (иначе бессмыслен план-факт по себестоимости: planned costs считаются из скопированного норматива, actual — из goods issues/confirmations, разница = variances).

## Выводы для KTM-2000 (страница «Продукты»)

### Берём

1. **Состав — отдельный объект связи «компонент + количество», а не поля материала.** SAP держит BOM вне material master; наш план «состав ГП на Product (ProductComponent)» этому полностью соответствует. Карточка ГП показывает результат разузлования (BOM explosion) — агрегат «из чего сделано».
2. **«Где используется» — обратный запрос от сырья**, а не хранимый список на сырьевом артикуле (SAP-подход; где-used у нас и так уже решён в пользу обратного индекса — совпадает с SAP и чуть расходится с Odoo-денормализацией).
3. **Норматив отдельно от факта через «снимок в документе»**: SAP копирует BOM+routing в заказ при создании и не пересчитывает задним числом. Для KTM-2000 факт out of scope, но принцип валидирует нашу модель: норматив (Product + состав) — master data; задания/ledger — фактическая сторона, изолированная от изменений норматива.
4. **Операции — отдельный объект (аналог routing), связанный с продуктом через «версию», а не вложенный список в карточке.** В SAP операции живут в routing/task list, work centers — отдельно; карточка материала лишь указывает на production version.

### Не берём

5. **Блок операций как обязательная часть карточки ГП — не берём.** В SAP операции — это не атрибут материала, а отдельный шаблон процесса, подключаемый через production version; на карточке материала они видны только как ссылка/переход. Учитывая, что техкарты упразднены (решение заказчика) и операции как норматив выполнения никуда не привязываются, полный список возможных операций (route stages) на карточке ГП — балласт; максимум, что допустимо, — упоминание стадий как справочника, но не редактируемый список на карточке. → отвечает на открытый вопрос карты #138: блок операций не нужен.
6. **Альтернативные BOM / variant BOM / production versions с lot-size интервалами** — механизм множественности способов изготовления; у нас 1–2 компонента на ГП и вариантов нет (длины/цвета уже покрыты `ProductLength`+`color`), конфигуратор не проектируем.
7. **Просмотровая модель material master (MRP/Accounting/Classification views)** — следствие масштаба SAP-справочника; наш Product — одна сущность с атрибутами (подвес/пары на сырьевом артикуле уже решены). Classification (атрибуты через классы) нам не нужен.
8. **Component allocation на операцию** («какие материалы на какой операции») — у нас операции как норматив упразднены; связи «компонент→операция» не строим.

### Итоговый ответ на вопрос тикета

Список операций **не должен** быть частью карточки ГП: и SAP (routing — отдельный объект, подключаемый production version), и Odoo (операции принадлежат BoM) хранят операции вне карточки материала. При упразднении техкарт в KTM-2000 норматив — это только состав на Product (+ подвес/пары на сырье); отделение норматива от факта в SAP достигается копией-снимком в заказе, что подтверждает: на странице «Продукты» факт не показываем, норматив держим как чистые master data.
