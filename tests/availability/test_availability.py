"""
Weekly recurring hours.

GET is unauthenticated on purpose so an embedded widget can pull a tenant's
hours without a key. PUT is a full replace, not a per-day patch: any weekday
absent from the payload is normalised to closed, never left as whatever was
previously stored.
"""
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from tests._fixtures.entities import auth

pytestmark = pytest.mark.asyncio

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def url(app: FastAPI, clinic_id: str) -> str:
    return app.url_path_for("clinic-availability:get-availability", clinic_id=clinic_id)


class TestGetAvailability:
    async def test_get_is_unauthenticated(
        self, app: FastAPI, client: AsyncClient, clinic_a
    ) -> None:
        res = await client.get(url(app, clinic_a.id))
        assert res.status_code == 200

    async def test_a_clinic_with_no_hours_gets_the_default_week(
        self, app: FastAPI, client: AsyncClient, clinic_a
    ) -> None:
        """Self-healing read: GET never 404s for a clinic that exists just
        because its hours were never explicitly provisioned."""
        res = await client.get(url(app, clinic_a.id))
        body = res.json()
        assert body["clinic_id"] == clinic_a.id
        assert body["timezone"] == "UTC"
        assert body["schedule"]["monday"] == [{"start": "09:00:00", "end": "17:00:00"}]
        assert body["schedule"]["sunday"] == []

    async def test_an_unknown_clinic_is_404(self, app: FastAPI, client: AsyncClient) -> None:
        res = await client.get(url(app, "00000000-0000-0000-0000-000000000000"))
        assert res.status_code == 404


class TestUpdateAvailability:
    async def test_clinic_admin_can_replace_the_week(
        self, app: FastAPI, client: AsyncClient, clinic_a, clinic_a_admin
    ) -> None:
        res = await client.put(
            url(app, clinic_a.id),
            json={
                "schedule": {"tuesday": [{"start": "08:00:00", "end": "12:00:00"}]},
                "timezone": "America/Mexico_City",
            },
            headers=auth(clinic_a_admin),
        )
        assert res.status_code == 200
        body = res.json()
        assert body["timezone"] == "America/Mexico_City"
        assert body["schedule"]["tuesday"] == [{"start": "08:00:00", "end": "12:00:00"}]

    async def test_omitted_days_become_closed_not_unchanged(
        self, app: FastAPI, client: AsyncClient, clinic_a, clinic_a_admin
    ) -> None:
        """The default week has Monday open. Sending a payload without Monday
        must close it, not leave it as it was."""
        await client.get(url(app, clinic_a.id))   # provision the default week

        res = await client.put(
            url(app, clinic_a.id),
            json={"schedule": {"tuesday": [{"start": "08:00:00", "end": "12:00:00"}]}},
            headers=auth(clinic_a_admin),
        )
        schedule = res.json()["schedule"]
        assert schedule["monday"] == []
        assert set(schedule) == set(WEEKDAYS)     # every weekday is present, explicitly

    async def test_the_update_persists(
        self, app: FastAPI, client: AsyncClient, clinic_a, clinic_a_admin
    ) -> None:
        await client.put(
            url(app, clinic_a.id),
            json={"schedule": {"friday": [{"start": "10:00:00", "end": "18:00:00"}]}},
            headers=auth(clinic_a_admin),
        )
        res = await client.get(url(app, clinic_a.id))
        assert res.json()["schedule"]["friday"] == [{"start": "10:00:00", "end": "18:00:00"}]

    async def test_ranges_are_sorted(
        self, app: FastAPI, client: AsyncClient, clinic_a, clinic_a_admin
    ) -> None:
        res = await client.put(
            url(app, clinic_a.id),
            json={
                "schedule": {
                    "monday": [
                        {"start": "14:00:00", "end": "18:00:00"},
                        {"start": "09:00:00", "end": "12:00:00"},
                    ]
                }
            },
            headers=auth(clinic_a_admin),
        )
        assert [r["start"] for r in res.json()["schedule"]["monday"]] == ["09:00:00", "14:00:00"]

    @pytest.mark.parametrize(
        "schedule",
        (
            {"monday": [{"start": "09:00:00", "end": "09:00:00"}]},                        # zero length
            {"monday": [{"start": "17:00:00", "end": "09:00:00"}]},                        # end before start
            {"monday": [{"start": "09:00:00", "end": "12:00:00"},
                        {"start": "11:00:00", "end": "13:00:00"}]},                        # overlapping
        ),
    )
    async def test_invalid_ranges_are_rejected(
        self, app: FastAPI, client: AsyncClient, clinic_a, clinic_a_admin, schedule
    ) -> None:
        res = await client.put(
            url(app, clinic_a.id), json={"schedule": schedule}, headers=auth(clinic_a_admin)
        )
        assert res.status_code == 422

    async def test_an_unauthenticated_put_is_rejected(
        self, app: FastAPI, client: AsyncClient, clinic_a
    ) -> None:
        res = await client.put(url(app, clinic_a.id), json={"schedule": {}})
        assert res.status_code == 401

    async def test_another_clinics_admin_cannot_write(
        self, app: FastAPI, client: AsyncClient, clinic_a, clinic_b_admin
    ) -> None:
        res = await client.put(
            url(app, clinic_a.id), json={"schedule": {}}, headers=auth(clinic_b_admin)
        )
        assert res.status_code == 403

    async def test_clinic_aux_cannot_write(
        self, app: FastAPI, client: AsyncClient, clinic_a, clinic_a_aux
    ) -> None:
        """The reference host reserves this for clinic_admin; the library
        delegates entirely to the host's own permission check."""
        res = await client.put(
            url(app, clinic_a.id), json={"schedule": {}}, headers=auth(clinic_a_aux)
        )
        assert res.status_code == 403
