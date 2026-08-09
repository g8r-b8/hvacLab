"""WriteGate — the sole minter of `WriteTicket`s, and the priority array bookkeeper.

The BACnet priority array is 16 slots per commandable object. The lowest-numbered
non-null slot wins; when all are null, the object falls back to `relinquish-default`.
Conventional (not enforced) assignments:

     1  manual life safety          NEVER WRITE
     2  automatic life safety       NEVER WRITE
     3  available
     4  available
     5  critical equipment control
     6  minimum on/off
     7  available
     8  manual operator             <- the human override an operator expects
     9-16 available; 16 is the usual "lowest, safe to experiment" slot

**The core problem: there is no registry of claimants.** BACnet records that slot 8 holds
72.0. It does not record who wrote it, when, why, or whether they intend to release it.
So a contractor overrides a valve at priority 8 during commissioning in March, forgets,
and the coil runs wide open until someone notices the gas bill in November. This is
extremely common. `find_orphaned_overrides` is a genuinely valuable read-only product
feature on its own.

Physical consequences of a bad or unreleased write:

* Short-cycling a compressor — thousands of dollars of damage in hours.
* A frozen coil from an overridden valve at low outside air temp — burst tubes, flooding.
* An overridden outside air damper — ASHRAE 62.1 ventilation non-compliance, occupant
  complaints, and in some jurisdictions a code violation.
* An overridden fan in a listed smoke control sequence — see `blocklist`.

Therefore every write is: blocklist-checked, ticketed with an expiry, audited, tracked as
a claim, and required to be released.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum

from hvaclab.adapters.base import WriteResult, WriteTicket
from hvaclab.model.point import PointRef
from hvaclab.safety.blocklist import LifeSafetyBlocklist


class Priority(IntEnum):
    """BACnet write priorities, with the reserved slots named so they cannot be typo'd."""

    MANUAL_LIFE_SAFETY = 1
    AUTOMATIC_LIFE_SAFETY = 2
    AVAILABLE_3 = 3
    AVAILABLE_4 = 4
    CRITICAL_EQUIPMENT = 5
    MINIMUM_ON_OFF = 6
    AVAILABLE_7 = 7
    MANUAL_OPERATOR = 8
    AVAILABLE_9 = 9
    AVAILABLE_10 = 10
    AVAILABLE_11 = 11
    AVAILABLE_12 = 12
    AVAILABLE_13 = 13
    AVAILABLE_14 = 14
    AVAILABLE_15 = 15
    LOWEST = 16


FORBIDDEN_PRIORITIES: frozenset[int] = frozenset({1, 2})
"""Life safety slots. This system never writes them, under any configuration."""

DEFAULT_PRIORITY: int = 16
"""Default write priority: the lowest, most easily overridden by anything the BAS does."""


class ClaimState(StrEnum):
    """Lifecycle of a priority slot claim."""

    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"
    ORPHANED = "orphaned"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class GateDecision(StrEnum):
    """Why a write was allowed or refused."""

    ALLOWED = "allowed"
    BLOCKED_LIFE_SAFETY = "blockedLifeSafety"
    BLOCKED_READ_ONLY = "blockedReadOnly"
    BLOCKED_FORBIDDEN_PRIORITY = "blockedForbiddenPriority"
    BLOCKED_RANGE = "blockedRange"
    BLOCKED_RATE_LIMIT = "blockedRateLimit"
    BLOCKED_NO_AUTHORITY = "blockedNoAuthority"
    BLOCKED_EXISTING_CLAIM = "blockedExistingClaim"
    BLOCKED_NOT_COMMANDABLE = "blockedNotCommandable"


@dataclass(frozen=True, slots=True)
class Claim:
    """A tracked claim on one priority slot of one point.

    `prior_value` is captured before the write so a release can be verified — and on
    Modbus, where there is no release, so a restore is even possible.
    """

    claim_id: str
    ref: PointRef
    priority: int
    value: float | bool | int | str | None
    requester: str
    reason: str
    claimed_at: datetime
    expires_at: datetime
    state: ClaimState = ClaimState.ACTIVE
    released_at: datetime | None = None
    prior_value: float | bool | int | str | None = None
    ticket_id: str = ""


@dataclass(frozen=True, slots=True)
class PriorityArraySnapshot:
    """A read of a point's 16 slots, plus what we believe we claimed.

    The gap between `slots` (what the device reports) and `known_claims` (what we think we
    did) is the orphan signal: a non-null slot no claim of ours explains was left by
    somebody else, and a claim of ours with a null slot means our write silently failed.
    """

    ref: PointRef
    slots: tuple[float | bool | int | None, ...]
    relinquish_default: float | bool | int | None
    read_at: datetime
    known_claims: tuple[Claim, ...] = ()

    def effective_priority(self) -> int | None:
        """Lowest-numbered non-null slot, or None when all are null.

        TODO: Scan slots 1..16 and return the first non-null index.
        What's missing: nothing beyond the 1-based indexing — the array is 1-indexed in
            BACnet and 0-indexed in Python, and getting that wrong shifts every priority
            by one, which is the difference between "operator override" and "minimum
            on/off".
        Acceptance: a slot-8 claim returns 8; an all-null array returns None.
        Depends on: nothing.
        """
        raise NotImplementedError("effective priority scan not yet implemented")

    def effective_value(self) -> float | bool | int | None:
        """The value the equipment is actually acting on.

        TODO: Return the value at `effective_priority`, or `relinquish_default` when all
            slots are null.
        What's missing: nothing — but the relinquish-default fallback is the part people
            forget. Releasing every claim does not return a point to "whatever the BAS
            wants"; it returns it to a fixed configured value that may be nothing like
            the BAS's intent if the BAS was itself writing at a priority.
        Acceptance: an all-null array returns the relinquish default, not None.
        Depends on: `effective_priority`.
        """
        raise NotImplementedError("effective value resolution not yet implemented")

    def unexplained_slots(self) -> tuple[int, ...]:
        """Non-null slots not explained by any of our known claims.

        TODO: Return the indices of non-null slots with no matching ACTIVE claim.
        What's missing: nothing structurally — this is the read-only diagnostic that finds
            every forgotten override on a site, including ones left by other vendors years
            ago. It is worth shipping before any write capability exists at all.
        Acceptance: a site scan reports slot 8 overrides with no corresponding claim.
        Depends on: `Claim`.
        """
        raise NotImplementedError("unexplained slot detection not yet implemented")


class WriteGate:
    """The only object that can mint a `WriteTicket`. All writes pass through it."""

    def __init__(
        self,
        blocklist: LifeSafetyBlocklist,
        signing_key: bytes,
        read_only: bool = True,
        default_expiry: timedelta = timedelta(minutes=15),
        max_writes_per_minute: int = 10,
    ) -> None:
        """Create a gate. `read_only=True` is the day-one default and refuses all writes.

        TODO: Store the blocklist, key, and limits; initialize empty claim tracking.
        What's missing: the signing key's provenance. It must come from deployment secrets
            and never from config committed to the repo, because it is the thing that makes
            a forged ticket impossible. Consider requiring the key to be at least 32 bytes
            and refusing a default.
        Acceptance: constructing with `read_only=True` refuses every `request_write`; a
            short or empty signing key raises.
        Depends on: `safety.blocklist.LifeSafetyBlocklist`.
        """
        raise NotImplementedError("write gate construction not yet implemented")

    def request_write(
        self,
        ref: PointRef,
        value: float | bool | int | str | None,
        priority: int,
        requester: str,
        reason: str,
        expiry: timedelta | None = None,
        equip_id: str | None = None,
    ) -> tuple[WriteTicket | None, GateDecision, str]:
        """Evaluate a write request and mint a ticket, or refuse with a reason.

        TODO: Check, in order — read-only mode, forbidden priority (1, 2), blocklist,
            commandability, value range, rate limit, existing claim conflict — then mint a
            signed ticket with an expiry.
        What's missing: the ordering is the specification, not an implementation detail.
            The blocklist check must occur before anything that could be interpreted as
            partial success, `reason` must be non-empty and human-meaningful (it appears in
            the audit log an AHJ may read), and every refusal path must write to the audit
            log just as loudly as an allow.
        Acceptance: priority 1 or 2 always refuses with BLOCKED_FORBIDDEN_PRIORITY;
            read_only mode refuses everything; a blocked point refuses with
            BLOCKED_LIFE_SAFETY and an explanation naming the matrix entry; an allowed
            request returns a ticket whose signature verifies.
        Depends on: `LifeSafetyBlocklist.check`, `sign_ticket`, `audit.AuditLog.record`.
        """
        raise NotImplementedError("write authorization not yet implemented")

    def request_release(
        self,
        claim_id: str,
        requester: str,
        reason: str = "release",
    ) -> tuple[WriteTicket | None, GateDecision, str]:
        """Mint a release ticket for an existing claim.

        TODO: Look up the claim, mint a ticket with `is_release=True` at the claim's
            priority.
        What's missing: release must be permitted even in `read_only` mode and even for a
            point that has since been added to the blocklist. Refusing to release an
            existing override because the point later became blocked would strand the
            override permanently, which is worse than the write that created it. Log the
            exception loudly.
        Acceptance: releasing a claim on a now-blocklisted point succeeds and is audited
            with an explicit override note.
        Depends on: `request_write`, `Claim`.
        """
        raise NotImplementedError("release authorization not yet implemented")

    def sign_ticket(self, ticket: WriteTicket) -> str:
        """Produce the HMAC signature that proves the gate minted this ticket.

        TODO: HMAC-SHA256 over the ticket's canonical serialization with the signing key.
        What's missing: the canonical serialization must include every field an adapter
            acts on — ref, value, priority, expiry, is_release — or a field not covered by
            the signature can be tampered with after minting, which defeats the whole
            mechanism.
        Acceptance: altering any signed field invalidates the signature; the same ticket
            signs identically across processes.
        Depends on: `WriteGate.__init__`.
        """
        raise NotImplementedError("ticket signing not yet implemented")

    def verify_ticket(self, ticket: WriteTicket) -> bool:
        """Verify signature and expiry. Adapters call this before touching the wire.

        TODO: Recompute the HMAC, compare in constant time, and check `expires_at`.
        What's missing: constant-time comparison (`hmac.compare_digest`, never `==`) and a
            small clock-skew tolerance — but skew tolerance must shorten validity, never
            extend it.
        Acceptance: a forged ticket fails; an expired ticket fails; a valid ticket passes.
        Depends on: `sign_ticket`.
        """
        raise NotImplementedError("ticket verification not yet implemented")

    def record_result(self, ticket: WriteTicket, result: WriteResult) -> Claim:
        """Record a completed write or release, updating claim state.

        TODO: Create an ACTIVE claim on a successful write, mark RELEASED on a successful
            release, and FAILED on error.
        What's missing: a failed write is not necessarily a write that did not happen — a
            timeout can follow a write the device applied. Failed claims must therefore be
            tracked as *possibly active* and swept by `find_orphaned_overrides` rather than
            assumed harmless.
        Acceptance: a timeout produces a claim that the orphan sweep still checks.
        Depends on: `request_write`, `audit.AuditLog.record`.
        """
        raise NotImplementedError("claim state tracking not yet implemented")

    def active_claims(self, ref: PointRef | None = None) -> tuple[Claim, ...]:
        """Our currently active claims, optionally for one point.

        TODO: Filter tracked claims to ACTIVE, optionally by ref.
        What's missing: expiry sweep — a claim past `expires_at` should surface as EXPIRED
            and generate an automatic release attempt, because an expiry that only changes
            a label leaves the physical override in place.
        Acceptance: a claim past its expiry appears as EXPIRED and triggers a release.
        Depends on: `record_result`.
        """
        raise NotImplementedError("claim query not yet implemented")

    def expiring_soon(self, within: timedelta) -> tuple[Claim, ...]:
        """Claims about to expire, so an operator can extend or release deliberately.

        TODO: Return ACTIVE claims whose `expires_at` falls within the window.
        What's missing: nothing — but the UI consequence matters: an override that is
            about to auto-release during occupied hours should warn someone first.
        Acceptance: returns claims in ascending expiry order.
        Depends on: `active_claims`.
        """
        raise NotImplementedError("claim expiry query not yet implemented")


def find_orphaned_overrides(
    snapshots: tuple[PriorityArraySnapshot, ...],
    known_claims: tuple[Claim, ...],
    min_age: timedelta = timedelta(days=1),
) -> tuple[PriorityArraySnapshot, ...]:
    """Find points overridden with no explaining claim — the forgotten-override sweep.

    TODO: For each snapshot, report unexplained non-null slots older than `min_age`,
        ranked by likely impact.
    What's missing: the impact ranking, which is what makes the output actionable rather
        than a wall of 400 rows. Rank by equipment type and point role — an overridden
        chilled water valve or outside air damper outranks an overridden zone setpoint —
        and by how far the override sits from what the sequence would command.
        This function is READ-ONLY and is arguably the single most sellable feature in the
        product: it finds real money on almost every site, and it risks nothing.
    Acceptance: a snapshot with a slot-8 value and no matching claim is reported; one
        fully explained by active claims is not.
    Depends on: `PriorityArraySnapshot.unexplained_slots`,
        `adapters.bacnet.BACnetAdapter.read_priority_array`.
    """
    raise NotImplementedError("orphaned override detection not yet implemented")


def validate_priority(priority: int) -> None:
    """Raise unless the priority is a writable slot in 3..16.

    TODO: Reject anything outside 1..16, and reject 1 and 2 unconditionally.
    What's missing: nothing. This is four lines and it is the last defence against a
        typo'd priority landing in a life safety slot, so it must be called on every path
        that accepts a priority from outside the process — including the REST API.
    Acceptance: 1 and 2 raise `ForbiddenPriorityError`; 0 and 17 raise ValueError;
        3 through 16 pass.
    Depends on: `FORBIDDEN_PRIORITIES`.
    """
    raise NotImplementedError("priority validation not yet implemented")


class ForbiddenPriorityError(ValueError):
    """Raised on any attempt to write BACnet priority 1 or 2 (life safety slots)."""


class WriteGateError(Exception):
    """Base for gate failures."""
