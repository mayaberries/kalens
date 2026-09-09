"""
The reference host's own models.

Two of these are subclasses of the library's, which is the pattern every real
host follows: `appts_core` types the hydrated fields loosely because it can't
know what a subject or a user looks like, and the host narrows them back so
the emitted OpenAPI schema names real models.
"""
from typing import Optional

from pydantic import BaseModel, EmailStr, model_validator

import appts_core


class ClinicPublic(BaseModel):
    id: str
    name: str


class UserPublic(BaseModel):
    id: str
    username: str
    email: str
    role: str = "client"
    clinic_id: Optional[str] = None
    is_active: bool = True
    is_guest: bool = False
    # Populated by UsersRepository.get_user_by_id; the appointment permission
    # checks reach through it for `owner_profile_id`.
    profile: Optional["OwnerProfilePublic"] = None


class OwnerProfilePublic(BaseModel):
    id: str
    user_id: str
    full_name: Optional[str] = None
    phone_number: Optional[str] = None


class PetProfilePublic(BaseModel):
    id: str
    owner_profile_id: str
    name: str
    species: Optional[str] = None


class PetProfileCreate(BaseModel):
    name: str
    species: Optional[str] = None


class PublicPetInput(BaseModel):
    """`pet_id` XOR `new_pet` -- book for an existing subject, or create one
    inline as part of booking. Mirrors the host model this came from."""
    pet_id: Optional[str] = None
    new_pet: Optional[PetProfileCreate] = None

    @model_validator(mode="after")
    def exactly_one_pet_source(self) -> "PublicPetInput":
        if (self.pet_id is None) == (self.new_pet is None):
            raise ValueError("provide exactly one of pet_id or new_pet")
        return self


class ServicePublic(BaseModel):
    id: str
    clinic_id: str
    name: str
    duration_minutes: Optional[int] = None


class ClinicOwnerProfileRegistration(BaseModel):
    owner_profile_id: str


class AppointmentPublic(appts_core.AppointmentPublic):
    """Re-narrows the three fields appts_core leaves as `Any`. This is what
    the routes declare as their response_model."""
    user: Optional[UserPublic] = None
    pet: Optional[PetProfilePublic] = None
    service: Optional[ServicePublic] = None


class PublicAppointmentCreate(appts_core.PublicAppointmentCreate):
    pet: PublicPetInput


class GuestUserCreate(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    phone_number: Optional[str] = None


UserPublic.model_rebuild()
