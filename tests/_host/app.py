"""
The reference host application.

A FastAPI app that implements the integration contract and nothing else. Its
existence is the actual claim this test suite makes: `kalens` runs against
an application that has never heard of pets-appts.

Route prefixes match what pets-appts mounts today, because the ported tests
resolve URLs by name and assert on paths.
"""
from contextlib import asynccontextmanager

from databases import Database
from fastapi import APIRouter, FastAPI

from kalens import AppointmentsIntegration, AppointmentsModule, Settings, configure
from tests._host import dependencies as host_deps
from tests._host.models import (
    AppointmentPublic,
    ClinicOwnerProfileRegistration,
    PetProfilePublic,
    PublicAppointmentCreate,
    ServicePublic,
)
from tests._host.repositories import (
    ClinicOwnerProfilesRepository,
    PetProfilesRepository,
    ServicesRepository,
    UsersRepository,
)


def build_integration(settings: Settings | None = None) -> AppointmentsIntegration:
    return AppointmentsIntegration(
        users_repository=UsersRepository,
        subject_repository=PetProfilesRepository,
        services_repository=ServicesRepository,
        owner_link_repository=ClinicOwnerProfilesRepository,
        get_current_active_user=host_deps.get_current_active_user,
        get_service_by_id_from_path=host_deps.get_service_by_id_from_path,
        get_user_by_username_from_path=host_deps.get_user_by_username_from_path,
        get_clinic_by_id_from_path=host_deps.get_clinic_by_id_from_path,
        check_clinic_modification_permissions=host_deps.check_clinic_modification_permissions,
        get_clinic_from_public_key=host_deps.get_clinic_from_public_key,
        user_can_manage_service=host_deps.user_can_manage_service,
        get_service_clinic_id=host_deps.get_service_clinic_id,
        get_owner_profile_id_for_user=host_deps.get_owner_profile_id_for_user,
        appointment_public_model=AppointmentPublic,
        public_appointment_create_model=PublicAppointmentCreate,
        subject_public_model=PetProfilePublic,
        service_public_model=ServicePublic,
        owner_link_registration_model=ClinicOwnerProfileRegistration,
        settings=settings or Settings(),
    )


def build_app(database_url: str, settings: Settings | None = None) -> tuple[FastAPI, AppointmentsModule]:
    appts = configure(build_integration(settings))

    api = APIRouter()
    api.include_router(
        appts.appointments_router,
        prefix="/services/{service_id}/appointments",
        tags=["appointments"],
    )
    api.include_router(appts.public_booking_router, prefix="/public", tags=["public-booking"])
    api.include_router(
        appts.availability_router,
        prefix="/clinics/{clinic_id}/availability",
        tags=["clinic-availability"],
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # The host owns the connection; the library only reads it back off
        # app.state. Mirrors pets-appts' connect_to_db.
        database = Database(database_url, min_size=2, max_size=10)
        await database.connect()
        app.state._db = database
        yield
        await database.disconnect()

    app = FastAPI(title="kalens reference host", lifespan=lifespan)
    app.include_router(api, prefix="/api")
    return app, appts
