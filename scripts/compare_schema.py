"""
Prove the library's migration produces the same schema pets-appts does.

Builds two throwaway databases side by side on the appts-core Postgres:

    reference  <- pets-appts' own alembic chain, `upgrade head`
    library    <- the host-prerequisite DDL, then appts_core's chain

and diffs `appointments` and `clinic_availability` between them -- columns,
types, nullability, defaults, indexes, constraints and foreign-key delete
rules. A wrong `ON DELETE` or a renamed constraint is invisible to the
behavioural suite and would only surface much later, in production, as a
delete that cascades when it should have been blocked. This is the check that
catches it.

Read-only with respect to pets-appts: it runs that repo's alembic against a
database of its own here, and touches neither its files nor its own database.

    make compare-schema
"""
import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy
from alembic import command
from alembic.config import Config

import appts_core

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._host.schema import HOST_TABLES_DDL  # noqa: E402

BASE_URL = os.environ.get(
    "APPTS_CORE_DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/postgres"
)
PETS_BACKEND = Path(
    os.environ.get("PETS_APPTS_BACKEND", Path(__file__).resolve().parents[2] / "pets-appts" / "backend")
)

REFERENCE_DB = "appts_core_cmp_reference"
LIBRARY_DB = "appts_core_cmp_library"
TABLES = ("appointments", "clinic_availability")

COLUMNS_SQL = """
SELECT table_name, column_name, data_type, character_maximum_length,
       is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = ANY(:tables)
ORDER BY table_name, column_name;
"""

CONSTRAINTS_SQL = """
SELECT rel.relname AS table_name,
       con.conname  AS constraint_name,
       con.contype  AS kind,
       pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
JOIN pg_namespace ns ON ns.oid = rel.relnamespace
WHERE ns.nspname = 'public' AND rel.relname = ANY(:tables)
ORDER BY rel.relname, con.conname;
"""

INDEXES_SQL = """
SELECT tablename AS table_name, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public' AND tablename = ANY(:tables)
ORDER BY tablename, indexname;
"""

TRIGGERS_SQL = """
SELECT rel.relname AS table_name, tg.tgname AS trigger_name,
       pg_get_triggerdef(tg.oid) AS definition
FROM pg_trigger tg
JOIN pg_class rel ON rel.oid = tg.tgrelid
JOIN pg_namespace ns ON ns.oid = rel.relnamespace
WHERE NOT tg.tgisinternal AND ns.nspname = 'public' AND rel.relname = ANY(:tables)
ORDER BY rel.relname, tg.tgname;
"""


def url_for(db: str) -> str:
    return BASE_URL.rsplit("/", 1)[0] + "/" + db


def recreate(db: str) -> None:
    engine = sqlalchemy.create_engine(BASE_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)'))
        conn.execute(sqlalchemy.text(f'CREATE DATABASE "{db}"'))
    engine.dispose()


def drop(db: str) -> None:
    engine = sqlalchemy.create_engine(BASE_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)'))
    engine.dispose()


def build_reference() -> None:
    """pets-appts' own chain, run from its own venv so its pins apply."""
    recreate(REFERENCE_DB)
    python = PETS_BACKEND.parent / ".venv" / "bin" / "python"
    if not python.exists():
        raise SystemExit(f"pets-appts venv not found at {python}")
    env = {
        **os.environ,
        "DATABASE_URL": url_for(REFERENCE_DB),
        "POSTGRES_DB": REFERENCE_DB,
        "SECRET_KEY": "comparison-only",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "postgres",
        "POSTGRES_SERVER": "localhost",
        "POSTGRES_PORT": "5433",
    }
    env.pop("TESTING", None)
    subprocess.run(
        [str(python), "-m", "alembic", "upgrade", "head"],
        cwd=PETS_BACKEND, env=env, check=True, capture_output=True,
    )


def build_library() -> None:
    """Host prerequisites, then the library's chain -- the documented order."""
    recreate(LIBRARY_DB)
    engine = sqlalchemy.create_engine(url_for(LIBRARY_DB), isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text(HOST_TABLES_DDL))
    engine.dispose()

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(next(iter(appts_core.__path__))) / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url_for(LIBRARY_DB))
    command.upgrade(cfg, "head")


def snapshot(db: str) -> dict:
    engine = sqlalchemy.create_engine(url_for(db))
    out = {}
    with engine.connect() as conn:
        for label, sql in (
            ("columns", COLUMNS_SQL),
            ("constraints", CONSTRAINTS_SQL),
            ("indexes", INDEXES_SQL),
            ("triggers", TRIGGERS_SQL),
        ):
            rows = conn.execute(sqlalchemy.text(sql), {"tables": list(TABLES)}).fetchall()
            out[label] = [tuple(str(v) for v in row) for row in rows]
    engine.dispose()
    return out


def main() -> int:
    print(f"reference : pets-appts alembic  -> {REFERENCE_DB}")
    build_reference()
    print(f"library   : appts_core alembic  -> {LIBRARY_DB}")
    build_library()

    reference, library = snapshot(REFERENCE_DB), snapshot(LIBRARY_DB)

    failures = 0
    for label in ("columns", "constraints", "indexes", "triggers"):
        ref, lib = set(reference[label]), set(library[label])
        only_ref, only_lib = sorted(ref - lib), sorted(lib - ref)
        if not only_ref and not only_lib:
            print(f"  {label:<12} identical ({len(ref)} rows)")
            continue
        failures += 1
        print(f"  {label:<12} DIFFERS")
        for row in only_ref:
            print(f"      only in pets-appts : {row}")
        for row in only_lib:
            print(f"      only in appts_core : {row}")

    drop(REFERENCE_DB)
    drop(LIBRARY_DB)

    print("\nSCHEMAS MATCH" if not failures else f"\n{failures} section(s) differ")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
