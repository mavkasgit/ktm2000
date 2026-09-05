"""Domain exceptions (KTM host adapter).

Services raise :class:`KTMException` for domain failures; the global handler
(``app.api.exception_handlers.ktm_exception_handler``) maps it to a JSON
response. Optional ``headers`` propagate verbatim (e.g. ``WWW-Authenticate``).
"""


class KTMException(Exception):
    def __init__(
        self,
        message: str,
        error_code: str = "ktm_error",
        status_code: int = 500,
        headers: dict[str, str] | None = None,
    ):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.headers = headers
        super().__init__(self.message)

    @property
    def detail(self) -> str:
        """Совместимость с HTTPException-стилем доступа (exc.detail)."""
        return self.message


class NotFoundError(KTMException):
    def __init__(self, message: str, error_code: str = "not_found"):
        super().__init__(message, error_code, status_code=404)


class IdempotencyConflict(KTMException):
    """Гонка идемпотентности на non-ledger таблицах (ADR-0022, тикет #135).

    Unique-бэкстоп на ``<table>.idempotency_key`` поймал INSERT с ключом,
    который конкурент уже провёл между нашим replay-SELECT и flush.
    Проигравшая подача отклоняется ЦЕЛИКОМ (409) — side effects вызывающего
    в текущем request-transaction откатываются вместе с ней; клиент
    повторяет операцию с тем же ключом и попадает в replay-ветку
    предварительной проверки. Наследует KTMException, а не ValueError:
    shopfloor-роуты переводят ValueError в 400.
    """

    def __init__(self, entity: str, idempotency_key: str) -> None:
        super().__init__(
            message=(
                f"Операция с idempotency_key={idempotency_key!r} уже проведена "
                "конкурентным запросом; повторите запрос с тем же ключом."
            ),
            error_code=f"{entity}_idempotency_conflict",
            status_code=409,
        )
