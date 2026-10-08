"""
Appointment path operations, from pets-appts
`app/api/routes/appointments/appointments.py`.

Built by a factory for the same reason the dependencies are (see
`api/dependencies/appointments.py`). Route `name=` values are preserved
exactly -- the host's tests build every URL with
`app.url_path_for("appointments:create-appointment", ...)`, so a renamed route
breaks them loudly, which is the point.
"""
from typing import Any, List, Optional

from fastapi import APIRouter, Body, status
from fastapi.param_functions import Depends

from kalens.api.dependencies.appointments import AppointmentDependencies
from kalens.db.appointments import AppointmentsRepository
from kalens.db.database import get_repository
from kalens.integration import AppointmentsIntegration
from kalens.models.appointment import (
    AppointmentCancelIn,
    AppointmentCreate,
    AppointmentInDB,
    AppointmentRequestIn,
    resolve_cancellation_status,
)


def build_appointments_router(
    integration: AppointmentsIntegration,
    deps: AppointmentDependencies,
) -> APIRouter:
    router = APIRouter()

    get_current_active_user = integration.get_current_active_user
    get_service_by_id_from_path = integration.get_service_by_id_from_path
    # The host's subclass, which re-narrows `user` / `pet` / `service` back to
    # concrete models. Declaring it as the response_model is what keeps the
    # emitted OpenAPI schema identical to the host's pre-extraction one.
    AppointmentPublic = integration.appointment_public_model

    @router.post(
        "/", response_model=AppointmentPublic, name="appointments:create-appointment",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(deps.check_appointment_create_permissions)],
    )
    async def create_appointment(
            appointment_in: AppointmentRequestIn = Body(..., embed=False),
            service: Any = Depends(get_service_by_id_from_path),
            current_user: Any = Depends(get_current_active_user),
            appointments_repo: AppointmentsRepository = Depends(get_repository(AppointmentsRepository)),
    ):
        created = await appointments_repo.create_appointment_for_service(
            new_appointment=AppointmentCreate(
                service_id=service.id,
                user_id=current_user.id,
                pet_id=appointment_in.pet_id,
                start_time=appointment_in.start_time,
            ),
            service=service,
        )
        return await appointments_repo.populate_appointment(appointment=created)

    @router.get(
        "/", response_model=List[AppointmentPublic], name="appointments:list-appointments-for-service",
        status_code=status.HTTP_200_OK,
        dependencies=[Depends(deps.check_appointment_list_permissions)],
    )
    async def list_appointments_for_service(
            service: Any = Depends(get_service_by_id_from_path),
            appointments_repo: AppointmentsRepository = Depends(get_repository(AppointmentsRepository)),
    ):
        return await appointments_repo.list_appointments_for_service(service=service)

    @router.get(
        "/{appointment_id}", response_model=AppointmentPublic, name="appointments:get-appointment-by-id",
        status_code=status.HTTP_200_OK,
        dependencies=[Depends(deps.check_appointment_get_permissions)],
    )
    async def get_appointment_by_id(
            appointment: AppointmentInDB = Depends(deps.get_appointment_by_id_from_path),
            appointments_repo: AppointmentsRepository = Depends(get_repository(AppointmentsRepository)),
    ):
        return await appointments_repo.populate_appointment(appointment=appointment)

    @router.put(
        "/{appointment_id}/confirm", response_model=AppointmentPublic, name="appointments:confirm-appointment",
        status_code=status.HTTP_200_OK,
        dependencies=[Depends(deps.check_appointment_confirmation_permissions)],
    )
    async def confirm_appointment(
            appointment: AppointmentInDB = Depends(deps.get_appointment_by_id_from_path),
            appointments_repo: AppointmentsRepository = Depends(get_repository(AppointmentsRepository)),
    ):
        confirmed = await appointments_repo.confirm_appointment(appointment=appointment)
        return await appointments_repo.populate_appointment(appointment=confirmed)

    @router.put(
        "/{appointment_id}/cancel", response_model=AppointmentPublic, name="appointments:cancel-appointment",
        status_code=status.HTTP_200_OK,
        dependencies=[Depends(deps.check_appointment_cancel_permissions)],
    )
    async def cancel_appointment(
            cancel_in: Optional[AppointmentCancelIn] = Body(None, embed=False),
            appointment: AppointmentInDB = Depends(deps.get_appointment_by_id_from_path),
            current_user: Any = Depends(get_current_active_user),
            appointments_repo: AppointmentsRepository = Depends(get_repository(AppointmentsRepository)),
    ):
        # Body is optional so a bodyless PUT stays valid -- cancelling without
        # giving a reason is legitimate, and every pre-existing caller does it.
        cancelled = await appointments_repo.cancel_appointment(
            appointment=appointment,
            # A never-confirmed booking is declined, not cancelled.
            new_status=resolve_cancellation_status(appointment.status),
            cancellation_reason=cancel_in.cancellation_reason if cancel_in else None,
            cancelled_by=current_user.id,
        )
        return await appointments_repo.populate_appointment(appointment=cancelled)

    @router.delete(
        "/{appointment_id}", response_model=AppointmentPublic, name="appointments:withdraw-appointment",
        status_code=status.HTTP_200_OK,
        dependencies=[Depends(deps.check_appointment_withdrawal_permissions)],
    )
    async def withdraw_appointment(
            appointment: AppointmentInDB = Depends(deps.get_appointment_by_id_from_path),
            appointments_repo: AppointmentsRepository = Depends(get_repository(AppointmentsRepository)),
    ):
        withdrawn = await appointments_repo.withdraw_appointment(appointment=appointment)
        # Not populated: the row is gone, so there is nothing left to hydrate
        # the subject or user from. Same as pre-extraction.
        return AppointmentPublic(**withdrawn.model_dump())

    return router
