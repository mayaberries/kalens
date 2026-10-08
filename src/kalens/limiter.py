"""
Rate limiting for the public booking surface and the availability endpoints.

Copied from pets-appts `app/core/limiter.py`. The only structural change is
that the storage, strategy and parsed limits are built lazily on first use
instead of at import time -- the host's values arrive with `configure()`, which
necessarily runs after this module is imported. Everything downstream of
`_state()` is the original code, comments included.
"""
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Path, Request, status
from limits import RateLimitItem, parse
from limits.storage import MemoryStorage, Storage, storage_from_string
from limits.strategies import MovingWindowRateLimiter

from kalens.integration import get_settings


def _build_storage(redis_url: Optional[str]) -> Storage:
    if redis_url:
        return storage_from_string(redis_url)
    return MemoryStorage()


@dataclass
class _LimiterState:
    storage: Storage
    strategy: MovingWindowRateLimiter
    key_limit: RateLimitItem
    ip_limit: RateLimitItem
    clinic_availability_read_limit: RateLimitItem
    clinic_availability_write_limit: RateLimitItem


_state_instance: Optional[_LimiterState] = None


def _state() -> _LimiterState:
    # One shared storage + strategy. The two tiers stay independent because
    # each hit() call below is namespaced under a different first identifier
    # ("clinic-key" vs "ip"), so they land in different buckets even though
    # they share one backend -- no need for two separate storage instances.
    global _state_instance
    if _state_instance is None:
        settings = get_settings()
        storage = _build_storage(settings.redis_url)
        _state_instance = _LimiterState(
            storage=storage,
            strategy=MovingWindowRateLimiter(storage),
            key_limit=parse(f"{settings.public_rate_limit_per_key}/minute"),
            ip_limit=parse(f"{settings.public_rate_limit_per_ip}/minute"),
            clinic_availability_read_limit=parse(
                f"{settings.clinic_availability_read_rate_limit_per_clinic}/minute"
            ),
            clinic_availability_write_limit=parse(
                f"{settings.clinic_availability_write_rate_limit_per_clinic}/minute"
            ),
        )
    return _state_instance


def get_client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def get_clinic_key_from_request(request: Request) -> str:
    """
    Falls back to `anon:<ip>` if the header is missing/empty rather than
    raising here -- get_clinic_from_public_key (the host's public_auth) is
    what actually rejects a missing/bad key with a 401. This just makes sure
    that rejection path still consumes a bucket instead of being an
    unlimited way to hammer the DB lookup.
    """
    key = request.headers.get("X-Clinic-Key")
    return key if key else f"anon:{get_client_ip(request)}"


def enforce_public_rate_limits(request: Request) -> None:
    """
    Single dependency covering both tiers for the public booking surface.
    Mount once as a router-level dependency (see routes/public_booking.py)
    rather than per-route, and rather than stacking multiple decorators.

    Primary limiter: generous, scoped to one clinic's key -- the expected
    traffic shape (many end users booking through one embedded widget).

    Backstop limiter: much looser, scoped to the caller's IP regardless of
    which (or whether a valid) key it sent -- exists specifically to slow
    down someone enumerating pk_live_/pk_test_ values, which the per-key
    limiter alone can't catch since each guessed key starts its own fresh
    bucket. Deliberately kept well above the per-key limit (see
    kalens/settings.py) so it never binds during ordinary single-key
    traffic.
    """
    state = _state()
    clinic_key = get_clinic_key_from_request(request)
    client_ip = get_client_ip(request)

    if not state.strategy.hit(state.key_limit, "clinic-key", clinic_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for this clinic key. Please slow down.",
        )

    if not state.strategy.hit(state.ip_limit, "ip", client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for this IP address. Please slow down.",
        )


def _enforce_clinic_availability_limit(request: Request, clinic_id: str, limit: RateLimitItem, bucket: str) -> None:
    state = _state()
    if not state.strategy.hit(limit, bucket, clinic_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for this clinic's availability endpoint. Please slow down.",
        )
    # Shared IP backstop across the whole API, GET and PUT and the public
    # surface alike -- deliberately the one bucket that IS shared, since
    # its job is "stop one IP hammering anything," not per-resource budget.
    if not state.strategy.hit(state.ip_limit, "ip", get_client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for this IP address. Please slow down.",
        )


def enforce_clinic_availability_read_rate_limits(request: Request, clinic_id: str = Path(...)) -> None:
    """GET /clinics/{clinic_id}/availability -- unauthenticated, so
    clinic_id from the path is the only identity there is to key on."""
    _enforce_clinic_availability_limit(
        request, clinic_id, _state().clinic_availability_read_limit, "clinic-availability-read"
    )


# TODO(rate-limit): the write-side limiter is keyed on clinic_id (from the
# path), not on the authenticated caller -- so an unauthenticated request
# with a guessed/known clinic_id still consumes write budget even though
# check_clinic_modification_permissions will 403 it right after. A flood of
# such requests could still exhaust the real admin's write budget before
# the 403 ever gets checked. Fix: key this limiter on current_user.id
# instead, since PUT is JWT-authed anyway -- add
# current_user = Depends(integration.get_current_active_user) to this
# function's signature and hit the bucket with current_user.id.
def enforce_clinic_availability_write_rate_limits(request: Request, clinic_id: str = Path(...)) -> None:
    """PUT /clinics/{clinic_id}/availability -- separate bucket from the
    read tier on purpose, see kalens/settings.py, so public read traffic
    can never exhaust the clinic admin's own write budget."""
    _enforce_clinic_availability_limit(
        request, clinic_id, _state().clinic_availability_write_limit, "clinic-availability-write"
    )


def reset_public_rate_limits() -> None:
    """Test-only helper -- see tests/_fixtures/rate_limit.py.

    Also drops the cached state, so a test that rebuilds the integration with
    different limits gets them rather than the first test's parsed values.
    """
    global _state_instance
    if _state_instance is not None:
        _state_instance.storage.reset()
    _state_instance = None
