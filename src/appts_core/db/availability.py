import json
from typing import Optional
from uuid import uuid4

from databases.core import Database

from appts_core.db.base import BaseRepository
from appts_core.models.availability import (
    ClinicAvailabilityInDB,
    ClinicAvailabilityUpdate,
    DEFAULT_WEEKLY_SCHEDULE,
    WeeklySchedule,
)

CLINIC_AVAILABILITY_COLUMNS = "id, clinic_id, schedule, timezone, created_at, updated_at"

GET_CLINIC_AVAILABILITY_BY_CLINIC_ID_QUERY = f"""
    SELECT {CLINIC_AVAILABILITY_COLUMNS}
    FROM clinic_availability
    WHERE clinic_id = :clinic_id;
"""

# ON CONFLICT rather than separate INSERT/UPDATE branches: this single
# query backs both "provision hours for a brand-new clinic" and "replace
# an existing clinic's hours", and also transparently backfills a row for
# any clinic that predates this table (see get_or_create_availability)
# without a read-then-write race between the two statements.
UPSERT_CLINIC_AVAILABILITY_QUERY = f"""
    INSERT INTO clinic_availability (id, clinic_id, schedule, timezone)
    VALUES (:id, :clinic_id, CAST(:schedule AS JSONB), :timezone)
    ON CONFLICT (clinic_id) DO UPDATE
    SET schedule = EXCLUDED.schedule,
        timezone = EXCLUDED.timezone
    RETURNING {CLINIC_AVAILABILITY_COLUMNS};
"""


def _serialize_schedule(schedule: WeeklySchedule) -> str:
    # asyncpg (via `databases`) doesn't auto-adapt a Python dict to jsonb --
    # the value has to go over the wire as a JSON string and get cast on
    # the SQL side (see CAST(:schedule AS JSONB) above).
    return json.dumps({
        day.value: [time_range.model_dump(mode="json") for time_range in ranges]
        for day, ranges in schedule.items()
    })


def _record_to_model(record) -> ClinicAvailabilityInDB:
    raw_schedule = record["schedule"]
    schedule = json.loads(raw_schedule) if isinstance(raw_schedule, str) else raw_schedule
    return ClinicAvailabilityInDB(
        id=record["id"],
        clinic_id=record["clinic_id"],
        schedule=schedule,
        timezone=record["timezone"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


class ClinicAvailabilityRepository(BaseRepository):
    def __init__(self, db: Database) -> None:
        super().__init__(db)

    async def _upsert(self, *, clinic_id: str, schedule: WeeklySchedule, timezone: str) -> ClinicAvailabilityInDB:
        record = await self.db.fetch_one(
            query=UPSERT_CLINIC_AVAILABILITY_QUERY,
            values={
                "id": str(uuid4()),
                "clinic_id": clinic_id,
                "schedule": _serialize_schedule(schedule),
                "timezone": timezone,
            },
        )
        return _record_to_model(record)

    async def create_default_availability_for_clinic(self, *, clinic_id: str) -> ClinicAvailabilityInDB:
        """Called once from ClinicsRepository.create_clinic_for_admin right
        after the clinic row is inserted, so every clinic has an hours row
        from day one."""
        return await self._upsert(clinic_id=clinic_id, schedule=DEFAULT_WEEKLY_SCHEDULE, timezone="UTC")

    async def get_availability_by_clinic_id(self, *, clinic_id: str) -> Optional[ClinicAvailabilityInDB]:
        record = await self.db.fetch_one(
            query=GET_CLINIC_AVAILABILITY_BY_CLINIC_ID_QUERY, values={"clinic_id": clinic_id}
        )
        if record:
            return _record_to_model(record)

    async def get_or_create_availability(self, *, clinic_id: str) -> ClinicAvailabilityInDB:
        """Self-healing read: backs GET. Covers clinics created before this
        table existed, or any future path that creates a clinic without
        going through create_clinic_for_admin -- GET never 404s for a
        clinic that legitimately exists just because hours were never
        explicitly provisioned."""
        existing = await self.get_availability_by_clinic_id(clinic_id=clinic_id)
        if existing:
            return existing
        return await self.create_default_availability_for_clinic(clinic_id=clinic_id)

    async def update_availability(
        self, *, clinic_id: str, availability_update: ClinicAvailabilityUpdate
    ) -> ClinicAvailabilityInDB:
        return await self._upsert(
            clinic_id=clinic_id,
            schedule=availability_update.schedule,
            timezone=availability_update.timezone,
        )