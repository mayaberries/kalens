"""
The publishable-key surface.

Every failure mode returns the same generic 401, and an unknown email returns
`200 []` rather than 404. Both exist so a caller cannot use the widget to
learn who has booked with a clinic. These are the assertions that keep that
true.
"""
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestPublicKeyAuth:
    @pytest.mark.parametrize(
        "headers",
        (
            {},                                   # no key at all
            {"X-Clinic-Key": ""},                 # empty
            {"X-Clinic-Key": "not-a-key"},        # wrong shape
            {"X-Clinic-Key": "sk_live_secret"},   # a secret-key prefix
            {"X-Clinic-Key": "pk_live_deadbeef"}, # right shape, unknown
        ),
    )
    async def test_every_bad_key_gets_the_same_401(
        self, app: FastAPI, client: AsyncClient, service_a, headers
    ) -> None:
        res = await client.get(app.url_path_for("public-booking:list-services"), headers=headers)
        assert res.status_code == 401
        assert res.json()["detail"] == "Invalid or missing clinic key."

    async def test_a_valid_key_lists_that_clinics_services(
        self, app: FastAPI, client: AsyncClient, service_a, service_b, clinic_a_public_key
    ) -> None:
        res = await client.get(
            app.url_path_for("public-booking:list-services"), headers={"X-Clinic-Key": clinic_a_public_key}
        )
        assert res.status_code == 200
        ids = [s["id"] for s in res.json()]
        assert service_a.id in ids
        assert service_b.id not in ids   # scoped to the key's own clinic

    async def test_an_unknown_email_returns_an_empty_list_not_404(
        self, app: FastAPI, client: AsyncClient, clinic_a_public_key
    ) -> None:
        res = await client.get(
            app.url_path_for("public-booking:list-pets"),
            params={"email": "nobody@example.com"},
            headers={"X-Clinic-Key": clinic_a_public_key},
        )
        assert res.status_code == 200
        assert res.json() == []

    async def test_a_known_email_at_another_clinic_also_returns_empty(
        self, app: FastAPI, client: AsyncClient, client_one, client_one_pet, clinic_a_public_key
    ) -> None:
        """The user and subject both exist, but the owner was never registered
        with this clinic -- so from this key's point of view they don't."""
        res = await client.get(
            app.url_path_for("public-booking:list-pets"),
            params={"email": client_one.email},
            headers={"X-Clinic-Key": clinic_a_public_key},
        )
        assert res.status_code == 200
        assert res.json() == []
