# Adapting kalens to your domain

The extraction was verbatim. Nothing was generalised on the way out, so the
code still reads like a veterinary clinic: the appointment's subject column is
literally `pet_id`, and double-booking is scoped to a `clinic_id`. None of
that is load-bearing — but knowing *which* parts are vocabulary and which are
actual assumptions is the difference between a rename and a rewrite.

This page is that map. It is documentation, not a plan of record: no code
changes described here have been made.

---

## The four seams

Everything domain-specific in this library reduces to four bindings. Find
these and you have found all of it.

| Seam | Bound to today | What it answers |
|---|---|---|
| **Subject** | `appointments.pet_id` → `pet_profiles.id`, `NOT NULL`, `ON DELETE RESTRICT` | *Who or what is the appointment for?* |
| **Provider scope** | `services.clinic_id`, reached by a JOIN in `CHECK_OVERLAPPING_CONFIRMED_APPOINTMENT_QUERY` | *Whose calendar can't be double-booked?* |
| **Duration** | `service.duration_minutes`, falling back to 30 | *How long is a slot?* |
| **Booking authority** | `owner_profile_id`, compared in `check_appointment_create_permissions` | *Who may book on the subject's behalf?* |

Two of these are pure vocabulary. Two are real assumptions. The rest of this
page is about telling them apart.

---

## Tier 1 — pets: the reference implementation

This is what ships, and what the reference host in `tests/_host/` reproduces.

**Subject.** Every appointment carries a pet. Not "optionally a pet" — the
column is `NOT NULL`, because a veterinary booking without an animal is
meaningless. Ownership is indirect: a pet belongs to an *owner profile*, not
to a user, which is what lets a guest with no account still have pets. The
`RESTRICT` delete rule blocks deleting a pet that has appointment history;
`b94eca323053` carries a TODO wondering whether soft delete would have been
better, and that question is still open.

**Provider scope.** A clinic is the unit that can't be double-booked. Confirming
checks for overlapping *confirmed* appointments across **all** of that
clinic's services — so a clinic can't accept a dental cleaning and a wellness
exam at the same instant, regardless of who would perform them.

**Duration.** Comes off the service. `end_time` is computed at insert and
stored, never derived at read time, so changing a service's duration doesn't
retroactively move existing appointments.

**Booking authority.** You may book for a subject whose `owner_profile_id`
matches your own profile's id. A mismatch returns **404, not 403** —
deliberately, so a caller can't probe which pet ids exist.

**Two behaviours that look like bugs and aren't.** Overlap is only checked
against `confirmed` rows, so two people *can* both successfully request the
same slot; confirming one resolves it. And confirming one does not auto-decline
the others. Both are explicit decisions for manual review at low volume, both
are pinned by tests here, and both should be revisited before real traffic.

---

## Tier 2 — humans: health appointments

Most of this has already been done once, in the `human-appts` fork. Treat that
repo as the worked example rather than starting from this page.

### The rename, which is the easy part

`pet_id` → `patient_profile_id`, throughout: the column, the FK target
(`patient_profiles`), the models, the `APPOINTMENT_COLUMNS` list, the
`PublicPetInput` XOR wrapper, the `/public/pets` route and its name
(`public-booking:list-pets`), the `subject_repository` method names, and the
error string `"No pet found with that id."`.

The shape is unchanged. Everything the pets version assumes about a subject —
that there is exactly one, that it belongs to an owner rather than to a user,
that it can't be deleted while history exists — is true of patients too.

### What health actually adds

**A clinician on the appointment.** In pets, an appointment names the client,
the pet and the service, but *nobody on the clinic side*. "Connect the patient
and the doctor" cannot be expressed. `human-appts` adds a nullable
`assigned_staff_user_id`:

- `ON DELETE SET NULL`, matching the reasoning already used for
  `cancelled_by`: deleting a clinician's account must not delete a patient's
  appointment history, nor be blocked by it.
- Unassigned is the ordinary resting state, so no backfill is needed.
- Claiming a seat puts the `NULL` check **inside the UPDATE**, so two
  clinicians opening the same consultation at the same instant resolve
  deterministically; the loser gets `None` back, not an exception. Takeover is
  a separate query constant, so overriding a colleague can never be the silent
  outcome of a race — only an explicit request.
- Eligibility keys on clinic membership, not on the admin/aux role, which is
  what makes a clinic owner eligible as a practising specialist. Role enters
  only at takeover.

**A deliberately narrowed disclosure.** `AppointmentPublic` is readable by the
booking client, so hydrating the clinician with a full `UserPublic` would hand
patients their doctor's email, clinic id and profile. `human-appts` adds a
purpose-built `AssignedStaffPublic` carrying only `id` and `username`, with a
test asserting the email does not ride along. **This is the pattern to copy
whenever you widen a response model in a health context**, and it generalises:
this library's injected `appointment_public_model` is exactly where you'd
enforce it.

**Telehealth.** Rooms key on `appointment.id` directly — the surrogate UUID PK
is globally unique, so a room does not need to nest under `service_id`. The
signalling server is a relay only and never touches media.

### Merge debt, in both directions

The fork is older than this extraction in some places and newer in others.
`human-appts` does **not** have `cancellation_reason`, `cancelled_by`, or
`resolve_cancellation_status` — so it has no `declined` distinction and no
record of who cancelled or why. Those come from this library. Going the other
way, `assigned_staff_user_id` and calls exist only in the fork. Adopting
`appts_core` in `human-appts` means taking the cancellation work and
re-applying the staff-assignment work on top.

### What this library does not give you for health

Named plainly, because "it's for health care" is not a property of the code:

- **No audit log.** Nothing records who read an appointment. Every lifecycle
  transition is a plain synchronous `UPDATE` with no event emitted — there is
  no hook to attach one to.
- **No encryption at rest** beyond whatever Postgres is configured with, and
  no field-level encryption for anything.
- **`pk_test_` keys write real data.** The `live`/`test` distinction on
  publishable keys is currently cosmetic; both hit the same tables. The
  `TODO(env-scoping)` in pets-appts' `public_auth.py` says so. Do not hand a
  test key to a third party expecting a sandbox.
- **No notifications of any kind.** No email, push, webhook or queue anywhere
  in the extracted code. A cancelled consultation tells nobody.
- **Rate-limit storage is in-process** unless `redis_url` is set — fine for
  one worker, wrong for several, and the availability write limiter is keyed
  on the path's `clinic_id` rather than the authenticated caller (its own TODO
  explains the exposure).

---

## Tier 3 — everyone else: a tailor, a spa

Two domains that share nothing with a clinic except the shape of a calendar.
They're worth thinking about because between them they hit both of the seams
that are *not* just vocabulary.

### A tailor: there is no subject

A fitting is for the customer. The garment isn't a party to the appointment —
it doesn't get booked, doesn't have an owner distinct from the customer, and
often doesn't exist yet at booking time.

**`pet_id NOT NULL` is the blocker, and it is the single biggest change on
this page.** Renaming it doesn't help; a tailor has nothing to put in it. What
has to happen:

- the column becomes nullable, in the migration and in `AppointmentInDB` /
  `AppointmentCreate` (which currently re-declare it as required `str`);
- `check_appointment_create_permissions` must skip the ownership check when no
  subject is given, rather than 404;
- `populate_appointment` must skip the subject fetch;
- `PublicPetInput`'s XOR validator has to allow a third state — neither.

Everything else a tailor needs already works. "Service" maps cleanly onto
*hem, fitting, alteration*, and `duration_minutes` is exactly right. One
tailor is one tenant, so scoping overlap to the tenant is correct.

### A spa: the tenant is the wrong scope

A spa has four therapists and three rooms. Two clients at 3pm is normal
business, not a conflict.

But the overlap query scopes to `clinic_id`:

```sql
INNER JOIN services s ON a.service_id = s.id
WHERE s.clinic_id = :clinic_id
  AND a.status = 'confirmed'
  AND a.start_time < :end_time AND a.end_time > :start_time
```

So confirming one 3pm massage blocks every other 3pm booking at that spa.
**This query is the one place the library is genuinely not general**, and the
failure is silent: no error, just a spa that can serve one client at a time.

The fix is to make the scoping key a parameter of the integration rather than
a column name — "the id of the thing that can only be in one place at once."
For a clinic that's the clinic. For a spa it's the therapist or the room. For
a hair salon it's the chair. Note that `human-appts`' `assigned_staff_user_id`
is already *most* of the mechanism: once appointments name a practitioner,
scoping overlap to that practitioner is a small change to one query — and it
would fix pets too, where a clinic with two vets has the same over-blocking
problem nobody has hit yet.

A spa also wants **buffer time** between bookings (clean-down, turnaround),
which nothing here models — `end_time` is `start_time + duration`, full stop.

### What neither of them wants

- **Veterinary service categories.** `wellness_exam`, `spay_neuter`,
  `end_of_life` and friends live in the host's `services` table, not here, so
  this one costs nothing — the library never reads `category`.
- **Evaluations as the completion trigger.** Leaving a review is currently the
  only thing that marks an appointment `completed`. A spa that doesn't collect
  reviews has appointments that stay `confirmed` forever, years past their
  end time. This is a known gap in pets-appts too.
- **`RESTRICT` on subject deletion.** A business that deletes customer records
  on request — which, in several jurisdictions, is not optional — will find
  those deletes blocked by appointment history.

---

## What to generalise first

Ranked by how much it unblocks, not by effort:

1. **Make `pet_id` nullable and rename it `subject_id`.** Blocks the entire
   class of domains where the appointment is for the customer directly. Touches
   one migration, three model classes, one permission check and
   `populate_appointment`. Everything else on this list is optional; this one
   isn't.
2. **Parameterise the overlap scoping key.** Currently silently wrong for any
   tenant with more than one practitioner or room — which includes most
   two-vet clinics, not just spas. `human-appts`' `assigned_staff_user_id` is
   the natural key.
3. **Give completion its own trigger.** Decouple it from evaluations so an
   appointment can complete because its `end_time` passed, not because someone
   left a review.
4. **Emit lifecycle events.** One hook on create/confirm/cancel/complete would
   cover notifications, audit logging and telehealth-room provisioning at once
   — three separate gaps with one shape.
5. **Wire availability into the overlap check.** Weekly hours and booking
   conflicts are still two unrelated systems: you can confirm an appointment
   for 3am on a Sunday and nothing objects. This is the least urgent because
   nothing today depends on it, and the most interesting because it's the
   feature everyone assumes already exists.

Items 1 and 2 are the ones that make this a general scheduling engine. Until
then it is pets-appts' scheduler with the imports moved — which is exactly what it
was asked to be, and worth being clear-eyed about.
