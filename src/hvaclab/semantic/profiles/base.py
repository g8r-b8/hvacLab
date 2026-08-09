"""Tagging profile interface, confidence-scored candidates, and the review queue.

Design stance: a profile never *decides*. It proposes `TagCandidate`s with calibrated
confidence, and an explicit policy decides what auto-applies, what goes to review, and
what is dropped. Two reasons this matters:

1. Auto-applying a 55%-confidence guess produces a tag store that looks complete and is
   quietly wrong — far worse than one that is visibly 78% complete.
2. Human corrections in the review queue are training data. Persisted as overrides they
   improve the next site with the same integrator's naming conventions, which is where
   real coverage gains come from — not from more regexes.

Confidence bands (proposed; calibrate against the fixtures in phase 4):

    >= 0.90   auto-apply
    0.60-0.89 auto-apply, flagged for spot-check
    0.30-0.59 review queue
    <  0.30   review queue, unranked
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from hvaclab.model.equip import EquipType
from hvaclab.model.point import PointKind, PointRef, Volatility
from hvaclab.model.units import Unit
from hvaclab.semantic.tags import TagSet


class MatchSource(StrEnum):
    """Where a candidate's evidence came from — drives confidence weighting."""

    OBJECT_NAME = "objectName"
    DESCRIPTION = "description"
    OBJECT_TYPE = "objectType"
    UNITS = "units"
    EQUIP_CONTEXT = "equipContext"
    DEVICE_NAME = "deviceName"
    STATE_TEXT = "stateText"
    VALUE_RANGE = "valueRange"
    USER_OVERRIDE = "userOverride"
    PRIOR_SITE = "priorSite"


class ReviewStatus(StrEnum):
    """Lifecycle of a review queue item."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    CORRECTED = "corrected"
    REJECTED = "rejected"
    DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class DiscoveredObject:
    """A raw object as an adapter found it, before any semantics are applied.

    This is the profile's sole input. It intentionally contains no interpreted fields —
    interpretation is the profile's job and must be auditable back to these raw values.
    """

    ref: PointRef
    object_name: str
    description: str = ""
    object_type: str = ""
    units_enum: int | None = None
    units_text: str | None = None
    device_name: str = ""
    device_model: str = ""
    device_vendor_id: int | None = None
    state_text: tuple[str, ...] = ()
    present_value: Any = None
    min_present_value: float | None = None
    max_present_value: float | None = None
    is_commandable: bool = False
    raw_properties: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class TagCandidate:
    """A proposed tagging of one discovered object, with its evidence.

    `evidence` is not decoration — it is what a reviewer reads to decide in two seconds
    instead of two minutes, and what makes a systematically wrong heuristic findable.
    """

    ref: PointRef
    tags: TagSet
    confidence: float
    sources: tuple[MatchSource, ...]
    evidence: tuple[str, ...] = ()
    proposed_kind: PointKind | None = None
    proposed_unit: Unit | None = None
    proposed_volatility: Volatility | None = None
    proposed_equip_type: EquipType | None = None
    proposed_equip_id: str | None = None
    profile_name: str = ""

    def is_auto_applicable(self, threshold: float = 0.6) -> bool:
        """Whether this candidate may be applied without human review.

        TODO: Compare confidence against the threshold, with hard overrides.
        What's missing: the overrides, which are the whole point. A candidate carrying
            the `lifeSafety` marker is NEVER auto-applicable regardless of confidence —
            life safety status is asserted from the smoke control matrix, never inferred.
            Conversely a USER_OVERRIDE source is always applicable at any confidence.
        Acceptance: confidence 0.95 with a lifeSafety tag returns False; confidence 0.1
            with source USER_OVERRIDE returns True.
        Depends on: `semantic.tags.LIFE_SAFETY_MARKER`.
        """
        raise NotImplementedError("auto-apply policy not yet implemented")


@dataclass(frozen=True, slots=True)
class ProfileMatch:
    """Result of running a profile over a device's objects."""

    profile_name: str
    candidates: tuple[TagCandidate, ...] = ()
    unmatched: tuple[DiscoveredObject, ...] = ()
    equip_candidates: tuple[TagCandidate, ...] = ()

    def coverage(self) -> float:
        """Fraction of discovered objects that received any candidate, 0..1.

        TODO: len(candidates) / (len(candidates) + len(unmatched)).
        What's missing: a second, harsher metric — coverage at the auto-apply threshold.
            Raw coverage flatters the profile; 85% raw with 40% above 0.6 is a bad
            profile wearing a good number. Report both.
        Acceptance: an all-matched profile returns 1.0; an empty match returns 0.0 rather
            than raising ZeroDivisionError.
        Depends on: `TagCandidate.is_auto_applicable`.
        """
        raise NotImplementedError("coverage metric not yet implemented")


class TaggingProfile(Protocol):
    """Interface every vendor profile implements."""

    name: str
    vendor_ids: tuple[int, ...]

    def claims(self, obj: DiscoveredObject) -> float:
        """How strongly this profile believes it owns the object's naming convention, 0..1.

        Lets a site with mixed Trane and ALC gear route each device to the right profile
        without the operator declaring it. BACnet vendor-id is the strongest signal, but a
        Trane controller integrated behind an i-Vu front end still uses Trane names, so
        naming style must be able to override vendor id.
        """
        ...

    def tag_point(
        self,
        obj: DiscoveredObject,
        equip_hint: EquipType | None = None,
    ) -> TagCandidate | None:
        """Propose tags for one discovered object, or None if unrecognized."""
        ...

    def tag_equip(
        self,
        device_name: str,
        objects: tuple[DiscoveredObject, ...],
    ) -> TagCandidate | None:
        """Propose an equipment identity for a device from its name and object population."""
        ...

    def tokenize_name(self, name: str) -> tuple[str, ...]:
        """Split a vendor point name into semantic tokens."""
        ...


def run_profile(
    profile: TaggingProfile,
    objects: tuple[DiscoveredObject, ...],
    overrides: dict[str, TagSet] | None = None,
) -> ProfileMatch:
    """Run a profile over a device's objects, applying any persisted overrides.

    TODO: Infer the equipment first, then tag each object with that equipment as context,
        substituting overrides (keyed by `PointRef.key()`) at full confidence.
    What's missing: the two-pass ordering rationale — equipment context materially
        changes point interpretation ("SP" on a VAV is a setpoint; "SP" on an AHU is
        static pressure), so equipment must be resolved before points, and a low-confidence
        equipment guess must propagate its uncertainty into every point candidate rather
        than being laundered into certainty.
    Acceptance: on the Trane fixture, coverage >= 0.7; every object appears exactly once
        across `candidates` and `unmatched`.
    Depends on: `TaggingProfile`, `TagCandidate`.
    """
    raise NotImplementedError("profile execution pipeline not yet implemented")


def select_profile(
    profiles: tuple[TaggingProfile, ...],
    objects: tuple[DiscoveredObject, ...],
) -> TaggingProfile | None:
    """Pick the best profile for a device by polling each profile's `claims`.

    TODO: Score every profile over a sample of objects and return the highest scorer
        above a minimum threshold.
    What's missing: the tie-break and the abstention case. A device no profile claims
        must return None so its objects go to review wholesale, rather than being mangled
        by whichever profile scored 0.11.
    Acceptance: an all-Trane device selects the Trane profile; a device of generic
        AV objects named "AV1".."AV50" returns None.
    Depends on: `TaggingProfile.claims`.
    """
    raise NotImplementedError("profile selection not yet implemented")


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """One object awaiting human tagging, with the profile's best guesses ranked."""

    obj: DiscoveredObject
    suggestions: tuple[TagCandidate, ...] = ()
    status: ReviewStatus = ReviewStatus.PENDING
    resolved_tags: TagSet | None = None
    reviewer: str | None = None
    resolved_at: datetime | None = None
    note: str = ""


class ReviewQueue:
    """The workflow for the 15-30% of points heuristics cannot confidently tag."""

    def __init__(self, items: tuple[ReviewItem, ...] = ()) -> None:
        """Create a queue, optionally seeded with existing items.

        TODO: Store items indexed by `PointRef.key()`.
        What's missing: persistence. The queue must survive a restart and be shareable
            between reviewers, so phase 4 should back this with the same DuckDB the
            historian uses rather than memory.
        Acceptance: constructing with no arguments yields an empty queue.
        Depends on: `ReviewItem`.
        """
        raise NotImplementedError("review queue storage not yet implemented")

    def enqueue(self, obj: DiscoveredObject, suggestions: tuple[TagCandidate, ...]) -> None:
        """Add an unmatched or low-confidence object to the queue.

        TODO: Wrap in a `ReviewItem` with suggestions sorted by descending confidence.
        What's missing: idempotency — rediscovery on every startup must not create
            duplicates, so re-enqueueing a key that is already resolved is a no-op.
        Acceptance: enqueueing the same ref twice yields one item; an already-ACCEPTED
            ref is not re-queued.
        Depends on: `ReviewQueue.__init__`.
        """
        raise NotImplementedError("review enqueue not yet implemented")

    def pending(self, limit: int | None = None) -> tuple[ReviewItem, ...]:
        """Return pending items, highest-value-first.

        TODO: Filter to PENDING and order by review value.
        What's missing: the ordering heuristic, which is where reviewer time is won or
            lost. Order by (number of identical unmatched names across the site) desc,
            because resolving one "UN-T" on a hundred identical VAVs resolves a hundred
            points at once. Then by equipment importance (an AHU beats a VAV).
        Acceptance: an object whose name recurs 50 times outranks a unique one.
        Depends on: `ReviewQueue.__init__`.
        """
        raise NotImplementedError("review prioritization not yet implemented")

    def resolve(self, ref_key: str, tags: TagSet, reviewer: str, note: str = "") -> ReviewItem:
        """Record a human decision for one item.

        TODO: Mark ACCEPTED when the tags equal a suggestion, CORRECTED otherwise, and
            stamp reviewer and time.
        What's missing: the feedback loop — a CORRECTED resolution should emit a
            candidate override (see `learn_overrides`) so the same vendor name is handled
            automatically next time. Without that, review is a treadmill.
        Acceptance: resolving sets status and `resolved_tags`; the item leaves `pending`.
        Depends on: `enqueue`, `learn_overrides`.
        """
        raise NotImplementedError("review resolution not yet implemented")

    def bulk_resolve(self, name_pattern: str, tags: TagSet, reviewer: str) -> tuple[str, ...]:
        """Apply one decision to every pending item whose vendor name matches a pattern.

        TODO: Match pending items by pattern and resolve each, returning the ref keys hit.
        What's missing: a dry-run mode. Bulk-tagging 400 points from a bad glob is exactly
            the mistake that destroys trust in the tool, so the UI must be able to preview
            the match set before committing.
        Acceptance: a pattern matching 12 items resolves exactly those 12 and returns
            their keys.
        Depends on: `resolve`.
        """
        raise NotImplementedError("bulk review resolution not yet implemented")

    def stats(self) -> dict[str, int]:
        """Counts by `ReviewStatus`, for a coverage dashboard.

        TODO: Tally items per status.
        What's missing: nothing.
        Acceptance: counts sum to the total item count; every status key is present even
            at zero.
        Depends on: `ReviewQueue.__init__`.
        """
        raise NotImplementedError("review statistics not yet implemented")


def learn_overrides(queue: ReviewQueue) -> dict[str, TagSet]:
    """Derive reusable name-to-tags overrides from human corrections.

    TODO: Group CORRECTED and ACCEPTED items by normalized vendor name and emit an
        override for each name that resolved consistently.
    What's missing: the consistency requirement and its scope. The same name can mean
        different things on different equipment types ("SP" again), so overrides must be
        keyed by (vendor, equip type, normalized name), not by name alone — and a name
        that reviewers resolved two different ways under the same key must produce NO
        override rather than the majority answer.
    Acceptance: ten identical "UN-T" corrections yield one override; five "SP" -> flow
        setpoint and five "SP" -> static pressure under the same key yield none.
    Depends on: `ReviewQueue.resolve`.
    """
    raise NotImplementedError("override learning not yet implemented")
