"""
The seam between this library and its host application.

This is the only genuinely new code in `appts_core`. Everything else is the
pets-appts scheduling engine copied across with its imports repointed at this
module.

WHY A CONTRACT AND NOT A BASE CLASS
    The extracted code does not own users, services, clinics, or the *subject*
    of an appointment (a pet, today). It reads all four, joins to two of them
    in SQL, and returns two of them inside its response bodies. Those are the
    host's tables and the host's models. Rather than pretend otherwise with
    abstract base classes nobody would implement twice, the host hands over
    the concrete pieces once and this library uses them directly.

WHY THE MODELS ARE INJECTED TOO
    `AppointmentPublic.pet` is typed `PetProfilePublic` in pets-appts. A
    library that hardcoded that type would only work for pets; one that typed
    it `Any` would change the generated OpenAPI schema, and the schema is the
    contract the host's own tests and frontends are written against. So the
    library declares the hydrated fields loosely and the host passes down a
    subclass that re-narrows them. The emitted schema is then identical to the
    one pets-appts produces today.

    See docs/integration-contract.md for the full method-by-method contract,
    and docs/adapting.md for what each of these seams *means* -- which is what
    you change when the appointment is for a patient, a garment, or a massage
    instead of a pet.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from appts_core.settings import Settings


@dataclass(frozen=True)
class AppointmentsIntegration:
    """Everything `appts_core` needs from its host, supplied once at startup.

    Every `type` below is a repository *class*, not an instance -- they are
    constructed per-request with the shared `databases.Database`, exactly as
    the host's own `get_repository` does it.
    """

    # --- host repositories ------------------------------------------------
    # get_user_by_id(user_id), get_user_by_email(email, populate),
    # get_or_create_guest_user(email, full_name, phone_number),
    # and a `.profiles_repo` exposing get_profile_by_user_id(user_id).
    users_repository: type

    # The SUBJECT of an appointment -- `PetProfilesRepository` in pets-appts.
    # get_pet_by_id(id), get_pet_by_id_for_clinic(id, clinic_id),
    # create_pet(new_pet, owner_profile_id),
    # list_pet_profiles_for_clinic(clinic_id, owner_profile_id).
    # The method names are pets-shaped because the extraction is verbatim;
    # docs/adapting.md covers renaming them.
    subject_repository: type

    # get_service_by_id_for_clinic(id, clinic_id),
    # list_services_by_clinic_id(clinic_id).
    services_repository: type

    # Links a subject's owner to a tenant -- `ClinicOwnerProfilesRepository`.
    # get_pivot_for_clinic_and_owner(clinic_id, owner_profile_id),
    # register_owner_profile_with_clinic(clinic_id, registration).
    owner_link_repository: type

    # --- host dependencies (FastAPI-callable) -----------------------------
    get_current_active_user: Callable
    get_service_by_id_from_path: Callable
    get_user_by_username_from_path: Callable
    get_clinic_by_id_from_path: Callable
    check_clinic_modification_permissions: Callable
    get_clinic_from_public_key: Callable

    # --- host predicates (plain functions, keyword-called) ----------------
    user_can_manage_service: Callable        # (*, user, service) -> bool
    get_service_clinic_id: Callable          # (service) -> str
    get_owner_profile_id_for_user: Callable  # (*, user) -> str

    # --- host models, so the emitted OpenAPI schema stays unchanged -------
    # Subclass of appts_core.models.AppointmentPublic that re-narrows
    # `user`, `pet` and `service` to the host's own public models.
    appointment_public_model: type
    # Subclass of appts_core.models.PublicAppointmentCreate re-narrowing `pet`.
    public_appointment_create_model: type
    # The host's PetProfilePublic / ServicePublic / ClinicOwnerProfileRegistration.
    subject_public_model: type
    service_public_model: type
    owner_link_registration_model: type

    settings: Settings = field(default_factory=Settings)


_integration: Optional[AppointmentsIntegration] = None


def set_integration(integration: AppointmentsIntegration) -> None:
    """Install the host contract. Called by `appts_core.configure()`."""
    global _integration
    _integration = integration


def get_integration() -> AppointmentsIntegration:
    """Read the installed contract.

    Repositories and models resolve host pieces through here at *call* time
    rather than import time, which is what lets them stay plain module-level
    classes. Dependencies and routers cannot do that -- FastAPI reads their
    signatures when they are defined -- so those are built by factories that
    run after `configure()`. See `appts_core.configure`.
    """
    if _integration is None:
        raise RuntimeError(
            "appts_core is not configured. Call appts_core.configure(...) with an "
            "AppointmentsIntegration before importing routers or using repositories."
        )
    return _integration


def get_settings() -> Settings:
    return get_integration().settings


def reset_integration() -> None:
    """Test-only. Lets one process build several differently-wired hosts."""
    global _integration
    _integration = None


def coerce(model: type, value: Any) -> Any:
    """Rebuild `value` as `model`, tolerating a host model that has already
    produced the right shape.

    `populate_appointment` hydrates with whatever the host's repositories
    return; those are the host's own pydantic models, and the response model
    is the host's subclass. Passing them straight through works, but a host
    whose repository returns an *InDB* variant where a *Public* one is
    expected would otherwise leak extra fields into the response.
    """
    if value is None:
        return None
    if isinstance(value, model):
        return value
    return model(**value.model_dump())
