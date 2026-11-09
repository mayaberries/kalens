---
name: add-setting
description: Add a configuration value, or an external service client (Redis, an email or storage provider), with its type, default, production rules, failure mode and health check — in an app (pets-appts/Vetted, Sinapsis) or a library's Settings (Kalens, Xolo). Use for "make X configurable", "add REDIS_URL", "we need to call the email API", "what happens when Y is down?".
---

# Add a setting or an external client

This file is identical in pets-appts (Vetted), Sinapsis, Kalens and Xolo. If you
change it in one repo, copy the change to the other three. The policy behind it
is recorded once per repo (Sinapsis: `docs/DECISIONS.md`, "Settings and
startup"; Xolo: `docs/DECISIONS.md`, "Settings in the Kalens shape"; Vetted:
`docs/architecture.md`, "Settings and startup").

Two rules hold everywhere:

- **Apps read the environment; libraries never do.** An app has one
  `Settings`. A library has a frozen dataclass `Settings` passed in through its
  integration, and the host maps its own environment onto it.
- **The app starts even when a dependency is down, and says so.** A request
  that needs it gets a `503`, `/health/ready` names it, and nothing fails as a
  500 or an `AttributeError` somewhere else.

## 0. Before you start

- **Existing configuration isn't moved in passing.** Vetted's
  `app/core/config.py` (module constants read at import, frozen into
  defaults in `AuthService` and `models/auth/token.py`), its hardcoded CORS
  and its `connect_to_db` are replaced in one change of their own. New
  settings there go in the new `Settings` once it exists; until then, add
  them to `config.py` *and* read them where used, not into a default.
- **Library or host?** A tunable the library reads is a field on the
  library's `Settings` (step 5). Everything else, including secrets the
  library never uses, stays with the host.

## 1. The `Settings` class (apps)

Sinapsis' `backend/app/shared/config.py` is the reference:

```python
ROOT = Path(__file__).resolve().parents[3]          # the repo root, not the cwd


class Environment(StrEnum):
    development = "development"
    test = "test"
    production = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    environment: Environment = Environment.development

    database_url: PostgresDsn = PostgresDsn("postgresql://app:app@localhost:5432/app")
    secret_key: SecretStr = SecretStr("dev-only-not-a-secret")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:4321"])

    @model_validator(mode="after")
    def production_has_real_values(self) -> "Settings":
        if self.environment is not Environment.production:
            return self
        problems = [
            name for name in ("database_url", "secret_key", "cors_origins")
            if name not in self.model_fields_set
        ]
        if self.secret_key.get_secret_value() in KNOWN_TEMPLATE_SECRETS:
            problems.append("secret_key (still the template's value)")
        if "*" in self.cors_origins:
            problems.append("cors_origins (no wildcard with credentials)")
        if problems:
            raise ValueError("Production settings missing or unsafe: " + ", ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- **One class, pydantic-settings, typed**: `PostgresDsn`, `RedisDsn`,
  `HttpUrl`, `SecretStr`, `list[str]`, enums. A value that doesn't parse
  fails at startup with the field's name.
- **Environment first, then `.env`**, resolved from the file's own location
  (`ROOT / ".env"`), never relative to the working directory. Vetted's
  `Config(".env")` silently finds nothing when run from the repo root.
- **`environment` replaces scattered testing flags.** `test` is what the
  harness sets; derived values (`effective_database_url` for `<db>_test`) are
  properties on `Settings`. No module reads `os.environ` itself (Vetted reads
  `TESTING` in `db/tasks.py` and `migrations/env.py`).
- **Development runs with no `.env`**: every value has a default that matches
  Docker Compose. **Production refuses those defaults** for anything unsafe,
  and lists *every* problem in one error, at startup.

## 2. Add a setting

- [ ] **A field** in `Settings`, `snake_case`; its env var is the same name in
      upper case (`PUBLIC_RATE_LIMIT_PER_KEY`).
- [ ] **The narrowest type**, with bounds where they mean something
      (`Annotated[int, Field(ge=1)]` for a limit).
- [ ] **Its default, or "required in production"**: if the development default
      would be wrong or dangerous in production (a URL, a secret, an origin),
      add it to `production_has_real_values`.
- [ ] **Secrets are `SecretStr`**, read only with `.get_secret_value()` at the
      point of use, never logged, never in a repr or an error message.
- [ ] **A comment** saying what it controls and how the default is sized, the
      way Vetted's rate limits do ("sized for many visitors booking through
      one clinic's widget at once").
- [ ] **`.env.example`** gets the variable, with the default as its value and
      the same comment. It names the file that reads it correctly (Sinapsis'
      still says `backend/app/core/config.py`).
- [ ] **CI and Docker Compose** set it if the default doesn't suit them.

## 3. Read it where it's used

- **Call `get_settings()` at the point of use**, or take it as a dependency
  (`SettingsDep = Annotated[Settings, Depends(get_settings)]`) in routes and
  dependencies. Never copy a value into a module constant, a function
  default (`secret_key: str = str(SECRET_KEY)`) or a model default
  (`aud: str = JWT_AUDIENCE`): those freeze at import and can't be changed by
  a test or the CLI.
- **Services receive values, not `Settings`**, when they need one or two
  (`token_ttl=settings.access_token_ttl`); a service that needs many takes a
  small dataclass of them. Models never read settings (`create-model` step 4).
- **Tests change settings** by overriding the dependency
  (`app.dependency_overrides[get_settings] = lambda: Settings(...)`) or with
  `get_settings.cache_clear()` around an env change, never by patching a
  module.

## 4. CORS, specifically

`cors_origins: list[str]` in settings, passed to `CORSMiddleware(allow_origins=…)`.
With `allow_credentials=True`, a `*` is never allowed: Starlette answers it
with the caller's own origin, so any site could make credentialed requests.
Vetted's `server.py` hardcodes exactly that; it moves to a setting in the
configuration change.

## 5. Library settings

```python
@dataclass(frozen=True)
class Settings:
    # Fallback slot length when a service carries no `duration_minutes`.
    default_appointment_duration_minutes: int = 30
```

- **A field on the library's frozen `Settings`**, with a default suited to
  one small deployment and a comment (Kalens' `settings.py` is the model).
  Libraries never read env vars or the host's config.
- **Read through `get_settings()`** at call time (it's lazy, see
  `library-contract`).
- **The host maps its own setting onto it** in its wiring module, using the
  env var name the host already had, so a deployment's values don't change
  when code moves into the library (Vetted's `scheduling.py` does this for
  the rate limits).
- **It's part of the contract:** document it in the contract doc and the
  changelog; changing a default is a breaking change (`library-contract`
  step 5).

## 6. Add an external client

For any service the app talks to over the network: Redis, an email or SMS
provider, object storage.

- [ ] **Its URL and credentials are settings** (steps 1–2), required in
      production unless the client is optional.
- [ ] **Built in the lifespan, stored on `app.state`**, closed on shutdown
      (Sinapsis' `lifespan.py`). Never at import, never per request.
- [ ] **Connecting doesn't block startup.** Try once, log a `warning` with
      `exc_info` if it fails, and start anyway. Reconnect lazily.
- [ ] **A dependency hands it out** (`get_redis`, `RedisDep`), so a test can
      replace it with `override_dependency`.
- [ ] **Its failure mode is decided and written next to the setting**:

      | Mode | Means | Use for |
      |---|---|---|
      | **fail-closed** | the request gets `503 {"detail": "Service temporarily unavailable."}` | anything the request can't be correct without: the database, auth |
      | **fail-open** | log at `warning`, carry on without it | anything that protects or enriches but isn't the request's purpose: rate limiting, caches, analytics |

      Kalens' rate limiter today is neither: `strategy.hit()` raises
      whatever Redis raises, so every public-booking request 500s while
      Redis is down. New limiters and caches are fail-open.
- [ ] **A readiness check** in `/health/ready` (step 7), named after the
      client (`"redis"`).
- [ ] **Log state changes, not every failure**: one `warning` when it becomes
      unreachable, one `info` when it's back. A per-request log line during an
      outage buries everything else.

## 7. Health and 503s

- **`GET /health/live`**: always `200 {"status": "ok"}` while the process can
  answer. For an orchestrator's restart decision; checks nothing.
- **`GET /health/ready`**: `200` or `503`, naming each check
  (`{"status": "unavailable", "checks": {"postgres": "unreachable", "redis": "ok"}}`).
  For a load balancer's routing decision. This is Sinapsis' `/health`
  (PLT-002/003); new apps split it, and Sinapsis keeps `/health` as an alias.
- **The database is fail-closed through its dependency, not a global
  catch.** A query on a `databases.Database` that never connected raises a
  bare `AssertionError("DatabaseBackend is not running")`, which no handler
  should catch globally. So `get_database` checks `database.is_connected`,
  tries `try_connect` once, and otherwise raises `ServiceUnavailableError`
  (a `DomainError` mapped to `503`, added to the hierarchy from
  `create-repository` step 3).
- **Connections that drop mid-request** raise asyncpg's
  `PostgresConnectionError` family (`ConnectionDoesNotExistError`) or an
  `OSError`; one exception handler maps those to the same `503` body and logs
  them. Vetted's `connect_to_db` swallows the failure and leaves
  `app.state._db` unset, so every later request fails with an
  `AttributeError` 500.

## 8. Test it

- **Settings**: production with a missing required value, a template secret
  or a wildcard origin fails, and the error names each one; development with
  no `.env` builds; a bad URL names the field.
- **Outages**, with `override_dependency` (`write-tests` step 1): the client
  unreachable gives `503` from a fail-closed route and success from a
  fail-open one; `/health/ready` names it; `/health/live` stays `200`.
- **Startup**: the app builds and `/health/live` answers with PostgreSQL down
  (Sinapsis' infra smoke check is the opposite: it aborts the *test* session
  when infrastructure is down, which is right for tests).
- **Library settings**: the reference host builds with non-default values and
  the behaviour follows them (Kalens' `appts_settings` fixture).

## Checklist

- [ ] App: one typed `Settings`; env then `.env` from the file's location; no `os.environ` elsewhere.
- [ ] Default for development; required-in-production where the default is unsafe; one error lists every problem.
- [ ] Secrets `SecretStr`; never logged; read at point of use.
- [ ] Read with `get_settings()` / `SettingsDep` where used; never frozen into constants or defaults.
- [ ] `.env.example` updated with the same comment.
- [ ] Library: a frozen-dataclass field with a default; the host maps its env var in the wiring module.
- [ ] Client: built in the lifespan, handed out by a dependency, failure mode written down.
- [ ] Fail-closed gives `503` via the dependency or the connection-error handler, never a 500.
- [ ] `/health/ready` checks it; state changes logged once.
- [ ] Tests for production validation and each outage.

## Where things are in each repo

| | Settings | Lifespan / clients | Health | Policy recorded in |
|---|---|---|---|---|
| **pets-appts (Vetted)** | `backend/app/core/config.py` *(module constants; moves to a `Settings` class)* | `app/core/tasks.py`, `app/db/tasks.py` | *(none yet)* | `docs/architecture.md` |
| **Sinapsis** | `backend/app/shared/config.py` (the reference) | `backend/app/lifespan.py`, `app/shared/db/` | `modules/health/` (`GET /health`) | `docs/DECISIONS.md` |
| **Kalens** | `src/kalens/settings.py` (frozen dataclass) | — (never connects; the host's pool) | — | `docs/integration-contract.md` (`settings`) |
| **Xolo** | `src/xolo/settings.py` *(planned: `SECRET_KEY`, `JWT_*`, `PROFILE_CLAIM_*`)* | — | — | `docs/DECISIONS.md` |
