"""
Rate limiting on the availability endpoints.

Each clinic gets its own budget, and reads and writes are kept in separate
buckets so public read traffic (the embedded widget) can never use up the
clinic admin's own write budget. The shared per-IP backstop sits behind both,
but it is left at its default here so it never binds.

The real limits are far too high to exhaust in a test, so this class overrides
`appts_settings` with tiny ones -- see tests/public_booking/test_rate_limiting.py.
"""
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

import kalens
from tests._fixtures.entities import auth

pytestmark = pytest.mark.asyncio

READ_LIMIT = 3
WRITE_LIMIT = 2


def url(app: FastAPI, clinic_id: str) -> str:
    return app.url_path_for("clinic-availability:get-availability", clinic_id=clinic_id)


class TestClinicAvailabilityRateLimits:
    @pytest.fixture
    def appts_settings(self) -> kalens.Settings:
        return kalens.Settings(
            clinic_availability_read_rate_limit_per_clinic=READ_LIMIT,
            clinic_availability_write_rate_limit_per_clinic=WRITE_LIMIT,
        )

    async def test_the_per_clinic_read_budget_is_enforced(
        self, app: FastAPI, client: AsyncClient, clinic_a
    ) -> None:
        for _ in range(READ_LIMIT):
            assert (await client.get(url(app, clinic_a.id))).status_code == 200

        blocked = await client.get(url(app, clinic_a.id))
        assert blocked.status_code == 429
        assert "availability endpoint" in blocked.json()["detail"]

    async def test_each_clinic_has_its_own_read_budget(
        self, app: FastAPI, client: AsyncClient, clinic_a, clinic_b
    ) -> None:
        """GET is unauthenticated, so the clinic id in the path is the only
        thing there is to key on -- and one busy clinic's widget must not
        starve another's."""
        for _ in range(READ_LIMIT):
            await client.get(url(app, clinic_a.id))
        assert (await client.get(url(app, clinic_a.id))).status_code == 429

        assert (await client.get(url(app, clinic_b.id))).status_code == 200

    async def test_the_per_clinic_write_budget_is_enforced(
        self, app: FastAPI, client: AsyncClient, clinic_a, clinic_a_admin
    ) -> None:
        for _ in range(WRITE_LIMIT):
            res = await client.put(
                url(app, clinic_a.id), json={"schedule": {}}, headers=auth(clinic_a_admin)
            )
            assert res.status_code == 200

        blocked = await client.put(
            url(app, clinic_a.id), json={"schedule": {}}, headers=auth(clinic_a_admin)
        )
        assert blocked.status_code == 429
        assert "availability endpoint" in blocked.json()["detail"]

    async def test_reads_and_writes_have_separate_budgets(
        self, app: FastAPI, client: AsyncClient, clinic_a, clinic_a_admin
    ) -> None:
        """The reason there are two tiers at all: exhausting the public read
        budget leaves the admin able to write."""
        for _ in range(READ_LIMIT):
            await client.get(url(app, clinic_a.id))
        assert (await client.get(url(app, clinic_a.id))).status_code == 429

        res = await client.put(
            url(app, clinic_a.id), json={"schedule": {}}, headers=auth(clinic_a_admin)
        )
        assert res.status_code == 200

    async def test_rejected_writes_still_use_up_the_clinics_budget(
        self, app: FastAPI, client: AsyncClient, clinic_a, clinic_a_admin, clinic_b_admin
    ) -> None:
        """Pins the current behaviour described at TODO(rate-limit) in
        kalens/limiter.py, not the desired one. The write limiter is keyed on
        the clinic id in the path and runs before the permission check, so
        another clinic's admin -- who gets 403 -- spends clinic A's budget,
        and clinic A's own admin is then locked out.

        Once the limiter is keyed on the caller instead, the last request
        here should return 200: update this test to say so."""
        for _ in range(WRITE_LIMIT):
            res = await client.put(
                url(app, clinic_a.id), json={"schedule": {}}, headers=auth(clinic_b_admin)
            )
            assert res.status_code == 403

        res = await client.put(
            url(app, clinic_a.id), json={"schedule": {}}, headers=auth(clinic_a_admin)
        )
        assert res.status_code == 429

    async def test_unauthenticated_writes_still_use_up_the_clinics_budget(
        self, app: FastAPI, client: AsyncClient, clinic_a, clinic_a_admin
    ) -> None:
        """Same TODO(rate-limit), worse case: the caller needs no account at
        all, only a clinic id. Each request is rejected with 401, but only
        after it has been counted."""
        for _ in range(WRITE_LIMIT):
            res = await client.put(url(app, clinic_a.id), json={"schedule": {}})
            assert res.status_code == 401

        res = await client.put(
            url(app, clinic_a.id), json={"schedule": {}}, headers=auth(clinic_a_admin)
        )
        assert res.status_code == 429
