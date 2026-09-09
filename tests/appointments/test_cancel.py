"""
Cancelling, and the fact that cancelling a never-confirmed booking *declines*
it instead.

The table in `check_appointment_cancel_permissions` is the specification; this
file is that table, executed.
"""
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from tests._fixtures.entities import auth
from tests._helpers import appointment_row, cancel_url, confirm_appointment, request_appointment
from tests.conftest import unique_future_time

pytestmark = pytest.mark.asyncio


class TestCancelAppointment:
    async def test_client_cancels_a_confirmed_booking(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin, client_one, client_one_pet
    ) -> None:
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        await confirm_appointment(
            app, client, service=service_a, staff=clinic_a_admin, appointment_id=created["id"]
        )
        res = await client.put(
            cancel_url(app, service=service_a, appointment_id=created["id"]), headers=auth(client_one)
        )
        assert res.status_code == 200
        assert res.json()["status"] == "cancelled"
        assert res.json()["cancelled_by"] == client_one.id

    async def test_staff_cancelling_a_requested_booking_declines_it(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin, client_one, client_one_pet
    ) -> None:
        """`declined` exists for exactly this transition, and staff cancelling
        a requested appointment is the only thing that produces it."""
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        res = await client.put(
            cancel_url(app, service=service_a, appointment_id=created["id"]),
            headers=auth(clinic_a_admin),
        )
        assert res.status_code == 200
        assert res.json()["status"] == "declined"

    async def test_staff_cancels_a_confirmed_booking(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin, client_one, client_one_pet
    ) -> None:
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        await confirm_appointment(
            app, client, service=service_a, staff=clinic_a_admin, appointment_id=created["id"]
        )
        res = await client.put(
            cancel_url(app, service=service_a, appointment_id=created["id"]),
            headers=auth(clinic_a_admin),
        )
        assert res.status_code == 200
        assert res.json()["status"] == "cancelled"

    async def test_client_cannot_cancel_a_requested_booking(
        self, app: FastAPI, client: AsyncClient, service_a, client_one, client_one_pet
    ) -> None:
        """Clients *withdraw* a request; they don't cancel it."""
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        res = await client.put(
            cancel_url(app, service=service_a, appointment_id=created["id"]), headers=auth(client_one)
        )
        assert res.status_code == 400
        assert res.json()["detail"] == "Can only cancel appointments that have been confirmed"

    async def test_a_stranger_cannot_cancel(
        self, app: FastAPI, client: AsyncClient, service_a, client_one, client_one_pet, client_two
    ) -> None:
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        res = await client.put(
            cancel_url(app, service=service_a, appointment_id=created["id"]), headers=auth(client_two)
        )
        assert res.status_code == 403

    async def test_cancellation_reason_is_recorded_and_returned(
        self, app: FastAPI, client: AsyncClient, db, service_a, clinic_a_admin, client_one, client_one_pet
    ) -> None:
        """The reason is shown to the client -- that's the point of storing
        it -- and `cancelled_by` says which side wrote it."""
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        res = await client.put(
            cancel_url(app, service=service_a, appointment_id=created["id"]),
            json={"cancellation_reason": "Vet called in sick"},
            headers=auth(clinic_a_admin),
        )
        assert res.status_code == 200
        assert res.json()["cancellation_reason"] == "Vet called in sick"

        row = await appointment_row(db, created["id"])
        assert row["cancellation_reason"] == "Vet called in sick"
        assert row["cancelled_by"] == clinic_a_admin.id

    async def test_a_bodyless_cancel_is_valid(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin, client_one, client_one_pet
    ) -> None:
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        res = await client.put(
            cancel_url(app, service=service_a, appointment_id=created["id"]),
            headers=auth(clinic_a_admin),
        )
        assert res.status_code == 200
        assert res.json()["cancellation_reason"] is None

    async def test_an_overlong_reason_is_rejected(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin, client_one, client_one_pet
    ) -> None:
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        res = await client.put(
            cancel_url(app, service=service_a, appointment_id=created["id"]),
            json={"cancellation_reason": "x" * 501},
            headers=auth(clinic_a_admin),
        )
        assert res.status_code == 422

    async def test_a_cancelled_slot_frees_up_again(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin,
        client_one, client_one_pet, client_two, client_two_pet
    ) -> None:
        """Overlap only counts *confirmed* rows, so cancelling really does
        release the time rather than leaving it blocked."""
        slot = unique_future_time()
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet, start_time=slot
        )
        await confirm_appointment(
            app, client, service=service_a, staff=clinic_a_admin, appointment_id=created["id"]
        )
        await client.put(
            cancel_url(app, service=service_a, appointment_id=created["id"]),
            headers=auth(clinic_a_admin),
        )

        retry = await request_appointment(
            app, client, service=service_a, booker=client_two, pet=client_two_pet, start_time=slot
        )
        assert retry["status"] == "requested"
