from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.exceptions import KTMException


async def ktm_exception_handler(request: Request, exc: KTMException):
    # exc гарантированно KTMException (регистрация add_exception_handler по этому типу)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.message,
            "error_code": exc.error_code,
            "status_code": exc.status_code,
        },
        headers=exc.headers,
    )
