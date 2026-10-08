"""
Weekly recurring hours, from pets-appts
`app/api/routes/clinics/clinic_availability.py`.

GET is unauthenticated on purpose so an embedded widget can pull a tenant's
hours directly; only the rate limiter stands in front of it. PUT is
JWT-authed and additionally passes through the host's own
`check_clinic_modification_permissions`.

Note what this does NOT do, in this version or the one it came from: nothing
here combines these hours with existing bookings to produce a list of open
slots, and `has_overlapping_confirmed_appointment` never reads this table. The
two halves of "when can I book" are still independent. See docs/adapting.md.
"""
from typing import Any

from fastapi import APIRouter, Body, Depends

from kalens.db.availability import ClinicAvailabilityRepository
from kalens.db.database import get_repository
from kalens.integration import AppointmentsIntegration
from kalens.limiter import (
    enforce_clinic_availability_read_rate_limits,
    enforce_clinic_availability_write_rate_limits,
)
from kalens.models.availability import ClinicAvailabilityInDB, ClinicAvailabilityUpdate


def build_availability_router(integration: AppointmentsIntegration) -> APIRouter:
    router = APIRouter()

    get_clinic_by_id_from_path = integration.get_clinic_by_id_from_path
    check_clinic_modification_permissions = integration.check_clinic_modification_permissions

    @router.get(
        "/",
        response_model=ClinicAvailabilityInDB,
        name="clinic-availability:get-availability",
        dependencies=[Depends(enforce_clinic_availability_read_rate_limits)],
    )
    async def get_clinic_availability(
            clinic: Any = Depends(get_clinic_by_id_from_path),
            availability_repo: ClinicAvailabilityRepository = Depends(get_repository(ClinicAvailabilityRepository)),
    ) -> ClinicAvailabilityInDB:
        return await availability_repo.get_or_create_availability(clinic_id=clinic.id)

    @router.put(
        "/",
        response_model=ClinicAvailabilityInDB,
        name="clinic-availability:update-availability",
        dependencies=[
            Depends(enforce_clinic_availability_write_rate_limits),
            Depends(check_clinic_modification_permissions),
        ],
    )
    async def update_clinic_availability(
            clinic: Any = Depends(get_clinic_by_id_from_path),
            availability_update: ClinicAvailabilityUpdate = Body(..., embed=False),
            availability_repo: ClinicAvailabilityRepository = Depends(get_repository(ClinicAvailabilityRepository)),
    ) -> ClinicAvailabilityInDB:
        return await availability_repo.update_availability(clinic_id=clinic.id, availability_update=availability_update)

    return router
