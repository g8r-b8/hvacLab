"""Project Haystack tag vocabulary and tag sets.

Haystack has three tag flavours:

* **Marker** — presence-only truth (`point`, `sensor`, `discharge`, `air`, `temp`).
* **Value** — a scalar or string (`unit:"°F"`, `dis:"AHU-1 DAT"`, `tz:"America/Chicago"`).
* **Ref** — a pointer to another entity (`equipRef:@ahu-1`, `siteRef:@site-hq`).

A point's meaning is the *conjunction* of its markers. `discharge air temp sensor` is not
three facts, it is one: the discharge-air temperature sensor. This is why the filter
language in `filter.py` is fundamentally a set-containment language.

We add one custom marker beyond the standard vocabulary: **`lifeSafety`**. Any entity
carrying it participates in a UL 864 / UUKL-listed sequence. It exists as a tag (not only
as a database column) so it survives every export, is queryable in a filter, and appears
on any Zinc grid a third party consumes. It is asserted from the smoke control matrix and
never inferred by a heuristic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class TagKind(StrEnum):
    """Which of the three Haystack tag flavours a tag is."""

    MARKER = "marker"
    VALUE = "value"
    REF = "ref"


class Namespace(StrEnum):
    """Tag provenance — standard Haystack, or ours."""

    PH = "ph"
    PH_IOT = "phIoT"
    PH_SCIENCE = "phScience"
    HVAC_LAB = "hvacLab"


@dataclass(frozen=True, slots=True)
class TagDef:
    """Definition of one tag in the vocabulary.

    `conjuncts` captures Haystack's conjunct defs — `discharge-air-temp-sensor` implies
    `discharge`, `air`, `temp`, `sensor`, and `point`. Storing the implication chain lets
    the filter evaluator answer `point and temp` for an entity tagged only with the
    specific conjunct.
    """

    name: str
    kind: TagKind
    namespace: Namespace = Namespace.PH
    doc: str = ""
    is_of: str | None = None
    subtype_of: tuple[str, ...] = ()
    conjuncts: tuple[str, ...] = ()
    value_type: str | None = None


@dataclass(frozen=True, slots=True)
class Ref:
    """A Haystack ref — `@id` with an optional display string."""

    id: str
    dis: str | None = None

    def to_zinc(self) -> str:
        """Render as a Zinc ref literal.

        TODO: Emit `@id` or `@id "dis"` with the display string properly escaped.
        What's missing: Zinc's id charset rule — refs allow only alphanumerics plus
            `_ : - . ~`, so ids sourced from vendor object names must be sanitized on the
            way in, not escaped on the way out.
        Acceptance: Ref("ahu-1") -> "@ahu-1"; a dis containing a quote round-trips
            through the Zinc reader.
        Depends on: `semantic.export.haystack`.
        """
        raise NotImplementedError("Zinc ref encoding not yet implemented")


@dataclass(frozen=True, slots=True)
class TagSet:
    """An immutable set of tags on one entity: markers, values, and refs.

    Kept as three maps rather than one because the filter language treats them
    differently — markers test presence, values test comparison, refs traverse.
    """

    markers: frozenset[str] = frozenset()
    values: tuple[tuple[str, Any], ...] = ()
    refs: tuple[tuple[str, Ref], ...] = ()

    def has(self, tag: str) -> bool:
        """Whether the tag is present in any flavour, including via conjunct implication.

        TODO: Check markers, value keys, and ref keys; then expand implied tags via the
            vocabulary's `conjuncts`/`subtype_of` chain.
        What's missing: the vocabulary reference. `has` needs access to `TagVocabulary` to
            resolve implication, so phase 2 should either inject it or precompute the
            closure at TagSet construction (prefer precomputing — filters run hot).
        Acceptance: a TagSet with marker "discharge-air-temp-sensor" answers True for
            "temp", "air", "sensor" and "point".
        Depends on: `TagVocabulary.implied_tags`.
        """
        raise NotImplementedError("tag presence with conjunct expansion not yet implemented")

    def get(self, tag: str) -> Any | None:
        """Return a value or ref tag's payload, or None.

        TODO: Look up `values` then `refs`; return None for markers and unknown tags.
        What's missing: a decision on marker lookup — returning None for a *present*
            marker is ambiguous with absence, so callers must use `has` for markers.
            Document that; do not return a sentinel.
        Acceptance: get("unit") returns the unit string; get("point") returns None even
            when the marker is present.
        Depends on: nothing.
        """
        raise NotImplementedError("tag payload lookup not yet implemented")

    def with_tags(self, *markers: str, **values: Any) -> TagSet:
        """Return a new TagSet with additional markers and value tags.

        TODO: Build and return a new frozen TagSet; never mutate in place.
        What's missing: conflict policy — re-adding an existing value tag with a
            different payload should raise rather than silently overwrite, because that
            is how two profiles disagreeing about a unit gets caught.
        Acceptance: the original TagSet is unchanged; adding a conflicting value raises.
        Depends on: nothing.
        """
        raise NotImplementedError("immutable tag addition not yet implemented")

    def to_dict(self) -> dict[str, Any]:
        """Flatten to a plain dict suitable for JSON/Hayson encoding.

        TODO: Markers become `{"_kind": "marker"}`, refs become
            `{"_kind": "ref", "val": ...}`, values pass through.
        What's missing: verification against the current Hayson spec, which changed the
            marker encoding from Haystack 3's `"m:"` string prefixes.
        Acceptance: round-trips through `export.haystack.from_hayson`.
        Depends on: `semantic.export.haystack`.
        """
        raise NotImplementedError("Hayson dict encoding not yet implemented")


class TagVocabulary:
    """The known tag defs, plus implication resolution."""

    def __init__(self, defs: tuple[TagDef, ...] | None = None) -> None:
        """Build a vocabulary, defaulting to the built-in Haystack subset plus hvacLab tags.

        TODO: Populate the `TagDef` table and index by name.
        What's missing: the actual vocabulary. Minimum viable set for phase 2 —
            entity: site, building, floor, space, equip, point, device
            point role: sensor, cmd, sp
            substance: air, water, steam, elec, chilled, hot, condenser, refrig
            position: discharge, supply, return, exhaust, outside, mixed, entering, leaving, zone
            quantity: temp, humidity, pressure, flow, power, energy, co2, occ, freq, current, volt
            equip: ahu, vav, cav, fcu, rtu, doas, chiller, boiler, coolingTower,
                pump, fan, damper, valve, meter
            refs: siteRef, equipRef, ahuRef, spaceRef, floorRef, chilledWaterRef, hotWaterRef
            values: dis, unit, tz, kind, area, geoCity, minVal, maxVal
            hvacLab: lifeSafety, uuklDevice, trunkRef, volatility, tagConfidence
        Acceptance: constructs with no arguments; `lifeSafety` resolves with namespace
            HVAC_LAB; every `conjuncts` entry resolves to another def.
        Depends on: nothing.
        """
        raise NotImplementedError("Haystack tag vocabulary table not yet populated")

    def get(self, name: str) -> TagDef | None:
        """Return a tag def by name, or None if unknown.

        TODO: Index lookup.
        What's missing: the index.
        Acceptance: "temp" resolves; "tmep" returns None without raising.
        Depends on: `TagVocabulary.__init__`.
        """
        raise NotImplementedError("tag def index not yet built")

    def implied_tags(self, tag: str) -> frozenset[str]:
        """All tags implied by the given tag, transitively.

        TODO: Walk `conjuncts` and `subtype_of` to a fixed point, returning the closure
            including the tag itself.
        What's missing: cycle protection — a malformed vocabulary can loop — and
            memoization, because this is called on every filter evaluation.
        Acceptance: implied_tags("discharge-air-temp-sensor") is a superset of
            {"discharge","air","temp","sensor","point"}; implied_tags("temp") == {"temp"}.
        Depends on: `TagVocabulary.get`.
        """
        raise NotImplementedError("tag implication closure not yet implemented")

    def validate_tagset(self, tagset: TagSet) -> tuple[str, ...]:
        """Return human-readable problems with a tag set.

        TODO: Flag unknown tags, mutually exclusive markers, missing required refs, and
            value tags with wrong payload types.
        What's missing: the exclusivity rules. `sensor`/`cmd`/`sp` are mutually exclusive;
            `point` requires an `equipRef` or at least a `siteRef`; a `unit` value tag on
            a binary point is a smell.
        Acceptance: a valid discharge air temp sensor returns (); a point tagged both
            `sensor` and `cmd` returns exactly one message.
        Depends on: `TagVocabulary.get`, `implied_tags`.
        """
        raise NotImplementedError("tag set validation rules not yet defined")


LIFE_SAFETY_MARKER = "lifeSafety"
"""Custom hvacLab marker: entity participates in a UL 864 / UUKL-listed sequence."""

UUKL_DEVICE_MARKER = "uuklDevice"
"""Custom hvacLab marker: the whole device is part of a listed smoke control panel."""

TAG_CONFIDENCE_TAG = "tagConfidence"
"""Custom hvacLab value tag (0..1): profile confidence in the auto-assigned tags."""
