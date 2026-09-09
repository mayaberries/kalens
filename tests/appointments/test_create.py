"""Requesting an appointment."""
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from tests._fixtures.entities import auth
from tests._host.models import PetProfileCreate
from tests.conftest import unique_future_time

pytestmark = pytest.mark.asyncio


def payload(pet_id: str, start_time=None) -> dict:
    return {
        "pet_id": pet_id,
        "start_time": (start_time or unique_future_time()).isoformat(),
    }


class TestCreateAppointment:
    async def test_client_can_request_an_appointment(
        self, app: FastAPI, client: AsyncClient, service_a, client_one, client_one_pet
    ) -> None:
        res = await client.post(
            app.url_path_for("appointments:create-appointment", service_id=service_a.id),
            json=payload(client_one_pet.id),
            headers=auth(client_one),
        )
        assert res.status_code == 201
        body = res.json()
        assert body["status"] == "requested"
        assert body["service_id"] == service_a.id
        assert body["user_id"] == client_one.id
        assert body["pet_id"] == client_one_pet.id
        # end_time is derived from the service's duration, not sent by the caller.
        assert body["end_time"] > body["start_time"]

    async def test_response_is_hydrated_with_host_models(
        self, app: FastAPI, client: AsyncClient, service_a, client_one, client_one_pet
    ) -> None:
        """populate_appointment reaches into the host's users and subject
        repositories. If the integration were mis-wired, these would be null."""
        res = await client.post(
            app.url_path_for("appointments:create-appointment", service_id=service_a.id),
            json=payload(client_one_pet.id),
            headers=auth(client_one),
        )
        body = res.json()
        assert body["pet"]["name"] == client_one_pet.name
        assert body["pet"]["species"] == client_one_pet.species
        assert body["user"]["username"] == client_one.username

    async def test_unauthenticated_request_is_rejected(
        self, app: FastAPI, client: AsyncClient, service_a, client_one_pet
    ) -> None:
        res = await client.post(
            app.url_path_for("appointments:create-appointment", service_id=service_a.id),
            json=payload(client_one_pet.id),
        )
        assert res.status_code == 401

    async def test_staff_cannot_book_their_own_clinics_service(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin, pets_repo
    ) -> None:
        pet = await pets_repo.create_pet(
            new_pet=PetProfileCreate(name="Staff pet"),
            owner_profile_id=clinic_a_admin.profile.id,
        )
        res = await client.post(
            app.url_path_for("appointments:create-appointment", service_id=service_a.id),
            json=payload(pet.id),
            headers=auth(clinic_a_admin),
        )
        assert res.status_code == 400
        assert "services they own" in res.json()["detail"]

    async def test_cannot_book_for_someone_elses_subject(
        self, app: FastAPI, client: AsyncClient, service_a, client_one, client_two_pet
    ) -> None:
        """404 not 403, deliberately: the response must not confirm that a
        pet_id belonging to someone else exists at all."""
        res = await client.post(
            app.url_path_for("appointments:create-appointment", service_id=service_a.id),
            json=payload(client_two_pet.id),
            headers=auth(client_one),
        )
        assert res.status_code == 404
        assert res.json()["detail"] == "No pet found with that id."

    async def test_unknown_subject_is_also_404(
        self, app: FastAPI, client: AsyncClient, service_a, client_one
    ) -> None:
        res = await client.post(
            app.url_path_for("appointments:create-appointment", service_id=service_a.id),
            json=payload("00000000-0000-0000-0000-000000000000"),
            headers=auth(client_one),
        )
        assert res.status_code == 404

    @pytest.mark.parametrize(
        "body",
        (
            {},
            {"start_time": "2099-01-01T10:00:00+00:00"},
            {"pet_id": "abc"},
        ),
    )
    async def test_incomplete_payload_is_422(
        self, app: FastAPI, client: AsyncClient, service_a, client_one, body
    ) -> None:
        res = await client.post(
            app.url_path_for("appointments:create-appointment", service_id=service_a.id),
            json=body,
            headers=auth(client_one),
        )
        assert res.status_code == 422

    async def test_start_time_in_the_past_is_rejected(
        self, app: FastAPI, client: AsyncClient, service_a, client_one, client_one_pet
    ) -> None:
        res = await client.post(
            app.url_path_for("appointments:create-appointment", service_id=service_a.id),
            json={"pet_id": client_one_pet.id, "start_time": "2001-01-01T10:00:00+00:00"},
            headers=auth(client_one),
        )
        assert res.status_code == 422

    async def test_same_service_can_be_booked_more_than_once(
        self, app: FastAPI, client: AsyncClient, service_a, client_one, client_one_pet
    ) -> None:
        """The surrogate id PK is what makes this possible; under the original
        composite (user_id, service_id) key the second request would collide."""
        url = app.url_path_for("appointments:create-appointment", service_id=service_a.id)
        first = await client.post(url, json=payload(client_one_pet.id), headers=auth(client_one))
        second = await client.post(url, json=payload(client_one_pet.id), headers=auth(client_one))
        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["id"] != second.json()["id"]

    async def test_two_requests_for_the_same_slot_both_succeed(
        self, app: FastAPI, client: AsyncClient, service_a, client_one, client_one_pet, client_two, client_two_pet
    ) -> None:
        """Deliberate product behaviour, not a defect: overlap is only checked
        against *confirmed* appointments, so two people may both request the
        same slot and confirming one resolves it. Pinned here so extraction
        can't quietly 'fix' it."""
        url = app.url_path_for("appointments:create-appointment", service_id=service_a.id)
        slot = unique_future_time()
        first = await client.post(url, json=payload(client_one_pet.id, slot), headers=auth(client_one))
        second = await client.post(url, json=payload(client_two_pet.id, slot), headers=auth(client_two))
        assert first.status_code == 201
        assert second.status_code == 201

    async def test_cannot_request_a_slot_already_confirmed(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin,
        client_one, client_one_pet, client_two, client_two_pet
    ) -> None:
        url = app.url_path_for("appointments:create-appointment", service_id=service_a.id)
        slot = unique_future_time()

        first = await client.post(url, json=payload(client_one_pet.id, slot), headers=auth(client_one))
        confirmed = await client.put(
            app.url_path_for(
                "appointments:confirm-appointment",
                service_id=service_a.id,
                appointment_id=first.json()["id"],
            ),
            headers=auth(clinic_a_admin),
        )
        assert confirmed.status_code == 200

        clash = await client.post(url, json=payload(client_two_pet.id, slot), headers=auth(client_two))
        assert clash.status_code == 400
        assert clash.json()["detail"] == "This time is already booked."
