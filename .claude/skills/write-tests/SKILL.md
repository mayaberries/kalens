---
name: write-tests
description: Write backend tests (pytest) for models, repositories, services, dependencies, routes, migrations or a library contract, with the right isolation, fixtures, auth and test IDs. Use when adding or changing tests, or when another skill's "Test it" step applies, in pets-appts (Vetted), Sinapsis, Kalens or Xolo. Frontend suites (Vitest, Playwright) are covered by each repo's own testing doc.
---

# Write tests

This file is identical in pets-appts (Vetted), Sinapsis, Kalens and Xolo. If you
change it in one repo, copy the change to the other three. Every other skill's
"Test it" step assumes what this one sets up.

The rule underneath all of it: **tests run against the real app and a real
PostgreSQL, and each test sees only its own data.** No mocked repositories, no
shared rows between tests, no live server.

## 0. Before you start

- **Read the repo's testing doc first** (Vetted: `docs/testing.md`; Sinapsis:
  `CLAUDE.md` "Commands" and `backend/tests/conftest.py`'s docstring; Kalens:
  `CLAUDE.md`; Xolo: `docs/WORKFLOW.md`). It says how to start the database
  and which suites exist.
- **Existing suites are not rewritten in passing.** Vetted's named-singleton
  fixtures, `create_authorized_client`, `Test*` classes and kalens' random
  time windows stay until a change is about them. New tests follow this skill,
  next to old ones if need be.
- **Does this test belong here?** In a host, a test of behaviour a library owns
  belongs in the library (Vetted's `docs/testing.md`, "Tests that go through
  kalens' routes"). A host keeps only contract tests and its own code reached
  through the library's routes.

## 1. Which test, for which layer

| Layer | Test | Database | Entry point |
|---|---|---|---|
| **Model** | each constraint and validator at its edges; cross-field rules; unknown fields rejected; `*Public` doesn't carry internal fields | none | construct the model |
| **Repository** | each method's happy path; `None` for missing *and* out-of-scope ids; each constraint translated to its domain error | rolled back | the repository, on `db` |
| **Service** | each rule raises its domain error with nothing written; atomicity; tenant masking; races (step 4) | rolled back; **committing** for races | the service, built by hand |
| **Dependency** | resolvers: every failure is the same 401; gates and guards: each excluded actor 403s; loaders: missing and other-tenant are the same 404 | rolled back | a route that uses it |
| **Route** | the HTTP mapping only: success status and body shape, one test per declared error response, 422 for non-trivial validation | rolled back | the ASGI client, URL from `app.url_path_for(...)` |
| **Migration** | upgrade → downgrade base → upgrade; asserted preconditions raise | a scratch database | Alembic |
| **Library contract** | the library against its reference host (`tests/_host/`); a misconfigured integration fails at `configure()` | rolled back | the reference host's app |
| **Host contract** | the host's real implementations satisfy what the library calls | rolled back | the library's routes, mounted by the host |

- **Rules are tested once, at the layer that owns them.** A service rule gets
  service tests; the route test checks only that the error becomes the right
  status. Don't re-test every rule through HTTP.
- **No mocks of our own code.** `override_dependency` (Sinapsis) is for
  simulating *infrastructure* that can't fail on demand: Redis down, PostgreSQL
  unreachable, a clock. Not for replacing a repository or a service.

## 2. Isolation: every test rolls back

- **The test `Database` uses `force_rollback=True`.** `databases` then routes
  every query in the test through one connection inside one transaction, and
  rolls it back when the lifespan exits. Each test enters the lifespan once
  (`initialized_app`), so each test starts clean. Sinapsis
  (`create_database`) and Vetted (`connect_to_db`) do this; Kalens' reference
  host doesn't yet (kalens#12).
- **Inside a test, a service's `db.transaction()` becomes a savepoint**, so
  "a failing step rolls back the earlier ones" is testable here: force the
  later step to fail, then assert the earlier rows aren't there.
- **Migrations are session-scoped**; nothing else is. A fixture with
  `scope="session"` or `"module"` that writes rows is a leak.
- **Don't assert on global counts** ("there are 3 clinics") unless the test
  created all of them; assert on the rows it created, by id.
- Vetted's test DB is rolled back after each test (`force_rollback`, confirmed
  in its `docs/testing.md`). New tests still use unique values (step 3): it
  keeps them independent of order and ready for `committing_db`, which doesn't
  roll back.

## 3. Fixtures: factories, not singletons

```python
async def make_clinic(db: Database, **overrides: Any) -> ClinicInDB:
    suffix = uuid4().hex[:8]
    values = {"name": f"Clinic {suffix}", "slug": f"clinic-{suffix}", **overrides}
    return await ClinicsRepository(db).create_clinic(new_clinic=ClinicCreate(**values))


async def make_user(db: Database, *, role: UserRole = UserRole.client, **overrides: Any) -> UserInDB:
    suffix = uuid4().hex[:8]
    values = {"email": f"user-{suffix}@example.test", "username": f"user_{suffix}", "password": "correct-horse", **overrides}
    ...
```

- **Factories are plain async functions** in `tests/_fixtures/` (or
  `_helpers/`), taking `db` and keyword overrides, returning the `*InDB`.
  Tests call them for exactly the data they need, so the setup is visible in
  the test.
- **Unique by default.** Every unique column gets a random suffix, so no test
  depends on another's rows and rollback isn't load-bearing for correctness.
  Times are explicit in the test (`start_time=NOW + timedelta(days=1)`) rather
  than randomly spread to dodge collisions (kalens' `unique_future_time()` is
  that workaround).
- **No get-or-create.** A factory always creates. Vetted's
  `user_fixture_helper` returns an existing user by email, which is how data
  leaks between tests become invisible.
- **Build from the lowest layer that makes valid data**: repositories, and the
  services' own use cases only when the data can't be made otherwise.
  Fixtures that call the workflows under test (Vetted's helpers calling
  `create_clinic_for_admin`) break when the workflow changes, for reasons
  unrelated to the test.
- **pytest fixtures are for infrastructure and shared actors**: `app`,
  `initialized_app`, `db`, `client`, `committing_db`, and a small number of
  composed actors (`clinic_admin`, returning the user and their clinic) built
  from factories. Not one fixture per row.
- **A long fixture file is a finding** (kalens' `entities.py` says so): the
  entity graph is in the domain. Factories that build their own parents
  (`make_service(db)` makes a clinic if none is given) keep tests short.

## 4. Races need real connections

With `force_rollback`, every query in a test shares **one** connection, and
`databases` serialises queries on it. Two "concurrent" requests then never
overlap at the database, so `asyncio.gather` proves nothing about a lock or
an exclusion constraint.

Race tests use a separate fixture and are marked:

```python
@pytest.mark.commits
async def test_only_one_of_two_concurrent_bookings_wins(committing_db: Database) -> None:
    clinic = await make_clinic(committing_db)
    ...
    results = await asyncio.gather(
        book(service_a), book(service_b), return_exceptions=True
    )
    assert sum(isinstance(r, SlotTakenError) for r in results) == 1
```

- **`committing_db`** is a `Database` on the same test database **without**
  `force_rollback`, with its own pool so each task gets its own connection.
  After the test it truncates every application table (`TRUNCATE … RESTART
  IDENTITY CASCADE`, skipping the Alembic version tables).
- Build the services under test with `committing_db`, not the app's `db`.
- **Mark them `commits`** (registered in `pytest.ini`), so they can be run
  or skipped as a group, and keep them few: one per lock or constraint the
  service skill's "Races" section relies on.
- If the repo has no `committing_db` yet, add it to `tests/_fixtures/database.py`
  in the same change as the first race test.

## 5. Auth in tests

- **Per-request headers, never a mutated client:**
  ```python
  response = await client.post(url, json=body, headers=auth_headers(user))
  ```
  `auth_headers(user)` mints the token (or, in a reference host, the stub
  header: kalens' `auth(user)`). Vetted's `create_authorized_client` sets
  `client.headers` on the shared client, so a second call in the same test
  silently turns every later request into the second user's.
- **One test per actor kind** at each gate: anonymous, wrong role, other
  tenant's staff, the superuser (whichever way `create-dependency` step 3
  decided).

## 6. Test IDs and markers

- **The test-ID plugin** (`tests/_plugins/test_ids.py`, identical in Sinapsis
  and Xolo) ships in every repo's suite. `@pytest.mark.test_id("XXX-NNN")` ties a
  test to a story's test case; `pytest --test-id XXX-NNN` runs it.
- **Required in Sinapsis and Xolo** (their `docs/WORKFLOW.md`: a behaviour
  without a test ID isn't built). **Optional in Vetted and Kalens**, which
  don't track stories that way; mark tests there when an issue names an ID.
- **Markers are registered** in `pytest.ini` and enforced with
  `--strict-markers`: `sanity` (the platform works), `test_id`, `commits`.

## 7. Layout and style

- **Tests mirror the code**: Sinapsis `tests/modules/<module>/`, `tests/shared/`;
  Vetted and Kalens one folder per domain. Within it, one file per behaviour or
  per layer (`test_create.py`, `test_service.py`, `test_models.py`).
- **Plain `async def test_*` functions.** A class only when its tests share
  real setup (a fixture override, as kalens' rate-limit tests do with
  `appts_settings`).
- **Names say the behaviour and the outcome**:
  `test_other_clinics_invoice_is_not_found`, not `test_get_invoice_2`.
- **`parametrize` with `ids=`** for tables of cases, so failures name the case.
- **Arrange, act, assert, visibly.** Factory calls at the top, one action,
  then the assertions. Compare responses against the route's `*Public` model
  (imported from the host's wiring module for library-served routes) or an
  explicit dict, never against another response.
- **Comments say why a case exists** when it isn't obvious from the name
  (`# 404 not 403: a caller can't learn the id exists elsewhere`).

## 8. Harness baseline

Each suite has, and new repos start with:

- `pytest.ini` (or `[tool.pytest.ini_options]`): `asyncio_mode = auto` with one
  session-wide event loop, `addopts = --strict-markers --strict-config`, the
  markers above, `filterwarnings` for known third-party noise only;
- **`conftest.py`**: `TESTING=1` set before the app is imported; an
  **infra smoke check** (session, autouse) that builds the app and pings
  PostgreSQL (and Redis where used), and `pytest.exit`s with one message
  naming the command that starts them;
- **`tests/_fixtures/database.py`**: `apply_migrations` (session) creating the
  test database *in the fixture* (`create-migration` step 6), upgrading, and
  downgrading to base at the end; `app`, `initialized_app`, `db`, `client`;
  `committing_db` once needed;
- **libraries**: the reference host in `tests/_host/`, `configure()` and
  `reset()` per test, and an autouse reset for any process-global state
  (kalens' rate-limit storage);
- **CI** running the whole suite on every pull request, with PostgreSQL as a
  service container on the repo's port (Vetted 5432, Kalens 5433, Xolo 5434).
  Kalens doesn't have CI yet (kalens#12).

Vetted's and Kalens' current `pytest.ini`s use `asyncio_mode = strict` and no
strict markers; move them to this baseline in a change of its own, since
`auto` mode changes how every async fixture is collected.

## 9. Running them

| | Everything | One file / test | One test ID |
|---|---|---|---|
| **pets-appts (Vetted)** | `make test-be` (needs `make` db up) | `cd backend && pytest tests/pets/test_clinic_pets.py -k name` | — |
| **Sinapsis** | `make test-backend` | `cd backend && uv run pytest tests/modules/health/test_routes.py` | `make test ID=PLT-002` |
| **Kalens** | `make test` (needs `make db-up`) | `.venv/bin/pytest tests/appointments/test_cancel.py::test_name -v` | — |
| **Xolo** | `make test` | `.venv/bin/pytest tests/test_harness.py` | `.venv/bin/pytest --test-id PLT-005` |

## Checklist

- [ ] The test is at the layer that owns the behaviour; rules aren't re-tested through HTTP.
- [ ] Real database; no mocks of our own code; `override_dependency` only for infrastructure.
- [ ] Rolled back per test; no session- or module-scoped fixture writes rows.
- [ ] Data from factories with unique values; no get-or-create; times explicit.
- [ ] Races use `committing_db`, are marked `commits`, and assert exactly one winner.
- [ ] Auth via per-request headers; one test per actor kind at each gate.
- [ ] URLs from `app.url_path_for(...)`; responses compared to the `*Public` model or an explicit dict.
- [ ] Test ID marked where the repo requires it; markers registered.
- [ ] The suite passes locally and in CI.
