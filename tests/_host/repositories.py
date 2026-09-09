"""
The reference host's repositories.

One method per line of the integration contract, and nothing else. Raw SQL via
`databases`, the same style the library's own repositories use, so the two are
interchangeable from `get_repository`'s point of view.
"""
from typing import List, Optional
from uuid import uuid4

from databases import Database

from appts_core import BaseRepository
from tests._host.models import (
    ClinicOwnerProfileRegistration,
    ClinicPublic,
    OwnerProfilePublic,
    PetProfileCreate,
    PetProfilePublic,
    ServicePublic,
    UserPublic,
)


class ProfilesRepository(BaseRepository):
    async def get_profile_by_user_id(self, *, user_id: str) -> Optional[OwnerProfilePublic]:
        record = await self.db.fetch_one(
            query="SELECT id, user_id, full_name, phone_number FROM owner_profiles WHERE user_id = :user_id",
            values={"user_id": user_id},
        )
        return OwnerProfilePublic(**record) if record else None

    async def create_profile_for_user(
        self, *, user_id: str, full_name: Optional[str] = None, phone_number: Optional[str] = None
    ) -> OwnerProfilePublic:
        record = await self.db.fetch_one(
            query="""
                INSERT INTO owner_profiles (id, user_id, full_name, phone_number)
                VALUES (:id, :user_id, :full_name, :phone_number)
                RETURNING id, user_id, full_name, phone_number
            """,
            values={
                "id": str(uuid4()),
                "user_id": user_id,
                "full_name": full_name,
                "phone_number": phone_number,
            },
        )
        return OwnerProfilePublic(**record)


USER_COLUMNS = "id, username, email, role, clinic_id, is_active, is_guest"


class UsersRepository(BaseRepository):
    def __init__(self, db: Database) -> None:
        super().__init__(db)
        # `public_booking` reaches through `users_repo.profiles_repo`; the
        # contract names that attribute, so the reference host provides it.
        self.profiles_repo = ProfilesRepository(db)

    async def _hydrate(self, record, populate: bool = True) -> UserPublic:
        user = UserPublic(**record)
        if populate:
            user.profile = await self.profiles_repo.get_profile_by_user_id(user_id=user.id)
        return user

    async def get_user_by_id(self, *, user_id: str, populate: bool = True) -> Optional[UserPublic]:
        record = await self.db.fetch_one(
            query=f"SELECT {USER_COLUMNS} FROM users WHERE id = :id", values={"id": user_id}
        )
        return await self._hydrate(record, populate) if record else None

    async def get_user_by_username(self, *, username: str, populate: bool = True) -> Optional[UserPublic]:
        record = await self.db.fetch_one(
            query=f"SELECT {USER_COLUMNS} FROM users WHERE username = :username",
            values={"username": username},
        )
        return await self._hydrate(record, populate) if record else None

    async def get_user_by_email(self, *, email: str, populate: bool = True) -> Optional[UserPublic]:
        record = await self.db.fetch_one(
            query=f"SELECT {USER_COLUMNS} FROM users WHERE email = :email", values={"email": email}
        )
        return await self._hydrate(record, populate) if record else None

    async def register_user(
        self,
        *,
        email: str,
        username: str,
        role: str = "client",
        clinic_id: Optional[str] = None,
        is_guest: bool = False,
        full_name: Optional[str] = None,
        phone_number: Optional[str] = None,
    ) -> UserPublic:
        record = await self.db.fetch_one(
            query=f"""
                INSERT INTO users (id, username, email, role, clinic_id, is_guest)
                VALUES (:id, :username, :email, :role, :clinic_id, :is_guest)
                RETURNING {USER_COLUMNS}
            """,
            values={
                "id": str(uuid4()),
                "username": username,
                "email": email,
                "role": role,
                "clinic_id": clinic_id,
                "is_guest": is_guest,
            },
        )
        user = UserPublic(**record)
        # Every user gets a profile, because the appointment permission check
        # resolves the booker's owner_profile_id through it.
        await self.profiles_repo.create_profile_for_user(
            user_id=user.id, full_name=full_name, phone_number=phone_number
        )
        return await self.get_user_by_id(user_id=user.id)

    async def get_or_create_guest_user(
        self, *, email: str, full_name: Optional[str] = None, phone_number: Optional[str] = None
    ) -> UserPublic:
        existing = await self.get_user_by_email(email=email)
        if existing:
            return existing
        return await self.register_user(
            email=email,
            username=f"guest_{uuid4().hex[:12]}",
            is_guest=True,
            full_name=full_name,
            phone_number=phone_number,
        )


PET_COLUMNS = "id, owner_profile_id, name, species"


class PetProfilesRepository(BaseRepository):
    """The SUBJECT repository. Named for pets because the extraction is
    verbatim -- see docs/adapting.md."""

    async def get_pet_by_id(self, *, id: str) -> Optional[PetProfilePublic]:
        record = await self.db.fetch_one(
            query=f"SELECT {PET_COLUMNS} FROM pet_profiles WHERE id = :id", values={"id": id}
        )
        return PetProfilePublic(**record) if record else None

    async def get_pet_by_id_for_clinic(self, *, id: str, clinic_id: str) -> Optional[PetProfilePublic]:
        record = await self.db.fetch_one(
            query=f"""
                SELECT p.id, p.owner_profile_id, p.name, p.species
                FROM pet_profiles p
                INNER JOIN clinic_owner_profiles cop ON cop.owner_profile_id = p.owner_profile_id
                WHERE p.id = :id AND cop.clinic_id = :clinic_id
            """,
            values={"id": id, "clinic_id": clinic_id},
        )
        return PetProfilePublic(**record) if record else None

    async def list_pet_profiles_for_clinic(
        self, *, clinic_id: str, owner_profile_id: str
    ) -> List[PetProfilePublic]:
        records = await self.db.fetch_all(
            query=f"""
                SELECT p.id, p.owner_profile_id, p.name, p.species
                FROM pet_profiles p
                INNER JOIN clinic_owner_profiles cop ON cop.owner_profile_id = p.owner_profile_id
                WHERE cop.clinic_id = :clinic_id AND p.owner_profile_id = :owner_profile_id
                ORDER BY p.name
            """,
            values={"clinic_id": clinic_id, "owner_profile_id": owner_profile_id},
        )
        return [PetProfilePublic(**r) for r in records]

    async def create_pet(self, *, new_pet: PetProfileCreate, owner_profile_id: str) -> PetProfilePublic:
        record = await self.db.fetch_one(
            query=f"""
                INSERT INTO pet_profiles (id, owner_profile_id, name, species)
                VALUES (:id, :owner_profile_id, :name, :species)
                RETURNING {PET_COLUMNS}
            """,
            values={
                "id": str(uuid4()),
                "owner_profile_id": owner_profile_id,
                "name": new_pet.name,
                "species": new_pet.species,
            },
        )
        return PetProfilePublic(**record)


SERVICE_COLUMNS = "id, clinic_id, name, duration_minutes"


class ServicesRepository(BaseRepository):
    async def get_service_by_id(self, *, id: str) -> Optional[ServicePublic]:
        record = await self.db.fetch_one(
            query=f"SELECT {SERVICE_COLUMNS} FROM services WHERE id = :id", values={"id": id}
        )
        return ServicePublic(**record) if record else None

    async def get_service_by_id_for_clinic(self, *, id: str, clinic_id: str) -> Optional[ServicePublic]:
        record = await self.db.fetch_one(
            query=f"SELECT {SERVICE_COLUMNS} FROM services WHERE id = :id AND clinic_id = :clinic_id",
            values={"id": id, "clinic_id": clinic_id},
        )
        return ServicePublic(**record) if record else None

    async def list_services_by_clinic_id(self, *, clinic_id: str) -> List[ServicePublic]:
        records = await self.db.fetch_all(
            query=f"SELECT {SERVICE_COLUMNS} FROM services WHERE clinic_id = :clinic_id ORDER BY name",
            values={"clinic_id": clinic_id},
        )
        return [ServicePublic(**r) for r in records]

    async def create_service(
        self, *, clinic_id: str, name: str, duration_minutes: Optional[int] = 30
    ) -> ServicePublic:
        record = await self.db.fetch_one(
            query=f"""
                INSERT INTO services (id, clinic_id, name, duration_minutes)
                VALUES (:id, :clinic_id, :name, :duration_minutes)
                RETURNING {SERVICE_COLUMNS}
            """,
            values={
                "id": str(uuid4()),
                "clinic_id": clinic_id,
                "name": name,
                "duration_minutes": duration_minutes,
            },
        )
        return ServicePublic(**record)


class ClinicsRepository(BaseRepository):
    async def get_clinic_by_id(self, *, id: str) -> Optional[ClinicPublic]:
        record = await self.db.fetch_one(
            query="SELECT id, name FROM clinics WHERE id = :id", values={"id": id}
        )
        return ClinicPublic(**record) if record else None

    async def create_clinic(self, *, name: str) -> ClinicPublic:
        record = await self.db.fetch_one(
            query="INSERT INTO clinics (id, name) VALUES (:id, :name) RETURNING id, name",
            values={"id": str(uuid4()), "name": name},
        )
        return ClinicPublic(**record)


class ClinicOwnerProfilesRepository(BaseRepository):
    async def get_pivot_for_clinic_and_owner(self, *, clinic_id: str, owner_profile_id: str):
        return await self.db.fetch_one(
            query="""
                SELECT clinic_id, owner_profile_id, status
                FROM clinic_owner_profiles
                WHERE clinic_id = :clinic_id AND owner_profile_id = :owner_profile_id
            """,
            values={"clinic_id": clinic_id, "owner_profile_id": owner_profile_id},
        )

    async def register_owner_profile_with_clinic(
        self, *, clinic_id: str, registration: ClinicOwnerProfileRegistration
    ):
        # Idempotent: the public booking flow calls this on every booking,
        # including repeat visits by the same guest.
        return await self.db.fetch_one(
            query="""
                INSERT INTO clinic_owner_profiles (clinic_id, owner_profile_id)
                VALUES (:clinic_id, :owner_profile_id)
                ON CONFLICT (clinic_id, owner_profile_id) DO UPDATE SET status = 'active'
                RETURNING clinic_id, owner_profile_id, status
            """,
            values={"clinic_id": clinic_id, "owner_profile_id": registration.owner_profile_id},
        )


class ClinicAPIKeysRepository(BaseRepository):
    async def get_active_clinic_by_public_key(self, *, public_key: str) -> Optional[ClinicPublic]:
        record = await self.db.fetch_one(
            query="""
                SELECT c.id, c.name
                FROM clinic_api_keys k
                INNER JOIN clinics c ON c.id = k.clinic_id
                WHERE k.public_key = :public_key AND k.is_active = TRUE
            """,
            values={"public_key": public_key},
        )
        return ClinicPublic(**record) if record else None

    async def create_key_for_clinic(self, *, clinic_id: str, public_key: str) -> str:
        await self.db.execute(
            query="INSERT INTO clinic_api_keys (id, clinic_id, public_key) VALUES (:id, :clinic_id, :public_key)",
            values={"id": str(uuid4()), "clinic_id": clinic_id, "public_key": public_key},
        )
        return public_key
