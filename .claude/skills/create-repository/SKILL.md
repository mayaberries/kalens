---
name: create-repository
description: Create a database repository (a class that runs SQL through `databases` and returns models) together with the service that builds on it. Use when adding a repository or a new table's data access, e.g. "add a repository for invoices" or "we need to store clinic notes", in pets-appts (Vetted), Sinapsis, Kalens or Xolo.
---

# Create a repository

This file is identical in pets-appts (Vetted), Sinapsis, Kalens and Xolo. If you
change it in one repo, copy the change to the other three.

A repository does one job: it **runs SQL against its own table and returns
models**. Everything else goes to a layer that already exists for it:

| Concern | Goes in | Not in the repository because |
|---|---|---|
| Who may do this | dependency (403 before the route runs) and/or service | repositories that checked permissions drifted from the dependency layer (Vetted's `ClinicAPIKeysRepository`) |
| Business rules, validation beyond the model | service | rules stay testable without a database or HTTP |
| Steps that touch several tables | service, inside one transaction | a repository that calls another repository hides writes and can't make them atomic |
| Turning `*InDB` into a nested `*Public` (the old `populate_*`) | service | composing other tables' data needs their repositories |
| Hashing, key generation, slugs, "now" as a decision | service (or `services/`/`shared/` helper it calls) | they're decisions, not storage |
| HTTP status codes | the error handler | nothing below the route layer should know it's behind HTTP |

The model to copy is Vetted's `PetProfilesRepository`
(`backend/app/db/repositories/pets.py`). It takes no user, raises nothing, calls
no other repository, and speaks only in IDs.

## 0. Before you start

- **Find the repo's paths** in the table at the end. Read the neighbouring
  repository and service files first and match their idiom.
- **Existing repositories are not in scope.** Most older ones break these rules
  (Vetted's raise `HTTPException`, take `requesting_user` and `populate_*`).
  Don't fix them in passing. In Xolo's Extraction stage they move verbatim *on
  purpose*, and Kalens' repository signatures are part of its host contract.
  Moving one over is its own change, so propose it instead of doing it.
- **A Kalens or Xolo repository a host calls** (listed in Kalens'
  `docs/integration-contract.md`) is a contract method. Its name, keyword
  arguments and return type are fixed by that document. Follow it, and change
  the contract, the reference host in `tests/_host/` and the docs together if
  you must change it.

## 1. Model the table

Use the repo's model conventions (Vetted: `app/models/<domain>/`; Sinapsis:
`modules/<domain>/schemas.py`; Kalens/Xolo: `models/`):

- `XCreate`: what a caller supplies. Leave out anything resolved server-side
  (owner IDs, tenant IDs), with a comment saying where it comes from.
- `XUpdate`: every field optional; the repository applies only what was set.
- `XInDB`: one row, exactly the table's columns. **This is what a repository
  returns.**
- `XPublic`: the API shape, built by the service. A repository never returns it.

Migrations come from the tool (`alembic revision -m "..."`), never by hand.

## 2. Write the repository

```python
X_COLUMNS = "id, name, owner_profile_id, created_at, updated_at"

CREATE_X_QUERY = f"""
    INSERT INTO xs (id, name, owner_profile_id)
    VALUES (:id, :name, :owner_profile_id)
    RETURNING {X_COLUMNS};
"""

GET_X_BY_ID_FOR_OWNER_QUERY = f"""
    SELECT {X_COLUMNS}
    FROM xs
    WHERE id = :id AND owner_profile_id = :owner_profile_id;
"""

LIST_XS_BY_IDS_QUERY = f"""
    SELECT {X_COLUMNS}
    FROM xs
    WHERE id = ANY(:ids);
"""


class XsRepository(BaseRepository):
    """All database access for the xs table. Speaks only in IDs."""

    async def create_x(self, *, new_x: XCreate, owner_profile_id: str) -> XInDB:
        try:
            record = await self.db.fetch_one(
                query=CREATE_X_QUERY,
                values={**new_x.model_dump(), "id": str(uuid4()), "owner_profile_id": owner_profile_id},
            )
        except UniqueViolationError as exc:
            raise XNameTakenError("An x with that name already exists.") from exc
        return XInDB(**record)

    async def get_x_by_id_for_owner(self, *, id: str, owner_profile_id: str) -> Optional[XInDB]:
        record = await self.db.fetch_one(
            query=GET_X_BY_ID_FOR_OWNER_QUERY, values={"id": id, "owner_profile_id": owner_profile_id}
        )
        if not record:
            return None
        return XInDB(**record)

    async def list_xs_by_ids(self, *, ids: list[str]) -> list[XInDB]:
        records = await self.db.fetch_all(query=LIST_XS_BY_IDS_QUERY, values={"ids": ids})
        return [XInDB(**r) for r in records]
```

The rules behind it:

- **SQL is module-level constants**, `:named` parameters, an explicit column
  list (a shared `X_COLUMNS` when several queries return the row). No `SELECT *`,
  no f-strings with values in them.
- **Keyword-only arguments** (`*`), named for what they are (`clinic_id`,
  `owner_profile_id`), never a user object. Scope is a plain ID the caller has
  already resolved, so the same method works for a logged-in user, a public key
  or the CLI. Vetted's `ServicesRepository` had to grow
  `list_services_by_clinic_id` next to a `requesting_user` version because
  public booking has no user.
- **Scope goes in the `WHERE`**, not in Python after the fetch: `WHERE id = :id
  AND clinic_id = :clinic_id`. A JOIN used only to scope (see
  `GET_PET_BY_ID_FOR_CLINIC_QUERY`) is fine; it still returns this table's row.
- **Return `XInDB`, `Optional[XInDB]` or `list[XInDB]`**, and annotate exactly
  that. No `populate=` flag, no union return types.
- **Not found is `None`**, for reads and for scoped writes (`UPDATE … WHERE id =
  :id AND owner_id = :owner_id RETURNING …` that matched nothing). The service
  decides whether that's a 404 or a 403.
- **Give the service what it needs to compose**: a `list_xs_by_ids` (or
  `by_<parent>_ids`) next to the single-row getter, so it can hydrate a list in
  one query instead of one per row.
- **Only this table.** No other repository in `__init__`, no SQL against another
  table's columns. If a write must also touch another table, it's two repository
  calls in a service.
- **No transactions here.** The service opens them (step 4). `databases` binds
  the transaction to the running task, so repository calls made inside it take
  part without being told.
- **IDs are generated here** (`str(uuid4())`), as in the existing repositories.
  Values that are decisions (passwords, keys, slugs, timestamps like
  `revoked_at`) are passed in by the service.
- **Imports**: models, `BaseRepository`, `databases`, the domain errors, and
  `asyncpg.exceptions` for constraint errors. Never `fastapi` or `starlette`.

## 3. Domain errors

A repository raises a domain error in one case only: **translating a
constraint violation** into something a caller understands. Catch the specific
asyncpg exception (`UniqueViolationError`, `ForeignKeyViolationError`,
`CheckViolationError`) around the statement that can trigger it, and raise from
it. Rely on the constraint, not on a check-then-insert: the check races, the
constraint doesn't (Vetted's `bootstrap_first_superuser` needed both for this
reason).

Business-rule errors ("already belongs to a clinic", "only confirmed
appointments can be evaluated") are raised by the **service**.

The hierarchy is Sinapsis' (`backend/app/shared/errors.py`):

```python
class DomainError(Exception):          # → 400
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

class NotFoundError(DomainError): ...          # → 404
class PermissionDeniedError(DomainError): ...  # → 403
class ConflictError(DomainError): ...          # → 409
```

Subclass the closest one per case (`class EmailTakenError(ConflictError)`) so
callers and tests can catch it by name. `detail` is the user-facing message.

One handler maps them to HTTP (Sinapsis' `backend/app/shared/http/errors.py`):
a `STATUS_CODES` list ordered most-specific-first and `register_error_handlers(app)`,
called once in app setup. To map a new subclass to a different code, add it to
`STATUS_CODES` above its parent.

**If the repo doesn't have these yet** (see the table), add both in the same
change as the first repository that raises: copy Sinapsis' two files into the
paths below and register the handler. In a library (Kalens, Xolo) the app isn't
yours: export `register_error_handlers` from the package, give the library its
own `DomainError` base so its errors and the host's don't collide, and add the
call to the host contract docs and the reference host.

## 4. Write the service

The service is where the repository's rows become behaviour (`list_profiles_by_ids`
stands for whatever by-IDs getter the related repository has or gains):

```python
class XsService:
    def __init__(self, *, db: Database, xs_repo: XsRepository, owners_repo: OwnerProfilesRepository) -> None:
        self.db = db
        self.xs_repo = xs_repo
        self.owners_repo = owners_repo

    async def get_x(self, *, id: str, owner_profile_id: str) -> XPublic:
        x = await self.xs_repo.get_x_by_id_for_owner(id=id, owner_profile_id=owner_profile_id)
        if x is None:
            raise XNotFoundError("No x found with that id.")
        return (await self._to_public([x]))[0]

    async def create_x_with_owner(self, *, new_x: XCreate, new_owner: OwnerProfileCreate) -> XPublic:
        async with self.db.transaction():
            owner = await self.owners_repo.create_owner_profile(profile_create=new_owner)
            x = await self.xs_repo.create_x(new_x=new_x, owner_profile_id=owner.id)
        return (await self._to_public([x]))[0]

    async def _to_public(self, xs: list[XInDB]) -> list[XPublic]:
        owners = await self.owners_repo.list_profiles_by_ids(ids=[x.owner_profile_id for x in xs])
        by_id = {o.id: o for o in owners}
        return [XPublic(**x.model_dump(), owner=by_id.get(x.owner_profile_id)) for x in xs]
```

- Repositories are passed in, not built inside.
- **Every multi-table write is one `async with self.db.transaction()`.** Without
  it, a failure halfway leaves the first rows written (Vetted's
  `register_new_user` can leave a user without a profile).
- Hydration replaces `populate_*`: batch-load the related rows by ID and
  assemble `XPublic`. If a field is missing from a response, the bug is here.
- The service raises domain errors, never `HTTPException`.
- Wire it with a dependency that builds it from `get_repository(...)` results,
  like Sinapsis' `get_health_service` / `HealthServiceDep`. Routes depend on
  the service and stay thin.
- Permission checks that need the request (current user, path params) stay in
  `dependencies/`, as today. Ones that need data the service loads go in the
  service and raise `PermissionDeniedError`. Pick one place per rule, and
  don't copy it into the repository.

## 5. Test it

- **Repository tests** against the real test database (each repo's testing doc
  says how it's created and reset): each method's happy path, `None` for
  missing and for out-of-scope IDs, and each constraint translation raising its
  domain error.
- **Service tests**: the rules, the error raised in each case, and that a
  failing step in a transaction leaves nothing written.
- **Route tests**: that each domain error comes out as the right status code
  and `{"detail": …}`.
- Follow the repo's test-ID convention where it has one (Sinapsis, Xolo:
  `XXX-NNN`, see `docs/WORKFLOW.md`). A behaviour without a test ID isn't built.

## 6. Checklist

- [ ] No `fastapi`/`starlette` import under the repository's folder.
- [ ] No `requesting_user` / `UserInDB` parameter; scope is a plain ID in the `WHERE`.
- [ ] Returns only `XInDB` / `Optional[XInDB]` / `list[XInDB]`, annotated exactly.
- [ ] No other repository constructed, no other table written.
- [ ] Constraint violations caught and re-raised as named domain errors.
- [ ] Multi-table writes are in a service, inside one transaction.
- [ ] Domain errors are mapped in the handler; the handler is registered.
- [ ] OpenAPI regenerated if routes changed (Vetted: `make openapi`; Sinapsis: `make gen-api`; Kalens: `make compare-openapi` against its host).

## Where things go in each repo

| | Repository | Models | Service | Domain errors | HTTP handler |
|---|---|---|---|---|---|
| **pets-appts (Vetted)** | `backend/app/db/repositories/<domain>.py` (flat for now, see `docs/roadmap.md`) | `backend/app/models/<domain>/` | `backend/app/services/<domain>.py` | `backend/app/core/errors.py` *(not created yet)* | `backend/app/api/errors.py`, registered in `api/server.py` *(not created yet)* |
| **Sinapsis** | `backend/app/modules/<domain>/repository.py` | `modules/<domain>/schemas.py` | `modules/<domain>/service.py`, built in `dependencies.py` | `backend/app/shared/errors.py` (+ module-specific subclasses in the module) | `backend/app/shared/http/errors.py`, already registered in `main.py` |
| **Kalens** | `src/kalens/db/<domain>.py` | `src/kalens/models/<domain>.py` | `src/kalens/services/<domain>.py` *(no services layer yet)* | `src/kalens/errors.py` *(not created yet)* | exported `register_error_handlers`; the host calls it *(not created yet)* |
| **Xolo** | `src/xolo/db/<domain>.py` | `src/xolo/models/<domain>.py` | `src/xolo/services/<domain>.py` | `src/xolo/errors.py` *(not created yet)* | as Kalens |

In Sinapsis, `lint-imports` enforces routes → dependencies → service →
repository → schemas, so a repository that imports its service fails `make
lint`. The other repos have no such check, so the checklist above is what
enforces it there.
