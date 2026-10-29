from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.errors import NotFoundError, RuleViolationError, TooLargeError


async def _not_found(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


async def _too_large(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_413_CONTENT_TOO_LARGE, content={"detail": str(exc)})


async def _rule_violation(request: Request, exc: Exception) -> JSONResponse:
    extra = exc.extra if isinstance(exc, RuleViolationError) else {}
    content = {"detail": str(exc), **extra}

    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=content)


def register_error_handlers(app: FastAPI) -> None:
    """Map the app's error kinds to HTTP responses."""
    app.add_exception_handler(NotFoundError, _not_found)
    app.add_exception_handler(TooLargeError, _too_large)
    app.add_exception_handler(RuleViolationError, _rule_violation)
