"""
Test bootstrap.

The session builds a throwaway database, creates the *host* tables by raw DDL,
then runs the library's own Alembic chain over the top -- which is exactly the
two-phase ordering docs/migrations.md tells a real host to follow. If the
prerequisite contract were wrong, `alembic upgrade` would fail here on a
foreign key, which is the point of doing it in this order rather than creating
everything in one script.
"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from random import randint
from typing import AsyncIterator, Optional, Tuple

import pytest
import pytest_asyncio
import sqlalchemy
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from databases import Database
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import kalens
from tests._host.app import build_app
from tests._host.schema import HOST_TABLES_DDL

pytest_plugins = ["tests._fixtures.entities"]

BASE_URL = os.environ.get(
    "KALENS_DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/postgres"
)
TEST_DB = os.environ.get("KALENS_TEST_DB", "kalens_test")
TEST_URL = BASE_URL.rsplit("/", 1)[0] + "/" + TEST_DB


def _library_migrations_config(url: str) -> Config:
    """Point Alembic at the migrations shipped inside the installed package --
    the same resolution a host does with `script_location` in its own ini."""
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(next(iter(kalens.__path__))) / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
def migrated_database() -> str:
    admin = sqlalchemy.create_engine(BASE_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sqlalchemy.text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
        conn.execute(sqlalchemy.text(f'CREATE DATABASE "{TEST_DB}"'))
    admin.dispose()

    # Phase 1: the host's tables. Phase 2: ours, on top.
    engine = sqlalchemy.create_engine(TEST_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text(HOST_TABLES_DDL))
    engine.dispose()

    command.upgrade(_library_migrations_config(TEST_URL), "head")

    yield TEST_URL

    admin = sqlalchemy.create_engine(BASE_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sqlalchemy.text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def appts_settings() -> Optional[kalens.Settings]:
    """Override in a test class to build the app with different Settings --
    see tests/public_booking/test_rate_limiting.py. There is one app and one
    installed integration per test, so a test that wants different settings
    has to change them *here* rather than build a second app; a second
    configure() would overwrite the first."""
    return None


@pytest.fixture
def app_and_module(
    migrated_database: str, appts_settings: Optional[kalens.Settings]
) -> Tuple[FastAPI, kalens.AppointmentsModule]:
    # configure() is re-run per test so a test may install different Settings;
    # reset() first so the previous test's integration and rate-limit buckets
    # can't leak into this one.
    kalens.reset()
    return build_app(migrated_database, appts_settings)


@pytest.fixture
def app(app_and_module) -> FastAPI:
    return app_and_module[0]


@pytest.fixture
def appts(app_and_module) -> kalens.AppointmentsModule:
    return app_and_module[1]


@pytest_asyncio.fixture
async def initialized_app(app: FastAPI) -> AsyncIterator[FastAPI]:
    async with LifespanManager(app):
        yield app


@pytest_asyncio.fixture
async def db(initialized_app: FastAPI) -> Database:
    return initialized_app.state._db


@pytest_asyncio.fixture
async def client(initialized_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=initialized_app),
        base_url="http://testserver",
        headers={"Content-Type": "application/json"},
    ) as c:
        yield c


def unique_future_time() -> datetime:
    """A start_time far enough out, and randomly enough placed, that two tests
    booking against the same provider don't collide.

    pets-appts carries the same helper for the same reason: its test database
    isn't reset between tests, so appointment fixtures in one test can conflict
    with another's. This suite recreates the schema per session rather than per
    test, so it inherits the problem and the same mitigation. Per-test
    transaction rollback is the real fix, in both places.
    """
    return datetime.now(timezone.utc) + timedelta(days=randint(2, 4000), minutes=randint(0, 59))
