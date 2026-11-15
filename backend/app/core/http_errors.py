"""Sanitized errors for the private API."""

from fastapi import Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.core.logging import logger
from backend.app.repositories.candidate_profile import ProfileNotFoundError
from backend.app.services.credit_manager import CreditBudgetExhaustedError


def install_exception_handlers(app):
    @app.exception_handler(CreditBudgetExhaustedError)
    async def credit_budget_exception_handler(
        request: Request, exc: CreditBudgetExhaustedError
    ):
        logger.warning(f"Credit budget check failed: {exc}")
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": str(exc), "error_type": "credit_budget_exhausted"},
        )

    @app.exception_handler(ValueError)
    async def value_error_exception_handler(request: Request, exc: ValueError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "Invalid argument", "error_type": "invalid_argument"},
        )

    @app.exception_handler(RequestValidationError)
    async def private_validation_error(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/v1/"):
            return JSONResponse(
                {"detail": "Invalid request"},
                status_code=422,
                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
            )
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(LookupError)
    @app.exception_handler(ProfileNotFoundError)
    async def missing_saved_record(request: Request, exc: Exception):
        return JSONResponse(
            {"detail": "Saved record or candidate profile not found"},
            status_code=404,
            headers={"Cache-Control": "no-store"},
        )
