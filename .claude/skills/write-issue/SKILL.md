---
name: write-issue
description: How to write GitHub issues for kalens concisely. Use whenever drafting, opening, or editing an issue for this repo or for pets-appts.
---

# Writing issues

The reader is a teammate who will act on the issue. Give them what they need to act and nothing else. Build every claim on what is actually in the repo, not on memory.

## Before writing

- Read the code, docs and open issues the issue touches. Name files, classes, query constants and route `name=` values by their real names (`CHECK_OVERLAPPING_CONFIRMED_APPOINTMENT_QUERY`, `appointments:create-appointment`).
- Issues go to `mayaberries/kalens` (this repo's `origin`). Run `gh repo view --json nameWithOwner` if unsure which repo `gh` will target.
- Check existing titles and labels (`gh issue list --state all`, `gh label list`) and reuse them. If no fitting label exists, ask before creating one.
- Write dates as absolute dates (2026-09-11), never relative ones.

## Title

`Area · what needs to happen`. Reuse prefixes already in use. Until there are some, use one area per part of the library:

- **`Contract ·`**: `AppointmentsIntegration`, `configure()`, injected models.
- **`Appointments ·`**, **`Booking ·`**, **`Availability ·`**: the three API surfaces and their repositories.
- **`Migrations ·`**: the library's own Alembic chain.
- **`Limiter ·`**, **`Docs ·`**, **`Tests ·`**, **`CI ·`**: as named.

For a generalisation from `docs/adapting.md`, name the seam (subject, provider scope, duration, booking authority), not the domain that needs it.

## Body

1. **Opening paragraph (2–3 sentences):** what's wrong or missing, and what the issue covers. If the examples come from one place, name it here.
2. **One `##` section per deliverable**, numbered when there are several. Split a section into `###` subsections only when the request itself lists sub-topics.
3. **Each section or subsection gets at most one paragraph and one bullet list:**
   - The paragraph gives the rule or the reason, stated once.
   - The bullets are concrete: a file, a name or a case, plus a short clause saying why.
   - Bold the lead-in of a bullet when the list works like a lookup table (marker → when to use it).
4. **Code examples only when they settle a question the prose can't.** Take them from real code in the repo, trimmed to 3–8 lines with `...`. Never invent an API.
5. **`## Done when`** is a checklist of verifiable outcomes, one per deliverable. Prefer outcomes a command proves: a named test passes, `make verify` is green, `make compare-schema` still reports identical (or the issue says why it shouldn't).

## What a kalens issue must say

- **Whether it breaks verbatim.** The library is copied unchanged from pets-appts. If the change alters copied behaviour or names, say so, and say whether pets-appts needs the same change or will drift on purpose.
- **Whether it touches the contract.** If yes, list all three places that change together: `integration.py`, `docs/integration-contract.md`, `tests/_host/`.
- **Whether it needs a migration.** If yes, the new revision goes in `src/kalens/migrations/versions/` and is written by hand (there's no autogenerate). New appointment columns also go in `APPOINTMENT_COLUMNS`.
- **Whether it changes intended behaviour.** For example: overlap is checked only against confirmed appointments, and some lookups return 404 instead of 403. Changing one of those is a decision, not a bug fix, so the issue has to say so (see `CLAUDE.md`).

## Style

- Lead with the rule, then the reason ("Scope overlap to the practitioner, not `clinic_id`, because a two-vet clinic is otherwise blocked by one confirmed booking").
- Drop anything that doesn't help someone act: no history, no "this issue aims to", no closing summary.
- Cite the source of truth instead of repeating it: `CLAUDE.md`, `docs/integration-contract.md`, `docs/migrations.md`, `docs/adapting.md`, or the module docstring.

## Mechanics

- Write the body to a file in the scratchpad and pass it with `gh issue create --title … --label … --body-file …`. Don't use a heredoc, because it mangles backticks.
- If the fix belongs in `../pets-appts` (or another upstream repo), open an **issue there, not a PR**: a feature request for them to review first.
- After opening it, reply with the URL and a few lines on the choices you made. Don't paste the body back.
