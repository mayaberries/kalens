"""Small helpers shared by the appointment tests."""
from typing import Optional

from fastapi import FastAPI
from httpx import AsyncClient

from tests._fixtures.entities import auth
from tests.conftest import unique_future_time


async def request_appointment(
    app: FastAPI, client: AsyncClient, *, service, booker, pet, start_time=None
) -> dict:
    """Create one appointment through the API and return its body.

    Goes through the route rather than the repository on purpose: a fixture
    that wrote straight to the table would skip the permission checks, and
    then a test asserting on a *later* transition would pass against a row the
    API would never have produced.
    """
    res = await client.post(
        app.url_path_for("appointments:create-appointment", service_id=service.id),
        json={
            "pet_id": pet.id,
            "start_time": (start_time or unique_future_time()).isoformat(),
        },
        headers=auth(booker),
    )
    assert res.status_code == 201, res.text
    return res.json()


async def confirm_appointment(
    app: FastAPI, client: AsyncClient, *, service, staff, appointment_id: str
) -> dict:
    res = await client.put(
        app.url_path_for(
            "appointments:confirm-appointment",
            service_id=service.id,
            appointment_id=appointment_id,
        ),
        headers=auth(staff),
    )
    assert res.status_code == 200, res.text
    return res.json()


def cancel_url(app: FastAPI, *, service, appointment_id: str) -> str:
    return app.url_path_for(
        "appointments:cancel-appointment", service_id=service.id, appointment_id=appointment_id
    )


def withdraw_url(app: FastAPI, *, service, appointment_id: str) -> str:
    return app.url_path_for(
        "appointments:withdraw-appointment", service_id=service.id, appointment_id=appointment_id
    )


def get_url(app: FastAPI, *, service, appointment_id: str) -> str:
    return app.url_path_for(
        "appointments:get-appointment-by-id", service_id=service.id, appointment_id=appointment_id
    )


async def appointment_row(db, appointment_id: str) -> Optional[dict]:
    row = await db.fetch_one(
        query="SELECT id, status, cancellation_reason, cancelled_by FROM appointments WHERE id = :id",
        values={"id": appointment_id},
    )
    return dict(row) if row else None
