"""
Appointment permission checks and path-param resolution, from pets-appts
`app/api/dependencies/appointments.py`.

WHY THESE ARE BUILT BY A FACTORY
    Everything else in this library resolves the host through
    `get_integration()` at call time. Dependencies can't: FastAPI reads a
    dependency's *signature* when the function is defined, and the host's
    `get_current_active_user` / `get_service_by_id_from_path` appear in these
    signatures. So they are defined inside a factory that runs after
    `configure()`, closing over the host's callables.

    The function bodies below are unchanged from the source. Only the
    annotations moved: `UserInDB` and `ServiceInDB` are the host's models, so
    they are `Any` here -- FastAPI never validates a `Depends`-supplied
    parameter against its annotation, so this changes nothing at runtime and
    nothing in the emitted schema.
"""
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable

from fastapi import Body, Depends, HTTPException, Path, status

from kalens.db.appointments import AppointmentsRepository
from kalens.db.database import get_repository
from kalens.integration import AppointmentsIntegration
from kalens.models.appointment import (
    AppointmentInDB,
    AppointmentRequestIn,
    AppointmentStatus,
)


@dataclass(frozen=True)
class AppointmentDependencies:
    """The built dependency callables.

    Identity matters: FastAPI caches a dependency per request by the callable
    object, and the host's evaluations code must import the *same*
    `get_appointment_by_id_from_path` the routes use, or a request would
    resolve the appointment twice. `configure()` builds this once and hands
    back the same instance every time.
    """
    get_appointment_for_service_from_user_by_path: Callable
    get_appointment_by_id_from_path: Callable
    check_appointment_create_permissions: Callable
    check_appointment_list_permissions: Callable
    check_appointment_get_permissions: Callable
    check_appointment_confirmation_permissions: Callable
    check_appointment_cancel_permissions: Callable
    check_appointment_withdrawal_permissions: Callable


def build_appointment_dependencies(
    integration: AppointmentsIntegration,
) -> AppointmentDependencies:
    get_current_active_user = integration.get_current_active_user
    get_service_by_id_from_path = integration.get_service_by_id_from_path
    get_user_by_username_from_path = integration.get_user_by_username_from_path
    get_owner_profile_id_for_user = integration.get_owner_profile_id_for_user
    user_can_manage_service = integration.user_can_manage_service
    get_service_clinic_id = integration.get_service_clinic_id
    subject_repository = integration.subject_repository
    default_duration = integration.settings.default_appointment_duration_minutes

    async def get_appointment_for_service_from_user_by_path(
            user: Any = Depends(get_user_by_username_from_path),
            service: Any = Depends(get_service_by_id_from_path),
            appointments_repo: AppointmentsRepository = Depends(get_repository(AppointmentsRepository)),
    ) -> AppointmentInDB:
        """
        TEMPORARY shim, kept only so evaluations.py can still import something.
        Evaluations currently assume one appointment per (service, user) pair,
        which is no longer true post-phase-2 — a client can have several
        appointments for the same service. This returns the most recent one
        as a stopgap. Do not build new functionality on top of this; it goes
        away when evaluations move to being keyed by appointment_id (phase 3).

        It survives extraction only because evaluations stayed with the host
        and still imports it. See docs/integration-contract.md.
        """
        appointments = await appointments_repo.list_appointments_for_service_from_user(service=service, user=user)

        if not appointments:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

        return appointments[0]  # most recent — repo query orders by start_time DESC

    async def get_appointment_by_id_from_path(
            appointment_id: str = Path(...),
            service: Any = Depends(get_service_by_id_from_path),
            appointments_repo: AppointmentsRepository = Depends(get_repository(AppointmentsRepository)),
    ) -> AppointmentInDB:
        appointment = await appointments_repo.get_appointment_by_id(id=appointment_id)

        if not appointment or appointment.service_id != service.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

        return appointment

    async def check_appointment_create_permissions(
            appointment_in: AppointmentRequestIn = Body(..., embed=False),
            current_user: Any = Depends(get_current_active_user),
            service: Any = Depends(get_service_by_id_from_path),
            appointments_repo: AppointmentsRepository = Depends(get_repository(AppointmentsRepository)),
            pets_repo: Any = Depends(get_repository(subject_repository)),
    ) -> None:
        if user_can_manage_service(user=current_user, service=service):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Users are unable to request appointments for services they own.",
            )

        # NEW — same 404-not-403 opacity as the pet/owner dependencies
        # elsewhere: don't confirm whether a given pet_id exists at all if it
        # isn't the requesting user's own.
        pet = await pets_repo.get_pet_by_id(id=appointment_in.pet_id)
        if not pet or pet.owner_profile_id != get_owner_profile_id_for_user(user=current_user):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No pet found with that id.",
            )

        clinic_id = get_service_clinic_id(service)
        duration = service.duration_minutes or default_duration
        end_time = appointment_in.start_time + timedelta(minutes=duration)

        if await appointments_repo.has_overlapping_confirmed_appointment(
                clinic_id=clinic_id, start_time=appointment_in.start_time, end_time=end_time
        ):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This time is already booked.")

    def check_appointment_list_permissions(
            current_user: Any = Depends(get_current_active_user),
            service: Any = Depends(get_service_by_id_from_path),
    ) -> None:
        if not user_can_manage_service(user=current_user, service=service):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unable to access appointments.")

    def check_appointment_get_permissions(
            current_user: Any = Depends(get_current_active_user),
            service: Any = Depends(get_service_by_id_from_path),
            appointment: AppointmentInDB = Depends(get_appointment_by_id_from_path),
    ) -> None:
        if not user_can_manage_service(user=current_user, service=service) and appointment.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unable to access appointment.")

    async def check_appointment_confirmation_permissions(
            current_user: Any = Depends(get_current_active_user),
            service: Any = Depends(get_service_by_id_from_path),
            appointment: AppointmentInDB = Depends(get_appointment_by_id_from_path),
            appointments_repo: AppointmentsRepository = Depends(get_repository(AppointmentsRepository)),
    ) -> None:
        if not user_can_manage_service(user=current_user, service=service):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only staff of the clinic that owns this service may confirm appointments.",
            )

        if appointment.status != AppointmentStatus.requested:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Can only confirm appointments that are currently requested",
            )

        clinic_id = get_service_clinic_id(service)

        if await appointments_repo.has_overlapping_confirmed_appointment(
                clinic_id=clinic_id,
                start_time=appointment.start_time,
                end_time=appointment.end_time,
                exclude_id=appointment.id,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This time conflicts with another confirmed appointment.",
            )

    def check_appointment_cancel_permissions(
            current_user: Any = Depends(get_current_active_user),
            service: Any = Depends(get_service_by_id_from_path),
            appointment: AppointmentInDB = Depends(get_appointment_by_id_from_path),
    ) -> None:
        """
        Either side of the booking may cancel, but not from the same states.

            booking client + confirmed  -> cancelled
            clinic staff   + confirmed  -> cancelled
            clinic staff   + requested  -> declined  (see resolve_cancellation_status)
            booking client + requested  -> 400; clients withdraw, they don't cancel
            anyone else                 -> 403

        Staff may act on a requested appointment because declining a booking is
        theirs to do; a client hasn't had anything to cancel yet at that point,
        which is what the separate withdraw route is for.
        """
        is_booking_client = appointment.user_id == current_user.id
        is_clinic_staff = user_can_manage_service(user=current_user, service=service)

        if not is_booking_client and not is_clinic_staff:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unable to cancel this appointment.")

        if appointment.status == AppointmentStatus.confirmed:
            return
        if is_clinic_staff and appointment.status == AppointmentStatus.requested:
            return

        if is_clinic_staff:
            detail = "Can only cancel appointments that are requested or confirmed"
        else:
            detail = "Can only cancel appointments that have been confirmed"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    def check_appointment_withdrawal_permissions(
            current_user: Any = Depends(get_current_active_user),
            appointment: AppointmentInDB = Depends(get_appointment_by_id_from_path),
    ) -> None:
        if appointment.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unable to withdraw this appointment.")
        if appointment.status != AppointmentStatus.requested:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Can only withdraw currently requested appointments.",
            )

    return AppointmentDependencies(
        get_appointment_for_service_from_user_by_path=get_appointment_for_service_from_user_by_path,
        get_appointment_by_id_from_path=get_appointment_by_id_from_path,
        check_appointment_create_permissions=check_appointment_create_permissions,
        check_appointment_list_permissions=check_appointment_list_permissions,
        check_appointment_get_permissions=check_appointment_get_permissions,
        check_appointment_confirmation_permissions=check_appointment_confirmation_permissions,
        check_appointment_cancel_permissions=check_appointment_cancel_permissions,
        check_appointment_withdrawal_permissions=check_appointment_withdrawal_permissions,
    )
