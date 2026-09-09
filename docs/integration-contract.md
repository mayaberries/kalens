# The integration contract

Everything `appts_core` needs from its host, in one place. If you are wiring
the library into an application, this is the checklist.

The contract is wide — sixteen fields — and that width is honest rather than
accidental. Scheduling reads four things it doesn't own (a user, a service, a
tenant, and the *subject* of the booking), and the public booking flow writes
three of them. A narrower contract would only mean hiding those dependencies
behind an abstraction, not removing them.

`tests/_host/` is a complete, working implementation of everything below, in
about 400 lines. Read it alongside this page.

---

## Prerequisite tables

The library owns `appointments` and `clinic_availability`. Its foreign keys
point at four tables the host must have created first:

| Table | Columns the library needs |
|---|---|
| `users` | `id CHAR(36)` primary key |
| `services` | `id CHAR(36)` primary key, `clinic_id CHAR(36)`, `duration_minutes INT` |
| `pet_profiles` | `id CHAR(36)` primary key — the appointment's *subject* |
| `clinics` | `id CHAR(36)` primary key — the tenant |

There is no softer check than the foreign keys themselves: run the migration
against a database missing any of these and it fails loudly. That is
deliberate.

The host also needs **`ix_services_clinic_id`** on its own `services` table.
The overlap query joins through it on every create and every confirm, and it
is an index on a table this library does not own, so the library documents it
rather than creating it.

Ordering and adoption: [migrations.md](migrations.md).

---

## `AppointmentsIntegration`

### Repositories

Passed as **classes**, not instances. They are constructed per request with
the shared `databases.Database`, the same way `get_repository` does it.

| Field | Required methods |
|---|---|
| `users_repository` | `get_user_by_id(*, user_id)` · `get_user_by_email(*, email, populate)` · `get_or_create_guest_user(*, email, full_name, phone_number)` · an attribute `profiles_repo` exposing `get_profile_by_user_id(*, user_id)` |
| `subject_repository` | `get_pet_by_id(*, id)` · `get_pet_by_id_for_clinic(*, id, clinic_id)` · `create_pet(*, new_pet, owner_profile_id)` · `list_pet_profiles_for_clinic(*, clinic_id, owner_profile_id)` |
| `services_repository` | `get_service_by_id_for_clinic(*, id, clinic_id)` · `list_services_by_clinic_id(*, clinic_id)` |
| `owner_link_repository` | `get_pivot_for_clinic_and_owner(*, clinic_id, owner_profile_id)` · `register_owner_profile_with_clinic(*, clinic_id, registration)` — must be idempotent, it is called on every public booking |

The subject repository's method names are pets-shaped because the extraction
is verbatim. Renaming them is a breaking change to this contract, covered in
[adapting.md](adapting.md).

Objects returned must expose: a user's `.id`, `.is_active`, `.clinic_id` and
`.profile`; a service's `.id`, `.clinic_id`, `.duration_minutes`; a subject's
`.id` and `.owner_profile_id`; a clinic's `.id`.

### Dependencies

FastAPI-callable. They appear in the library's own dependency signatures,
which is why `configure()` has to run before any router is built.

| Field | Contract |
|---|---|
| `get_current_active_user` | returns the authenticated user, or raises 401 |
| `get_service_by_id_from_path` | resolves `{service_id}`, 404 if absent |
| `get_user_by_username_from_path` | resolves `{username}`, 404 if absent — only used by the evaluations shim |
| `get_clinic_by_id_from_path` | resolves `{clinic_id}`, 404 if absent. **Must not require authentication** — `GET` availability is public |
| `check_clinic_modification_permissions` | raises 403 unless the caller may write this clinic |
| `get_clinic_from_public_key` | resolves the `X-Clinic-Key` header to a clinic, 401 otherwise. Every failure mode should return the *same* 401 |

### Predicates

Plain functions, called with keywords.

| Field | Signature |
|---|---|
| `user_can_manage_service` | `(*, user, service) -> bool` — "is this caller staff of the service's tenant" |
| `get_service_clinic_id` | `(service) -> str` — the key double-booking is scoped to |
| `get_owner_profile_id_for_user` | `(*, user) -> str` — who may book for a subject |

### Models

Injected so the emitted OpenAPI schema names real types instead of `Any`.

| Field | What to pass |
|---|---|
| `appointment_public_model` | a subclass of `appts_core.AppointmentPublic` re-narrowing `user`, `pet`, `service` |
| `public_appointment_create_model` | a subclass of `appts_core.PublicAppointmentCreate` re-narrowing `pet` |
| `subject_public_model` | your `PetProfilePublic` — the `/public/pets` response and the hydrated `pet` field |
| `service_public_model` | your `ServicePublic` — the `/public/services` response |
| `owner_link_registration_model` | constructed as `Model(owner_profile_id=...)` and handed to `register_owner_profile_with_clinic` |

```python
class AppointmentPublic(appts_core.AppointmentPublic):
    user: Optional[UserPublic] = None
    pet: Optional[PetProfilePublic] = None
    service: Optional[ServicePublic] = None

class PublicAppointmentCreate(appts_core.PublicAppointmentCreate):
    pet: PublicPetInput
```

`PublicPetInput` must expose `.pet_id` and `.new_pet`, exactly one of which is
set; `.new_pet` is passed straight to `subject_repository.create_pet`.

### `settings`

Optional. Defaults reproduce pets-appts exactly.

| Setting | Default |
|---|---|
| `default_appointment_duration_minutes` | `30` — used when a service has no `duration_minutes` |
| `redis_url` | `None` — in-process rate-limit storage, correct for one worker only |
| `public_rate_limit_per_key` | `120` / minute |
| `public_rate_limit_per_ip` | `600` / minute |
| `clinic_availability_read_rate_limit_per_clinic` | `60` / minute |
| `clinic_availability_write_rate_limit_per_clinic` | `20` / minute |
| `database_state_attr` | `"_db"` — where on `app.state` the pool lives |

---

## What the host keeps

`configure()` does not connect to a database, authenticate anyone, or mount
itself. The host still owns:

- **The connection.** Open a `databases.Database` in your lifespan and put it
  on `app.state`. The library only ever reads it back.
- **Route prefixes.** The library fixes route `name=` values, not paths. What
  pets-appts mounts today:
  `/services/{service_id}/appointments`, `/public`,
  `/clinics/{clinic_id}/availability`.
- **Authentication**, of both kinds — JWT and the publishable key.

---

## If you kept evaluations in the host

Evaluations are not part of this library, but in pets-appts they sit directly
on top of appointments, so a host that keeps them needs five things exported
from here:

```python
from appts_core import AppointmentsRepository, AppointmentInDB, AppointmentStatus

appts = configure(...)
appts.dependencies.get_appointment_by_id_from_path
appts.dependencies.get_appointment_for_service_from_user_by_path
```

Take the two dependencies **off the module handle**, never rebuild them.
FastAPI caches a dependency per request by callable identity, so a
re-derived copy would resolve the same appointment a second time.

Two consequences worth knowing:

1. **Completion still lives in your code.** `create_evaluation_for_appointment`
   calling `appointments_repo.mark_as_completed` is the only thing that moves
   an appointment to `completed`. The library preserves `mark_as_completed`
   but never calls it. A confirmed appointment nobody rates stays `confirmed`
   forever — a known gap in pets-appts, carried across unchanged.
2. **Your evaluations table has a foreign key into a library-owned table**
   (`appointment_id → appointments.id`), which is what makes migration
   ordering three-phase. See [migrations.md](migrations.md).

`get_appointment_for_service_from_user_by_path` is documented in its own
source as a temporary shim that assumes one appointment per (service, user) —
which stopped being true when appointments got a surrogate key. It moved
across because deleting it would break the host, not because it is good.
