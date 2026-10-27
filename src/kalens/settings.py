"""
Tunables the host may override.

Only the settings the library actually reads live here. Everything else
in the host's config -- SECRET_KEY, JWT_*, POSTGRES_* -- stays with the host,
because this library never authenticates anyone or opens a connection itself:
it is handed an authenticated user by an injected dependency and a live
`databases.Database` off `app.state`.

Defaults are sized for a single small deployment; a host that passes no
Settings at all gets exactly these.
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

    # Where `get_database` looks for the connection pool on `app.state`. A
    # host that names it something else says so here rather than being forced
    # to rename.
    database_state_attr: str = "_db"
