from asyncio import run
from logging.config import fileConfig

from app.core.env_file import apply_env_file

# DSN берём из env-файла (`.env.dev` / `$ENV_FILE`), и он перекрывает переменные
# окружения процесса. Иначе устаревшая `DATABASE_URL` в окружении (протечка из
# шелла агента/CI) уводила бы миграции на чужую БД — вплоть до отказа
# подключения при полностью рабочем Postgres. Вызываем до импорта приложения.
apply_env_file()


import app.models  # noqa: F401
from alembic import context
from alembic.ddl.postgresql import PostgresqlImpl
from app.core.config import settings
from app.models.base import Base
from sqlalchemy import Column, MetaData, PrimaryKeyConstraint, String, Table, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


#: Служебные таблицы шагов пересчёта. Их создают миграции-пересчёты
#: (`071_route_code_identity`, `218_hanger_norm_key_normalization` и т.п.) как
#: временные артефакты, и на них опираются тесты (`tests/test_migrations.py`
#: читает `hanger_norm_key_migration`). В моделях они не описаны намеренно —
#: autogenerate не должен предлагать их удаление, иначе `alembic check` красный
#: всегда (тикет #261).
MIGRATION_HELPER_TABLES = frozenset(
    {
        "route_signature_migration",
        "route_code_migration",
        "route_stage_significance_migration",
        "hanger_norm_key_migration",
    }
)


def include_object(object, name, type_, reflected, compare_to):
    return not (
        type_ == "table"
        and (name == "alembic_version" or name in MIGRATION_HELPER_TABLES)
    )


class WideVersionTablePostgresqlImpl(PostgresqlImpl):
    """Widen alembic_version.version_num to varchar(64).

    Alembic creates the version column with String(32) by default
    (alembic.ddl.impl.DefaultImpl.version_table_impl). Long descriptive
    revision ids (e.g. "026_stock_reason_transform_consume", 34 chars) exceed
    that limit and break `alembic upgrade` on fresh databases. Override the
    hook so the version table is created with room for longer ids.
    """

    __dialect__ = "postgresql"

    def version_table_impl(
        self,
        *,
        version_table: str,
        version_table_schema: str | None,
        version_table_pk: bool,
        **kw: object,
    ) -> Table:
        vt = Table(
            version_table,
            MetaData(),
            Column("version_num", String(64), nullable=False),
            schema=version_table_schema,
        )
        if version_table_pk:
            vt.append_constraint(
                PrimaryKeyConstraint("version_num", name=f"{version_table}_pkc")
            )
        return vt


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run(run_migrations_online())