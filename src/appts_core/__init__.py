"""
appts_core -- the scheduling engine extracted from pets-appts.

Appointments, weekly availability, and the public booking widget surface,
lifted out verbatim so more than one application can run the same engine
instead of forking it. It owns two tables (`appointments`,
`clinic_availability`) and nothing else; users, services, tenants and the
subject of a booking stay with the host and arrive through
`AppointmentsIntegration`.

USAGE

    from appts_core import AppointmentsIntegration, Settings, configure

    appts = configure(AppointmentsIntegration(
        users_repository=UsersRepository,
        subject_repository=PetProfilesRepository,
        ...
    ))

    router.include_router(
        appts.appointments_router,
        prefix="/services/{service_id}/appointments",
        tags=["appointments"],
    )
    router.include_router(appts.public_booking_router, prefix="/public", tags=["public-booking"])
    router.include_router(
        appts.availability_router,
        prefix="/clinics/{clinic_id}/availability",
        tags=["clinic-availability"],
    )

Those prefixes are the host's to choose, and are what pets-appts mounts today.
The route `name=` values are fixed by this library, because tests and
templates resolve URLs through `app.url_path_for(...)`.

`configure()` must run before the routers are read, and returns the module
handle you keep. Calling it twice rebuilds everything; see `reset()`.

See docs/integration-contract.md for the contract, docs/migrations.md for the
schema, and docs/adapting.md for what to change when the appointment is for a
patient, a garment, or a massage rather than a pet.
"""
from dataclasses import dataclass

from fastapi import APIRouter

from appts_core.api.dependencies.appointments import (
    AppointmentDependencies,
    build_appointment_dependencies,
)
from appts_core.api.routes.appointments import build_appointments_router
from appts_core.api.routes.availability import build_availability_router
from appts_core.api.routes.public_booking import build_public_booking_router
from appts_core.db.appointments import AppointmentsRepository
from appts_core.db.availability import ClinicAvailabilityRepository
from appts_core.db.base import BaseRepository
from appts_core.db.database import get_database, get_repository
from appts_core.integration import (
    AppointmentsIntegration,
    get_integration,
    reset_integration,
    set_integration,
)
from appts_core.limiter import reset_public_rate_limits
from appts_core.models.appointment import (
    DEFAULT_APPOINTMENT_DURATION_MINUTES,
    AppointmentBase,
    AppointmentCancelIn,
    AppointmentCreate,
    AppointmentInDB,
    AppointmentPublic,
    AppointmentRequestIn,
    AppointmentStatus,
    AppointmentUpdate,
    PublicAppointmentCreate,
    resolve_cancellation_status,
)
from appts_core.models.availability import (
    DEFAULT_WEEKLY_SCHEDULE,
    ClinicAvailabilityBase,
    ClinicAvailabilityInDB,
    ClinicAvailabilityUpdate,
    TimeRange,
    Weekday,
    WeeklySchedule,
)
from appts_core.models.core import CoreModel, DateTimeModelMixin, IDModelMixin
from appts_core.settings import Settings

__version__ = "0.1.0"


@dataclass(frozen=True)
class AppointmentsModule:
    """What `configure()` hands back: the wired routers and dependencies.

    Hold onto it. The dependencies in particular are built once and must not
    be rebuilt -- FastAPI caches a dependency per request by callable
    identity, so a host that re-derived `get_appointment_by_id_from_path`
    would resolve the same appointment twice in one request.
    """
    integration: AppointmentsIntegration
    dependencies: AppointmentDependencies
    appointments_router: APIRouter
    public_booking_router: APIRouter
    availability_router: APIRouter


def configure(integration: AppointmentsIntegration) -> AppointmentsModule:
    """Install the host contract and build the routers.

    Call once, at import time of whatever module assembles your API, and
    before including any of the returned routers.
    """
    set_integration(integration)
    # The rate limiter caches its parsed limits on first use; drop that so a
    # reconfigure with different Settings takes effect rather than silently
    # keeping the previous host's budgets.
    reset_public_rate_limits()

    dependencies = build_appointment_dependencies(integration)
    return AppointmentsModule(
        integration=integration,
        dependencies=dependencies,
        appointments_router=build_appointments_router(integration, dependencies),
        public_booking_router=build_public_booking_router(integration),
        availability_router=build_availability_router(integration),
    )


def reset() -> None:
    """Test-only. Forget the installed integration and the limiter state."""
    reset_public_rate_limits()
    reset_integration()


__all__ = [
    # wiring
    "AppointmentsIntegration",
    "AppointmentsModule",
    "AppointmentDependencies",
    "Settings",
    "configure",
    "reset",
    "get_integration",
    # repositories -- the host's evaluations code needs AppointmentsRepository
    "AppointmentsRepository",
    "ClinicAvailabilityRepository",
    "BaseRepository",
    "get_database",
    "get_repository",
    # appointment models
    "AppointmentBase",
    "AppointmentCancelIn",
    "AppointmentCreate",
    "AppointmentInDB",
    "AppointmentPublic",
    "AppointmentRequestIn",
    "AppointmentStatus",
    "AppointmentUpdate",
    "PublicAppointmentCreate",
    "resolve_cancellation_status",
    "DEFAULT_APPOINTMENT_DURATION_MINUTES",
    # availability models
    "ClinicAvailabilityBase",
    "ClinicAvailabilityInDB",
    "ClinicAvailabilityUpdate",
    "TimeRange",
    "Weekday",
    "WeeklySchedule",
    "DEFAULT_WEEKLY_SCHEDULE",
    # shared model mixins, vendored so the library has no host imports
    "CoreModel",
    "DateTimeModelMixin",
    "IDModelMixin",
    "reset_public_rate_limits",
]
