"""UL 864 / UUKL life safety blocklist. Deny by default.

Smoke control equipment in a commercial building is listed under **UL 864, category
UUKL**, and the listing is *as-configured*. The sequence, the devices, the wiring, and
the programming were evaluated as a unit and accepted by the Authority Having
Jurisdiction. Writing to a point that participates in that sequence — even a value that
seems harmless, even at a low priority, even briefly — modifies a listed system.

Consequences, in ascending order of unpleasantness:

* The listing is void. The building's smoke control system is now unlisted.
* The AHJ can red-tag the system, and in some jurisdictions the building.
* The insurer can deny a claim on the basis that a listed life-safety system was
  modified without re-listing.
* If a fire occurs and smoke control does not perform, the exposure is criminal, not
  merely civil.

Therefore this module is **deny-by-default**: a point whose UUKL status we do not know is
blocked. That will block some points that were never life safety, and operators will be
annoyed. That is the correct trade — the cost of a false block is a support ticket; the
cost of a false allow is unbounded.

The blocklist is seeded from the project's **smoke control sequence matrix**, the drawing
that lists every device participating in every smoke control mode. That document is the
authority. Heuristics may only ADD to the blocklist, never remove from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from hvaclab.model.point import PointRef


class BlockScope(StrEnum):
    """Granularity at which a block is asserted. Broader scopes win."""

    DEVICE = "device"
    EQUIP = "equip"
    POINT = "point"
    OBJECT_TYPE = "objectType"
    SITE = "site"


class BlockReason(StrEnum):
    """Why an entity is blocked — carried into the audit log and the operator message."""

    UUKL_LISTED = "uuklListed"
    SMOKE_CONTROL_MATRIX = "smokeControlMatrix"
    FIRE_ALARM_INTERFACE = "fireAlarmInterface"
    STAIRWELL_PRESSURIZATION = "stairwellPressurization"
    SMOKE_DAMPER = "smokeDamper"
    ELEVATOR_RECALL = "elevatorRecall"
    EMERGENCY_POWER = "emergencyPower"
    UNKNOWN_PROVENANCE = "unknownProvenance"
    OPERATOR_ASSERTED = "operatorAsserted"
    ADJACENT_TO_LISTED = "adjacentToListed"


class Decision(StrEnum):
    """Outcome of a blocklist check. There is no MAYBE — unknown resolves to BLOCK."""

    ALLOW = "allow"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class BlockEntry:
    """One assertion that something must never be written.

    `source_document` and `asserted_by` are not bureaucracy. When an AHJ or an insurer
    asks why a system did or did not touch a listed point, this record is the answer.
    """

    scope: BlockScope
    identifier: str
    reason: BlockReason
    source_document: str = ""
    asserted_by: str = ""
    asserted_at: datetime | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class BlockCheck:
    """Result of a check, with the reasoning preserved for the audit log."""

    decision: Decision
    ref: PointRef
    matched_entries: tuple[BlockEntry, ...] = ()
    explanation: str = ""


class LifeSafetyBlocklist:
    """Deny-by-default gate over every writable point in the system."""

    def __init__(
        self,
        entries: tuple[BlockEntry, ...] = (),
        allow_unknown: bool = False,
    ) -> None:
        """Build a blocklist. `allow_unknown` defaults to False and should stay False.

        TODO: Index entries by scope and identifier for O(1) lookup.
        What's missing: `allow_unknown` exists only so a fully-surveyed site with a
            complete point inventory can opt in after review. It must be logged loudly at
            construction, must be recorded in the audit log for every subsequent decision,
            and must not be settable from an API request — only from deployment config.
            Consider requiring an explicit signed attestation object rather than a bool.
        Acceptance: `LifeSafetyBlocklist()` with no arguments blocks every ref;
            constructing with `allow_unknown=True` emits a warning.
        Depends on: `BlockEntry`.
        """
        raise NotImplementedError("blocklist index not yet built")

    def check(self, ref: PointRef, equip_id: str | None = None) -> BlockCheck:
        """Decide whether a point may be written. Unknown resolves to BLOCK.

        TODO: Test the ref against SITE, DEVICE, EQUIP, OBJECT_TYPE and POINT scoped
            entries in that order; if nothing matched and the ref is not in the known-safe
            inventory, return BLOCK with UNKNOWN_PROVENANCE.
        What's missing: the known-safe inventory concept. ALLOW requires positive evidence
            that the point was surveyed and is not on the matrix — absence of a block entry
            is NOT evidence. This inversion is the entire safety property of the module and
            is the easiest thing in the codebase to accidentally get backwards.
        Acceptance: an empty blocklist blocks every ref with UNKNOWN_PROVENANCE; a
            device-scoped block blocks every point on that device; the explanation names
            the matched entry.
        Depends on: `LifeSafetyBlocklist.__init__`.
        """
        raise NotImplementedError("deny-by-default check not yet implemented")

    def is_blocked(self, ref: PointRef, equip_id: str | None = None) -> bool:
        """Convenience predicate over `check`.

        TODO: Return `check(...).decision is Decision.BLOCK`.
        What's missing: nothing — but callers that need to explain themselves to an
            operator should use `check` so the reason survives.
        Acceptance: agrees with `check` for all inputs.
        Depends on: `check`.
        """
        raise NotImplementedError("blocklist predicate not yet implemented")

    def add(self, entry: BlockEntry) -> LifeSafetyBlocklist:
        """Return a new blocklist with an additional entry. Never removes.

        TODO: Return a new instance with the entry indexed.
        What's missing: nothing structural — but note the deliberate asymmetry. There is
            an `add` and there is no `remove`. Un-blocking must go through
            `load_from_matrix` with a revised source document, so that every relaxation is
            traceable to a document and a person rather than to a runtime call.
        Acceptance: the original instance is unchanged; the new one blocks the added
            identifier.
        Depends on: `LifeSafetyBlocklist.__init__`.
        """
        raise NotImplementedError("immutable blocklist extension not yet implemented")

    def entries_for(self, ref: PointRef) -> tuple[BlockEntry, ...]:
        """All entries that match a ref, for operator display.

        TODO: Return every matching entry across all scopes.
        What's missing: nothing.
        Acceptance: a point blocked at both device and point scope returns both entries.
        Depends on: `check`.
        """
        raise NotImplementedError("blocklist entry lookup not yet implemented")

    def coverage_report(self, all_refs: tuple[PointRef, ...]) -> dict[str, int]:
        """Counts of blocked / allowed / unknown across an inventory.

        TODO: Tally decisions and reasons across every ref.
        What's missing: this report is the operator-facing artifact that makes
            deny-by-default tolerable. It says "3,847 points, 122 blocked by matrix,
            3,201 surveyed safe, 524 unknown — here is the list of 524 to survey", which
            turns a blanket denial into a finite work item.
        Acceptance: counts sum to the inventory size; a fresh site reports everything as
            unknown.
        Depends on: `check`.
        """
        raise NotImplementedError("blocklist coverage report not yet implemented")


def load_from_matrix(path: Path) -> tuple[BlockEntry, ...]:
    """Load block entries from a smoke control sequence matrix export.

    TODO: Parse the matrix (CSV/JSON export of the drawing) into `BlockEntry` objects,
        one per participating device/point, stamped with the source document and date.
    What's missing: the input format, and a hard stance on partial parses. If any row of
        the matrix fails to resolve to a device or point, the load must FAIL rather than
        import the rows that worked — a partially loaded life safety blocklist is more
        dangerous than none, because it looks loaded.
    Acceptance: a valid matrix yields one entry per participating device; a matrix with
        one unresolvable row raises and imports nothing.
    Depends on: `BlockEntry`, `store.tagstore`.
    """
    raise NotImplementedError("smoke control matrix parser not yet implemented")


def heuristic_candidates(
    refs: tuple[PointRef, ...],
    names: dict[str, str],
) -> tuple[BlockEntry, ...]:
    """Propose additional blocks from naming patterns. May only ADD, never allow.

    TODO: Flag names containing smoke, fire, FSD, damper-with-fire context, stair press,
        elevator recall, purge, exhaust-fan-with-smoke-mode, duct detector, and similar.
    What's missing: an explicit statement of the asymmetry, enforced in code review: this
        function's output is unioned into the blocklist and its silence means nothing. A
        point this heuristic does not flag is not thereby safe — it is merely still
        unknown, and `check` will block it anyway.
    Acceptance: "SMOKE-DPR-CMD" and "STAIR-PRESS-FAN-C" are flagged; the function never
        returns a decision to allow anything.
    Depends on: `BlockEntry`, `semantic.tags.LIFE_SAFETY_MARKER`.
    """
    raise NotImplementedError("life safety naming heuristics not yet implemented")


def assert_read_only_mode(refs: tuple[PointRef, ...]) -> None:
    """Assert the process is in day-one read-only mode; raise if any write path is armed.

    TODO: Verify that no adapter has writes enabled and that no `WriteGate` is armed.
    What's missing: the wiring. This is a belt-and-braces startup check for phase 1-4,
        so that an accidentally-enabled write path fails at boot in a loud, obvious place
        rather than silently at 2am on a Sunday.
    Acceptance: raises `LifeSafetyViolation` when any adapter reports `read_only=False`.
    Depends on: `adapters.base.HVACAdapter`.
    """
    raise NotImplementedError("read-only mode assertion not yet implemented")


class LifeSafetyViolation(Exception):
    """Raised when an operation would touch a UUKL-listed or unknown-provenance point."""
