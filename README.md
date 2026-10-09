# kalens

The scheduling engine from [`pets-appts`](../pets-appts), extracted verbatim so
more than one application can run it instead of forking it.

It owns **two tables** — `appointments` and `clinic_availability` — and three
API surfaces:

| Surface | Auth | Routes |
|---|---|---|
| Appointments | host's JWT dependency | create · list · get · confirm · cancel · withdraw |
| Public booking | host's `X-Clinic-Key` dependency + built-in rate limiting | list services · list subjects · create appointment |
| Availability | GET unauthenticated, PUT via host's permission check | get · replace weekly hours |

Everything else — users, services, tenants, and the *subject* of a booking (a
pet, a patient, a garment) — stays with the host and arrives through
`AppointmentsIntegration`.

## Install

```bash
pip install "kalens @ git+ssh://git@github.com/mayaberries/kalens.git@v0.1.0-alpha.2"
```

## Wire it up

```python
from kalens import AppointmentsIntegration, Settings, configure

appts = configure(AppointmentsIntegration(
    users_repository=UsersRepository,
    subject_repository=PetProfilesRepository,
    services_repository=ServicesRepository,
    owner_link_repository=ClinicOwnerProfilesRepository,
    get_current_active_user=get_current_active_user,
    get_service_by_id_from_path=get_service_by_id_from_path,
    get_user_by_username_from_path=get_user_by_username_from_path,
    get_clinic_by_id_from_path=get_clinic_by_id_from_path,
    check_clinic_modification_permissions=check_clinic_modification_permissions,
    get_clinic_from_public_key=get_clinic_from_public_key,
    user_can_manage_service=user_can_manage_service,
    get_service_clinic_id=get_service_clinic_id,
    get_owner_profile_id_for_user=get_owner_profile_id_for_user,
    appointment_public_model=AppointmentPublic,
    public_appointment_create_model=PublicAppointmentCreate,
    subject_public_model=PetProfilePublic,
    service_public_model=ServicePublic,
    owner_link_registration_model=ClinicOwnerProfileRegistration,
    settings=Settings(redis_url=REDIS_URL),
))

router.include_router(appts.appointments_router,
                      prefix="/services/{service_id}/appointments", tags=["appointments"])
router.include_router(appts.public_booking_router, prefix="/public", tags=["public-booking"])
router.include_router(appts.availability_router,
                      prefix="/clinics/{clinic_id}/availability", tags=["clinic-availability"])
```

Two host models are subclasses of this library's, re-narrowing the fields the
library can't type:

```python
class AppointmentPublic(kalens.AppointmentPublic):
    user: Optional[UserPublic] = None
    pet: Optional[PetProfilePublic] = None
    service: Optional[ServicePublic] = None

class PublicAppointmentCreate(kalens.PublicAppointmentCreate):
    pet: PublicPetInput
```

That is what keeps the emitted OpenAPI schema identical to the host's own,
pre-extraction one. Full contract in
[docs/integration-contract.md](docs/integration-contract.md).

## Migrate

The library keeps its own Alembic chain in its own version table
(`kalens_alembic_version`), so it upgrades independently of the host's.

```bash
alembic -n kalens upgrade head    # greenfield
alembic -n kalens stamp head      # adopting a database that already has these tables
```

Host tables must exist first — the foreign keys are the enforcement. See
[docs/migrations.md](docs/migrations.md).

## Make it yours

The extraction is verbatim, which means the code is still shaped like a
veterinary clinic: the appointment's subject column is literally `pet_id`, and
double-booking is scoped to a clinic. Nothing about that is load-bearing, and
[docs/adapting.md](docs/adapting.md) is the map — what pets binds each seam to,
what changes for human health appointments, and what a tailor or a spa would
have to change on top of that.

## Test

```bash
make test          # needs Postgres; see the Makefile for the URL it expects
```

The suite runs against a **reference host** in `tests/_host/` — a minimal
FastAPI app that implements the contract with throwaway `users` / `services` /
`pet_profiles` / `clinics` tables. That app existing at all is the proof the
library stands on its own.
