"""
Routes exist, are named, and resolve to the paths pets-appts serves today.

The `name=` values are load-bearing: hosts and their tests build URLs with
`app.url_path_for(...)`, so renaming one is a breaking change to this
library's public surface, not an internal detail.
"""
import pytest
from httpx import AsyncClient
from fastapi import FastAPI

pytestmark = pytest.mark.asyncio


class TestAppointmentRoutes:
    @pytest.mark.parametrize(
        "name, params, expected",
        (
            ("appointments:create-appointment", {"service_id": "s1"}, "/api/services/s1/appointments/"),
            ("appointments:list-appointments-for-service", {"service_id": "s1"}, "/api/services/s1/appointments/"),
            (
                "appointments:get-appointment-by-id",
                {"service_id": "s1", "appointment_id": "a1"},
                "/api/services/s1/appointments/a1",
            ),
            (
                "appointments:confirm-appointment",
                {"service_id": "s1", "appointment_id": "a1"},
                "/api/services/s1/appointments/a1/confirm",
            ),
            (
                "appointments:cancel-appointment",
                {"service_id": "s1", "appointment_id": "a1"},
                "/api/services/s1/appointments/a1/cancel",
            ),
            (
                "appointments:withdraw-appointment",
                {"service_id": "s1", "appointment_id": "a1"},
                "/api/services/s1/appointments/a1",
            ),
            ("public-booking:list-services", {}, "/api/public/services"),
            ("public-booking:list-pets", {}, "/api/public/pets"),
            ("public-booking:create-appointment", {}, "/api/public/appointments"),
            ("clinic-availability:get-availability", {"clinic_id": "c1"}, "/api/clinics/c1/availability/"),
            ("clinic-availability:update-availability", {"clinic_id": "c1"}, "/api/clinics/c1/availability/"),
        ),
    )
    async def test_route_resolves_to_expected_path(self, app: FastAPI, name, params, expected) -> None:
        assert app.url_path_for(name, **params) == expected

    async def test_routes_exist(self, app: FastAPI, client: AsyncClient) -> None:
        # No auth header, so these must not 404 -- a 404 here would mean the
        # route isn't mounted at all, which is what this asserts.
        res = await client.post(app.url_path_for("appointments:create-appointment", service_id="s1"), json={})
        assert res.status_code != 404

    async def test_appointment_public_schema_is_the_hosts_model(self, app: FastAPI) -> None:
        """The library types `pet`/`user`/`service` as Any and the host
        re-narrows them. If the injected response_model were ignored, the
        emitted schema would carry bare `Any` and this would fail."""
        schema = app.openapi()["components"]["schemas"]["AppointmentPublic"]["properties"]
        for field, model in (("pet", "PetProfilePublic"), ("user", "UserPublic"), ("service", "ServicePublic")):
            refs = str(schema[field])
            assert model in refs, f"{field} did not resolve to {model}: {refs}"
