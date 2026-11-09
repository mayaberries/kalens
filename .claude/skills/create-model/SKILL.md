---
name: create-model
description: Create the Pydantic models for an entity or an endpoint (XCreate, XUpdate, XInDB, XPublic, request and response bodies), with their validation, naming and exposure rules. Use when adding a table's models, a request or response body, or a validated field type, e.g. "add models for invoices", "the cancel endpoint needs a body" or "ratings must be 1 to 5", in pets-appts (Vetted), Sinapsis, Kalens or Xolo.
---

# Create a model

This file is identical in pets-appts (Vetted), Sinapsis, Kalens and Xolo. If you
change it in one repo, copy the change to the other three. The other four
skills (`create-repository`, `create-service`, `create-dependency`,
`create-route`) all pass these models between them.

A model is **a shape, and the rules that are only about that shape**. Which
model a value is tells you where it came from and where it's going:

| Model | Is | Comes from / goes to | Base |
|---|---|---|---|
| `XCreate` | what a caller supplies to create an X | request body → service | `InputModel` |
| `XUpdate` | a partial change to an X, every field optional | request body → service | `InputModel` |
| `<Action>Request` | any other request body (`AppointmentCancelRequest`, `OwnerRegistrationRequest`) | request body → service | `InputModel` |
| `XInDB` | **one row of X's table**, exactly its columns | repository → service | `CoreModel` |
| `XPublic` | what the API shows of an X, plus hydrated relations | service → response | `CoreModel` |
| `<Thing>Response` | a response that isn't an entity (`ProfileClaimTokenResponse`, `EvaluationStats`) | service → response | `CoreModel` |

No `*In`, `*Input`, `*Registration`, `*Data`, `*Out`. A reader should be able to
tell a request body from an entity from a response by its name.

## 0. Before you start

- **Model class names are OpenAPI schema names.** `docs/openapi.json`,
  Sinapsis' generated `frontend/src/lib/api/schema.d.ts` and the admin app's
  types all derive from them. Renaming a model, or changing a field's type,
  is a client-facing change, even if no route changed.
- **Existing models are not in scope.** Vetted's `*Public` models that inherit
  `*InDB`, the `str | Model` fields, `UserPublic.access_token` and
  `price: float` are published. Changing them is its own change, with the
  schema regenerated and the clients updated. In Xolo's Extraction stage
  models move verbatim.
- **Kalens' models are contract types.** Hosts subclass `AppointmentPublic`
  and `PublicAppointmentCreate` to narrow loosely typed fields back to their own
  models. A new kalens model that carries host data follows that pattern
  (step 6), and goes into `docs/integration-contract.md`.

## 1. The bases

Each codebase has one `core.py` (Sinapsis: `shared/schemas.py`). The libraries
can't import the host's, so there are four copies; keep them the same as
**Sinapsis' version**, which is the reference:

```python
class CoreModel(BaseModel):
    """Every model. Common config goes here."""


class InputModel(CoreModel):
    """Every request body. Unknown fields are a 422, not silently dropped:
    a typo'd or unsupported field must not look like it was accepted."""
    model_config = ConfigDict(extra="forbid")


class IDModelMixin(BaseModel):
    id: str


class DateTimeModelMixin(BaseModel):
    created_at: AwareDatetime
    updated_at: AwareDatetime
```

- **Add `InputModel` the first time a repo needs it**, in the same change.
- **Timestamps are required and timezone-aware.** The tables always have
  them, so a missing one is a bug to surface, not to paper over. Today's
  `DateTimeModelMixin` fills a missing value with `datetime.now()` (naive
  local time except in Sinapsis) and so can report a creation time that never
  happened. New entities use the required version; if existing models still
  need the old one, name the new mixin distinctly (`TimestampsMixin`) rather
  than changing the old one under them. Columns are `TIMESTAMPTZ`.

## 2. Entity models

```python
InvoiceNumber = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
Money = Annotated[Decimal, Field(max_digits=10, decimal_places=2, ge=0)]


class InvoiceCreate(InputModel):
    number: InvoiceNumber
    amount: Money
    notes: str | None = None
    # clinic_id is intentionally not here: it comes from the path
    # (/clinics/{clinic_id}/invoices), not from the body.


class InvoiceUpdate(InputModel):
    notes: str | None = None
    status: InvoiceStatus | None = None


class InvoiceInDB(IDModelMixin, DateTimeModelMixin, CoreModel):
    number: str
    amount: Decimal
    notes: str | None
    status: InvoiceStatus
    clinic_id: str
    voided_by: str | None   # internal: who voided it, not shown to clients


class InvoicePublic(IDModelMixin, DateTimeModelMixin, CoreModel):
    number: str
    amount: Decimal
    notes: str | None
    status: InvoiceStatus
    clinic_id: str
    clinic: ClinicPublic | None = None   # hydrated by the service
```

- **`XInDB` is exactly the table's columns**, with the table's nullability:
  required where the column is `NOT NULL`, `X | None` (no default) where it's
  nullable. No joined columns: Vetted's `OwnerProfileInDB` carries `username`
  and `email` from `users`, which belong on the `Public` the service builds.
- **`XPublic` is an allow-list.** It lists the fields it exposes and never
  inherits `XInDB`, so a column added later stays private until someone
  decides to show it. `UserPublic` (built from `UserBase`, so `password` and
  `salt` can't leak) is the model; `PetProfilePublic(PetProfileInDB)` is what
  not to copy.
- **Relations are a separate field next to the ID**: `clinic_id: str` plus
  `clinic: ClinicPublic | None`. Never one key that's sometimes an ID and
  sometimes an object (`owner_profile_id: "str | OwnerProfilePublic"`), which
  makes every client branch on its type.
- **Leave out of `XCreate` anything the server resolves** (tenant, owner,
  author, status), with a comment saying where it comes from, as
  `PetProfileCreate` does. When one surface really does take it from the
  client, that's a different model (`ClinicPetProfileCreate`).
- **`XUpdate` lists only what may change.** Immutable fields (`clinic_id`, a
  slug that keys the static sites) aren't in it, so the immutability shows in
  the schema rather than only in the repository's `UPDATE`.
- **A `XBase` is optional.** Use one only for fields with the same type and
  optionality in every model that inherits it, typically to share
  validators. If subclasses have to re-declare fields to tighten them
  (`name: str` over a Base's `name: str | None`), drop the Base and list the
  fields per model: each model should show what it requires without reading
  its parents.
- **Don't validate stored data as if it were input.** `UserInDB.password`
  carries `constr(min_length=7)` on a bcrypt hash. Input constraints go on
  input models.
- **Response-only additions are their own model.** A registration response
  that includes a token is `UserRegisteredResponse(user: UserPublic,
  access_token: AccessToken)`, not an `access_token: … | None` on every
  `UserPublic`.

## 3. Field types and validation

- **Reusable constraints are `Annotated` aliases** in the domain's models:
  `Rating = Annotated[int, Field(ge=1, le=5)]`, `Username`, `Slug`, `Money`.
  Not `constr` / `conint` / `confloat` (Pydantic v1's style).
- **Money is `Decimal`** with `max_digits`/`decimal_places`, and `NUMERIC` in
  the table, never `float`. Pydantic serialises `Decimal` as a JSON string, so
  the generated client types it as `string`; that's intended. Vetted's
  `price: float` predates this.
- **Emails are `EmailStr`, URLs `HttpUrl`, enums `str, Enum`** (`StrEnum` in
  Sinapsis), so they serialise as strings and appear as enums in the schema.
- **Validators `raise ValueError`, never `assert`.** Asserts are stripped
  under `python -O`, taking the check with them; Vetted's `validate_username`
  does this.
- **Cross-field rules are `model_validator(mode="after")`**, like the "exactly
  one of `pet_id` / `new_pet`" rule in `PublicPetInput`. Say in the error
  which fields and what's expected.
- **Normalise in `mode="before"` validators** (slugs, categories, trimming), so
  the stored value is the canonical one.
- **Time-relative checks ("in the future") go only on input models.** A
  stored appointment must still parse once its time has passed; kalens'
  `AppointmentCreate` / `AppointmentRequestIn` do this right.
- **Describe fields the client sees**: `Field(description=…, examples=[…])`
  on non-obvious request fields. It's what the OpenAPI and the generated
  client show.

## 4. What logic a model may hold

| In the model | Not in the model (→ service) |
|---|---|
| shape: types, ranges, lengths, formats | anything that needs the database |
| normalisation of its own fields | "now" as a decision (`revoked_at`, defaults) |
| cross-field rules within one model | settings or secrets |
| pure functions over its own fields (`resolve_cancellation_status`, `slugify`) | rules about other entities |

- **Models never import settings.** `models/auth/token.py` reads
  `JWT_AUDIENCE` at import, which freezes it into a default and ties the
  model layer to configuration. Pass such values in from the service.
- **A pure function that lives with a model says why there**, as
  `resolve_cancellation_status` does, and is the one place the rule exists.

## 5. Placement and naming

- **One file per entity**, in its domain: Vetted `backend/app/models/<domain>/<entity>.py`;
  Sinapsis `backend/app/modules/<domain>/schemas.py` (split into a
  `schemas/` package when it grows); Kalens and Xolo `src/<pkg>/models/<entity>.py`.
- An entity's request and response models live in the same file as the
  entity.
- **Imports at the top**, no aliases for model names (`OwnerProfilePublic as
  ProfilePublic`), modern syntax (`X | None`, `list[X]`).
- **Names are unique across the app**, since they're schema names: two
  domains can't both have a `StatusResponse`. Prefix with the entity.

## 6. Library models that carry host data

Kalens (and Xolo, for what it hands out) can't import host models. Where a
library model has a host-owned field:

- type it loosely in the library (`pet: Any`), with a comment naming which
  host model fills it and the integration field that narrows it;
- add an integration field for the host's subclass
  (`appointment_public_model`, `public_appointment_create_model`), and declare
  *that* as the route's `response_model` / body type;
- the host subclasses and narrows (`pet: PetProfilePublic | None`), in its
  one wiring module (Vetted: `app/api/scheduling.py`), and imports the
  narrowed class everywhere else, tests included.

Loose in the library, exact in the emitted schema.

## 7. Test it

- **Validation**: each constraint and validator accepts its edge values and
  rejects the next ones (rating 1 and 5 pass, 0 and 6 fail; blank name fails);
  each cross-field rule, both ways; unknown fields on an input model → error.
- **Exposure**: a `*Public` built from an `*InDB` doesn't contain the
  internal fields (`voided_by`, `password`, `salt`).
- **Schema**: after `make openapi` / `make gen-api`, the diff shows only the
  schemas you meant to add or change.

Model tests are plain unit tests (no database). Follow the repo's test-ID
convention where it has one (Sinapsis, Xolo: `XXX-NNN`).

## 8. Checklist

- [ ] Every model is one of the six roles and named for it.
- [ ] Inputs extend `InputModel` (`extra="forbid"`); server-resolved fields left out, with a comment.
- [ ] `XInDB` is exactly the table's columns and nullability; timestamps required and aware.
- [ ] `XPublic` is an allow-list, never inherits `XInDB`; relations are a separate field next to the ID.
- [ ] Constraints are `Annotated` aliases; money is `Decimal`; no `assert` in validators.
- [ ] No settings, database or "now" decisions in models.
- [ ] Names are unique; schema regenerated and the diff checked.
- [ ] Library models with host data are loose with a narrowing integration field.

## Where things go in each repo

| | Entity models | Bases | Schema regenerated by |
|---|---|---|---|
| **pets-appts (Vetted)** | `backend/app/models/<domain>/<entity>.py` | `backend/app/models/core.py` *(add `InputModel`, aware timestamps)* | `make openapi` |
| **Sinapsis** | `backend/app/modules/<domain>/schemas.py` | `backend/app/shared/schemas.py` *(the reference; add `InputModel`)* | `make gen-api` |
| **Kalens** | `src/kalens/models/<entity>.py` | `src/kalens/models/core.py` | `make compare-openapi` against its host *(pending kalens#9)* |
| **Xolo** | `src/xolo/models/<entity>.py` | `src/xolo/models/core.py` | as Kalens |
