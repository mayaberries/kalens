---
name: library-contract
description: Change the seam between a library (Kalens, Xolo) and its host (pets-appts/Vetted, Sinapsis) — add or change an integration field on the library side, or adopt a library or a new contract version on the host side. Use when a library needs something it doesn't own ("kalens needs the clinic's timezone"), when a host wires a library in ("set up xolo in sinapsis"), when bumping a library pin, or when one library must use another's pieces.
---

# Change a library contract

This file is identical in pets-appts (Vetted), Sinapsis, Kalens and Xolo. If you
change it in one repo, copy the change to the other three. It covers both sides
of one seam:

- **Library side** (Kalens, Xolo): steps 1–6, adding or changing what the
  library asks of its host.
- **Host side** (Vetted, Sinapsis): steps 7–10, wiring a library in, or moving
  to a new contract version.

The shape is Kalens' (`src/kalens/integration.py`, `docs/integration-contract.md`,
`tests/_host/`), and Xolo adopted it on purpose (`docs/DECISIONS.md`: "Host
contract in the Kalens shape"). Read those three Kalens files before changing
either library.

## The model, in one picture

```
host                                           library
app/integrations/<lib>.py (Vetted: api/scheduling.py)
  mod = <lib>.configure(<Lib>Integration(...))  → installs a frozen dataclass
                                                  repos/models: get_integration() at CALL time
                                                  deps/routers: build_*() at configure() time
                                               ← <Lib>Module(dependencies, routers)
routes: include_router(mod.x_router, prefix=…)   names fixed by the library, paths by the host
lifespan: Database on app.state                  library reads it, never opens one
alembic: host chain + `alembic -n <lib>`         library owns its chain and version table
```

What never changes: **the host owns the connection, the URL prefixes and
authentication; the library owns its tables, its route names and its rules.**
A library never imports its host, and **libraries never import each other**.

## 0. Before you start

- **Existing fields are not in scope.** Kalens' 19 fields (4 repositories, 6
  dependencies, 3 predicates, 5 models, `settings`) and Xolo's verbatim
  extraction stay as they are. Replacing the repository fields with services
  (step 2) is a planned breaking change in Kalens' `docs/adapting.md`, done
  once, not field by field.
- **Is it really the host's?** A library asks for something only when it reads
  data it doesn't own or needs a decision only the host can make. If the
  library owns the table or the rule, it belongs in the library (and if it's a
  domain-specific assumption, `adapting.md` says whether it's vocabulary or a
  real assumption).
- **Does it change a published surface?** A new field, a renamed route
  `name=`, a changed library model or table is a contract change: step 5.

## 1. Pick the field's kind (library side)

| Kind | Use for | Resolved | Example |
|---|---|---|---|
| **Service** (new) | a use case the host owns that the library triggers | lazily, `get_integration()` | `get_or_create_guest_owner` |
| **Repository** (existing fields only) | reading host rows | lazily, constructed `Repo(db)` per call | `services_repository` |
| **Dependency** | FastAPI-callable: resolving the actor or a path entity, guards | at `configure()`, into factory-built signatures | `get_current_active_user` |
| **Predicate** | a keyword-called rule the library must ask the host | lazily | `user_can_manage_service(*, user, service)` |
| **Model** | a host type the library returns or accepts, so the schema names it | lazily, as `response_model`/body type in factories | `appointment_public_model` |
| **Setting** | a tunable with a sane default | lazily, `get_settings()` | `default_appointment_duration_minutes` |

- **Prefer the narrowest kind.** A predicate over a dependency, a
  dependency over a service, a service over a repository. Each step down
  hands the library less of the host.
- **New fields ask for services or narrow callables, never repository
  classes.** Today's contract calls workflows on host repositories
  (`get_or_create_guest_user`, `register_owner_profile_with_clinic`) and reads
  `users_repo.profiles_repo`, another repository's internals. By
  `create-service`, those are host services. A new seam names the use case
  the library needs, not the table it would read.
- **Settings** are a frozen dataclass of only what the library reads, each
  with a default suited to one small deployment and a comment saying what it
  controls. The host maps its own environment onto them; the library never
  reads env vars or the host's config.

## 2. Type it

Each host-supplied collaborator is a `typing.Protocol` in the library, next to
the integration:

```python
@runtime_checkable
class GuestOwnersPort(Protocol):
    """What the library needs to book for someone without an account.
    Implemented by the host's owners service."""

    async def get_or_create_guest_owner(
        self, *, clinic_id: str, email: str, full_name: str | None, phone_number: str | None
    ) -> "GuestOwner": ...


class GuestOwner(Protocol):
    user_id: str
    owner_profile_id: str
```

- **Keyword-only signatures**, exactly as the library calls them, with the
  attributes it reads off returned objects (today's doc lists these in prose:
  "a user's `.id`, `.is_active`, `.clinic_id`…").
- **The integration field is typed with the Protocol** (`guest_owners:
  Callable[[Database], GuestOwnersPort]` for a per-request factory, or the
  Protocol itself for a stateless object). Callables are typed
  `Callable[..., ReturnType]`, not bare `Callable`.
- **The doc points at the Protocols** instead of restating signatures. The
  contract doc's "sixteen fields" against the dataclass's 19 is what
  hand-maintained duplication turns into.

## 3. Validate at `configure()`

`configure()` checks every field before installing anything, and raises one
`ContractError` (a plain `Exception`, not a `DomainError`) listing **all** the
problems, naming the field and what's missing:

- each Protocol-typed field conforms: `issubclass(field, Port)` for a class
  the library constructs per request (today's repository fields),
  `isinstance(field, Port)` for an object. `runtime_checkable` checks that
  the methods and attributes exist, not their signatures; mypy checks those
  in hosts that run it;
- a factory field (`Callable[[Database], Port]`) can only be checked for being
  callable, because its product doesn't exist until a request. The reference
  host's suite is what proves its shape, so don't rely on validation alone;
- each model field is a subclass of the library model it must narrow;
- each callable is callable.

A misconfigured host must fail at startup, not on the first request that hits
the wrong method. Add a test for it (step 6).

## 4. Errors

- The library has its own `DomainError` base (`<lib>/errors.py`), separate
  from the host's, with the same subclasses (`NotFoundError`,
  `PermissionDeniedError`, `ConflictError`, `NotAuthenticatedError`) and the
  same `detail`/`headers` shape (`create-repository` step 3,
  `create-dependency` step 1).
- It exports `register_error_handlers(app)` from its package. **Calling it is a
  host step in the contract** (step 8), listed in the contract doc.
- The contract describes failures as errors, not status codes: "raises
  `NotFoundError` if absent", not "404 if absent". A host dependency in the
  contract may raise the *host's* domain errors; the host's handler covers
  them.
- No `HTTPException` in new library code (existing code moves verbatim in
  Xolo's Extraction stage and is left alone in Kalens).

## 5. Make the change (library side)

One PR, all of these together:

- [ ] the field on the integration dataclass, typed (step 2), with a comment
      grouping it under its kind;
- [ ] resolution: lazy through `get_integration()` for repositories, services,
      predicates, models and settings; a factory parameter for anything that
      appears in a dependency or route signature;
- [ ] `configure()` validation (step 3);
- [ ] `docs/integration-contract.md`: the field, its kind, what the host must
      supply, and any prerequisite table, column or index the host owns
      (e.g. `ix_services_clinic_id`), stated rather than created;
- [ ] **`tests/_host/`**: the reference host implements the new field. Its
      suite passing is the proof that the contract is implementable;
- [ ] **`CHANGELOG.md`**, under the next version, in a **Contract** section:
      what a host must add or change, with a before/after snippet;
- [ ] the version: `__version__` matches the tag (`0.2.0-alpha.1`, not `0.1.0`
      under a `v0.1.0-alpha.3` tag).

**What counts as breaking**: adding a required field, changing a field's type
or signature, renaming or removing a route `name=` or an exported symbol,
changing a library model's fields, or changing a library-owned table. While on
`0.x`, breaking means a **minor** bump (`0.1 → 0.2`); additive changes with a
default are a patch. Breaking changes in Kalens are planned in `adapting.md`
first.

**If the field creates a foreign key across migration chains** (a library
table pointing at a host table, or the host pointing into a library table, as
evaluations → `appointments` and Xolo's `users` ↔ the host's `clinics` /
`owner_profiles` do), say so in the contract doc and the changelog: it
changes the upgrade order. Alembic can't express dependencies between two
chains, so the order is a documented phase sequence (Kalens'
`docs/migrations.md` "Three phases"), not something the tooling enforces.

## 6. Test it (library side)

Against the reference host:

- the behaviour the field enables, end to end through the library's routes;
- **a misconfigured integration fails at `configure()`**, naming the field
  (missing method, wrong model base, non-callable);
- `reset()` between differently-wired hosts in one process, if the test
  builds more than one (the integration is module-global; `configure()` must
  also clear anything cached from the previous one, as it does for the rate
  limiter's limits);
- the equivalence checks still pass where they apply (`make compare-schema`,
  `make compare-openapi` against a host checkout; both pending kalens#9, see
  `create-migration` step 9 for the interim manual check).

## 7. Wire it (host side)

**One wiring module per library**: `app/integrations/<lib>.py` (Sinapsis:
`backend/app/integrations/<lib>.py`; Vetted keeps `app/api/scheduling.py` for
Kalens). It:

- calls `configure()` once, at import, and exposes the module handle
  (`appts`, `auth`);
- passes the host's repositories, services, dependencies, predicates and
  narrowed models, and `Settings` built from the host's own config;
- **defines the narrowing subclasses** of the library's models
  (`class AppointmentPublic(kalens.AppointmentPublic): user: UserPublic | None …`)
  and is where the rest of the app imports them from, tests included;
- **imports no route module.** Route packages import it to mount its
  routers, so the reverse import is a cycle.

Everywhere else:

- **Take dependencies off the module handle, never rebuild them**
  (`get_appointment_by_id_from_path = appts.dependencies.get_appointment_by_id_from_path`).
  FastAPI caches per request by callable identity; a rebuilt copy loads the
  entity twice.
- **Mount the library's routers** in the route package `__init__` at the
  host's prefix, with a comment pointing at the wiring module.
- **The library's internals are imported only in the wiring module.** The
  rest of the app uses the handle and the re-exported models.

## 8. Adopt it (host side)

- [ ] **Pin by exact tag** (`git+…@v0.2.0-alpha.1`) in the host's dependency
      file, then let the tool resolve the lockfile (Vetted: `make update-deps`;
      Sinapsis: `uv lock`). Never hand-edit a lockfile.
- [ ] **Pins agree across every library the host uses.** Kalens and Xolo pin
      their framework versions exactly, and the host must match all of them.
      If two libraries disagree, that's fixed in a library release, not by
      overriding in the host.
- [ ] **Register the library's error handlers**: `<lib>.register_error_handlers(app)`
      in app setup, next to the host's own.
- [ ] **Migrations**: the library's chain is wired as `[<lib>]` in
      `alembic.ini` with its own version table.
      - *Greenfield:* upgrade in the documented phase order.
      - *Adopting a database that already has the tables* (Vetted with
        Kalens, Vetted with Xolo): **stamp**, never upgrade, after checking
        with `compare-schema` that the tables match the library's revision
        (pending kalens#9; until then the manual `pg_dump` diff in
        `create-migration` step 9).
        From then on, mirror each library revision in the host's chain and
        re-stamp (Vetted's `docs/architecture.md`, "Migrations").
- [ ] **Run the equivalence checks** when the library was extracted from this
      host: `docs/openapi.json` unchanged except for intended changes, schema
      unchanged.
- [ ] **Read the changelog's Contract section** for every version between the
      old pin and the new one, and make each listed host change.

## 9. Two libraries in one host

Xolo will provide four of Kalens' fields (`users_repository`,
`get_current_active_user`, `get_user_by_username_from_path`,
`get_clinic_from_public_key`). The host connects them; neither library knows
the other exists:

```python
# app/integrations/auth.py
auth = xolo.configure(XoloIntegration(...))

# app/integrations/scheduling.py
from app.integrations.auth import auth

appts = kalens.configure(AppointmentsIntegration(
    get_current_active_user=auth.dependencies.get_current_active_user,
    get_clinic_from_public_key=auth.dependencies.get_clinic_from_public_key,
    ...
))
```

- **Configure in dependency order** (the provider first), and import the
  provider's handle, never rebuild its dependencies.
- **The wiring modules may import each other in that one direction only.**
- **Pins**: the check that a library's install leaves the host's pins untouched
  (Xolo's `check-pins`) has to hold for every library pair the host uses.

## 10. Test it (host side)

- the host's existing tests for the routes the library serves pass unchanged
  (that's what proves the adoption);
- the host imports its narrowed models from the wiring module in tests, so a
  comparison against a response uses the class the route declares;
- a sanity test that the library is pinned to the expected tag in the
  lockfile and its wiring imports (Sinapsis' `tests/test_kalens.py`, PLT-004).

## Checklist

**Library side**
- [ ] The narrowest kind; new seams ask for services or callables, not repository classes.
- [ ] Typed with a Protocol; the doc points at it.
- [ ] `configure()` validates and fails at startup, naming every problem.
- [ ] Errors are the library's own `DomainError`s; `register_error_handlers` exported.
- [ ] Contract doc, reference host, changelog (Contract section) and version updated together.
- [ ] Breaking or not, decided by the list in step 5; cross-chain FKs called out.

**Host side**
- [ ] One wiring module; configures once; imports no routes; re-exports narrowed models.
- [ ] Dependencies taken off the handle; routers mounted at the host's prefixes.
- [ ] Exact tag pin, lockfile regenerated, pins agree across libraries.
- [ ] Library error handlers registered.
- [ ] Migrations stamped or upgraded per the library's docs; equivalence checks run.
- [ ] Libraries connected only through the host.

## Where things are in each repo

| | Contract | Contract doc | Reference host / wiring | Changelog |
|---|---|---|---|---|
| **Kalens** | `src/kalens/integration.py` (+ Protocols, `configure()` in `__init__.py`) | `docs/integration-contract.md`, `docs/adapting.md`, `docs/migrations.md` | `tests/_host/` | `CHANGELOG.md` *(not created yet)* |
| **Xolo** | `src/xolo/integration.py` *(planned: `XoloIntegration`)* | `docs/extraction-map.md` until an integration-contract doc exists | `tests/_host/` *(planned)* | `CHANGELOG.md` *(not created yet)* |
| **pets-appts (Vetted)** | — | `docs/architecture.md` ("Scheduling lives in kalens", "Migrations") | `backend/app/api/scheduling.py` | — |
| **Sinapsis** | — | `docs/DECISIONS.md` | `backend/app/integrations/<lib>.py` *(planned; story 5 wires Kalens)* | — |
