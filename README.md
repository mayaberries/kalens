# kalens

A scheduling engine for FastAPI applications. Any business that books time —
a clinic, a practice, a studio, a shop — can mount it instead of building its
own appointments, opening hours and public booking flow.

## Scope

kalens owns **two tables** — `appointments` and `clinic_availability` — and three
API surfaces:

| Surface | Auth | Routes |
|---|---|---|
| Appointments | host's JWT dependency | create · list · get · confirm · cancel · withdraw |
| Public booking | host's `X-Clinic-Key` dependency + built-in rate limiting | list services · list subjects · create appointment |
| Availability | GET unauthenticated, PUT via host's permission check | get · replace weekly hours |

Everything else — users, services, tenants, and the *subject* of a booking (a
pet, a patient, a garment) — stays with the host and arrives through
`AppointmentsIntegration`.

**Not in scope**, by design: authentication, user accounts, tenants and their
services, the subjects being booked, and payments. Those are the host's.

**Not in scope yet**, and worth knowing before you adopt it: notifications or
lifecycle events, an audit log, turning weekly hours plus bookings into open
slots, and double-booking per practitioner or room rather than per tenant.
[docs/adapting.md](docs/adapting.md) ranks them.

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

That is what makes the emitted OpenAPI schema name your real types instead of
`Any`. Full contract in
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

kalens was first bound to a veterinary clinic, and the code is still shaped
like one: the appointment's subject column is literally `pet_id`, and
double-booking is scoped to a clinic. Nothing about that is load-bearing, and
[docs/adapting.md](docs/adapting.md) is the map — what each seam is bound to
today, what changes for health appointments, and what a tailor or a spa would
have to change on top of that.

## Develop

```bash
git clone git@github.com:mayaberries/kalens.git
cd kalens
make install       # .venv with the package editable, plus test extras (Python >= 3.13)
make db-up         # Postgres in its own container, kalens-db, on port 5433
make test          # the suite
make verify        # syntax check + suite
```

`make help` lists every target. To run one test:

```bash
.venv/bin/pytest tests/appointments/test_cancel.py -k client_cancels_a_confirmed -v
```

**The suite drops and recreates its database on every run.** That's why it
has its own container on 5433 rather than the default 5432, where an
application database is likely to be. Point `KALENS_DATABASE_URL` anywhere
else only if you mean it.

`.venv` stores absolute paths, so if you move or rename the checkout, rebuild
it: `rm -rf .venv && make install`.

The suite runs against a **reference host** in `tests/_host/`, a minimal
FastAPI app that implements the contract with throwaway `users` / `services` /
`pet_profiles` / `clinics` tables. That app existing at all is the proof the
library stands on its own.
