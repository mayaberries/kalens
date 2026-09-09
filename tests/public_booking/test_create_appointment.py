"""
Booking through the widget, with no login.

This is the other appointment-creation path, and the one that carries the most
host orchestration: guest user, owner-to-clinic link, subject lookup-or-create,
then the appointment.
"""
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from tests._fixtures.entities import auth
from tests._helpers import confirm_appointment, request_appointment
from tests.conftest import unique_future_time

pytestmark = pytest.mark.asyncio


def key(public_key: str) -> dict:
    return {"X-Clinic-Key": public_key}


def booking(service_id: str, *, email="guest@example.com", pet=None, start_time=None) -> dict:
    return {
        "email": email,
        "full_name": "A Guest",
        "phone_number": "555-0100",
        "service_id": service_id,
        "pet": pet if pet is not None else {"new_pet": {"name": "Blacky", "species": "cat"}},
        "start_time": (start_time or unique_future_time()).isoformat(),
    }


class TestPublicBooking:
    async def test_guest_can_book_with_a_new_subject(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_public_key
    ) -> None:
        res = await client.post(
            app.url_path_for("public-booking:create-appointment"),
            json=booking(service_a.id),
            headers=key(clinic_a_public_key),
        )
        assert res.status_code == 201
        body = res.json()
        assert body["status"] == "requested"
        assert body["pet"]["name"] == "Blacky"
        assert body["user"]["is_guest"] is True

    async def test_a_returning_guest_reuses_their_account(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_public_key
    ) -> None:
        url = app.url_path_for("public-booking:create-appointment")
        first = await client.post(
            url, json=booking(service_a.id, email="repeat@example.com"), headers=key(clinic_a_public_key)
        )
        second = await client.post(
            url, json=booking(service_a.id, email="repeat@example.com"), headers=key(clinic_a_public_key)
        )
        assert first.status_code == 201 and second.status_code == 201
        assert first.json()["user_id"] == second.json()["user_id"]

    async def test_guest_can_book_for_a_subject_they_created_earlier(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_public_key
    ) -> None:
        url = app.url_path_for("public-booking:create-appointment")
        first = await client.post(
            url, json=booking(service_a.id, email="known@example.com"), headers=key(clinic_a_public_key)
        )
        pet_id = first.json()["pet"]["id"]

        second = await client.post(
            url,
            json=booking(service_a.id, email="known@example.com", pet={"pet_id": pet_id}),
            headers=key(clinic_a_public_key),
        )
        assert second.status_code == 201
        assert second.json()["pet_id"] == pet_id

    async def test_booking_registers_the_owner_with_the_clinic(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_public_key
    ) -> None:
        """Without this link GET /public/pets can never find them again."""
        await client.post(
            app.url_path_for("public-booking:create-appointment"),
            json=booking(service_a.id, email="linked@example.com"),
            headers=key(clinic_a_public_key),
        )
        listed = await client.get(
            app.url_path_for("public-booking:list-pets"),
            params={"email": "linked@example.com"},
            headers=key(clinic_a_public_key),
        )
        assert listed.status_code == 200
        assert [p["name"] for p in listed.json()] == ["Blacky"]

    async def test_a_service_from_another_clinic_is_404(
        self, app: FastAPI, client: AsyncClient, service_b, clinic_a_public_key
    ) -> None:
        res = await client.post(
            app.url_path_for("public-booking:create-appointment"),
            json=booking(service_b.id),
            headers=key(clinic_a_public_key),
        )
        assert res.status_code == 404
        assert "No bookable service" in res.json()["detail"]

    async def test_a_subject_belonging_to_someone_else_is_404(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_public_key
    ) -> None:
        """get_pet_by_id_for_clinic alone only proves the subject belongs to
        *a* registered owner at this clinic, not to *this* guest."""
        url = app.url_path_for("public-booking:create-appointment")
        theirs = await client.post(
            url, json=booking(service_a.id, email="owner-a@example.com"), headers=key(clinic_a_public_key)
        )
        pet_id = theirs.json()["pet"]["id"]

        res = await client.post(
            url,
            json=booking(service_a.id, email="owner-b@example.com", pet={"pet_id": pet_id}),
            headers=key(clinic_a_public_key),
        )
        assert res.status_code == 404
        assert "No pet found with that id for this clinic." == res.json()["detail"]

    async def test_a_confirmed_slot_returns_409(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin,
        client_one, client_one_pet, clinic_a_public_key
    ) -> None:
        """409 here, where the authenticated route returns 400 for the same
        condition. Both are preserved as-is."""
        slot = unique_future_time()
        created = await request_appointment(
            app, client, service=service_a, booker=client_one, pet=client_one_pet, start_time=slot
        )
        await confirm_appointment(
            app, client, service=service_a, staff=clinic_a_admin, appointment_id=created["id"]
        )

        res = await client.post(
            app.url_path_for("public-booking:create-appointment"),
            json=booking(service_a.id, start_time=slot),
            headers=key(clinic_a_public_key),
        )
        assert res.status_code == 409
        assert "no longer available" in res.json()["detail"]

    @pytest.mark.parametrize(
        "pet",
        (
            {},                                                        # neither
            {"pet_id": "x", "new_pet": {"name": "Both"}},              # both
        ),
    )
    async def test_subject_input_must_be_exactly_one_of_the_two(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_public_key, pet
    ) -> None:
        res = await client.post(
            app.url_path_for("public-booking:create-appointment"),
            json=booking(service_a.id, pet=pet),
            headers=key(clinic_a_public_key),
        )
        assert res.status_code == 422

    async def test_a_guest_booking_is_visible_to_clinic_staff(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_admin, clinic_a_public_key
    ) -> None:
        await client.post(
            app.url_path_for("public-booking:create-appointment"),
            json=booking(service_a.id, email="visible@example.com"),
            headers=key(clinic_a_public_key),
        )
        listed = await client.get(
            app.url_path_for("appointments:list-appointments-for-service", service_id=service_a.id),
            headers=auth(clinic_a_admin),
        )
        assert listed.status_code == 200
        assert len(listed.json()) == 1
