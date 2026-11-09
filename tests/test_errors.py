"""
kalens.errors: the status each domain error maps to, the body and headers the
handler sends, and that the reference host registers it as the contract asks.

No database: a bare app with only the handler, plus the reference host's app
object (never started).
"""
import pytest
import pytest_asyncio
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

import kalens
from kalens import (
    ConflictError,
    DomainError,
    InputModel,
    NotAuthenticatedError,
    NotFoundError,
    PermissionDeniedError,
    ServiceUnavailableError,
    error_responses,
    register_error_handlers,
)
from kalens.errors import status_code_for
from tests._host.app import build_app


class SlotTakenError(ConflictError):
    pass


CASES = [
    (NotAuthenticatedError, status.HTTP_401_UNAUTHORIZED),
    (PermissionDeniedError, status.HTTP_403_FORBIDDEN),
    (NotFoundError, status.HTTP_404_NOT_FOUND),
    (ConflictError, status.HTTP_409_CONFLICT),
    (SlotTakenError, status.HTTP_409_CONFLICT),
    (ServiceUnavailableError, status.HTTP_503_SERVICE_UNAVAILABLE),
    (DomainError, status.HTTP_400_BAD_REQUEST),
]
CASE_IDS = [error.__name__ for error, _ in CASES]


def _app_raising(error: DomainError) -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/raise", responses=error_responses(type(error)))
    async def raise_it() -> None:
        raise error

    return app


@pytest_asyncio.fixture
async def make_client():
    clients = []

    def make(app: FastAPI) -> AsyncClient:
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()


@pytest.mark.parametrize("error, code", CASES, ids=CASE_IDS)
def test_each_error_maps_to_its_status(error, code):
    assert status_code_for(error) == code


@pytest.mark.asyncio
@pytest.mark.parametrize("error, code", CASES, ids=CASE_IDS)
async def test_handler_sends_the_status_and_detail(error, code, make_client):
    response = await make_client(_app_raising(error("Something specific."))).get("/raise")

    assert response.status_code == code
    # The same shape HTTPException gives, so a host's clients can't tell.
    assert response.json() == {"detail": "Something specific."}


@pytest.mark.asyncio
async def test_handler_passes_the_errors_headers(make_client):
    error = NotAuthenticatedError("Not authenticated.", headers={"WWW-Authenticate": "Bearer"})

    response = await make_client(_app_raising(error)).get("/raise")

    assert response.headers["www-authenticate"] == "Bearer"


def test_error_responses_lists_each_status_once_in_order():
    responses = error_responses(SlotTakenError, NotFoundError, ConflictError, PermissionDeniedError)

    assert list(responses) == [403, 404, 409]


def test_the_reference_host_registers_the_handler():
    kalens.reset()
    app, _ = build_app("postgresql://unused/unused")

    assert DomainError in app.exception_handlers


class InvoiceCreate(InputModel):
    number: str


def test_input_models_reject_unknown_fields():
    with pytest.raises(ValidationError) as excinfo:
        InvoiceCreate.model_validate({"number": "A-1", "nmuber": "typo"})

    assert excinfo.value.errors()[0]["type"] == "extra_forbidden"
