"""
Host-side fixtures: the tenants, staff, clients, subjects and services an
appointment needs before it can exist.

That this file is as long as it is *is* a finding, not an accident. There is
no such thing as a cheap appointment fixture: a clinic, an admin, a client, an
owner profile, a subject and a service all have to exist first. The same
observation holds in pets-appts, and it is what makes appointments hard to
test in isolation there. Extracting the library doesn't fix it -- the graph is
in the domain, not the packaging.
"""
from uuid import uuid4

import pytest
import pytest_asyncio

import appts_core
from tests._host.repositories import (
    ClinicAPIKeysRepository,
    ClinicsRepository,
    PetProfilesRepository,
    ServicesRepository,
    UsersRepository,
)
from tests._host.models import PetProfileCreate


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """The limiter's storage is process-global, so a test that exhausts a
    bucket would otherwise 429 every test after it. pets-appts carries the
    identical autouse fixture for the identical reason."""
    appts_core.reset_public_rate_limits()
    yield
    appts_core.reset_public_rate_limits()


def auth(user) -> dict:
    """The reference host's stub scheme -- see tests/_host/dependencies.py."""
    return {"Authorization": f"Bearer {user.id}"}


@pytest_asyncio.fixture
async def clinics_repo(db) -> ClinicsRepository:
    return ClinicsRepository(db)


@pytest_asyncio.fixture
async def users_repo(db) -> UsersRepository:
    return UsersRepository(db)


@pytest_asyncio.fixture
async def services_repo(db) -> ServicesRepository:
    return ServicesRepository(db)


@pytest_asyncio.fixture
async def pets_repo(db) -> PetProfilesRepository:
    return PetProfilesRepository(db)


@pytest_asyncio.fixture
async def keys_repo(db) -> ClinicAPIKeysRepository:
    return ClinicAPIKeysRepository(db)


@pytest_asyncio.fixture
async def clinic_a(clinics_repo):
    return await clinics_repo.create_clinic(name=f"Clinic A {uuid4().hex[:6]}")


@pytest_asyncio.fixture
async def clinic_b(clinics_repo):
    return await clinics_repo.create_clinic(name=f"Clinic B {uuid4().hex[:6]}")


async def _make_user(users_repo, *, role="client", clinic_id=None):
    tag = uuid4().hex[:10]
    return await users_repo.register_user(
        email=f"{tag}@example.com",
        username=f"user_{tag}",
        role=role,
        clinic_id=clinic_id,
        full_name=f"User {tag}",
    )


@pytest_asyncio.fixture
async def clinic_a_admin(users_repo, clinic_a):
    return await _make_user(users_repo, role="clinic_admin", clinic_id=clinic_a.id)


@pytest_asyncio.fixture
async def clinic_a_aux(users_repo, clinic_a):
    return await _make_user(users_repo, role="clinic_aux", clinic_id=clinic_a.id)


@pytest_asyncio.fixture
async def clinic_b_admin(users_repo, clinic_b):
    return await _make_user(users_repo, role="clinic_admin", clinic_id=clinic_b.id)


@pytest_asyncio.fixture
async def client_one(users_repo):
    return await _make_user(users_repo)


@pytest_asyncio.fixture
async def client_two(users_repo):
    return await _make_user(users_repo)


async def _make_pet(pets_repo, owner_user, name="Blacky", species="cat"):
    return await pets_repo.create_pet(
        new_pet=PetProfileCreate(name=name, species=species),
        owner_profile_id=owner_user.profile.id,
    )


@pytest_asyncio.fixture
async def client_one_pet(pets_repo, client_one):
    return await _make_pet(pets_repo, client_one)


@pytest_asyncio.fixture
async def client_two_pet(pets_repo, client_two):
    return await _make_pet(pets_repo, client_two, name="Rex", species="dog")


@pytest_asyncio.fixture
async def service_a(services_repo, clinic_a):
    return await services_repo.create_service(
        clinic_id=clinic_a.id, name="Wellness exam", duration_minutes=30
    )


@pytest_asyncio.fixture
async def service_b(services_repo, clinic_b):
    return await services_repo.create_service(
        clinic_id=clinic_b.id, name="Dental cleaning", duration_minutes=45
    )


@pytest_asyncio.fixture
async def clinic_a_public_key(keys_repo, clinic_a) -> str:
    return await keys_repo.create_key_for_clinic(
        clinic_id=clinic_a.id, public_key=f"pk_live_{uuid4().hex}"
    )
