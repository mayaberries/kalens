"""
Withdrawing a request.

Withdrawal is a hard DELETE, not a status change -- the row goes away. That is
what separates it from cancelling, and it is why the response cannot be
hydrated: there is nothing left to hydrate from.
"""
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from tests._fixtures.entities import auth
from tests._helpers import appointment_row, confirm_appointment, request_appointment, withdraw_url

pytestmark = pytest.mark.asyncio


class TestWithdrawAppointment:
    async def test_the_booker_can_withdraw_a_request(
        self, app: FastAPI, client: AsyncClient, db, service_a, client_one, client_one_pet
    ) -> None:
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        res = await client.delete(
            withdraw_url(app, service=service_a, appointment_id=created["id"]), headers=auth(client_one)
        )
        assert res.status_code == 200
        assert res.json()["id"] == created["id"]
        assert await appointment_row(db, created["id"]) is None

    async def test_the_withdrawal_response_is_not_hydrated(
        self, app: FastAPI, client: AsyncClient, service_a, client_one, client_one_pet
    ) -> None:
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        res = await client.delete(
            withdraw_url(app, service=service_a, appointment_id=created["id"]), headers=auth(client_one)
        )
        body = res.json()
        assert body["pet_id"] == client_one_pet.id   # the raw id is still returned
        assert body["pet"] is None                   # but nothing was fetched back
        assert body["user"] is None

    async def test_clinic_staff_cannot_withdraw(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin, client_one, client_one_pet
    ) -> None:
        """Staff decline; only the booker withdraws."""
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        res = await client.delete(
            withdraw_url(app, service=service_a, appointment_id=created["id"]),
            headers=auth(clinic_a_admin),
        )
        assert res.status_code == 403

    async def test_another_client_cannot_withdraw(
        self, app: FastAPI, client: AsyncClient, service_a, client_one, client_one_pet, client_two
    ) -> None:
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        res = await client.delete(
            withdraw_url(app, service=service_a, appointment_id=created["id"]), headers=auth(client_two)
        )
        assert res.status_code == 403

    async def test_a_confirmed_appointment_cannot_be_withdrawn(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin, client_one, client_one_pet
    ) -> None:
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet
        )
        await confirm_appointment(
            app, client, service=service_a, staff=clinic_a_admin, appointment_id=created["id"]
        )
        res = await client.delete(
            withdraw_url(app, service=service_a, appointment_id=created["id"]), headers=auth(client_one)
        )
        assert res.status_code == 400
        assert "currently requested" in res.json()["detail"]
