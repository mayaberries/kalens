"""Reading appointments back: who may see what."""
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from tests._fixtures.entities import auth
from tests._helpers import get_url, request_appointment

pytestmark = pytest.mark.asyncio


class TestGetAppointment:
    async def test_booking_client_can_read_their_own(
        self, app: FastAPI, client: AsyncClient, service_a, client_one, client_one_pet
    ) -> None:
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        res = await client.get(
            get_url(app, service=service_a, appointment_id=created["id"]), headers=auth(client_one)
        )
        assert res.status_code == 200
        assert res.json()["id"] == created["id"]

    async def test_clinic_staff_can_read_it(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin, client_one, client_one_pet
    ) -> None:
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        res = await client.get(
            get_url(app, service=service_a, appointment_id=created["id"]), headers=auth(clinic_a_admin)
        )
        assert res.status_code == 200

    async def test_an_unrelated_client_cannot(
        self, app: FastAPI, client: AsyncClient, service_a, client_one, client_one_pet, client_two
    ) -> None:
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        res = await client.get(
            get_url(app, service=service_a, appointment_id=created["id"]), headers=auth(client_two)
        )
        assert res.status_code == 403

    async def test_unknown_appointment_is_404(
        self, app: FastAPI, client: AsyncClient, service_a, client_one
    ) -> None:
        res = await client.get(
            get_url(app, service=service_a, appointment_id="00000000-0000-0000-0000-000000000000"),
            headers=auth(client_one),
        )
        assert res.status_code == 404

    async def test_appointment_under_the_wrong_service_is_404(
        self, app: FastAPI, client: AsyncClient, service_a, service_b,
        client_one, client_one_pet, clinic_b_admin
    ) -> None:
        """The path is /services/{service_id}/appointments/{id}; an id that
        exists but belongs to another service must not resolve."""
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        res = await client.get(
            get_url(app, service=service_b, appointment_id=created["id"]), headers=auth(clinic_b_admin)
        )
        assert res.status_code == 404


class TestListAppointments:
    async def test_staff_can_list_for_their_service(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin, client_one, client_one_pet
    ) -> None:
        await request_appointment(app, client, service=service_a, booker=client_one, pet=client_one_pet)
        await request_appointment(app, client, service=service_a, booker=client_one, pet=client_one_pet)

        res = await client.get(
            app.url_path_for("appointments:list-appointments-for-service", service_id=service_a.id),
            headers=auth(clinic_a_admin),
        )
        assert res.status_code == 200
        body = res.json()
        assert len(body) == 2
        # Listing hydrates too -- populate=True is the repository default.
        assert body[0]["pet"]["id"] == client_one_pet.id

    async def test_a_client_cannot_list(
        self, app: FastAPI, client: AsyncClient, service_a, client_one
    ) -> None:
        res = await client.get(
            app.url_path_for("appointments:list-appointments-for-service", service_id=service_a.id),
            headers=auth(client_one),
        )
        assert res.status_code == 403

    async def test_staff_of_another_clinic_cannot_list(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_b_admin
    ) -> None:
        res = await client.get(
            app.url_path_for("appointments:list-appointments-for-service", service_id=service_a.id),
            headers=auth(clinic_b_admin),
        )
        assert res.status_code == 403
