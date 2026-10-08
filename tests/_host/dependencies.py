"""
The reference host's dependencies and predicates.

Auth is deliberately a stub: `Authorization: Bearer <user_id>`. The library
never inspects a token -- it is handed a user object by whatever the host
injects -- so reproducing JWT here would test PyJWT, not `kalens`. What
*is* faithfully reproduced is the shape the library depends on: an object with
`.id`, `.clinic_id` and `.profile.id`, and the 401/403/404 codes the routes'
tests assert on.
"""
from typing import Optional

from fastapi import Depends, Header, HTTPException, Path, status

from kalens import get_repository
from tests._host.models import ClinicPublic, OwnerProfilePublic, ServicePublic, UserPublic
from tests._host.repositories import (
    ClinicAPIKeysRepository,
    ClinicsRepository,
    ServicesRepository,
    UsersRepository,
)


async def get_current_active_user(
    authorization: Optional[str] = Header(None),
    users_repo: UsersRepository = Depends(get_repository(UsersRepository)),
) -> UserPublic:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = await users_repo.get_user_by_id(user_id=authorization.removeprefix("Bearer ").strip())
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


async def get_service_by_id_from_path(
    service_id: str = Path(...),
    current_user: UserPublic = Depends(get_current_active_user),
    services_repo: ServicesRepository = Depends(get_repository(ServicesRepository)),
) -> ServicePublic:
    service = await services_repo.get_service_by_id(id=service_id)
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No service found with that id.")
    return service


async def get_user_by_username_from_path(
    username: str = Path(...),
    users_repo: UsersRepository = Depends(get_repository(UsersRepository)),
) -> UserPublic:
    user = await users_repo.get_user_by_username(username=username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No user found with that username.")
    return user


async def get_clinic_by_id_from_path(
    clinic_id: str = Path(...),
    clinics_repo: ClinicsRepository = Depends(get_repository(ClinicsRepository)),
) -> ClinicPublic:
    """No auth dependency on purpose: GET availability is unauthenticated, so
    resolving the clinic from the path must not require a token."""
    clinic = await clinics_repo.get_clinic_by_id(id=clinic_id)
    if not clinic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No clinic found with that id.")
    return clinic


def check_clinic_modification_permissions(
    current_user: UserPublic = Depends(get_current_active_user),
    clinic: ClinicPublic = Depends(get_clinic_by_id_from_path),
) -> None:
    if current_user.clinic_id != clinic.id or current_user.role != "clinic_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unable to modify this clinic.")


async def get_clinic_from_public_key(
    x_clinic_key: Optional[str] = Header(None, alias="X-Clinic-Key"),
    keys_repo: ClinicAPIKeysRepository = Depends(get_repository(ClinicAPIKeysRepository)),
) -> ClinicPublic:
    """Every failure mode returns the same generic 401 on purpose -- a caller
    must not be able to tell a malformed key from a revoked one from one
    belonging to a clinic that doesn't exist."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing clinic key."
    )
    if not x_clinic_key or not x_clinic_key.startswith(("pk_live_", "pk_test_")):
        raise unauthorized
    clinic = await keys_repo.get_active_clinic_by_public_key(public_key=x_clinic_key)
    if not clinic:
        raise unauthorized
    return clinic


def user_can_manage_service(*, user: UserPublic, service: ServicePublic) -> bool:
    return bool(user.clinic_id) and user.clinic_id == get_service_clinic_id(service)


def get_service_clinic_id(service: ServicePublic) -> str:
    return service.clinic_id


def get_owner_profile_id_for_user(*, user: UserPublic) -> str:
    profile: Optional[OwnerProfilePublic] = getattr(user, "profile", None)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This user has no owner profile.",
        )
    return profile.id
