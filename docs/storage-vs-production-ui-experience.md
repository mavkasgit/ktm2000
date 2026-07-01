# UI-опыт: «цех vs. склад» в маршрутах

Документ описывает, как конечный пользователь и фронтенд-разработчик видят
новое разделение «цех / склад / транзит» в маршрутах после миграции 020.

Источник истины: [app/services/route_storage_classifier.py](file:///c:/Users/user/VibeCoding/ktm2000/backend/app/services/route_storage_classifier.py)
на бэкенде и зеркало [routeStageClassifier.ts](file:///c:/Users/user/VibeCoding/ktm2000/frontend/src/shared/lib/routeStageClassifier.ts)
на фронте.

---

## 1. Три сущности, которые пользователь различает

| Сущность | Где живёт | Что значит для пользователя |
|---|---|---|
| **Цех (production)** | `Section.kind = 'production'`, `SectionOperation.operation_type = 'production'`, `RouteStage.stage_kind = 'production'` | Здесь делают реальную работу (сверлят, прессуют, упаковывают). На цехе есть конкретные операции, по ним создаются задания (`WorkTask`). |
| **Склад (storage)** | `Section.kind ∈ {raw_stock, wip_stock, finished_stock}` | Это **место хранения**, а не работы. На нём нечего выполнять — материал лежит, ожидает следующего цеха. |
| **Транзит (transit)** | `RouteStage.stage_kind = 'transit'`, `storage_section_id` указывает на склад | Узел в маршруте между двумя цехами. Не задание, не работа — просто факт, что материал проходит через склад. |

**Ключевая мысль для UI**: цех — это блок, склад — иконка-ромб между блоками, транзит — это сам «пунктирный мост» через склад.

---

## 2. Карточка маршрута (`GET /api/routes/{id}`)

Раньше этапы выглядели так (проблемная модель):

```
[1] WH         ·  Issue raw       (is_significant=false)  ← pass-through
[2] DRILL      ·  Drill           (is_significant=true)
[3] WIP_WH     ·  Move to WIP     (is_significant=false)  ← pass-through
[4] ANOD       ·  Anodize         (is_significant=true)
```

Пользователь не понимал: «почему WIP_WH в маршруте? На нём же никто не работает?»

**Теперь** карточка маршрута выглядит так:

```
[1] DRILL      ·  Сверловка                    ← сплошной блок, цех
       ⬨ WIP_WH                                 ← пунктирный ромб, транзит
[2] ANOD       ·  Анодирование                 ← сплошной блок, цех
       ⬨ FG_WH                                  ← пунктирный ромб, транзит
[3] PACK       ·  Упаковка                     ← сплошной блок, цех
```

Конкретные правила отрисовки в React:

- `stage_kind === 'production'` → `<ProductionStageChip section_id={…} icon={…} name={…}>`
  - фон сплошной, цвет = `section.icon_color`
  - внутри — название цеха и список операций
- `stage_kind === 'transit'` → `<TransitNode storageSection={…}>`
  - контур пунктирный, иконка `Warehouse`/`Boxes`/`Container` (в зависимости от `kind`)
  - внутри — `Хранение: {storageSection.name}`
  - тултип: «Транзитный узел. Не требует выполнения работы.»

### API-ответ `StepOut`

```json
{
  "id": 42,
  "route_id": 7,
  "sequence": 2,
  "section_id": null,
  "section_code": "WIP_WH",
  "section_name": "Склад полуфабриката",
  "operation_code": null,
  "operation_name": "Транзит через Склад полуфабриката",
  "norm_time_minutes": null,
  "is_final": false,
  "stage_kind": "transit",
  "storage_section_id": 5
}
```

Важно: `section_id === null` для transit, `storage_section_id` всегда заполнен. UI должен смотреть `stage_kind` первым, а не `section_id`.

---

## 3. Редактор маршрута (форма добавления этапа)

Сценарий: технолог создаёт новый маршрут или редактирует существующий, добавляет этапы.

### Шаг 1 — тип этапа

Переключатель (radio) в верхней части формы:

```
○  Цех (операция)
●  Склад (транзит)
```

При выборе «Цех» форма переключается в production-режим, при выборе «Склад» — в transit-режим.

### Шаг 2a — режим «Цех»

Поля:
- `section_id` (обязательное) — выпадающий список **только production-секций** (`DRILL`, `PRESS`, `SHOT`, `ANOD`, `SAW`, `PACK` и т.п.)
- `operation_code` — выпадающий список операций выбранной секции (только с `operation_type='production'`)
- `operation_name` — автозаполнение из справочника
- `norm_time_minutes`, `requires_acceptance`, `allow_parallel`, `is_final` — все доступны

Если пользователь попытается выбрать секцию-склад (вдруг, через прямой URL/другой компонент) — backend вернёт 400:

```json
{
  "detail": "Section 5 (WIP_WH) is a storage section. To add it as a transit hop set stage_kind='transit'."
}
```

UI показывает это сообщение и подсвечивает поле красным.

### Шаг 2b — режим «Склад»

Поля:
- `storage_section_id` (обязательное) — выпадающий список **только storage-секций** (`WH`, `WIP_WH`, `FG_WH`, `SHIPMENT`, `SENT`)

UI вызывает `GET /api/sections/storage-points` и получает готовый список.

Поля `norm_time_minutes`, `allow_parallel`, `is_final` — **disabled** (серым, с тултипом «Неприменимо для транзитного узла»). `requires_acceptance` — disabled (транзит не требует приёмки).

### Что НЕ показываем пользователю

- Поле `stage_kind` не редактируется напрямую — оно выводится из переключателя в шаге 1
- Поле `section_id` для transit остаётся `null` (в БД enforced TRIGGER-ом)

---

## 4. Доска цеха (Section Board) — `GET /api/sections/all/operations`

Раньше endpoint возвращал **синтетическую** `SectionOperation` для секций без операций (с `is_significant=True`, что вводило в заблуждение — UI показывал её как настоящую).

**Теперь** ответ имеет явный признак роли:

```json
{
  "id": 5,
  "code": "WIP_WH",
  "name": "Склад полуфабриката",
  "kind": "wip_stock",
  "role": "storage",
  "has_real_operations": true,
  "icon": "Boxes",
  "icon_color": "#84CC16",
  "operations": [
    {
      "id": 17,
      "operation_code": "MOVE_TO_WIP",
      "operation_name": "Передача на склад полуфабриката",
      "is_significant": false,
      ...
    }
  ]
}
```

### Как UI использует `role`

В списке секций (боковое меню, фильтры, доски):

- `role === 'production'` — стандартная иконка станка/молота, цвет секции. Можно открыть доску и работать с заданиями.
- `role === 'storage'` — иконка склада (`Warehouse`/`Boxes`/`Container`/`Truck`). Доска показывает остатки, последние перемещения, но **не показывает** «взять в работу» (нет операций).

### Как UI использует `has_real_operations`

Если у production-секции `has_real_operations === false` (теоретический кейс, не должно случаться), UI показывает на доске плейсхолдер «Нет настроенных операций» с CTA «Добавить операцию».

### Никаких синтетических операций

Раньше: у `WIP_WH` была только `MOVE_TO_WIP` (реальная), а у какой-нибудь свежесозданной секции без операций — фейк `SectionOperation(id=0, is_significant=True)`, который UI принимал за настоящую. Это путало.

Теперь: фейка нет. Если операций нет — `operations: []`. UI проверяет `operations.length > 0`, а не `is_significant`.

---

## 5. Планирование и генерация маршрута (динамический route builder)

Когда Excel-импорт или ручной ввод позиции плана запускает `build_route_from_profile`, секции-склады в `route_sections` профиля **автоматически** становятся transit-этапами:

```python
# В route_builder.py — раньше секция-склад могла породить production-этап
# с фейковой операцией; теперь это всегда transit:
if is_storage_section(section):
    sequence += 1
    steps.append(BuiltRouteStep(
        sequence=sequence,
        section_id=None,
        storage_section_id=section.id,
        stage_kind="transit",
        operation_name=f"Хранение: {section.name}",
        is_significant=False,
        ...
    ))
    continue
```

UI получает `route_snapshot` со снимком маршрута. В нём transit-этапы уже размечены `stage_kind="transit"` и `storage_section_id`. Карточка планируемой позиции отображает их так же, как в route editor — пунктирными ромбами.

---

## 6. Учёт остатков: «пройденные этапы» (`completed_stages_json`)

Когда задание (`WorkTask`) завершается, формируется JSON-список пройденных этапов для аудита и истории.

**Раньше**:
- Использовалась функция `_significant_section_ids` с двумя ad-hoc правилами
- Если у секции есть `SectionOperation` — смотрим `is_significant`
- Если нет — фолбэк на `Section.kind`
- В историю попадали `WH`/`WIP_WH`/`FG_WH` если у них случайно была `is_significant=True` операция

**Теперь**:
- Используется единый классификатор `classify_stages(db, stages)`
- В историю попадают **только** `stage_kind='production'` этапы
- Transit-этапы никогда не попадают в «пройденные» — это не работа, а перемещение

UI истории работы по позиции (timeline) теперь чистый:

```
✓ 1. Сверловка              (DRILL)
✓ 2. Анодирование           (ANOD)
✓ 3. Упаковка               (PACK)
```

Вместо старого:

```
✓ 1. Выдача сырья           (WH)        ← фантомное «выполнение»
✓ 2. Сверловка              (DRILL)
✓ 3. Передача на WIP        (WIP_WH)    ← фантомное «выполнение»
✓ 4. Анодирование           (ANOD)
✓ 5. Упаковка               (PACK)
```

---

## 7. Контракт для фронтенд-разработчика

### Новые/изменённые поля в API

| Endpoint | Поле | Тип | Что значит |
|---|---|---|---|
| `GET /api/sections/all/operations` | `role` | `'production' \| 'storage'` | Новое. Явная роль секции. |
| `GET /api/sections/all/operations` | `has_real_operations` | `bool` | Новое. У секции есть хотя бы одна настоящая `operation_type='production'` операция. |
| `GET /api/sections/storage-points` | — | endpoint | **Новый**. Только storage-секции. Использовать для выбора transit-узла. |
| `GET /api/routes/{id}` (StepOut) | `stage_kind` | `'production' \| 'transit'` | Новое. Смотреть в первую очередь. |
| `GET /api/routes/{id}` (StepOut) | `section_id` | `int \| null` | **Изменилось**: `null` для transit. |
| `GET /api/routes/{id}` (StepOut) | `storage_section_id` | `int \| null` | Новое. Заполнен только для transit. |
| `POST /api/routes/{id}/steps` | принимает `stage_kind`, `storage_section_id` | — | Новое. Валидация: `section_id` секции-склада запрещён в production-режиме. |
| Любой `route_snapshot` | `stage_kind`, `storage_section_id` в каждом step | — | Новое. |

### Хелпер для классификации на фронте

[routeStageClassifier.ts](file:///c:/Users/user/VibeCoding/ktm2000/frontend/src/shared/lib/routeStageClassifier.ts):

```ts
import { isTransitStage, isProductionStage, classifySectionRole } from "@/shared/lib";

isTransitStage({ stage_kind: "transit" })  // true
isProductionStage({ stage_kind: "production", section_id: 5 })  // true
classifySectionRole({ kind: "wip_stock" })  // "storage"
```

Все решения «как отрисовать» должны идти через эти функции, а не через собственные проверки `kind === 'raw_stock'` и т.п.

### Не нужно

- ~~`is_significant` на этапе~~ — legacy-поле, не несёт смысла, не смотрим на него
- ~~Синтетические операции в `/api/sections/all/operations`~~ — больше нет
- ~~Координация между 4 разными сервисами по поводу «что такое pass-through»~~ — теперь один классификатор

---

## 8. Конкретный сценарий пользователя

**Ситуация**: технолог Анна хочет описать маршрут для нового изделия, которое после сверловки временно складируется, потом едет на анодирование, а после анодирования уходит на упаковку.

**Действия Анны**:

1. Открывает «Маршруты» → «Создать маршрут» → вводит имя «ЮП-Новинка v1»
2. Нажимает «Добавить этап»
3. В форме этапа переключатель по умолчанию стоит на «Цех». Анна выбирает цех `DRILL` → операцию `Сверловка`. Жмёт «Сохранить».
4. Нажимает «Добавить этап» снова. На этот раз переключает на «Склад». В выпадающем списке — только `WH`, `WIP_WH`, `FG_WH`, `SHIPMENT`. Выбирает `WIP_WH`. Жмёт «Сохранить».
5. Снова «Добавить этап» → «Цех» → `ANOD` → `ANOD_01 Серебро`. Сохранить.
6. Снова «Добавить этап» → «Цех» → `PACK` → `Упаковка`. Ставит галочку `is_final`. Сохранить.

**Что видит Анна на превью маршрута**:

```
┌──────────┐         ⬨         ┌──────────┐         ┌──────────┐
│ Сверловка │   ─ ─ ─ ─ ─ ─ →   │  WIP_WH  │   ───→  │Анодиров. │  ──→  Упаковка ✓
└──────────┘   транзит         └──────────┘         └──────────┘
```

- Сплошные блоки — реальные цеха, там будут создаваться задания
- Пунктирный ромб с `⬨` — склад-транзит, **между** цехами, не самостоятельный этап
- Галочка на упаковке — финал маршрута

**Что НЕ видит Анна** (раньше это путало):

- ~~Этап «WH — Выдача сырья» в начале~~ — теперь если она его добавит, он будет transit-узлом, а не отдельной работой
- ~~Фантомные операции~~ — система не покажет ничего, чего нет

**Что произойдёт дальше**: когда план по этому маршруту выпустит задания, в `WorkTask` попадут **только** `DRILL`, `ANOD`, `PACK`. Склад `WIP_WH` появится как «адрес доставки» в `Transfer`-заявке между `DRILL` и `ANOD` (existing механика межцеховых трансферов).

---

## 9. Что осталось вне UI-слоя

В этом релизе фронт **не получил** готовых рендер-компонентов для новой модели — только типы и хелпер. Когда потребуется:

- `<RouteStageChip stage={stage}>` — компонент-чип (production = solid, transit = dashed diamond)
- `<TransitNode section={storageSection}>` — отдельный компонент для склада-транзита между этапами
- `RouteEditor` (feature) — форма с переключателем «Цех/Склад» и валидацией

Это естественный следующий шаг, но не блокер для backend-релиза.
