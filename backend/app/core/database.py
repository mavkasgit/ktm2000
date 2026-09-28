from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.SQL_ECHO,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Сессия запроса с финальным коммитом.

    ВНИМАНИЕ, ПОРЯДОК СОБЫТИЙ. FastAPI 0.106+ выполняет код после ``yield``
    ПОСЛЕ отправки ответа клиенту, поэтому коммит ниже происходит уже тогда,
    когда ответ ушёл. Клиент, получивший 2xx и сразу перечитавший данные
    (react-query refetch после мутации), увидит незакоммиченное состояние.

    Поэтому мутирующий эндпоинт обязан коммитить САМ до формирования ответа —
    так уже сделано в `approve_position`, `take_rows_to_work`,
    `delete_position` и др. На коммит ниже полагаться нельзя: он гарантирует
    только закрытие сессии, но не видимость изменений к моменту ответа.

    Именно этим объяснялся баг «approve вернул 200, а кнопка «Утвердить» не
    ушла»: позиция оставалась `draft` для refetch, пока транзакция не
    фиксировалась. e2e-регресс на это — `sawing-four-lengths-cycle.spec.ts`
    (шаг «утверждение всех позиций»).
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
