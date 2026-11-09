---
name: create-route
description: Create a FastAPI route (path operation) and mount it, with its loader and guard dependencies, its service call, declared error responses and route tests. Use when adding an endpoint, e.g. "add an endpoint to archive a pet" or "expose the clinic's invoices over the API", in pets-appts (Vetted), Sinapsis, Kalens or Xolo.
---

# Create a route

This file is identical in pets-appts (Vetted), Sinapsis, Kalens and Xolo. If you
change it in one repo, copy the change to the other three. Its companion is the
`create-repository` skill: a route sits on top of the service that skill
describes.

A route **translates HTTP to a service call and back**, and nothing else:

| Concern | Goes in | Why not in the route |
|---|---|---|
| Loading the entity a path param names (→ 404) | a loader dependency `get_x_by_id_from_path` | shared, cached per request, and the guard needs it too |
| Who may call it (→ 401/403) | a guard dependency, on the route or the whole router | a guard can't be forgotten on a route the router covers |
| Business rules, multi-step workflows, tokens, hydration to `*Public` | the service | Vetted's `profiles:create-claim-token` does all of this inline, and the three `users:` registration routes each copy the same token-minting block |
| Turning a failure into a status code | the domain error handler | Vetted repeats `if not x: raise HTTPException(404, …)` in four files |
| Validating the shape of input | the request model, `Query(...)`, `Path(...)` | FastAPI returns the 422 for you |

## 0. Before you start

- **Existing routes are not in scope.** The published URLs, route names and
  response shapes are consumed by the admin app, the static sites, the admin
  CLI, kalens' host tests and xolo's pinned tests (GRD-009 pins
  `/login/token`). Don't rename, re-slash or re-shape one in passing. Changing
  one is its own change, with its consumers updated in the same PR.
- **New routes on an existing router match their neighbours** (trailing slash,
  segment style, name prefix) even where step 2 says otherwise. Consistency
  inside one router beats the convention.
- **Xolo's Extraction stage** moves routes verbatim, `HTTPException` included.
  This skill applies to routes written new, and to the Decoupling stage.
- **Kalens' route `name=` values and paths are part of its host contract.**
  Hosts build URLs with `app.url_path_for(...)`. A new kalens route is a new
  contract entry: add it to `docs/integration-contract.md` and the reference
  host's tests.
- You need a service method to call. If it doesn't exist, write it first with
  `create-repository`.

## 1. Decide the resource and the address

- **Plural kebab-case nouns, nested under the owner:** `/clinics/{clinic_id}/invoices`,
  `/services/{service_id}/appointments/{appointment_id}`. No underscores in new
  segments (Vetted's `/clinic_owners/` and `/clinic_pets/` are the old style).
- **No trailing slash** on new routers, as Sinapsis and kalens' public surface
  already do. A route declared `/x/` and called as `/x` costs a 307 redirect,
  and behind a TLS-terminating proxy that redirect can point at `http://`.
- **Put the tenant in the path** (`/clinics/{clinic_id}/...`) and check it with
  a guard, rather than inferring it from the token as `/clinic_pets/` does.
  It's explicit in the URL and the OpenAPI, it works unchanged for the
  superuser acting on another clinic, and the loader caches the clinic for the
  rest of the request.
- **Literal segments before parameters.** FastAPI matches in declaration
  order, so a `GET /me` declared after `GET /{username}` (Vetted's profiles
  router) would never be reached. Declare literal routes first, and keep
  reserved words like `me` out of the parameter's `pattern`.
- **Methods and status codes:**

  | Operation | Method | Success | Body |
  |---|---|---|---|
  | create | `POST /xs` | `201` | the `XPublic` |
  | read one / list | `GET /xs/{x_id}` / `GET /xs` | `200` | `XPublic` / `list[XPublic]` |
  | partial update (an `XUpdate` with all-optional fields) | `PATCH /xs/{x_id}` | `200` | the updated `XPublic` |
  | delete | `DELETE /xs/{x_id}` | `204` | none |
  | an action that isn't CRUD (confirm, cancel, revoke) | `POST /xs/{x_id}/confirm` | `200` | the resulting `XPublic` |

  Vetted uses `PUT` for partial updates and returns the deleted id as a bare
  `str` with `200`; keep that on its existing routers, use the table for new ones.
- **Every list is bounded:** `limit: int = Query(50, ge=1, le=500)`,
  `offset: int = Query(0, ge=0)`, as `clinics:list-all-clinics` does. An
  unbounded list is a slow endpoint waiting for data.

## 2. Name it

`name="<domain>:<verb>-<noun>"`, kebab-case on both sides of the colon:
`invoices:create-invoice`, `invoices:list-invoices-for-clinic`. The domain is
the router's (one per file). The name is how tests and hosts build URLs, so
it is as public as the path: never rename one in passing.

## 3. Write the dependencies

Next to the domain's other dependencies (paths in the table at the end):

```python
async def get_invoice_by_id_from_path(
    invoice_id: Annotated[str, Path()],
    clinic: ClinicDep,                       # already loaded and cached
    invoices_service: InvoicesServiceDep,
) -> InvoiceInDB:
    # Scoped by clinic, so another clinic's invoice is a 404, not a 403:
    # a caller can't learn that an id exists somewhere else.
    return await invoices_service.get_invoice_for_clinic(id=invoice_id, clinic_id=clinic.id)

InvoiceDep = Annotated[InvoiceInDB, Depends(get_invoice_by_id_from_path)]


async def check_clinic_staff(current_user: CurrentUserDep, clinic: ClinicDep) -> None:
    if not user_is_clinic_staff(user=current_user, clinic_id=clinic.id):
        raise PermissionDeniedError("Only this clinic's staff may do that.")
```

- **Loader:** named `get_x_by_id_from_path`, takes the path param, scopes by
  its parent, raises `NotFoundError` (through the service) when missing. Use
  it everywhere the entity is needed, including inside guards, so FastAPI
  resolves it once.
- **Guard:** named `check_x_permissions` / `check_<role>`, returns `None`,
  raises `PermissionDeniedError`. The rule itself is a plain keyword-called
  predicate (`user_can_manage_service(user=, service=)`) so services and
  kalens can call it too. Permission rules live in one place: here or in the
  service, never also in the repository.
- **`Annotated` aliases** for anything used twice: `CurrentUserDep`,
  `ClinicDep`, `InvoiceDep`, `InvoicesServiceDep`, as Sinapsis does with
  `HealthServiceDep`. Define the alias next to its function. If a shared one
  (`CurrentUserDep`) doesn't exist yet, add it beside the dependency it wraps.
- **In kalens and xolo**, a dependency that has a host callable in its
  signature is built by a factory, and a host must take it off the configured
  module, never rebuild it (callable identity is what FastAPI caches on).

## 4. Write the route

```python
router = APIRouter(dependencies=[Depends(check_clinic_staff)])   # covers every route here


@router.get(
    "/{invoice_id}",
    response_model=InvoicePublic,
    name="invoices:get-invoice",
    responses=error_responses(NotFoundError, PermissionDeniedError),
)
async def get_invoice(invoice: InvoiceDep, invoices_service: InvoicesServiceDep) -> InvoicePublic:
    return await invoices_service.to_public(invoice)


@router.patch(
    "/{invoice_id}",
    response_model=InvoicePublic,
    name="invoices:update-invoice",
    responses=error_responses(NotFoundError, PermissionDeniedError, ConflictError),
)
async def update_invoice(
    invoice: InvoiceDep,
    invoice_update: InvoiceUpdate,
    invoices_service: InvoicesServiceDep,
) -> InvoicePublic:
    return await invoices_service.update_invoice(invoice=invoice, invoice_update=invoice_update)


@router.delete(
    "/{invoice_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    name="invoices:delete-invoice",
    responses=error_responses(NotFoundError, PermissionDeniedError),
)
async def delete_invoice(invoice: InvoiceDep, invoices_service: InvoicesServiceDep) -> None:
    await invoices_service.delete_invoice(invoice=invoice)
```

- **The body is one service call**, plus at most shaping the HTTP response
  (a header, a status set on `Response`, as Sinapsis' `/health` does for 503).
  If you're writing an `if` about the domain, it belongs in the service.
- **Use the loaded entity.** Don't redeclare `x_id: str = Path(...)` and
  rebuild scope from the user when a loader already has the row
  (`pets:delete-pet-by-id` does; `clinic_pets:delete-pet-by-id` gets it right).
- **No `HTTPException`, no `current_user` passed to a repository.** Raise
  domain errors (from the service); pass plain IDs (`clinic_id=clinic.id`).
- **`response_model` is always a `*Public` model**, never `*InDB`: it's what
  strips `password`/`salt` and what the OpenAPI names. The return annotation
  says the same type, and the service actually returns it. Vetted's
  `-> PetProfilePublic` routes that return an `InDB`, and kalens' `Any`, only
  work because FastAPI re-serialises.
- **Declare every non-2xx a route can produce** in `responses=` with the
  `error_responses(...)` helper (step 5). The 401 from `CurrentUserDep` and the
  403 from a router-level guard count. Without it the OpenAPI shows only 2xx
  and 422, and the typed clients (Sinapsis' `make gen-api`, the admin app)
  can't tell the errors apart.
- **Request bodies are plain typed params** (`invoice_update: InvoiceUpdate`).
  `Body(..., embed=False)` is the default; leave it out.
- **Defaults that depend on "now"** are resolved in the body, not the
  signature (see Vetted's `feed:get-service-feed-for-user`): a signature
  default is evaluated once at import and leaks into the OpenAPI.
- **A docstring on the route** becomes its OpenAPI description. Write one when
  the who or why isn't obvious from the name (`clinics:list-all-clinics` is a
  good one).
- **Imports**: `from fastapi import APIRouter, Depends, Path, Query, status`.
  Not `starlette.status`, `fastapi.param_functions` or `fastapi.exceptions`.
  Built-in generics (`list[...]`), not `typing.List`.

## 5. Error responses in the OpenAPI

Built from the same `STATUS_CODES` the handler uses (Sinapsis'
`backend/app/shared/http/errors.py`), so the two can't disagree:

```python
class ErrorResponse(CoreModel):
    detail: str


def error_responses(*errors: type[DomainError]) -> dict[int, dict[str, Any]]:
    """`responses=` for a route that can raise these. Each error resolves to
    the status code the handler would give it, most specific first."""
    codes = {next(code for error, code in STATUS_CODES if issubclass(err, error)) for err in errors}
    return {code: {"model": ErrorResponse} for code in sorted(codes)}
```

Add `401` explicitly for routes behind `CurrentUserDep` (auth raises it
outside the domain hierarchy). **If the repo doesn't have the helper yet**, add
it to the HTTP errors module in the same change as the first route that uses
it, along with the error hierarchy and handler if those are missing too (see
`create-repository`, step 3).

## 6. Mount it

- **One router per file, one file per resource**, in the domain's route package.
  Leaf routers are bare `APIRouter()` (or `APIRouter(dependencies=[...])` for a
  shared guard) with paths relative to the mount: `""`, `"/{x_id}"`.
- **The prefix and the tag are set where it's included**, in the package's
  `__init__` (Vetted: `routes/<domain>/__init__.py`; Sinapsis: the module's
  `__init__` exports `router` and `main.py` mounts it under
  `settings.api_prefix`). Path params can live in the prefix:
  `prefix="/clinics/{clinic_id}/invoices"`.
- **Kalens and xolo** build routers in a `build_*_router(...)` factory that
  `configure()` calls; the host picks the prefix. Add the router to the module
  the factory returns and to the reference host's mounting.
- Regenerate the API schema: Vetted `make openapi`, Sinapsis `make gen-api`,
  Kalens `make compare-openapi` against its host (pending kalens#9). Generated, never hand-edited.

## 7. Test it

Through the app, building every URL from the route name:
`app.url_path_for("invoices:get-invoice", clinic_id=..., invoice_id=...)`.

- the success case: status code, body shape (compare against the `*Public`
  model), and for creates that the row exists;
- **one test per declared error response**: unauthenticated (401), another
  clinic's staff (403), an unknown or other-tenant id (404), a conflict (409),
  and a bad body (422) when validation is non-trivial;
- for lists: bounds of `limit`/`offset`, and that other tenants' rows never
  appear.

Follow the repo's test-ID convention where it has one (Sinapsis, Xolo:
`XXX-NNN`, see `docs/WORKFLOW.md`). Vetted's backend test DB isn't reset
between tests (`docs/testing.md`), so don't assert on global counts there.

## 8. Checklist

- [ ] Path: plural kebab-case, tenant in the path, no trailing slash (unless matching the router).
- [ ] `name="domain:verb-noun"`, unique, kebab-case.
- [ ] Loader and guard are dependencies; the route uses the loaded entity.
- [ ] Body is one service call; no `HTTPException`, no `current_user` into a repository.
- [ ] `response_model` is `*Public`; return annotation matches; 201 / 204 set where they apply.
- [ ] `responses=error_responses(...)` lists every error the route can produce (plus 401).
- [ ] Lists take bounded `limit`/`offset`.
- [ ] Mounted in the package `__init__` with prefix and tag; schema regenerated.
- [ ] Tests for success and each declared error, URLs from `url_path_for`.

## Where things go in each repo

| | Route file | Mounted in | Dependencies | Error helper |
|---|---|---|---|---|
| **pets-appts (Vetted)** | `backend/app/api/routes/<domain>/<resource>.py` | `backend/app/api/routes/<domain>/__init__.py` | `backend/app/api/dependencies/<resource>.py` (flat for now) | `backend/app/api/errors.py` *(not created yet)* |
| **Sinapsis** | `backend/app/modules/<domain>/routes.py` | the module's `__init__` exports `router`; `backend/app/main.py` mounts it | `modules/<domain>/dependencies.py` | `backend/app/shared/http/errors.py` *(add `error_responses`)* |
| **Kalens** | `src/kalens/api/routes/<domain>.py`, `build_<domain>_router` | the module `configure()` returns; the host chooses the prefix | `src/kalens/api/dependencies/<domain>.py`, built by factory | `src/kalens/errors.py` + exported handler *(not created yet)* |
| **Xolo** | `src/xolo/api/routes/<domain>.py` | as Kalens | `src/xolo/api/dependencies/<domain>.py` | as Kalens |

In Sinapsis, `lint-imports` enforces routes → dependencies → service →
repository → schemas, so a route importing a repository directly fails `make
lint`. Elsewhere, the checklist is the check.
