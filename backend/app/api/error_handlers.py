from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.errors import NotFoundError, RuleViolationError


async def _not_found(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


async def _rule_violation(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": str(exc)}
    )


def register_error_handlers(app: FastAPI) -> None:
    """Map the app's error kinds to HTTP responses."""
    app.add_exception_handler(NotFoundError, _not_found)
    app.add_exception_handler(RuleViolationError, _rule_violation)
