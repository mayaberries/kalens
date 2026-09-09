"""Confirming a requested appointment."""
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from tests._fixtures.entities import auth
from tests._helpers import confirm_appointment, request_appointment
from tests.conftest import unique_future_time

pytestmark = pytest.mark.asyncio


def confirm_url(app: FastAPI, *, service, appointment_id: str) -> str:
    return app.url_path_for(
        "appointments:confirm-appointment", service_id=service.id, appointment_id=appointment_id
    )


class TestConfirmAppointment:
    async def test_clinic_admin_can_confirm(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin, client_one, client_one_pet
    ) -> None:
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        body = await confirm_appointment(
            app, client, service=service_a, staff=clinic_a_admin, appointment_id=created["id"]
        )
        assert body["status"] == "confirmed"

    async def test_clinic_aux_can_also_confirm(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_aux, client_one, client_one_pet
    ) -> None:
        """Eligibility keys on clinic membership, not on the admin/aux
        distinction -- pinned for both roles so a future role check can't
        narrow it by accident."""
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        res = await client.put(
            confirm_url(app, service=service_a, appointment_id=created["id"]),
            headers=auth(clinic_a_aux),
        )
        assert res.status_code == 200

    async def test_the_booking_client_cannot_confirm(
        self, app: FastAPI, client: AsyncClient, service_a, client_one, client_one_pet
    ) -> None:
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        res = await client.put(
            confirm_url(app, service=service_a, appointment_id=created["id"]),
            headers=auth(client_one),
        )
        assert res.status_code == 403

    async def test_staff_of_another_clinic_cannot_confirm(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_b_admin, client_one, client_one_pet
    ) -> None:
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        res = await client.put(
            confirm_url(app, service=service_a, appointment_id=created["id"]),
            headers=auth(clinic_b_admin),
        )
        assert res.status_code == 403

    async def test_cannot_confirm_twice(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin, client_one, client_one_pet
    ) -> None:
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        await confirm_appointment(
            app, client, service=service_a, staff=clinic_a_admin, appointment_id=created["id"]
        )
        res = await client.put(
            confirm_url(app, service=service_a, appointment_id=created["id"]),
            headers=auth(clinic_a_admin),
        )
        assert res.status_code == 400
        assert "currently requested" in res.json()["detail"]

    async def test_confirming_a_clashing_slot_is_rejected(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin,
        client_one, client_one_pet, client_two, client_two_pet
    ) -> None:
        """Both may request the same slot; only one may be confirmed. The
        exclude_id in the overlap query is what stops an appointment from
        conflicting with itself."""
        slot = unique_future_time()
        first = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet, start_time=slot
        )
        second = await request_appointment(
            app, client, service=service_a, booker=client_two, pet=client_two_pet, start_time=slot
        )

        await confirm_appointment(
            app, client, service=service_a, staff=clinic_a_admin, appointment_id=first["id"]
        )
        res = await client.put(
            confirm_url(app, service=service_a, appointment_id=second["id"]),
            headers=auth(clinic_a_admin),
        )
        assert res.status_code == 400
        assert "conflicts with another confirmed appointment" in res.json()["detail"]

    async def test_confirming_does_not_auto_decline_the_others(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin,
        client_one, client_one_pet, client_two, client_two_pet, db
    ) -> None:
        """Deliberate: the loser stays `requested` for manual review rather
        than being declined automatically."""
        slot = unique_future_time()
        first = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet, start_time=slot
        )
        second = await request_appointment(
            app, client, service=service_a, booker=client_two, pet=client_two_pet, start_time=slot
        )
        await confirm_appointment(
            app, client, service=service_a, staff=clinic_a_admin, appointment_id=first["id"]
        )

        row = await db.fetch_one(
            query="SELECT status FROM appointments WHERE id = :id", values={"id": second["id"]}
        )
        assert row["status"] == "requested"
