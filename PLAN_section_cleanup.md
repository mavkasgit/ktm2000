# План рефакторинга: Section Cleanup (одна классификация вместо двух)

> Эпик: `refactor/section-cleanup`. Самостоятельный, не привязан к `refactor/stock-ledger`.
> Один MR. В отдельной ветке. Не делается в рамках текущих сессий UI/правок.

---

## Контекст и мотивация

После рефакторинга Stock Ledger в `Section` появилось **два параллельных классификатора**:

- `Section.kind` (String(20), NOT NULL, default='production') — старая семантика production-routing
- `Section.type` (Enum LocationType, nullable) — новый, добавлен в миграции [023_section_location_type.py](../backend/alembic/versions/023_section_location_type.py) как "новый домен Stock Ledger"

Ни один из них не был доведён до конца:
- `type` (новый) был задуман как замена `kind`, но kind не удалили (Этап 7 из [PLAN_stock_ledger.md](PLAN_stock_ledger.md) не реализован)
- 7 из 11 значений `type` (`LASER, WELDING, PAINTING, ASSEMBLY, TRANSIT, ...`) не используются ни в данных, ни в коде, ни в тестах
- В `operations_defects.py` и `operations_tasks.py` автосоздаются секции с **фантомным** `kind="storage"`, который не входит в `STORAGE_KINDS = frozenset({"raw_stock", "wip_stock", "finished_stock"})` → баг R1: секции SCRAP/QUARANTINE классифицируются как production в роутинге

**Итог**: два классификатора, дублирующих друг друга, с фантомными значениями и непереведённой логикой.

---

## Архитектурное решение

### Один классификатор: `Section.type`

Расширяем старую семантику `kind` и переименовываем в `type`. Никаких новых полей, никаких enum'ов в БД, никаких `SPG.role`. Классификация — **одна колонка с 6 значениями**.

**Значения `Section.type`:**

| Значение | Категория | Примеры секций |
|---|---|---|
| `production` | цех | DRILL, PRESS, SHOT, ANOD, SAW, PACK |
| `raw_stock` | склад сырья | WH |
| `wip_stock` | склад полуфабриката | PREP_STOCK, WIP_WH |
| `finished_stock` | склад готовой продукции | FG_WH, SHIPMENT, SENT |
| `scrap` | склад брака | SCRAP (авто-создаётся) |
| `quarantine` | карантинный склад | QUARANTINE (авто-создаётся) |

6 значений вместо текущих 4 (kind) или 11 (type). Никаких `LASER/WELDING/PAINTING/ASSEMBLY` — если завтра потребуется детализация production, она делается через `code` конкретной секции или через `SectionOperation`, а не через общий enum.

### Что удаляется

| Что | Куда | Как |
|---|---|---|
| Текущий `Section.type` (LocationType enum, 11 значений) | БД, ORM, Python | DROP COLUMN, удалить enum `LocationType` |
| Текущий `Section.kind` (после переименования в `type`) | БД, ORM | RENAME COLUMN `kind` TO `type` |
| `LocationType` Python enum | `backend/app/stock/models.py` | удалить класс |
| `Enum("raw_stock", ..., name="location_type")` в ORM | `backend/app/models/section.py` | удалить, оставить `String(20)` |
| 7 неиспользуемых значений | БД enum (PostgreSQL) | миграция `ALTER TYPE` / DROP COLUMN |
| Фантомный `kind="storage"` в автосоздании | `operations_defects.py`, `operations_tasks.py` | заменить на `kind="scrap"` / `kind="quarantine"` (после R1 fix, до переименования) |

### Что НЕ трогается (граница ответственности `type`)

`Section.type` отвечает **только** на вопрос "что это за место?". Не на:

- **Сколько материала** → `StockBalance`, проекция из `StockTransaction`
- **Качество материала** → `StockTransaction.from_quality_state`, `to_quality_state` (QualityState: GOOD/SCRAP/REWORK/QUARANTINE)
- **Что сделали** (брак/выпуск) → `StockTransaction.reason` (Reason: ISSUE_TO_WORK, COMPLETE, SCRAP, FINAL_RELEASE, ...)
- **Текущая задача** → `WorkTask`
- **Перемещение** → `Transfer` (бизнес-обёртка над парой StockTransaction)
- **Принадлежность к ГХП** → `spg_sections` (many-to-many), без новых полей в SPG

---

## Что меняется

### Модель

```python
# backend/app/models/section.py
class Section(Base):
    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    # ТОЛЬКО ОДИН КЛАССИФИКАТОР
    type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        default="production", server_default=text("'production'"),
        # 6 допустимых значений — проверяется в API/ORM валидаторе
    )
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    icon_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    created_at: Mapped[datetime] = mapped_column(...)
    # relationships — без изменений
```

### route_storage_classifier.py

```python
# backend/app/services/route_storage_classifier.py
STORAGE_TYPES = frozenset({"raw_stock", "wip_stock", "finished_stock", "scrap", "quarantine"})

def is_storage_section(section: Section | None) -> bool:
    if section is None: return False
    return section.type in STORAGE_TYPES

def is_production_section(section: Section | None) -> bool:
    if section is None: return False
    return section.type == "production"
```

`STORAGE_TYPES` теперь включает `scrap` и `quarantine` (раньше kind их не покрывал → баг R1).

### 4 SQL-запроса в operations_defects.py / operations_tasks.py

```python
# Было:
.where(Section.type == 'scrap')      # operations_defects.py:196, tasks.py:279
.where(Section.type == 'quarantine') # operations_defects.py:321
.where(Section.type == 'finished_stock')  # tasks.py:406

# Стало (после рефакторинга — type единственный):
.where(Section.type == 'scrap')      # БЕЗ ИЗМЕНЕНИЙ — type уже единственный
.where(Section.type == 'quarantine') # БЕЗ ИЗМЕНЕНИЙ
.where(Section.type == 'finished_stock')  # БЕЗ ИЗМЕНЕНИЙ
```

### Авто-создание секций (R1 fix)

```python
# Было (operations_defects.py:200, operations_tasks.py:285):
_Section(
    code="SCRAP", name="Scrap",
    kind="storage",   # ← фантом, не в STORAGE_KINDS
    type="scrap", ...
)

# Стало (после рефакторинга — единое поле type):
_Section(
    code="SCRAP", name="Scrap",
    type="scrap",  # R1 fix: type=scrap, попадает в STORAGE_TYPES
)
```

### 30+ мест `section.kind == "production"` → `section.type == "production"`

Прямая замена во всех файлах, где сейчас `kind`:

| Файл | Строки | Что |
|---|---|---|
| `backend/app/transfers/services.py` | 77 | `sec.kind in {...}` → `sec.type in {...}` |
| `backend/app/transfers/queries.py` | 279, 381, 388 | то же |
| `backend/app/services/plan_generation.py` | 225, 504, 511 | `s.kind != "production"` → `s.type != "production"` |
| `backend/app/services/route_builder.py` | 148, 155, 184, 232 | `section_kind=section.kind` → `section_kind=section.type` |
| `backend/app/services/route_storage_classifier.py` | 39, 46 | внутренние проверки |
| `backend/app/services/production_planning_rows.py` | 740 | `section_kind=section.kind` |
| `backend/app/api/routes/production_plans.py` | 787, 881 | то же |
| `backend/app/api/routes/routes.py` | 361, 485 | error messages |
| `backend/app/api/routes/production_planning.py` | 498 | `section_kind=section.kind` |
| `backend/app/api/routes/sections.py` | 147, 185, 194 | API response, фильтры |
| `backend/app/api/routes/spg.py` | 105, 177 | SPG snapshot |
| `backend/app/services/shopfloor/operations_tasks.py` | 39, 67, 491, 495 | валидация |
| `backend/app/services/shopfloor/queries_sections.py` | 478 | `kind=section.kind` в response |
| `backend/app/seeds/seeders/sections_seeder.py` | 9-22 | сиды: заменить поле |
| `backend/app/seeds/seeders/spgs_seeder.py` | (использует kind) | то же |
| `backend/app/seeds/spgs.py` | SPGS_DATA | если использует kind |

### API

```python
# backend/app/api/routes/sections.py
class SectionBase(BaseModel):
    code: str
    name: str
    type: str  # было: kind + type
    icon: str | None = None
    icon_color: str | None = None
    sort_order: int = 0
    is_active: bool = True
    # Удалено: kind, type (отдельно)

class SectionIn(SectionBase): ...
class SectionPatch(BaseModel):
    # Все поля опциональны
    name: str | None = None
    type: str | None = None  # единственный классификатор
    # Удалено: kind
```

### Frontend

```typescript
// frontend/src/shared/api/sections.ts
export type Section = {
  id: number;
  code: string;
  name: string;
  type: SectionType;  // было: kind + type (отдельно)
  icon: string | null;
  icon_color: string | null;
  sort_order: number;
  is_active: boolean;
};

export type SectionType =
  | "production"
  | "raw_stock"
  | "wip_stock"
  | "finished_stock"
  | "scrap"
  | "quarantine";
```

В `SectionsPage`, `SectionSelect`, `SpgSelector`, фильтрах — заменить все ссылки на `kind` на `type`.

### Тесты

В `backend/tests/stock/` (~30 мест):

```python
# Было (test_stock_command.py:111):
laser = await _make_location(session, code="LASER", name="Laser", loc_type="laser")

# Стало:
laser = await _make_location(session, code="LASER", name="Laser", loc_type="production")
# или просто:
laser = await _make_location(session, code="LASER", name="Laser")
# (если _make_location не требует loc_type как обязательный)
```

**Удалить** фикстуры, которые создают локации с `loc_type="laser"/"welding"/"painting"/"assembly"` и проверяют специфичное поведение. Эти тесты писались на будущее, которое не наступило — production-секции в реальных данных все имеют `type=production`, и код их одинаково обрабатывает.

### Сиды

```python
# backend/app/seeds/seeders/sections_seeder.py
SECTIONS_DATA = [
    {"code": "WH", "name": "Склад сырья", "type": "raw_stock", ...},
    {"code": "DRILL", "name": "Сверловка", "type": "production", ...},
    # ... все 12 секций
]
```

`type` — единственное поле классификации. `kind` удалено.

---

## План реализации

### Подготовка

1. Создать ветку `refactor/section-cleanup` от `main` (или текущей рабочей).
2. Согласовать сроки: 1 рабочий день full-time.

### Шаг 1: R1 fix (1 час)

**До переименования**, чтобы не сломать production:

- [ ] `operations_defects.py:200,325` — заменить `kind="storage"` → `kind="raw_stock"` (или `scrap`/`quarantine` по контексту)
- [ ] `operations_tasks.py:285` — то же
- [ ] Проверить `route_storage_classifier.STORAGE_KINDS` — добавить `scrap`, `quarantine`
- [ ] Прогнать `pytest backend/tests/stock/`

### Шаг 2: Миграция (1 час)

- [ ] Создать `backend/alembic/versions/025_section_unified_type.py`:
  - `ALTER TABLE sections RENAME COLUMN kind TO type` (сначала type нужно удалить, если он есть)
  - `DROP COLUMN type` (старый LocationType)
  - Расширить default: `type String(20) NOT NULL DEFAULT 'production'`
  - Бэкфил: где `type IS NULL` → `type = 'production'`
- [ ] Проверить: `alembic upgrade head` и `alembic downgrade -1` работают
- [ ] Проверить: данные в БД корректны (12 секций, типы заполнены)

### Шаг 3: ORM (30 мин)

- [ ] `backend/app/models/section.py`:
  - Удалить старую колонку `type` (LocationType Enum)
  - Переименовать `kind` → `type`
  - Заменить `String(20)` остаётся, но с `default="production"`
  - Обновить комментарий (убрать "на Этапе 7 kind удаляется" — он удалён)
- [ ] `backend/app/stock/models.py`:
  - Удалить класс `LocationType`
  - Удалить все упоминания из `__init__.py` и `models/__init__.py`

### Шаг 4: route_storage_classifier.py (30 мин)

- [ ] `STORAGE_KINDS` → `STORAGE_TYPES`, добавить `scrap`, `quarantine`
- [ ] `is_storage_section(s)`: `s.kind in STORAGE_KINDS` → `s.type in STORAGE_TYPES`
- [ ] `is_production_section(s)`: `s.kind == "production"` → `s.type == "production"`
- [ ] Обновить docstring

### Шаг 5: 30+ правок `kind` → `type` (2-3 часа)

Механически по списку файлов выше:
- [ ] `transfers/services.py`, `transfers/queries.py`
- [ ] `plan_generation.py`, `route_builder.py`, `production_planning_rows.py`
- [ ] `production_plans.py`, `routes.py`, `production_planning.py`, `sections.py`, `spg.py`
- [ ] `shopfloor/operations_tasks.py`, `shopfloor/queries_sections.py`
- [ ] `seeds/seeders/sections_seeder.py`, `seeds/seeders/spgs_seeder.py`, `seeds/spgs.py`

### Шаг 6: API (1 час)

- [ ] `backend/app/api/routes/sections.py`:
  - `SectionBase`, `SectionIn`, `SectionPatch` — заменить `kind` + `type` на единый `type`
  - Обновить Pydantic валидацию: `type in {"production", "raw_stock", "wip_stock", "finished_stock", "scrap", "quarantine"}`
  - Внутренние `where(Section.kind.in_(...))` → `where(Section.type.in_(...))`
- [ ] `backend/app/api/routes/spg.py`: убрать `kind` из response

### Шаг 7: Frontend (1-2 часа)

- [ ] `frontend/src/shared/api/sections.ts`: убрать `kind`, добавить `type: SectionType`
- [ ] `SectionSelect`, `SpgSelector`, `SectionsPage` — заменить `kind` на `type`
- [ ] `SectionKind` тип → `SectionType` (6 значений)
- [ ] Проверить e2e тесты: `frontend/e2e/`

### Шаг 8: Тесты (1-2 часа)

- [ ] `backend/tests/stock/test_stock_command.py`: заменить `loc_type="laser"/etc` на `loc_type="production"` или удалить, если поведение идентично
- [ ] `test_task_cache_stage4.py`, `test_transfer_stage2.py` — то же
- [ ] Прогнать `pytest backend/tests/` — все зелёные

### Шаг 9: Документация (30 мин)

- [ ] Обновить `AGENTS.md`: убрать упоминания `kind` и `LocationType`, оставить одно `Section.type`
- [ ] Обновить `PLAN_stock_ledger.md`: Этап 7 теперь выполнен (через Этап 8)
- [ ] Создать коммит `feat(section): унифицировать классификатор Section — kind → type, удалить LocationType enum`

---

## Оценка объёма

| Этап | Часы |
|---|---|
| R1 fix | 1 |
| Миграция | 1 |
| ORM | 0.5 |
| route_storage_classifier | 0.5 |
| 30+ правок kind → type | 2-3 |
| API | 1 |
| Frontend | 1-2 |
| Тесты | 1-2 |
| Документация | 0.5 |
| **ИТОГО** | **8-11 часов** (1-1.5 рабочего дня) |

**Один MR. Одна ветка. Никаких feature flag'ов — kind выпиливается, type остаётся.**

---

## Чеклист готовности

- [ ] В коде нет упоминаний `Section.kind` (поиск `rg "kind" backend/app/` — только про operation kind и прочее, не про Section)
- [ ] В коде нет упоминаний `LocationType` enum
- [ ] В БД нет колонки `kind` (только `type`)
- [ ] PostgreSQL enum `location_type` удалён через миграцию
- [ ] `pytest backend/tests/` — все зелёные
- [ ] `frontend/e2e/` — все зелёные
- [ ] В API `/api/sections` response содержит `type`, не `kind`
- [ ] В `route_storage_classifier.is_storage_section(s)` корректно классифицирует SCRAP и QUARANTINE
- [ ] Документация обновлена (AGENTS.md, PLAN_stock_ledger.md)
- [ ] Линтер/тайпчекер фронта зелёный
- [ ] CodeGraph sync выполнен

---

## Что НЕ делается в этом эпике (out of scope)

- Удаление legacy `SpgRemainder`, `Movement` — это Этапы 0-6 из [PLAN_stock_ledger.md](PLAN_stock_ledger.md), уже завершены
- Удаление `stock_v1` API — Этап 7 из [PLAN_stock_ledger.md](PLAN_stock_ledger.md), отдельная задача
- Изменения в `StockTransaction`/`StockBalance` — это ядро ledger'а, не трогаем
- Изменения в `WorkTask`, `Transfer` — бизнес-логика, не трогаем
- Добавление новых `type`-значений (`LASER/WELDING/PAINTING/ASSEMBLY`) — не нужно, конкретные участки идентифицируются через `code`
- Детализация production-секций по типу работ — если когда-нибудь потребуется, делается через `SectionOperation.operation_type` или через `code`-based классификатор в `route_storage_classifier`

---

## Согласование

- [ ] Команда: ?
- [ ] Владелец MR: ?
- [ ] Дата старта: ?
- [ ] Дата завершения: ?
