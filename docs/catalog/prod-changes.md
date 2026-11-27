# Журнал правок прод-данных

Сводка по change-set'ам каталога и справочников: что менялось, почему и каким
бэкапом откатываться. Сами артефакты (снимки строк, отчёты, вырезанные файлы)
лежат вне git — `data/storage-prod/backups/changesets/<метка>/`; здесь — индекс,
чтобы правка не потерялась вместе с рабочей папкой.

Правило и полный чек-лист — [`docs/quality/changesets.md`](../quality/changesets.md).
Бэкапы созданы через `POST /api/backups` (тип manual, ротация их не удаляет).

| Метка | Дата | Что | Почему | Бэкап «до» | Бэкап «после» | Статус |
|---|---|---|---|---|---|---|
| `#461-aliases-1c` | 2026-11-25 | 49 арт. | правка каталога под 1С: алиасы 14, нормализации длин 22, добавления длин 9, переименования 13 | `backup_ktm2000_prod_2026-11-25_20-26-34.zip` | `backup_ktm2000_prod_2026-11-25_20-51-17.zip` | accepted |
| `#463-081-perimeter` | 2026-11-26 | 1 арт., attributes.perimeter_mm, attributes.quantity_per_hanger | Периметр ЮП-081 в БД 43,8 мм, на архивном чертеже РП/ЮП-081.jpg — 44,8 мм (Δ1,0). Решение заказчика: исправить периметр в БД по чертежу. | `backup_ktm2000_prod_2026-11-25_22-26-31.zip` | `backup_ktm2000_prod_2026-11-25_22-26-53.zip` | accepted |
| `#463-1880-placeholder` | 2026-11-26 | 1 арт. | Слот photo_full у ЮП-1880 занят файлом-заглушкой «БЕЗ ФОТО» (7 386 Б). Заглушка не изображение изделия: она маскирует пробел и ломает сверку «разметка ↔ карточка». Решение заказ… | `backup_ktm2000_prod_2026-11-25_22-05-49.zip` | `backup_ktm2000_prod_2026-11-25_22-06-11.zip` | accepted |
| `#463-2972-length-2700` | 2026-11-26 | 1 арт., product_lengths, attributes.quantity_per_hanger | Строка 26 листа «Склад сырой» ОСВ просит сырьё 2,75 м у ЮП-2972, а в реестре длин прода была только 3000. Добавлена нормальная длина 2700 мм с сырьевой 2750 мм; основная 3000 (3… | `backup_ktm2000_prod_2026-11-26_05-28-10.zip` | `backup_ktm2000_prod_2026-11-26_05-28-45.zip` | applied |
| `#463-perimeters-3077-7121` | 2026-11-26 | 2 арт., attributes.perimeter_mm | Сверка показала расхождение периметра с чертежом: ЮП-3077 93,5 против 93 и АТ-7121 75,2 против 75. Оба размера взяты из штампа чертежа; плакаты в расчёте не участвуют. | `backup_ktm2000_prod_2026-11-25_22-51-15.zip` | `backup_ktm2000_prod_2026-11-25_22-51-40.zip` | accepted |
| `#463-renames-leftover` | 2026-11-26 | 7 арт., name, aliases | После #461 семь артикулов остались со старым именем: #461 переименовывал только те, что были в файле 1С. Имя приводится к тому же правилу, что и переименованные соседи: «У1010»… | `backup_ktm2000_prod_2026-11-25_22-28-30.zip` | `backup_ktm2000_prod_2026-11-25_22-28-52.zip` | accepted |
| `#463-styk-26` | 2026-11-26 | 2 арт., name, aliases | Имя «Стык Т-образный 23мм» у 325 и ЮП-2910 противоречит геометрии: КТМ/325.pdf и плакат дают сечение 26x8, P=69,3; в БД mount_width=26. 23 мм — издание 2021 года (23,2x8,5, P=64… | `backup_ktm2000_prod_2026-11-25_22-34-57.zip` | `backup_ktm2000_prod_2026-11-25_22-35-18.zip` | accepted |
| `#466-2464-sku-rename` | 2026-11-26 | 2 арт., sku, aliases | 1С пишет полуфабрикаты как «ЮП-2464-01 ПФ» / «ЮП-2464-05 ПФ», то есть артикул с суффиксом исполнения. Наш SKU «ЮП-2464-1» в такой строке не распознавался: токен обрезался до «ЮП… | `backup_ktm2000_prod_2026-11-26_06-13-27.zip` | `backup_ktm2000_prod_2026-11-26_06-13-59.zip` | applied |
| `#466-codes-1c` | 2026-11-26 | 13 арт., `product_1c_codes` | Сверка ОСВ: 13 кодов 1С не были привязаны (круглые трубы, уголки, полосы, Ш-профиль). Привязка через ORM: `PATCH /api/products` коды не принимает. | `backup_ktm2000_prod_2026-11-26_08-19-29.zip` | `backup_ktm2000_prod_2026-11-26_08-21-12.zip` | applied |
| `#469-2083-37` | 2026-11-26 | 2 арт., `name`, `attributes.mount_width_mm` | Вопрос издания 2083/3328 (38×3,7 vs 36,9×3,3) оставляем открытым; рабочий размер — 37 мм по решению заказчика. | `backup_ktm2000_prod_2026-11-26_08-21-12.zip` | `backup_ktm2000_prod_2026-11-26_08-23-33.zip` | applied |
| `#474-als-sku` | 2026-11-26 | 11 арт., `sku`, `aliases` | Канон ALS без дефиса: `ALS-####` → `ALS####` в артикуле и эквивалентах, отмена 083. Применено миграцией 089 при деплое (086→089); резервные копии — `pg_dump -Fc`. | `pre-089-20261126-182414.dump` | `post-089-20261126-182646.dump` | applied |
| `#490-pipe-length-3000` | 2026-11-27 | 5 арт., `product_lengths`, `attributes.quantity_per_hanger`, `product_dimensions` | 1С пишет «3,0» у труб 8/10/12/20/28 мм; в карточках была 2,7 (28 — 2,5), но в 1С таких строк нет — только 3,0 (2,75 — сырьевая у 16 мм). Добавлена 3000/3050 и норма по π·D (102/96/90/67/48); старые 2700/2500 удалены, 3000 стала основной, типовой размер переведён на 3000. Прямой SQL, без alembic: схема осталась на 089. | `pre-490-20261127-093123.dump` | `post-490-cleanup-20261127-093738.dump` | applied |
| `#493-raw-lengths-1c` | 2026-11-27 | 6 арт., `product_lengths.raw_length_mm`, `products.notes` | ОСВ 1С пишет в наименовании сырьевую длину (2,54/2,55/2,76/2,75/2,08), а в карточках поле было пусто или равно нормальной. Проставлены пары нормальная → сырьевая: КП-5813 2500→2550, ЮП-3688 2500→2540, ЮП-3690 2500→2550, ЮП-2815 2750→2760, ЮП-2080 2700→2750, ЮП-009 2000→2080. Нормальная длина и `is_primary` не менялись; нормы на подвес не изменились (82/51). Источник дописан в примечания. Прямой SQL, без alembic: схема осталась на 090. | `pre-493-20261127-120718.dump` | `post-493-20261127-120718.dump` | applied |
| `#492-porog-alum` | 2026-11-27 | 36 арт., `product_lengths` (49), `product_1c_codes` (257) | 347 строк «Порог алюм.» ОСВ 1С: код ведёт на канон группы, длина (`К` 0,9 / `Н` 1,35 / `Т` 1,8 / `М` 2,7) — ось остатка, цвет — операции (ADR-0077). На проде не хватало 49 длин и 257 кодов; dev-`apply.sql` не переносится — `1212` на проде `id=225`, в dev `227`. Применён prod-`apply_prod.sql` по SKU: 306 insert + 6 `is_primary`; preview ОСВ — 347 «Нулевой остаток», проводок нет. | `pre-492-20261127-152343.dump` | `post-492-20261127-152343.dump` | accepted |
| `#492-length-spectrum` | 2026-11-27 | 62 арт., `product_lengths` (124) | Полный спектр длин (часть 2 #492): 36 канонов «Порог алюм.» → 900/1350/1800/2700, вне канонов — только подтверждённые 1С (ЮП-3168 — 0,9/1,35; ЮП-2082, ЮП-2902 — 0,9); все карточки с 3000 → 1000/2000, ЮП-004 → 3000. Сырьевые 2750/2760/2780 не трогались — уже `raw_length_mm`. `is_primary` выровнен по dev на 5 карточках (1212, ЮП-2256, ЮП-2900, 2525, 314). dev и prod по 406 длин, дублей нет; `1212` на проде `id=225`, в dev `227`. | `pre-492-spectrum-20261127-155121.dump` | `post-492-spectrum-20261127-155121.dump` | accepted |

## Артефакты

- `#461-aliases-1c` — data/storage-prod/backups/changesets/#461-aliases-1c/
- `#463-081-perimeter` — data/storage-prod/backups/changesets/#463-081-perimeter/
- `#463-1880-placeholder` — data/storage-prod/backups/changesets/#463-1880-placeholder/
- `#463-2972-length-2700` — data/storage-prod/backups/changesets/#463-2972-length-2700/
- `#463-perimeters-3077-7121` — data/storage-prod/backups/changesets/#463-perimeters-3077-7121/
- `#463-renames-leftover` — data/storage-prod/backups/changesets/#463-renames-leftover/
- `#463-styk-26` — data/storage-prod/backups/changesets/#463-styk-26/
- `#466-2464-sku-rename` — data/storage-prod/backups/changesets/#466-2464-sku-rename/
- `#466-codes-1c` — data/storage-prod/backups/changesets/#466-codes-1c/
- `#469-2083-37` — data/storage-prod/backups/changesets/#469-2083-37/
- `#474-als-sku` — data/storage-prod/backups/changesets/#474-als-sku/
- `#490-pipe-length-3000` — data/backups/changesets/#490-pipe-length-3000/ (dev: `direct.sql`, `cleanup-27.sql`, `report.md`, `before_rows.json`) и data/backups/prod/ (дампы prod)
- `#493-raw-lengths-1c` — data/backups/changesets/#493-raw-lengths-1c/ (`direct.sql`, `before_rows.json`, `after_rows.json`, `report.md`, `meta.json`) и data/backups/prod/ (дампы prod)
- `#492-porog-alum` — data/storage-prod/backups/changesets/#492-porog-alum/ (`review.html` — обзор «было → стало», `apply_prod.sql`, `apply_prod.py`, `before/after_rows_prod.json`, `ids_prod.json`, `preview_after_prod.json`, `report.md`, `meta.json`) и data/backups/prod/ (дампы prod); dev-черновик — data/backups/changesets/#492-porog-alum/
- `#492-length-spectrum` — data/storage-prod/backups/changesets/#492-length-spectrum/ (`review.html`, `apply.sql`, `apply_prod.sql`, `fix_primary.py`, `primary_prod.sql`, `before/after_rows*`, `ids*.json`, `report.md`, `meta.json`) и data/backups/prod/ (дампы prod); dev-черновик — data/backups/changesets/#492-length-spectrum/

## Как откатывать

- **Точечно** — по `before_rows.json` метки: там полная строка до правки, обратный
  `PATCH /api/products/{id}` возвращает как было.
- **Целиком** — «Бэкапы» → «Восстановить» на архиве «до». Перед восстановлением
  снять ещё один бэкап текущего состояния, чтобы не потерять диагностику.
- **Вырезанный файл** — в `<метка>/removed/`, вернуть в `data/storage-prod/products/`
  и прописать путь в поле артикула.
