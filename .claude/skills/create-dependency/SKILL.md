---
name: create-dependency
description: Create a FastAPI dependency (an actor resolver, role gate, entity loader, permission guard or service builder) with the right status codes, tenant scoping and Annotated alias. Use when a route needs to know who is calling, load what a path names, check whether the caller may act, or receive a service, e.g. "only clinic admins can do this", "load the invoice from the path" or "accept a signed link token", in pets-appts (Vetted), Sinapsis, Kalens or Xolo.
---

# Create a dependency

This file is identical in pets-appts (Vetted), Sinapsis, Kalens and Xolo. If you
change it in one repo, copy the change to the other three. It completes the set
with `create-route`, `create-service` and `create-repository`.

A dependency is **the HTTP edge's adapter**: it turns parts of the request
(headers, token, path, query) into trusted values, and hands them to a service.
There are five kinds, and a new dependency is exactly one of them:

| Kind | Turns | Into | Fails with | Example |
|---|---|---|---|---|
| **Actor resolver** | credentials (bearer token, `X-Clinic-Key`, a signed link token) | who is calling | `401` | `get_current_active_user`, `get_clinic_from_public_key` |
| **Role gate** | the actor | the actor, if this *kind* of actor may be here at all | `403` | `require_role(...)`, `require_superuser`, `get_current_clinic_staff` |
| **Loader** | a path param (+ its parent) | the entity, scoped | `404` | `get_clinic_pet_by_id_from_path` |
| **Guard** | the actor + loaded entities | nothing (`None`), if the actor may do *this* | `403` | `check_clinic_modification_permissions` |
| **Builder** | infrastructure | a service, repository or client | — | `get_health_service`, `get_repository`, `get_database` |

What is **not** a dependency, and where it goes instead:

| Not this | Today's example | Goes in |
|---|---|---|
| State rules ("only confirmed appointments") | `check_evaluation_create_permissions` | service |
| Uniqueness / overlap ("evaluation already exists", "time already booked") | `check_evaluation_create_permissions`, kalens' `check_appointment_create_permissions` | constraint or lock + service (`create-service`, "Races") |
| One-time-use rules ("already claimed") | `get_profile_from_claim_token`, also re-checked in `UsersRepository` | service, once |
| Running the route's query for it | `list_evaluations_for_cleaner_from_path` | service; the route calls it |
| Reading the request body | `check_pet_owner_registered_with_clinic` declares the route's `Body` | the service (it gets the body from the route), or the input model's validators |

## 0. Before you start

- **Existing dependencies are not in scope.** Seven of Vetted's are handed to
  kalens through `scheduling.py` (`AppointmentsIntegration`), and Xolo's
  Extraction stage moves the auth ones verbatim. Changing one is its own
  change, contract and reference host included.
- **Reuse before adding.** Grep the dependencies folder (both layers, as
  the architecture docs warn) for an existing loader or gate. A second
  loader for the same entity defeats FastAPI's per-request cache.
- **In kalens and xolo**, a dependency whose signature includes a host
  callable is built inside a factory (`build_*_dependencies`) that runs
  after `configure()`, returned in a frozen dataclass, and taken off the
  configured module by the host, never rebuilt. FastAPI caches by callable
  identity, so a rebuilt copy resolves the entity twice. Xolo, which will
  *provide* `get_current_active_user`, follows the same rule for what it
  hands out.

## 1. Status codes at the edge

| Condition | Status | Error |
|---|---|---|
| no credentials, malformed, expired, revoked, unknown | `401` (+ `WWW-Authenticate: Bearer` for bearer auth) | `NotAuthenticatedError` |
| authenticated but inactive, wrong role, not attached to a clinic, not allowed to do this | `403` | `PermissionDeniedError` |
| the path names something missing **or belonging to another tenant** | `404` | `NotFoundError` |
| conflicts with current state (exists, taken, already claimed) | `409` | `ConflictError` (raised by the service) |
| malformed input | `422` | FastAPI, from the model / `Path` / `Query` |

- **New dependencies raise domain errors**, not `HTTPException`.
  `NotAuthenticatedError(DomainError)` joins the hierarchy from
  `create-repository` step 3, mapped to `401` in `STATUS_CODES`. Give
  `DomainError` an optional `headers: dict[str, str] | None` that the handler
  passes to the response, so bearer failures can carry `WWW-Authenticate`.
  If the repo's errors module or handler doesn't have these yet, add them in
  the same change.
- **All of an actor resolver's failures look the same.** One status, one
  message for missing, malformed, unknown and revoked, so callers can't
  enumerate valid shapes (`public_auth.py`'s docstring is the model).
- Today's code differs: staff without a clinic and users without a profile
  get `400`, inactive users `401`, duplicates `400`. Keep that on existing
  dependencies; use the table for new ones.

## 2. Tenant scoping: 404, always

- **A loader queries with its parent scope** (`get_x_for_clinic(id=,
  clinic_id=)` on the service), so another tenant's row is indistinguishable
  from a missing one. Never load by ID and compare the tenant in Python
  (`get_clinic_api_key_by_id_from_path` does), and never load unscoped and
  let a guard 403 it (`get_pet_by_id_from_path` + `check_pet_access_permissions`
  confirm that the pet exists).
- **A guard 403s only when the actor can see the entity but may not do this
  to it**: aux staff revoking a key, a client cancelling someone else's
  confirmed booking at their own clinic.
- **Say why in the docstring** when a loader or resolver is deliberately
  opaque, as `get_clinic_owner_pivot_by_id_from_path` does. It's the kind of
  choice someone "fixes" later.

## 3. The superuser

`is_superuser` is a platform-operator flag, independent of `role`. Today
whether it bypasses a check depends on which predicate a route happens to use:
`user_can_manage_clinic` lets it through, `user_can_manage_service` and every
gate scoped to `current_user.clinic_id` don't.

For new gates, route the decision through **one predicate**:

```python
def acts_for_clinic(*, user: UserInDB, clinic_id: str) -> bool:
    """The single place that decides whether a user may act on a clinic's
    behalf. The platform operator may act for any clinic."""
    return user.is_superuser or user.clinic_id == clinic_id
```

and build role-specific predicates on top of it (`user_can_manage_clinic =
acts_for_clinic and role == clinic_admin`). Whether the operator also bypasses
a given surface is then one visible line, decided once.

## 4. Write it

```python
async def get_invoice_by_id_from_path(
    invoice_id: Annotated[str, Path(description="The invoice's id.")],
    clinic: ClinicDep,
    invoices_service: InvoicesServiceDep,
) -> InvoiceInDB:
    # Scoped by the clinic in the path: another clinic's invoice is a 404,
    # so staff can't probe for ids that exist elsewhere.
    return await invoices_service.get_invoice_for_clinic(id=invoice_id, clinic_id=clinic.id)

InvoiceDep = Annotated[InvoiceInDB, Depends(get_invoice_by_id_from_path)]


def check_can_void_invoice(current_user: CurrentUserDep, clinic: ClinicDep, invoice: InvoiceDep) -> None:
    if not user_can_void_invoice(user=current_user, clinic_id=clinic.id, invoice=invoice):
        raise PermissionDeniedError("Only this clinic's admin may void its invoices.")


def user_can_void_invoice(*, user: UserInDB, clinic_id: str, invoice: InvoiceInDB) -> bool:
    return acts_for_clinic(user=user, clinic_id=clinic_id) and user.role == UserRole.clinic_admin
```

- **Names say the kind**: `get_current_*` (actor), `require_*` / `get_current_<role>`
  (gate), `get_x_by_id_from_path` (loader), `check_*` (guard), `get_x_service`
  (builder), `user_can_*` / `acts_for_*` (predicate, not a dependency).
- **Loaders go through the service's scoped lookup**, which raises
  `NotFoundError`. They don't call repositories, don't add an `if not x`, and
  don't enforce rules beyond scope.
- **Guards use only what loaders and resolvers already produced.** No queries
  of their own: if a guard needs more data, there's a loader missing. They
  return `None` and are attached with `dependencies=[Depends(check_...)]`
  on the route or the whole router.
- **The rule is a plain keyword-called predicate**, defined next to its guard,
  that services and kalens can call too. Each rule lives in one place; never
  also in a repository or a second guard.
- **One guard per permission surface, not per message.** If two guards
  differ only in wording (`check_pet_access_permissions` /
  `check_pet_modification_permissions`), it's one guard. Keep separate guards
  when the surfaces may diverge, and say so (`check_clinic_admin_permissions`'
  docstring does).
- **No hidden auth in a loader.** If a loader needs the actor for scoping, it
  depends on it openly; if it doesn't, it doesn't.
  `get_user_by_username_from_path` requires login only because it depends on
  `get_current_active_user`, and nothing in the routes says so.
- **Validators of query or header input return the validated value**
  (`validate_owner_filter_registered_with_clinic` returns the id or `None`),
  so the route only ever sees trusted input. They never declare a `Body`.
- **Enums, not strings**: `user.role == UserRole.clinic_admin`, not
  `"clinic_admin"`.
- **Declare parameter metadata** (`Path(pattern=…)`, `Query(description=…)`,
  `Header(alias="X-Clinic-Key", description=…)`): it's what the OpenAPI shows.
- **Defaults that depend on "now" or settings** are resolved in the body, not
  the signature.

## 5. Aliases and builders

- **Every dependency used more than once gets an `Annotated` alias**, defined
  right under it: `CurrentUserDep`, `ClinicStaffDep`, `PublicClinicDep`,
  `ClinicDep`, `InvoiceDep`, `InvoicesServiceDep`. Routes and other
  dependencies use the alias, so the cached callable is always the same one.
- **Factories that parameterise** (`require_role(*roles)`, `get_repository(Repo)`)
  return a new callable per call, so two calls are two cache entries. Bind the
  result once to a module-level alias (`ClinicAdminDep =
  Annotated[UserInDB, Depends(require_role(UserRole.clinic_admin))]`) and reuse
  that.
- **`get_repository` is typed** as in Sinapsis
  (`def get_repository[RepoT: BaseRepository](repo_type: type[RepoT]) -> Callable[[Database], RepoT]`),
  with `DatabaseDep`. Builders are the only dependencies that touch
  repositories; per `create-service`, routes and other dependencies get a
  service.

## 6. Where it lives

- **Actor resolvers and role gates** are shared and live together in the
  auth/access module, not in a domain file (Vetted's `get_current_clinic_staff`
  sits in `clinic_owner_profiles.py` today).
- **Loaders, guards and predicates** live with their domain, next to its
  service builder.
- See the table at the end for each repo's paths.

## 7. Test it

Through routes that use it, with URLs from `app.url_path_for(...)`:

- **actor resolvers**: missing, malformed, expired/revoked, unknown → the same
  `401` and body; valid → the route runs as that actor;
- **gates**: each excluded role, inactive, no clinic → `403`; the superuser
  case, whichever way it was decided;
- **loaders**: missing id and another tenant's id → the same `404` and body;
- **guards**: an actor who can see but may not act → `403`; one who may → success;
- **caching**: where a loader is shared by a guard and the route, that the
  entity is fetched once (count calls on the service, or assert on query count).

Follow the repo's test-ID convention where it has one (Sinapsis, Xolo: `XXX-NNN`).

## 8. Checklist

- [ ] It's one of the five kinds, and its name says which.
- [ ] No business rules, uniqueness checks, use-case queries or `Body` params.
- [ ] Raises domain errors with the status codes in step 1; resolvers fail uniformly.
- [ ] Loaders scope by parent through the service: other tenants are 404.
- [ ] Guards use only resolved values; the rule is one predicate in one place.
- [ ] Clinic-scoped gates go through `acts_for_clinic` (or the repo's equivalent).
- [ ] `Annotated` alias for anything reused; parameterised factories bound once.
- [ ] In kalens/xolo: built by the factory, taken off the configured module.
- [ ] Tests for each failure status and the success path.

## Where things go in each repo

| | Actor resolvers, role gates | Loaders, guards, predicates, builders | Errors / handler |
|---|---|---|---|
| **pets-appts (Vetted)** | `backend/app/api/dependencies/auth.py`, `roles.py` | `backend/app/api/dependencies/<domain>.py` (flat for now) | `backend/app/core/errors.py`, `backend/app/api/errors.py` *(not created yet)* |
| **Sinapsis** | an `auth` module once Xolo lands; until then `backend/app/shared/` | `backend/app/modules/<domain>/dependencies.py` | `backend/app/shared/errors.py`, `shared/http/errors.py` *(add `NotAuthenticatedError` and `headers`)* |
| **Kalens** | provided by the host through `AppointmentsIntegration` | `src/kalens/api/dependencies/<domain>.py`, built by `build_*_dependencies` | `src/kalens/errors.py` *(not created yet)* |
| **Xolo** | `src/xolo/api/dependencies/auth.py`, built by the same factory pattern | `src/xolo/api/dependencies/<domain>.py` | `src/xolo/errors.py` *(not created yet)* |
