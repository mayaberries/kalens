# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`kalens` is the scheduling engine from the sibling repo `../pets-appts`, **extracted verbatim**: appointments, weekly clinic availability, and the public booking surface. It's a FastAPI library, not an app. It owns two tables (`appointments` and `clinic_availability`). Everything else (users, services, clinics/tenants, and the booking's *subject*, today a pet) belongs to the host. The host supplies those through `AppointmentsIntegration`. It ships as a pip package pinned to a git tag (`@v0.1.0`), not via PyPI.

`kalens` is the codename and the distribution name only. The import package (`appts_core`), the Alembic section (`-n appts_core`), the version table (`appts_core_alembic_version`) and the `APPTS_CORE_*` env vars keep the old name, because renaming them breaks hosts and already-stamped databases. Don't rename them in passing.

"Verbatim" is a design constraint, not an accident. The code still says `pet_id`, `clinic_id` and `get_pet_by_id` on purpose. Don't generalise names or behaviour in passing. `docs/adapting.md` lists the planned generalisations and their order, and none of them have been made. Function bodies and comments copied from pets-appts should stay as they are. Only imports and annotations were changed.

## Commands

```sh
make install          # .venv + editable install with [test] extras (Python >= 3.13)
make db-up            # Postgres 13 in its own container on port 5433
make test             # pytest -v against the reference host
make lint             # compileall syntax check; there is no ruff/mypy
make verify           # test + compare-schema + compare-openapi
make db-down          # stop and drop the volume

.venv/bin/pytest tests/appointments/test_cancel.py::test_name -v   # single test
```

- Tests use **port 5433, never 5432** (that's pets-appts' DB). Each session runs `DROP DATABASE ... WITH (FORCE)` on `APPTS_CORE_TEST_DB` (default `appts_core_test`). Set the server with `APPTS_CORE_DATABASE_URL`.
- `compare-schema` and `compare-openapi` read `../pets-appts` and only read it. You can override the paths with `PETS_APPTS_BACKEND` and `PETS_APPTS_OPENAPI`. `compare-schema` runs pets-appts' Alembic chain on a throwaway DB and diffs columns, constraints, indexes, triggers and FK delete rules against this library's chain. `compare-openapi` diffs paths, methods, operation ids and status codes, but not response bodies.
- Dependency versions in `pyproject.toml` are pinned to exactly match `pets-appts/backend/requirements.txt`. Installing the library must never change the host's versions, so don't bump them on their own.

## Architecture

### The host contract (`integration.py`)

`AppointmentsIntegration` is a frozen dataclass with 16 fields: repository **classes** (instantiated per request with the shared `databases.Database`), FastAPI dependencies, keyword-called predicates, host models, and `Settings`. `docs/integration-contract.md` is the method-by-method checklist. `tests/_host/` is a complete reference implementation of it. Change all three together.

### Two resolution modes. This is the key thing to understand.

- **Repositories, models and the limiter** look up the host lazily through `get_integration()` / `get_settings()` at *call* time. That lets them stay plain module-level classes. The limiter also builds its storage and limits lazily for this reason.
- **Dependencies and routers can't do that.** FastAPI reads a function's signature when it's defined, and the host's callables appear in those signatures. So they're built by factories (`build_appointment_dependencies`, `build_*_router`) that `configure()` calls after installing the integration.

`configure()` returns an `AppointmentsModule`. Hosts must hold on to its `dependencies`. FastAPI caches dependencies per request by callable identity, so building them again would resolve the same appointment twice. `reset()` is for tests only.

### Injected models keep the OpenAPI schema the same

The library declares `AppointmentPublic.user/pet/service` loosely. The host passes a subclass that narrows them back to concrete types and is used as `response_model`. As a result, the emitted schema matches pets-appts' pre-extraction one. `coerce()` rebuilds host objects as the host's public model so InDB-only fields don't leak into responses. Route `name=` values are fixed because hosts build URLs with `app.url_path_for("appointments:create-appointment", ...)`. Route prefixes are chosen by the host.

### Data access

There's no ORM. Repositories run raw SQL through `databases`. Every appointment query uses the shared `APPOINTMENT_COLUMNS` list (`db/appointments.py`) because all of `AppointmentInDB`'s fields are Optional: a column missing from one SELECT silently reads back as `None`. Any new column must be added there. The double-booking check (`CHECK_OVERLAPPING_CONFIRMED_APPOINTMENT_QUERY`) joins `services` and scopes to `clinic_id`.

### Migrations

The library has its own Alembic chain in `src/appts_core/migrations/` with its own version table, `appts_core_alembic_version`. Hosts run `alembic -n appts_core ...` as a separate step after their own migrations. FKs to the host tables are how the contract is enforced. The `migrations` directory is force-included in the wheel because Alembic finds it by filesystem path. There's no `target_metadata`, so `--autogenerate` doesn't work and revisions are written by hand with `op`. `0001` squashes five pets-appts revisions, which `docs/migrations.md` maps. Downgrade deliberately leaves `update_updated_at_column()` in place.

### Tests

`tests/conftest.py` mirrors the two-phase order a real host follows: host DDL first (`tests/_host/schema.py`), then the library's Alembic `upgrade head`. `configure()` runs again for every test. To test different `Settings`, override the `appts_settings` fixture (see `test_rate_limiting.py`); don't build a second app. The schema is created once per session and not rolled back per test, so tests that book against the same provider use `unique_future_time()` to avoid overlaps.

## Behaviour that looks like a bug but isn't

These are pinned by tests and inherited on purpose (see `docs/adapting.md`):

- Overlap is checked only against `confirmed` appointments. Two `requested` appointments for the same slot can both succeed, and confirming one doesn't decline the other.
- A booking-authority mismatch returns **404, not 403**, so callers can't probe which subject ids exist.
- The FK delete rules are deliberately different: user → CASCADE, subject → RESTRICT, `cancelled_by` → SET NULL.
- `end_time` is computed and stored at insert time. Changing a service's duration doesn't move existing appointments.

## Conventions

Module and function docstrings explain *why*, often under capitalised headings (`WHY THESE ARE BUILT BY A FACTORY`), and they matter for understanding the code. Keep them when refactoring and match their style. Settings defaults must reproduce pets-appts' behaviour exactly.

## Git identity

The project author is `Maya Morales <maymorales@proton.me>` (see `pyproject.toml`). Per the parent `../CLAUDE.md`, set git identity with `--local` only and never `--global`, because the global config is a different, work identity. This repo doesn't have a local identity set yet.
