"""
Tunables the host may override, lifted out of pets-appts' flat
`app/core/config.py`.

Only the settings the extracted code actually reads live here. Everything else
in the host's config -- SECRET_KEY, JWT_*, POSTGRES_* -- stays with the host,
because this library never authenticates anyone or opens a connection itself:
it is handed an authenticated user by an injected dependency and a live
`databases.Database` off `app.state`.

Defaults are the values pets-appts runs with today, so a host that passes no
Settings at all gets pets' behaviour exactly.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Settings:
    # Fallback slot length when a service carries no `duration_minutes`.
    default_appointment_duration_minutes: int = 30

    # Rate limiting. `redis_url` unset means in-process MemoryStorage --
    # correct for a single process, wrong for multiple workers, exactly as
    # it is in the host today.
    redis_url: Optional[str] = None
    public_rate_limit_per_key: int = 120
    public_rate_limit_per_ip: int = 600
    clinic_availability_read_rate_limit_per_clinic: int = 60
    clinic_availability_write_rate_limit_per_clinic: int = 20

    # Where `get_database` looks for the connection pool. pets-appts stashes
    # it as `app.state._db` in `connect_to_db`; a host that names it something
    # else says so here rather than being forced to rename.
    database_state_attr: str = "_db"
