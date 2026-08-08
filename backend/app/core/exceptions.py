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
