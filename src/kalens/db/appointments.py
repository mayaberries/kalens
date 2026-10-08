from datetime import timedelta, datetime
from typing import Any, List, Optional, Union
from uuid import uuid4

from databases.core import Database

from kalens.db.base import BaseRepository
from kalens.integration import coerce, get_integration, get_settings
from kalens.models.appointment import (
    AppointmentCreate,
    AppointmentPublic,
    AppointmentInDB,
    AppointmentStatus,
)

# Every query below builds an AppointmentInDB out of an explicit column list --
# there's no SELECT *. Because all of that model's fields are Optional, a column
# left out of one list doesn't raise: it silently reads back as None, so a value
# saves correctly and then appears to have vanished. One shared list is what
# stops that drift. (Interpolated into module-level constants only, never user
# input -- the :named placeholders are still bound by the driver.)
APPOINTMENT_COLUMNS = (
    "id, service_id, user_id, pet_id, status, start_time, end_time, "
    "cancellation_reason, cancelled_by, created_at, updated_at"
)

CREATE_APPOINTMENT_FOR_SERVICE_QUERY = f"""
    INSERT INTO appointments (id, service_id, user_id, pet_id, status, start_time, end_time)
    VALUES (:id, :service_id, :user_id, :pet_id, :status, :start_time, :end_time)
    RETURNING {APPOINTMENT_COLUMNS};
"""

GET_APPOINTMENT_BY_ID_QUERY = f"""
    SELECT {APPOINTMENT_COLUMNS}
    FROM appointments
    WHERE id = :id;
"""

LIST_APPOINTMENTS_FOR_SERVICE_QUERY = f"""
    SELECT {APPOINTMENT_COLUMNS}
    FROM appointments
    WHERE service_id = :service_id
    ORDER BY start_time;
"""

# Replaces "does this service already have any appointment from this user" —
# now it's just history, not an identity check.
LIST_APPOINTMENTS_FOR_SERVICE_FROM_USER_QUERY = f"""
    SELECT {APPOINTMENT_COLUMNS}
    FROM appointments
    WHERE service_id = :service_id AND user_id = :user_id
    ORDER BY start_time DESC;
"""

# The core of the new model: is this time range already claimed by a
# *confirmed* appointment for the same provider (across any of their services)?
CHECK_OVERLAPPING_CONFIRMED_APPOINTMENT_QUERY = """
    SELECT a.id
    FROM appointments a
    INNER JOIN services s ON a.service_id = s.id
    WHERE s.clinic_id = :clinic_id
      AND a.status = 'confirmed'
      AND (CAST(:exclude_id AS CHAR(36)) IS NULL OR a.id != CAST(:exclude_id AS CHAR(36)))
      AND a.start_time < :end_time
      AND a.end_time > :start_time
    LIMIT 1;
"""

CONFIRM_APPOINTMENT_QUERY = f"""
    UPDATE appointments
    SET status = 'confirmed'
    WHERE id = :id
    RETURNING {APPOINTMENT_COLUMNS};
"""

# Status is bound rather than hardcoded: cancelling a *requested* appointment
# declines it instead (see resolve_cancellation_status), so the caller decides.
CANCEL_APPOINTMENT_QUERY = f"""
    UPDATE appointments
    SET status = :status,
        cancellation_reason = :cancellation_reason,
        cancelled_by = :cancelled_by
    WHERE id = :id
    RETURNING {APPOINTMENT_COLUMNS};
"""

WITHDRAW_APPOINTMENT_QUERY = f"""
    DELETE FROM appointments
    WHERE id = :id
    RETURNING {APPOINTMENT_COLUMNS};
"""

MARK_AS_COMPLETED_QUERY = """
    UPDATE appointments
    SET status = 'completed'
    WHERE id = :id
"""


class AppointmentsRepository(BaseRepository):
    def __init__(self, db: Database) -> None:
        super().__init__(db)
        # The host's own repositories. Resolved from the integration at
        # construction rather than imported, because this library owns neither
        # users nor the subject of an appointment -- it only reads them back to
        # hydrate a response. See integration.py.
        integration = get_integration()
        self.users_repo = integration.users_repository(db)
        self.pets_repo = integration.subject_repository(db)

    async def create_appointment_for_service(
            self, *, new_appointment: AppointmentCreate, service: Any
    ) -> AppointmentInDB:
        duration = service.duration_minutes or get_settings().default_appointment_duration_minutes
        start_time = new_appointment.start_time
        end_time = start_time + timedelta(minutes=duration)

        created_appointment = await self.db.fetch_one(
            query=CREATE_APPOINTMENT_FOR_SERVICE_QUERY,
            values={
                "id": str(uuid4()),
                "service_id": new_appointment.service_id,
                "user_id": new_appointment.user_id,
                "pet_id": new_appointment.pet_id,  # NEW
                "status": AppointmentStatus.requested.value,
                "start_time": start_time,
                "end_time": end_time,
            },
        )
        return AppointmentInDB(**created_appointment)

    async def get_appointment_by_id(self, *, id: str) -> Optional[AppointmentInDB]:
        appointment_record = await self.db.fetch_one(query=GET_APPOINTMENT_BY_ID_QUERY, values={"id": id})
        if appointment_record:
            return AppointmentInDB(**appointment_record)

    async def list_appointments_for_service(
            self, *, service: Any, populate: bool = True
    ) -> List[Union[AppointmentInDB, AppointmentPublic]]:
        appointment_records = await self.db.fetch_all(
            query=LIST_APPOINTMENTS_FOR_SERVICE_QUERY, values={"service_id": service.id}
        )
        appointments = [AppointmentInDB(**a) for a in appointment_records]

        if populate:
            return [await self.populate_appointment(appointment=a) for a in appointments]
        return appointments

    async def list_appointments_for_service_from_user(
            self, *, service: Any, user: Any
    ) -> List[AppointmentInDB]:
        records = await self.db.fetch_all(
            query=LIST_APPOINTMENTS_FOR_SERVICE_FROM_USER_QUERY,
            values={"service_id": service.id, "user_id": user.id},
        )
        return [AppointmentInDB(**r) for r in records]

    async def has_overlapping_confirmed_appointment(
            self, *, clinic_id: str, start_time: datetime, end_time: datetime, exclude_id: Optional[str] = None
    ) -> bool:
        conflict = await self.db.fetch_one(
            query=CHECK_OVERLAPPING_CONFIRMED_APPOINTMENT_QUERY,
            values={
                "clinic_id": clinic_id,
                "exclude_id": exclude_id,
                "start_time": start_time,
                "end_time": end_time,
            },
        )
        return conflict is not None

    async def confirm_appointment(self, *, appointment: AppointmentInDB) -> AppointmentInDB:
        confirmed = await self.db.fetch_one(query=CONFIRM_APPOINTMENT_QUERY, values={"id": appointment.id})
        return AppointmentInDB(**confirmed)

    async def cancel_appointment(
            self,
            *,
            appointment: AppointmentInDB,
            new_status: AppointmentStatus,
            cancellation_reason: Optional[str] = None,
            cancelled_by: Optional[str] = None,
    ) -> AppointmentInDB:
        cancelled = await self.db.fetch_one(
            query=CANCEL_APPOINTMENT_QUERY,
            values={
                "id": appointment.id,
                "status": new_status.value,
                "cancellation_reason": cancellation_reason,
                "cancelled_by": cancelled_by,
            },
        )
        return AppointmentInDB(**cancelled)

    async def withdraw_appointment(self, *, appointment: AppointmentInDB) -> AppointmentInDB:
        withdrawn = await self.db.fetch_one(query=WITHDRAW_APPOINTMENT_QUERY, values={"id": appointment.id})
        return AppointmentInDB(**withdrawn)

    async def mark_as_completed(self, *, appointment: AppointmentInDB) -> None:
        return await self.db.execute(query=MARK_AS_COMPLETED_QUERY, values={"id": appointment.id})

    async def populate_appointment(self, *, appointment: AppointmentInDB) -> AppointmentPublic:
        integration = get_integration()
        pet = await self.pets_repo.get_pet_by_id(id=appointment.pet_id)
        return integration.appointment_public_model(
            **appointment.model_dump(),
            user=await self.users_repo.get_user_by_id(user_id=appointment.user_id),
            pet=coerce(integration.subject_public_model, pet),
        )
