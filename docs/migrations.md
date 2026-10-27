# Migrations

`kalens` ships its own Alembic chain and keeps it in its own version
table, **`kalens_alembic_version`**. Your application's history stays in
`alembic_version` and the two never see each other: you upgrade them
separately, and a revision in one can never be mistaken for a revision in the
other.

## Wiring it up

Add a second section to your `alembic.ini`:

```ini
[kalens]
script_location = %(here)s/.venv/lib/python3.13/site-packages/kalens/migrations
sqlalchemy.url  = postgresql://user:pass@localhost:5432/yourdb
```

If you'd rather not hardcode the site-packages path, resolve it at runtime:

```python
from pathlib import Path
import kalens
print(Path(next(iter(kalens.__path__))) / "migrations")
```

The URL can also come from `KALENS_DATABASE_URL` or `DATABASE_URL` in the
environment, in that order, if `sqlalchemy.url` is unset. `postgres://` and
`+asyncpg` are normalised, so the same URL your app uses will work.

Then:

```bash
alembic -n kalens upgrade head
alembic -n kalens current
alembic -n kalens downgrade base
```

## Greenfield

Order matters, because the foreign keys are real:

```bash
alembic upgrade head                    # 1. your tables: users, services, clinics, subjects
alembic -n kalens upgrade head      # 2. appointments, clinic_availability
```

Step 2 fails loudly if step 1 didn't happen. That's the prerequisite contract
enforcing itself — see [integration-contract.md](integration-contract.md).

### Three phases, if you kept evaluations

An evaluations table keyed by `appointment_id` has a foreign key **into** a
library-owned table, so it cannot be created until step 2 has run:

```
1. host     alembic upgrade <the revision before evaluations>
2. library  alembic -n kalens upgrade head
3. host     alembic upgrade head          # the evaluations FK now resolves
```

If your evaluations revision sits in the middle of a long chain, splitting the
host upgrade at that point is a one-time cost of adopting the library. The
alternative — `depends_on` across two chains — Alembic does not support.

## Adopting a database that already has these tables

For a host whose own migrations already created `appointments` and
`clinic_availability`, with live data in them. **Do not run `upgrade`** — it would try to
`CREATE TABLE appointments` and fail.

```bash
alembic -n kalens stamp head
```

That writes `0001_kalens` into `kalens_alembic_version` and creates
nothing. From then on the library's future revisions apply normally.

Stamping is only safe if your tables match what the revision below creates,
down to column types, delete rules, constraint and index names, and triggers.
Check that before you stamp; diffing your schema against a throwaway database
migrated with `alembic -n kalens upgrade head` is the reliable way. Then stop
your own chain from re-creating these tables. `ix_services_clinic_id` stays
yours either way — it's on your table.

## What the library's revision creates

**`appointments`**

| Column | Type | Notes |
|---|---|---|
| `id` | `CHAR(36)` | PK, named `pk_appointments` |
| `user_id` | `CHAR(36)` | → `users.id` **CASCADE** |
| `service_id` | `CHAR(36)` | → `services.id` **CASCADE** |
| `pet_id` | `CHAR(36)` | → `pet_profiles.id` **RESTRICT** |
| `status` | `TEXT` | not null, default `'requested'` |
| `start_time` / `end_time` | `TIMESTAMPTZ` | not null |
| `cancellation_reason` | `TEXT` | nullable |
| `cancelled_by` | `CHAR(36)` | → `users.id` **SET NULL** |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | trigger-maintained |

Indexes: `ix_appointments_user_id`, `ix_appointments_service_id`,
`ix_appointments_status`, `ix_appointments_pet_id`,
`ix_appointments_service_id_start_time`.
Trigger: `update_appointments_modtime`.

**The three delete rules are all different, on purpose.** Deleting a user
takes their appointments with them (CASCADE). Deleting a *subject* that has
appointment history is blocked outright (RESTRICT) rather than silently
erasing it — whether soft delete would be better is an open question. Deleting the staff account
that cancelled something loses only the attribution (SET NULL): appointment
history must neither disappear with a departing employee nor block their
account being removed.

**`clinic_availability`** — `id` PK, `clinic_id` → `clinics.id` CASCADE with a
unique constraint (`uq_clinic_availability_clinic_id`, which the repository's
`ON CONFLICT` upsert depends on), `schedule JSONB` default `{}`,
`timezone TEXT` default `UTC`, timestamps, trigger
`update_clinic_availability_modtime`.

**`update_updated_at_column()`** is emitted as `CREATE OR REPLACE`. Your
tables very likely already use a function by that name with that body; the
replace is a no-op there, and creates it for a host that has none.

## Downgrade

```bash
alembic -n kalens downgrade base
```

Drops both tables. It deliberately **does not drop
`update_updated_at_column()`** — your own tables' triggers call it, and this
migration may not be what created it. Dropping it would break the host.
