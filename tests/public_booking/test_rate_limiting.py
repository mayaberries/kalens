"""
Rate limiting on the public surface.

Two tiers: a generous per-key budget for the expected traffic shape (many end
users through one embedded widget), and a much looser per-IP backstop whose
job is to slow down someone enumerating key values -- which the per-key
limiter alone cannot catch, since every guessed key starts a fresh bucket.

The real limits are far too high to exhaust in a test, so this class overrides
`appts_settings` with tiny ones. That the limits are `Settings` at all, rather
than module constants read at import, is what makes this testable.
"""
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

import appts_core

pytestmark = pytest.mark.asyncio


class TestPublicRateLimits:
    @pytest.fixture
    def appts_settings(self) -> appts_core.Settings:
        return appts_core.Settings(public_rate_limit_per_key=3, public_rate_limit_per_ip=5)

    async def test_the_per_key_budget_is_enforced(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_public_key
    ) -> None:
        url = app.url_path_for("public-booking:list-services")
        headers = {"X-Clinic-Key": clinic_a_public_key}

        for _ in range(3):
            assert (await client.get(url, headers=headers)).status_code == 200

        blocked = await client.get(url, headers=headers)
        assert blocked.status_code == 429
        assert "clinic key" in blocked.json()["detail"]

    async def test_key_enumeration_is_caught_by_the_ip_backstop(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Each guessed key starts its own per-key bucket, so the per-key
        limiter can never catch enumeration. The IP tier is what does -- and
        it only works because a *rejected* key still consumes budget."""
        url = app.url_path_for("public-booking:list-services")

        codes = [
            (await client.get(url, headers={"X-Clinic-Key": f"pk_live_guess{i}"})).status_code
            for i in range(6)
        ]
        assert codes[:5] == [401] * 5   # merely wrong, one per IP-budget unit
        assert codes[5] == 429          # budget gone
        assert "IP address" in (await client.get(url, headers={"X-Clinic-Key": "pk_live_guess99"})).json()["detail"]

    async def test_the_limiter_runs_before_the_key_lookup(
        self, app: FastAPI, client: AsyncClient, clinic_a_public_key
    ) -> None:
        """Router-level dependency ordering. Once the IP budget is spent, even
        a perfectly valid key gets 429 -- which can only happen if the limiter
        resolved before `get_clinic_from_public_key` reached the database."""
        url = app.url_path_for("public-booking:list-services")
        for i in range(6):
            await client.get(url, headers={"X-Clinic-Key": f"pk_live_guess{i}"})

        res = await client.get(url, headers={"X-Clinic-Key": clinic_a_public_key})
        assert res.status_code == 429

    async def test_a_missing_key_is_bucketed_by_ip_not_shared(
        self, app: FastAPI, client: AsyncClient, service_a, clinic_a_public_key
    ) -> None:
        """A request with no key falls back to `anon:<ip>` for its per-key
        bucket, so unauthenticated noise cannot exhaust a real clinic's own
        per-key budget."""
        url = app.url_path_for("public-booking:list-services")
        for _ in range(3):
            await client.get(url)   # no key: burns the anon bucket

        res = await client.get(url, headers={"X-Clinic-Key": clinic_a_public_key})
        assert res.status_code == 200
