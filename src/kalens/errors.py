"""
The library's domain errors, and the handler that maps them to HTTP.

WHY THE LIBRARY HAS ITS OWN
    A host has its own domain-error hierarchy and its own handler. If this
    library raised the host's classes it would have to import the host; if it
    shared one base with every host, two libraries in one app would fight
    over a single handler. So kalens' errors subclass `kalens.DomainError`
    only, and the host registers this module's handler next to its own:

        kalens.register_error_handlers(app)

    The response body is the same `{"detail": ...}` shape `HTTPException`
    gives, so a host's clients can't tell which side raised.

WHAT RAISES THESE TODAY
    Nothing yet: existing routes and dependencies still raise `HTTPException`,
    and move over as they're changed, not in passing (CLAUDE.md). Registering
    the handler now costs nothing and means the first change that raises one
    doesn't also have to change every host.
"""
from typing import Any, Dict, List, Optional, Tuple, Type, Union

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from kalens.models.core import CoreModel


class DomainError(Exception):
    def __init__(self, detail: str, *, headers: Optional[Dict[str, str]] = None) -> None:
        super().__init__(detail)
        self.detail = detail
        # Response headers the error needs, e.g. `WWW-Authenticate` on a 401.
        self.headers = headers


class NotAuthenticatedError(DomainError):
    pass


class NotFoundError(DomainError):
    pass


class PermissionDeniedError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class ServiceUnavailableError(DomainError):
    """Something the request can't do without is unreachable."""


# Most specific first: the first class the error is an instance of wins. A
# subclass that needs a different code goes above its parent.
STATUS_CODES: List[Tuple[Type[DomainError], int]] = [
    (NotAuthenticatedError, status.HTTP_401_UNAUTHORIZED),
    (NotFoundError, status.HTTP_404_NOT_FOUND),
    (PermissionDeniedError, status.HTTP_403_FORBIDDEN),
    (ConflictError, status.HTTP_409_CONFLICT),
    (ServiceUnavailableError, status.HTTP_503_SERVICE_UNAVAILABLE),
    (DomainError, status.HTTP_400_BAD_REQUEST),
]


class ErrorResponse(CoreModel):
    detail: str


def status_code_for(error: Type[DomainError]) -> int:
    return next(code for parent, code in STATUS_CODES if issubclass(error, parent))


def error_responses(*errors: Type[DomainError]) -> Dict[Union[int, str], Dict[str, Any]]:
    """`responses=` for a library route that can raise these, built from the
    same table the handler uses, so the emitted schema lists each status."""
    codes = sorted({status_code_for(error) for error in errors})
    return {code: {"model": ErrorResponse} for code in codes}


async def _handle_domain_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return JSONResponse(
        status_code=status_code_for(type(exc)),
        content=ErrorResponse(detail=exc.detail).model_dump(),
        headers=exc.headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Called once by the host, in app setup, next to its own handlers."""
    app.add_exception_handler(DomainError, _handle_domain_error)
