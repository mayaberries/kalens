"""
Alembic environment for appts_core's own migration chain.

TWO CHAINS, TWO VERSION TABLES
    The host has its own history in its own `alembic_version` table. This
    library keeps a completely separate one in `appts_core_alembic_version`,
    so the two can be upgraded independently and neither can be confused by
    the other's revisions. That is the whole reason a host runs
    `alembic -n appts_core upgrade head` as a second command rather than
    having these revisions spliced into its own `versions/` directory.

DATABASE URL
    Resolved in this order, first hit wins:
      1. `sqlalchemy.url` in the alembic config section
      2. the `APPTS_CORE_DATABASE_URL` environment variable
      3. the `DATABASE_URL` environment variable
    A host that already has the URL in its config need only point
    `script_location` here.

No `target_metadata`: like the codebase this came from, there is no ORM model
layer, so `--autogenerate` is not available and every revision is written by
hand against `op`.
"""
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

VERSION_TABLE = "appts_core_alembic_version"


def _database_url() -> str:
    url = config.get_main_option("sqlalchemy.url", None)
    if url:
        return url
    url = os.environ.get("APPTS_CORE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "appts_core migrations need a database URL: set `sqlalchemy.url` in the "
            "alembic section, or APPTS_CORE_DATABASE_URL / DATABASE_URL in the environment."
        )
    # `databases` accepts postgres:// and postgresql+asyncpg://; SQLAlchemy's
    # sync engine here wants neither. Normalise rather than make the host keep
    # a second copy of the same URL in a different dialect.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url.replace("+asyncpg", "").replace("+aiopg", "")


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=None,
        literal_binds=True,
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=None,
            version_table=VERSION_TABLE,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
