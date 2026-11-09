---
name: create-service
description: Create a service, the layer that holds a domain's use cases, rules and transactions over its repositories, and wire it as a per-request dependency. Use when adding behaviour that spans steps or tables, a business rule, or hydration to a public model, e.g. "add booking with a guest owner", "clinics need a create-with-defaults flow" or "where does this rule go?", in pets-appts (Vetted), Sinapsis, Kalens or Xolo.
---

# Create a service

This file is identical in pets-appts (Vetted), Sinapsis, Kalens and Xolo. If you
change it in one repo, copy the change to the other three. It sits between the
`create-route` skill (above it) and `create-repository` (below it).

A service holds **a domain's use cases**: what a caller wants done, the rules
that decide whether it may happen, the transaction it happens in, and the
public shape of the result. It is the layer the other two skills push work
into:

| A service does | Examples moved here from today's code |
|---|---|
| **Use cases**: one method per thing a caller wants done, named for the action | `register_owner_with_clinic`, `book_public_appointment`, `issue_access_token` |
| **Rules**: invariants and data-dependent permissions, raised as domain errors | "already belongs to a clinic", "only confirmed appointments can be evaluated", "profile already linked" |
| **Transactions** around every use case that writes more than once | user + profile; clinic + default availability + admin attach; evaluation + mark completed |
| **Composition**: building `*Public` from rows, in batches | the old `populate_*` methods |
| **Decisions that aren't storage**: keys, hashes, tokens, slugs, "now" | `pk_live_…` minting, password hashing, claim tokens, slugify |

It does **not** read the request, know about HTTP status codes, write SQL, or
reach into another domain's repository.

## 0. Before you start

- **Is it a service or a helper?** Vetted's `AuthService` is stateless
  crypto (bcrypt, JWTs) with no repositories. That's a **helper**: plain
  functions or a small class in a `security`/`keys`-style module that services
  call. Keep the word *service* for the per-request class over repositories
  described here. Don't add repositories to a helper, and don't make a
  service a module-level singleton.
- **One service per domain, not per table.** A domain is a bounded context
  (Sinapsis' `modules/<domain>/`), which can cover several tables or a slice
  of one. The pivot table `clinic_owner_profiles` belongs to the owners
  domain; it doesn't get a service of its own.
- **Existing code is not in scope.** Moving `UsersRepository`'s workflows or
  kalens' public-booking route into a service is its own change. In Xolo's
  Extraction stage, code moves verbatim.
- **Kalens' host contract** (`AppointmentsIntegration`) hands kalens host
  *repository classes*, and kalens calls workflow methods on them
  (`get_or_create_guest_user`, `register_owner_profile_with_clinic`). By these
  rules those are service methods, so a kalens service will eventually take
  host services (or narrow callables) through the contract instead. That's a
  breaking change and a story in `docs/adapting.md`. Until it lands, a kalens
  service calls the contract's repositories as they are; don't change the
  contract in passing.

## 1. Shape it

```python
class BookingService:
    """Booking use cases. Owns appointments; uses owners, pets and services
    through their services, never their repositories."""

    def __init__(
        self,
        *,
        db: Database,
        appointments_repo: AppointmentsRepository,
        owners_service: OwnersService,
        pets_service: PetsService,
        services_service: ServicesService,
    ) -> None:
        self.db = db
        self.appointments_repo = appointments_repo
        self.owners_service = owners_service
        self.pets_service = pets_service
        self.services_service = services_service
```

- **Everything is injected, keyword-only**: the `Database` (for
  transactions), this domain's repositories, and other domains' services.
  Nothing is built inside `__init__`.
- **Its own repositories, other domains' services.** A service never imports
  another domain's repository. Sinapsis already enforces this with
  `lint-imports` (modules use each other only through their package
  `__init__`); elsewhere it's the rule. Today kalens' public booking reads
  `users_repo.profiles_repo`, another repository's internal attribute: that's
  what this prevents.
- **No cycles.** If two services need each other, the shared part is a third,
  smaller one, or one of them is calling something it should be told.

## 2. Write the use cases

Kalens' public-booking route as a service would write it. The method and model
names are illustrative, not today's code:

```python
    async def book_public_appointment(
        self, *, clinic_id: str, booking: PublicAppointmentCreate
    ) -> AppointmentPublic:
        service = await self.services_service.get_bookable_service(id=booking.service_id, clinic_id=clinic_id)
        end_time = booking.start_time + timedelta(minutes=service.duration_minutes or DEFAULT_DURATION)

        async with self.db.transaction():
            # Serialises bookings per clinic: the overlap check and the insert
            # must not interleave with another request's (see "Races" below).
            await self.appointments_repo.lock_clinic_schedule(clinic_id=clinic_id)
            if await self.appointments_repo.has_overlapping_confirmed_appointment(
                clinic_id=clinic_id, start_time=booking.start_time, end_time=end_time
            ):
                raise SlotTakenError("That time is no longer available. Please choose another slot.")

            owner = await self.owners_service.get_or_create_guest_owner_at_clinic(
                clinic_id=clinic_id, email=booking.email, full_name=booking.full_name,
                phone_number=booking.phone_number,
            )
            pet = await self.pets_service.resolve_pet_for_booking(
                owner_profile_id=owner.profile_id, clinic_id=clinic_id, pet=booking.pet
            )
            appointment = await self.appointments_repo.create_appointment(
                new_appointment=AppointmentCreate(
                    user_id=owner.user_id, pet_id=pet.id, service_id=service.id,
                    start_time=booking.start_time, end_time=end_time,
                ),
            )

        return (await self.to_public([appointment]))[0]
```

- **Arguments are plain IDs and input models**, keyword-only. When a rule
  depends on who is acting ("attach the admin who created the clinic",
  "staff of this clinic only"), take it explicitly as `actor: UserInDB`. A
  service never reads the request, the token or "the current user" itself,
  so the same method runs from a route, the CLI, a script or a test.
- **Rules raise named domain errors** (`SlotTakenError(ConflictError)`,
  `ProfileAlreadyLinkedError(ConflictError)`, `XNotFoundError(NotFoundError)`).
  Never `HTTPException`. Hiding another tenant's row is a rule too: raise
  the same `NotFoundError` for "missing" and "not yours" so a caller can't
  learn an ID exists elsewhere.
- **Permissions:** a check that needs only the request (logged in, role,
  "staff of the clinic in the path") is a guard dependency (`create-route`).
  A check that needs data the service loads lives here and raises
  `PermissionDeniedError`. Each rule lives in **one** place; never also in a
  repository. The predicate itself is a plain keyword-called function
  (`user_can_manage_service(user=, service=)`) so guards and kalens can share it.
- **Validation that's about shape** (non-blank name, start time in the future)
  belongs in the input model. Validation that needs the database or other
  rows belongs here.

## 3. Transactions

- **Every method that writes more than once opens `async with
  self.db.transaction():`.** Without it a failure halfway leaves the first
  rows written (Vetted's `register_new_user` can leave a user with no
  profile). `databases` binds the transaction to the running task, so
  repository and service calls inside it take part without being passed
  anything.
- **Nesting is fine.** When `book_public_appointment` calls
  `owners_service.get_or_create_guest_owner_at_clinic`, which opens its own
  transaction, `databases` makes the inner one a savepoint. Write each
  method so it's correct on its own; don't skip a transaction because "the
  caller has one".
- **Keep transactions short**: load and check what you can before opening
  one, and never await anything outside the database inside it (HTTP calls,
  Redis, sleeps).
- **Side effects outside the database run after the outermost commit.**
  Emails, notifications, cache invalidation, rate-limit charges: collect what
  to do inside, do it after the `async with` exits. Minting a token is fine
  inside; sending it isn't.
- **Races: a transaction is not a lock.** At PostgreSQL's default isolation
  (`READ COMMITTED`), two requests can both pass an "is it free?" check and
  both insert. Prefer, in order:
  1. a **constraint** that makes the bad state impossible (unique index,
     `EXCLUDE USING gist` for time ranges), translated to a domain error by
     the repository;
  2. a **lock** taken at the start of the transaction, exposed as a
     repository method (`lock_clinic_schedule` →
     `SELECT pg_advisory_xact_lock(hashtext(:clinic_id))`, or `SELECT … FOR
     UPDATE` on the parent row);
  3. never a check-then-insert alone. Kalens' public booking and Vetted's
     `bootstrap_first_superuser` both started that way.

## 4. Return types and composition

- **Use cases return `*Public`**, the shape the route sends.
- **Lookups used by loaders and other services return `*InDB`**
  (`get_invoice_for_clinic`, `get_bookable_service`) and raise `NotFoundError`
  rather than returning `None`. A loader dependency calls these, and routes
  that already hold an entity call `to_public`.
- **`to_public(rows: list[XInDB]) -> list[XPublic]`** is where the old
  `populate_*` went. Batch-load related rows by ID (`list_*_by_ids` on the
  repository, or the other domain's service), index them by ID, assemble.
  One query per relation, not one per row. If a field is missing from a
  response, the bug is here.
- **Return types say exactly what's returned.** No `populate=` flags, no
  `Union[XInDB, XPublic]`.

## 5. Helpers, settings, time

- Crypto, token and key generation are **helpers** the service calls
  (Vetted's `auth_service` today; Xolo after the extraction). Inject one only
  if a test needs to swap it; otherwise import the function.
- Settings come from the repo's settings object (Sinapsis: `get_settings()`;
  kalens/xolo: `get_settings()` from the integration), read where they're
  used, not frozen into defaults at import time.
- "Now" is a decision: take it from one place in the method
  (`now = datetime.now(timezone.utc)`) and pass it down, so a use case
  doesn't see two different times.

## 6. Wire it

Next to the domain's other dependencies:

```python
def get_booking_service(
    db: DatabaseDep,
    appointments_repo: Annotated[AppointmentsRepository, Depends(get_repository(AppointmentsRepository))],
    owners_service: OwnersServiceDep,
    pets_service: PetsServiceDep,
    services_service: ServicesServiceDep,
) -> BookingService:
    return BookingService(
        db=db, appointments_repo=appointments_repo, owners_service=owners_service,
        pets_service=pets_service, services_service=services_service,
    )


BookingServiceDep = Annotated[BookingService, Depends(get_booking_service)]
```

- **Built per request** by a `get_x_service` dependency, exposed as an
  `XServiceDep` alias (Sinapsis' `get_health_service` / `HealthServiceDep`).
  FastAPI caches dependencies per request, so a request that needs
  `OwnersService` twice, directly and through `BookingService`, gets one.
- **Every route calls exactly one service method**, even when the service is
  a thin pass-through (pets). That keeps hydration in one place, keeps the
  layer order (routes → dependencies → service → repository) true, and
  removes the "does this route talk to a repository?" question.
- **Outside FastAPI** (CLI, scripts, tests), build the service by hand with the
  same keyword arguments. If that's painful, the service has too many
  collaborators.
- **In kalens and xolo**, `get_x_service` is built by the same factories as
  the other dependencies when a host callable is in its signature, and hosts
  take it off the configured module, never rebuild it.

## 7. Test it

Services are where the behaviour is, so this is where most tests go. Use the
real test database; don't mock repositories.

- each use case's happy path, and the `*Public` it returns;
- **one test per rule**: each domain error, raised in the case that should
  raise it, with nothing written;
- **atomicity**: force a later step to fail (a constraint, or a collaborator
  that raises) and assert the earlier rows aren't there;
- **races** where there's a lock or constraint: two concurrent calls
  (`asyncio.gather`), exactly one succeeds;
- tenant masking: another tenant's ID gives the same `NotFoundError` as a
  missing one.

Route tests (`create-route`) then only check the HTTP mapping. Follow the
repo's test-ID convention where it has one (Sinapsis, Xolo: `XXX-NNN`). Vetted's
backend test DB isn't reset between tests (`docs/testing.md`).

## 8. Checklist

- [ ] Per-request class over repositories; a stateless helper isn't one.
- [ ] One per domain; collaborators injected keyword-only; nothing built inside.
- [ ] Own repositories only; other domains through their services; no cycles.
- [ ] Plain IDs, input models and an explicit `actor` where a rule needs one; no request, no current user.
- [ ] Rules raise named domain errors; each permission rule lives in one place.
- [ ] Every multi-write method is one transaction; outside-DB side effects after commit.
- [ ] No check-then-insert without a constraint or a lock.
- [ ] Use cases return `*Public`; lookups return `*InDB` or raise `NotFoundError`; `to_public` batches.
- [ ] `get_x_service` + `XServiceDep`; routes call exactly one method.
- [ ] Tests: each rule, atomicity, races, tenant masking, against the real DB.

## Where things go in each repo

| | Service | Wired in | Helpers |
|---|---|---|---|
| **pets-appts (Vetted)** | `backend/app/services/<domain>.py` | `backend/app/api/dependencies/<domain>.py` | `backend/app/services/authentication.py` today (moving to Xolo) |
| **Sinapsis** | `backend/app/modules/<domain>/service.py` | `modules/<domain>/dependencies.py` | `backend/app/shared/` if domain-agnostic, else the module |
| **Kalens** | `src/kalens/services/<domain>.py` *(no services layer yet)* | the dependency factories in `src/kalens/api/dependencies/` | the module that needs it |
| **Xolo** | `src/xolo/services/<domain>.py` | as Kalens | `src/xolo/security.py`-style modules for hashing and tokens |
