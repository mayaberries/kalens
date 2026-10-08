"""
Prove the library serves the same API surface pets-appts does.

Compares the reference host's generated OpenAPI against the appointment,
public-booking and availability slice of `pets-appts/docs/openapi.json`:
every path, method, operation id and declared response status.

What this does NOT compare is the response *schemas*. The reference host's
`PetProfilePublic` is a four-field stand-in, not pets-appts' real one, so the
bodies legitimately differ -- that is the whole point of the models being
injected. The routing suite covers the part that matters there: that the
injected model is the one the schema names.

    make compare-openapi
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._host.app import build_app  # noqa: E402

PETS_OPENAPI = Path(
    os.environ.get(
        "PETS_APPTS_OPENAPI",
        Path(__file__).resolve().parents[2] / "pets-appts" / "docs" / "openapi.json",
    )
)

# The library's slice of the host's surface. Everything else in that file --
# auth, clinics, services, profiles, evaluations, feed -- stays with the host.
OWNED_PREFIXES = (
    "/api/services/{service_id}/appointments",
    "/api/public/",
    "/api/clinics/{clinic_id}/availability",
)
# Evaluations nest *under* an appointment path but did not move.
EXCLUDED = ("evaluation",)


def owned(path: str) -> bool:
    if any(fragment in path for fragment in EXCLUDED):
        return False
    return any(path.startswith(prefix) for prefix in OWNED_PREFIXES)


def operations(spec: dict) -> dict:
    out = {}
    for path, methods in spec.get("paths", {}).items():
        if not owned(path):
            continue
        for method, op in methods.items():
            out[(method.upper(), path)] = {
                "operationId": op.get("operationId"),
                "responses": sorted(op.get("responses", {})),
            }
    return out


def main() -> int:
    if not PETS_OPENAPI.exists():
        raise SystemExit(f"pets-appts openapi.json not found at {PETS_OPENAPI}")

    reference = operations(json.loads(PETS_OPENAPI.read_text()))
    app, _ = build_app("postgresql://unused/unused")   # never connected; only the spec is read
    library = operations(app.openapi())

    print(f"pets-appts : {len(reference)} operations in the extracted slice")
    print(f"kalens : {len(library)} operations")

    failures = 0
    for key in sorted(set(reference) | set(library)):
        method, path = key
        if key not in library:
            print(f"  MISSING    {method:<6} {path}")
            failures += 1
            continue
        if key not in reference:
            print(f"  EXTRA      {method:<6} {path}")
            failures += 1
            continue
        ref, lib = reference[key], library[key]
        notes = []
        if ref["operationId"] != lib["operationId"]:
            notes.append(f"operationId {ref['operationId']} != {lib['operationId']}")
        if ref["responses"] != lib["responses"]:
            notes.append(f"responses {ref['responses']} != {lib['responses']}")
        if notes:
            print(f"  DIFFERS    {method:<6} {path}: {'; '.join(notes)}")
            failures += 1
        else:
            print(f"  ok         {method:<6} {path}")

    print("\nSURFACE MATCHES" if not failures else f"\n{failures} operation(s) differ")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
