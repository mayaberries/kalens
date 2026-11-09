---
name: create-migration
description: Write an Alembic revision — a table, column, constraint, index or data backfill — in a host (pets-appts/Vetted, Sinapsis) or a library (Kalens, Xolo), or bring a library's new revision into a host. Use for any schema change, e.g. "add a notes column to invoices", "make slugs unique", "backfill end_time", or "kalens released a migration, adopt it".
---

# Create a migration

This file is identical in pets-appts (Vetted), Sinapsis, Kalens and Xolo. If you
change it in one repo, copy the change to the other three. Models
(`create-model`) describe rows; this skill is how the rows' table gets there.

All four repos use Alembic **without SQLAlchemy metadata** (`target_metadata=None`):
the app talks to PostgreSQL through `databases` with raw SQL, so there is no
autogenerate. Every revision's body is written with `op` and SQL. The *file*
is still generated.

## 0. Before you start

- **Never edit an applied revision.** Once a revision has run anywhere other
  than your machine, fixing it is a new revision. This includes the stale
  comments and assumptions in existing ones.
- **Which chain?** A table belongs to the chain of whoever owns it: host
  tables in the host's chain, library tables in the library's
  (`kalens_alembic_version`, `xolo_alembic_version`). A host never creates a
  library's table in a fresh database, and a library never touches a host's
  table. Vetted's chain creating kalens' tables is the adoption history, not
  the pattern (step 7).
- **Is it a contract change?** A library revision that adds or changes a
  library-owned table, or a foreign key across chains, is one: follow
  `library-contract` step 5 as well.

## 1. Generate the file

```sh
# host (pets-appts: cd backend; Sinapsis: cd backend && uv run …)
alembic revision -m "add notes to invoices"

# library: stable, ordered, readable ids — hosts type them in `stamp` commands
alembic revision -m "add timezone to clinic availability" --rev-id 0002_kalens
```

- **Always generated, never hand-written.** The generator chains
  `down_revision` and writes a real `Create Date`. Two of Vetted's revisions
  (`a1f3c9d8e2b4`, `b2e4d1a7f3c6`) have patterned ids and date-only headers,
  and two comments cite revisions that never existed (`f1a2b3c4d5e6`,
  `c3f7a2e9d5b1`). That's what hand-writing leads to.
- **Apps keep Alembic's random ids. Libraries use `NNNN_<lib>`**, matching
  Kalens' `0001_kalens`.
- **Cite revisions by real id and slug** wherever code mentions one
  (`3a6fb55b8ce9_add_clinic_slug`), and grep for the id after writing it.
- **Docstring the why** at the top: what the revision is for, any
  non-obvious choice, what it assumes. `02702ac5c6e7_enforce_single_superuser`
  (why a partial unique index rather than an app check) is the model.

## 2. Write it

```python
def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("clinic_id", sa.CHAR(36), nullable=False),
        sa.Column("number", sa.Text, nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_invoices"),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], name="fk_invoices_clinic_id", ondelete="CASCADE"),
        sa.UniqueConstraint("clinic_id", "number", name="uq_invoices_clinic_id_number"),
        sa.CheckConstraint("status IN ('draft', 'issued', 'void')", name="ck_invoices_status"),
    )
    op.create_index("ix_invoices_clinic_id", "invoices", ["clinic_id"])
    op.execute(
        "CREATE TRIGGER update_invoices_modtime BEFORE UPDATE ON invoices "
        "FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();"
    )


def downgrade() -> None:
    op.drop_table("invoices")   # drops its index, constraints and trigger with it
```

- **Every constraint and index has an explicit name**, by this convention:

  | Kind | Name |
  |---|---|
  | primary key | `pk_<table>` |
  | foreign key | `fk_<table>_<column>` |
  | unique | `uq_<table>_<columns>` |
  | index | `ix_<table>_<columns>` |
  | check | `ck_<table>_<rule>` |
  | exclusion | `ex_<table>_<rule>` |

  No `index=True` / `unique=True` on columns: Alembic names those itself.
  Stamping and schema comparison only work when names are predictable (Kalens'
  `0001` says why).
- **Revisions are frozen: no app imports.** Copy helpers into the revision
  (`timestamps()`, `_slugify` in `3a6fb55b8ce9`) so a later change to the
  app's version can't change what an old revision does.
- **Types:** ids `CHAR(36)`; text `Text`; money `Numeric(p, s)`; timestamps
  `TIMESTAMP(timezone=True)`, i.e. `TIMESTAMPTZ`; JSON `JSONB`; enums as `Text`
  with a `ck_` check (adding a value later is a one-line constraint swap, not
  an `ALTER TYPE`).
- **Every table gets** `created_at` / `updated_at` as `TIMESTAMPTZ NOT NULL
  DEFAULT now()` (the `timestamps()` helper) and an `update_<table>_modtime`
  trigger.
- **`update_updated_at_column()` is shared across chains.** Vetted, Kalens and
  Xolo all use it. Define it only with `CREATE OR REPLACE`, never `DROP` it
  from a library, and drop it from a host only in the base downgrade, with a
  comment that library tables depend on it. Vetted's first downgrade drops it
  unconditionally, which fails in a host where kalens was upgraded rather
  than stamped.
- **Constraints over app checks** for anything the services rely on:
  uniqueness, one-of-a-kind rows (partial unique index, as
  `ix_users_single_superuser`), non-overlapping time ranges
  (`EXCLUDE USING gist (… WITH =, tstzrange(start_time, end_time) WITH &&)`,
  which needs `CREATE EXTENSION IF NOT EXISTS btree_gist`). `create-service`'s
  "Races" section depends on these existing.
- **Every foreign key states `ondelete`** (`CASCADE`, `RESTRICT`, `SET NULL`),
  with a comment when the choice isn't obvious. A wrong delete rule is
  invisible to behavioural tests.
- **Index what the queries filter and join on.** Each new repository query's
  `WHERE`/`JOIN` columns should have an index, or a comment saying why not.

## 3. Changing existing data

**Expand → backfill → contract**, so no step needs the data to be already
right:

```python
def upgrade() -> None:
    op.add_column("clinics", sa.Column("timezone", sa.Text, nullable=True))       # expand
    op.execute("UPDATE clinics SET timezone = 'America/Mexico_City' WHERE timezone IS NULL")  # backfill
    op.alter_column("clinics", "timezone", nullable=False)                         # contract
```

- **Backfills are set-based SQL** (`UPDATE … SET … FROM …`), not Python loops
  over rows. Use Python only for a transformation SQL can't express (the slug
  backfill), and then batch it.
- **Check assumptions, don't comment them.** When a revision depends on the
  state of existing data ("no rows yet", "every appointment has a service"),
  query it and raise:

  ```python
  rows = op.get_bind().execute(sa.text("SELECT count(*) FROM service_to_cleaner_evaluations")).scalar()
  if rows:
      raise RuntimeError(f"{rows} evaluations exist; backfill appointment_id before running this revision.")
  ```

  Vetted's evaluations rekey and scheduling backfill state their assumption
  in a comment and would silently do the wrong thing on real data.
- **Placeholder values are a last resort.** If a backfill can't know the real
  value, say so in the docstring and in `docs/roadmap.md`, not only in a
  comment.

## 4. Tables that hold real data

Locks, not correctness, are the risk once a table has real traffic. For any
table that may:

- **Indexes: `CONCURRENTLY`**, outside the revision's transaction:
  ```python
  with op.get_context().autocommit_block():
      op.create_index("ix_appointments_clinic_id", "appointments", ["clinic_id"], postgresql_concurrently=True)
  ```
- **New foreign keys and checks: `NOT VALID`, then `VALIDATE`**, so the table
  isn't locked while existing rows are checked.
- **Don't combine a rewriting `ALTER`** (type change, `NOT NULL` on a big
  table) with a backfill in one transaction; split into revisions.
- **Adding a column with a constant default is cheap** in PostgreSQL ≥ 11;
  adding one computed per row isn't.

None of this is needed for a table created in the same revision.

## 5. Downgrades

- **Always write one**, in reverse order of the upgrade, naming the same
  constraints and indexes.
- **A downgrade that loses data says so** in the docstring (dropping a
  column, collapsing a key back), so nobody runs it expecting a round trip.
- **The test suite runs them**: each repo's session upgrades to head and
  downgrades to base (Vetted's `apply_migrations` fixture does; Sinapsis'
  and Kalens' sessions should). A downgrade that doesn't run is a downgrade
  that doesn't work.

## 6. Test databases

- **New code creates and drops the test database in the test fixture**, as
  Kalens' `migrated_database` does, not in `env.py`. Vetted's and Sinapsis'
  `env.py` recreate `<db>_test` when `TESTING` is set, so `TESTING=1` left in a
  shell makes a plain `alembic upgrade` destructive. Leave those as they are
  until someone works on that env, and don't copy the pattern.
- **Library chains get the URL handed to them**: their `env.py` can't know the
  host's `_test` suffix. Pass `sqlalchemy.url` explicitly (Vetted's fixture,
  with `%` escaped as `%%` for configparser) or set `<LIB>_DATABASE_URL`.

## 7. Library revisions in a host

How a host takes a library's new revision depends on how it adopted the
library:

- **Greenfield host** (the library's chain was `upgrade`d): just upgrade the
  library's chain, in the documented phase order (step 8).
- **Adopted by `stamp`** (the host's own chain created the tables, as Vetted
  did with Kalens and will with Xolo):
  1. mirror the library's revision as a new revision in the **host's** chain,
     with the same constraint and index names;
  2. upgrade the host's chain;
  3. `alembic -n <lib> stamp head`;
  4. run the schema comparison (step 9).

  Never `upgrade` the library's chain on such a host: it would try to create
  what already exists.
- **Read the library's changelog** (`library-contract` step 5) for every
  version between the old pin and the new: it lists new revisions and any
  change to the phase order.

## 8. Foreign keys across chains

Alembic can't express a dependency between two chains (`depends_on` is
within one). So when a foreign key crosses chains, the **upgrade order is a
documented phase sequence**, not something the tool enforces:

- library table → host table (`appointments.pet_id → pet_profiles.id`): host
  first, then library. Kalens' `0001` lists these prerequisites in its
  docstring; do the same.
- host table → library table (Vetted's `evaluations.appointment_id →
  appointments.id`): host up to the revision before, library, then the rest
  of the host. Kalens' `docs/migrations.md`, "Three phases".
- both ways (Xolo's `users.clinic_id → clinics`, and the host's
  `owner_profiles.user_id → users`): more phases, written out in the
  library's docs and the host's Make target.

Every new cross-chain FK goes in the library's changelog and contract doc,
and the host's Make target and test fixture run the phases in that order.

## 9. Prove it

- [ ] `alembic upgrade head` then `alembic downgrade base` then `upgrade head`
      again, on a scratch database (the test session does the first two).
- [ ] The suite passes.
- [ ] **For any change to a library-owned table, in a host that stamped**:
      the schema comparison passes. It diffs the host's chain against the
      library's prerequisites + chain, table by table, names and delete rules
      included. Kalens removed its pets-appts-specific scripts in `1be99ba`;
      host-agnostic replacements are **kalens#9**
      (`python -m kalens.tools.compare_schema`, `make compare-schema`). Until
      it lands, compare `pg_dump --schema-only -t <table>` of the two by hand
      and say so in the PR.
- [ ] The `docs/` page that describes the table or the adoption is updated
      (Vetted: `docs/domain.md`, `docs/architecture.md`; libraries:
      `docs/migrations.md`).

## Checklist

- [ ] Generated with `alembic revision` (`--rev-id NNNN_<lib>` in libraries); docstring says why.
- [ ] Right chain; never an applied revision edited.
- [ ] Every constraint and index explicitly named by the convention; every FK has `ondelete`.
- [ ] No app imports; helpers copied in; `TIMESTAMPTZ` timestamps and the modtime trigger.
- [ ] Shared trigger function only `CREATE OR REPLACE`d, never dropped by a library.
- [ ] Data changes are expand → backfill → contract, set-based, with assumptions checked and raised.
- [ ] Live-table rules applied where the table may hold real data.
- [ ] Downgrade written, lossiness stated, round trip run.
- [ ] Library revisions mirrored + re-stamped in stamping hosts; cross-chain FKs phased and documented.
- [ ] Schema comparison run (or the manual `pg_dump` diff until kalens#9).

## Where things are in each repo

| | Revisions | Config / env | Run with | Test session |
|---|---|---|---|---|
| **pets-appts (Vetted)** | `backend/app/db/migrations/versions/` | `backend/alembic.ini` (`[alembic]`, `[kalens]`), `app/db/migrations/env.py` | `make upgrade-db` (upgrades ours, stamps kalens) | `tests/_fixtures/database.py::apply_migrations` |
| **Sinapsis** | `backend/app/migrations/versions/` | `backend/alembic.ini`, `app/migrations/env.py` (settings via `get_settings()`) | `make migrate` | recreated per session (`TESTING=1`) |
| **Kalens** | `src/kalens/migrations/versions/` (`NNNN_kalens`) | `src/kalens/migrations/env.py`, version table `kalens_alembic_version` | hosts: `alembic -n kalens …` | `tests/conftest.py::migrated_database` (host DDL, then the chain) |
| **Xolo** | `src/xolo/migrations/versions/` *(planned, `0001` squashes Vetted's `users` + `clinic_api_keys`)* | version table `xolo_alembic_version` | hosts: `alembic -n xolo …` | as Kalens |
