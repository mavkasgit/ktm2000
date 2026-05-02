# 02. Data Model

## Общие решения

База данных: PostgreSQL.

ORM: SQLAlchemy 2.x.

Миграции: Alembic.

Идентификаторы: `bigint generated always as identity primary key`.

Factoryflow использует числовые `bigint identity` primary keys для внутренней реляционной идентичности, как в HRMS. Человекочитаемые бизнес-номера хранятся отдельно в полях `*_no`. Дедупликация импорта выполняется не через primary key, а через dedicated source поля: `source_system`, `source_ref`, `source_fingerprint`, `file_sha256`, `source_row_hash`, `external_plan_id`.

UUID не используется как primary key в MVP. Если позже появится внешний публичный API или интеграции, можно добавить `public_id uuid unique` как отдельное поле без замены внутренних PK.

Бизнес-номера:

- `plan_no`: `PP-YYYY-000001`;
- `batch_no`: `RB-YYYY-000001`;
- `transfer_no`: `TR-YYYY-000001`.

Номера должны генерироваться backend-сервисом в транзакции. Пользователь видит бизнес-номер, внутренний `id` остается технической ссылкой.

Время: `timestamptz`, хранить в UTC, показывать в локальной зоне пользователя.

Количество: `numeric(14, 3)`, даже если на старте используются штуки. Это не ломает будущие килограммы, метры и дробные нормы.

Soft delete: для справочников использовать `is_active`, для документов - статусы. Физическое удаление разрешать только для черновиков без движений.

## Таблицы

### users

- `id bigint generated always as identity primary key`
- `email text unique not null`
- `password_hash text not null`
- `full_name text not null`
- `role user_role not null`
- `section_id bigint null references sections(id)`
- `is_active boolean not null default true`
- `created_at timestamptz not null`

### sections

- `id bigint generated always as identity primary key`
- `code text unique not null`
- `name text not null`
- `description text null`
- `is_active boolean not null default true`
- `created_at timestamptz not null`

### products

- `id bigint generated always as identity primary key`
- `sku text unique not null`
- `name text not null`
- `type product_type not null`
- `unit text not null`
- `is_active boolean not null default true`
- `notes text null`
- `created_at timestamptz not null`

### boms

- `id bigint generated always as identity primary key`
- `product_id bigint not null references products(id)`
- `version text not null`
- `is_active boolean not null default true`
- `created_at timestamptz not null`

Индексы:

- unique partial index on `(product_id)` where `is_active = true`.

### bom_lines

- `id bigint generated always as identity primary key`
- `bom_id bigint not null references boms(id)`
- `component_product_id bigint not null references products(id)`
- `quantity numeric(14,3) not null`
- `unit text not null`

Ограничения:

- `quantity > 0`;
- unique `(bom_id, component_product_id)`.

### production_routes

- `id bigint generated always as identity primary key`
- `product_id bigint not null references products(id)`
- `name text not null`
- `version text not null`
- `is_active boolean not null default true`
- `created_at timestamptz not null`

Индексы:

- unique partial index on `(product_id)` where `is_active = true`.

Правила:

- изменение маршрута после использования создает новую запись/версию;
- уже использованные route и route_steps не редактируются так, чтобы изменить историю запущенных задач.

### route_steps

- `id bigint generated always as identity primary key`
- `route_id bigint not null references production_routes(id)`
- `sequence integer not null`
- `section_id bigint not null references sections(id)`
- `operation_name text not null`
- `norm_time_minutes integer null`
- `requires_acceptance boolean not null default true`
- `allow_parallel boolean not null default false`
- `is_final boolean not null default false`

Ограничения:

- `sequence > 0`;
- unique `(route_id, sequence)`;
- только один `is_final = true` на маршрут.

### import_files

- `id bigint generated always as identity primary key`
- `original_filename text not null`
- `stored_path text not null`
- `file_sha256 text not null`
- `uploaded_by bigint not null references users(id)`
- `uploaded_at timestamptz not null`

### production_plans

- `id bigint generated always as identity primary key`
- `plan_no text unique not null`
- `name text not null`
- `period_start date null`
- `period_end date null`
- `status production_plan_status not null`
- `created_by bigint not null references users(id)`
- `created_at timestamptz not null`
- `approved_by bigint null references users(id)`
- `approved_at timestamptz null`
- `released_at timestamptz null`

Правила:

- период может быть месяцем, неделей, кварталом или произвольным диапазоном;
- план может содержать позиции из разных источников;
- запуск в производство можно делать по выбранным позициям, а не только по всему плану.

### import_batches

- `id bigint generated always as identity primary key`
- `production_plan_id bigint not null references production_plans(id)`
- `source_file_id bigint not null references import_files(id)`
- `source_system text not null default 'excel'`
- `source_ref text null`
- `mode import_mode not null`
- `status import_batch_status not null`
- `created_by bigint not null references users(id)`
- `created_at timestamptz not null`

`mode`:

- `create_plan`;
- `append_to_plan`;
- `replace_draft_from_same_source`.

### plan_positions

- `id bigint generated always as identity primary key`
- `production_plan_id bigint not null references production_plans(id)`
- `product_id bigint null references products(id)`
- `source_type plan_source_type not null`
- `source_system text null`
- `source_ref text null`
- `source_fingerprint text null`
- `external_plan_id text null`
- `source_row_hash text null`
- `import_batch_id bigint null references import_batches(id)`
- `source_sku text not null`
- `source_name text null`
- `quantity numeric(14,3) not null`
- `source_payload jsonb not null default '{}'`
- `due_date date null`
- `period_start date null`
- `period_end date null`
- `customer text null`
- `priority integer not null default 100`
- `source_row_number integer null`
- `status plan_position_status not null`
- `validation_status plan_position_validation_status not null`
- `validation_errors jsonb not null default '[]'`
- `approved_by bigint null references users(id)`
- `approved_at timestamptz null`
- `released_at timestamptz null`

Ограничения:

- `quantity > 0`;
- unique `(import_batch_id, source_row_number)` where `import_batch_id is not null`;
- unique `(source_system, source_ref)` where `source_system is not null and source_ref is not null`;
- unique `(import_batch_id, source_row_hash)` where `import_batch_id is not null and source_row_hash is not null`;
- запущенные позиции нельзя менять по `product_id`, `quantity`, `period_start`, `period_end`, `due_date`.

### plan_adjustments

- `id bigint generated always as identity primary key`
- `production_plan_id bigint not null references production_plans(id)`
- `plan_position_id bigint not null references plan_positions(id)`
- `adjustment_type plan_adjustment_type not null`
- `quantity_delta numeric(14,3) null`
- `new_due_date date null`
- `reason text not null`
- `status plan_adjustment_status not null`
- `created_by bigint not null references users(id)`
- `created_at timestamptz not null`
- `applied_by bigint null references users(id)`
- `applied_at timestamptz null`

Правила:

- исходная позиция не переписывается;
- примененная корректировка создает новую позицию, меняет оставшуюся потребность или отменяет незапущенный остаток.

### release_batches

- `id bigint generated always as identity primary key`
- `batch_no text unique not null`
- `production_plan_id bigint not null references production_plans(id)`
- `name text not null`
- `batch_type release_batch_type not null`
- `status release_batch_status not null`
- `horizon_start date null`
- `horizon_end date null`
- `created_by bigint not null references users(id)`
- `created_at timestamptz not null`
- `released_by bigint null references users(id)`
- `released_at timestamptz null`

`batch_type`:

- `near_term`;
- `weekly`;
- `future_preparation`;
- `manual`.

### release_batch_positions

- `id bigint generated always as identity primary key`
- `release_batch_id bigint not null references release_batches(id)`
- `plan_position_id bigint not null references plan_positions(id)`
- `release_quantity numeric(14,3) not null`
- `route_id bigint not null references production_routes(id)`
- `route_version text not null`
- `route_snapshot jsonb not null default '{}'`

Ограничения:

- `release_quantity > 0`;
- нельзя суммарно запустить больше утвержденного количества позиции.

### plan_change_sets

- `id bigint generated always as identity primary key`
- `production_plan_id bigint not null references production_plans(id)`
- `import_batch_id bigint null references import_batches(id)`
- `change_type plan_change_set_type not null`
- `status plan_change_set_status not null`
- `created_by bigint not null references users(id)`
- `created_at timestamptz not null`
- `applied_by bigint null references users(id)`
- `applied_at timestamptz null`
- `rolled_back_by bigint null references users(id)`
- `rolled_back_at timestamptz null`

Назначение:

- хранит набор изменений перед применением импорта или массовой правки;
- позволяет наглядно показать diff пользователю;
- позволяет откатить ошибочно примененный импорт, если затронутые позиции не были запущены в производство.

### plan_change_items

- `id bigint generated always as identity primary key`
- `change_set_id bigint not null references plan_change_sets(id)`
- `plan_position_id bigint null references plan_positions(id)`
- `change_action plan_change_action not null`
- `before_data jsonb null`
- `after_data jsonb not null`
- `status plan_change_item_status not null`

`change_action`:

- `create_position`;
- `update_draft_position`;
- `mark_possible_duplicate`;
- `ignore_unchanged`;
- `cancel_draft_position`.

### internal_plans

- `id bigint generated always as identity primary key`
- `production_plan_id bigint not null references production_plans(id)`
- `release_batch_id bigint null references release_batches(id)`
- `status internal_plan_status not null`
- `created_at timestamptz not null`

### section_plan_lines

- `id bigint generated always as identity primary key`
- `internal_plan_id bigint not null references internal_plans(id)`
- `plan_position_id bigint not null references plan_positions(id)`
- `section_id bigint not null references sections(id)`
- `product_id bigint not null references products(id)`
- `route_id bigint not null references production_routes(id)`
- `route_step_id bigint not null references route_steps(id)`
- `sequence integer not null`
- `planned_quantity numeric(14,3) not null`
- `due_date date null`
- `cached_available_quantity numeric(14,3) not null default 0`
- `cached_issued_quantity numeric(14,3) not null default 0`
- `cached_completed_quantity numeric(14,3) not null default 0`
- `cached_transferred_quantity numeric(14,3) not null default 0`
- `cached_received_quantity numeric(14,3) not null default 0`
- `cached_rejected_quantity numeric(14,3) not null default 0`
- `cached_remaining_quantity numeric(14,3) not null default 0`

Ограничения:

- unique `(internal_plan_id, plan_position_id, route_step_id)`.

### work_tasks

- `id bigint generated always as identity primary key`
- `section_plan_line_id bigint not null references section_plan_lines(id)`
- `section_id bigint not null references sections(id)`
- `product_id bigint not null references products(id)`
- `route_step_id bigint not null references route_steps(id)`
- `planned_quantity numeric(14,3) not null`
- `status work_task_status not null`
- `due_date date null`
- `assigned_to bigint null references users(id)`
- `created_at timestamptz not null`
- `cached_available_quantity numeric(14,3) not null default 0`
- `cached_issued_quantity numeric(14,3) not null default 0`
- `cached_in_work_quantity numeric(14,3) not null default 0`
- `cached_completed_quantity numeric(14,3) not null default 0`
- `cached_transferred_quantity numeric(14,3) not null default 0`
- `cached_received_quantity numeric(14,3) not null default 0`
- `cached_rejected_quantity numeric(14,3) not null default 0`
- `cached_remaining_quantity numeric(14,3) not null default 0`

### transfers

- `id bigint generated always as identity primary key`
- `transfer_no text unique not null`
- `from_task_id bigint not null references work_tasks(id)`
- `to_task_id bigint not null references work_tasks(id)`
- `from_section_id bigint not null references sections(id)`
- `to_section_id bigint not null references sections(id)`
- `product_id bigint not null references products(id)`
- `sent_quantity numeric(14,3) not null`
- `accepted_quantity numeric(14,3) null`
- `rejected_quantity numeric(14,3) null`
- `status transfer_status not null`
- `sent_by bigint null references users(id)`
- `sent_at timestamptz null`
- `accepted_by bigint null references users(id)`
- `accepted_at timestamptz null`
- `comment text null`

### movements

- `id bigint generated always as identity primary key`
- `product_id bigint not null references products(id)`
- `task_id bigint null references work_tasks(id)`
- `transfer_id bigint null references transfers(id)`
- `from_section_id bigint null references sections(id)`
- `to_section_id bigint null references sections(id)`
- `movement_type movement_type not null`
- `quantity numeric(14,3) not null`
- `created_by bigint not null references users(id)`
- `created_at timestamptz not null`
- `comment text null`

Ограничения:

- `quantity > 0`;
- movement rows are append-only.

### defects

- `id bigint generated always as identity primary key`
- `product_id bigint not null references products(id)`
- `section_id bigint not null references sections(id)`
- `task_id bigint not null references work_tasks(id)`
- `movement_id bigint null references movements(id)`
- `quantity numeric(14,3) not null`
- `reason defect_reason not null`
- `decision defect_decision null`
- `status defect_status not null`
- `responsible_section_id bigint null references sections(id)`
- `comment text null`
- `created_by bigint not null references users(id)`
- `created_at timestamptz not null`

### rework_tasks

- `id bigint generated always as identity primary key`
- `defect_id bigint not null references defects(id)`
- `source_task_id bigint not null references work_tasks(id)`
- `section_id bigint not null references sections(id)`
- `product_id bigint not null references products(id)`
- `quantity numeric(14,3) not null`
- `status rework_task_status not null`
- `created_by bigint not null references users(id)`
- `created_at timestamptz not null`
- `closed_at timestamptz null`

Правила:

- `quantity > 0`;
- одна активная задача доработки на один дефект, если бизнес не разрешит дробление.

## Агрегаты

Для чтения экранов нужны агрегаты:

- task totals;
- section plan totals;
- production plan progress;
- transfer discrepancies.

Для MVP используем кеш итогов в `work_tasks` и `section_plan_lines`, чтобы быстро показывать маршрут и количества по каждому этапу. Источник истины - `movements`. Любое расхождение кеша с журналом считается ошибкой, для диагностики нужна служебная команда пересчета кеша.

## Транзакционные границы

Одна пользовательская операция должна быть одной транзакцией:

- выдать в работу -> создать `movement`, обновить статус задачи;
- отметить выполнение -> создать `movement`, обновить статус, обновить кеши;
- отправить передачу -> создать `transfer`, создать `transfer_send`, обновить статус, обновить кеши;
- принять передачу -> обновить `transfer`, создать `transfer_receive`, при расхождении создать `defect` или `reject`, обновить доступность следующей задачи и кеши;
- создать решение по браку -> обновить `defect`, при необходимости создать `rework_task` или `scrap` movement;
- применить корректировку плана -> создать `plan_adjustment`, применить ее без изменения истории исходной позиции.



