"""Spatial hierarchy: site -> building -> floor -> space, plus 223P DomainSpace.

Haystack's spatial model is site/floor/space/room-ish and fairly loose. ASHRAE 223P is
stricter and distinguishes a *physical space* from a *domain space* — the volume of air
a piece of HVAC equipment actually conditions, which frequently does not line up with
architectural room boundaries (one VAV serving three offices; an open-plan floor split
into four thermal zones by nothing but a control drawing).

We keep both. `Space` is the architectural truth; `DomainSpace` is the HVAC truth. The
mapping between them is many-to-many and is exactly what a Brick/223P export needs and
a pure-Haystack model throws away.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SpaceType(StrEnum):
    """Architectural space classification (drives ASHRAE 62.1 ventilation rates)."""

    OFFICE = "office"
    CONFERENCE = "conference"
    CLASSROOM = "classroom"
    CORRIDOR = "corridor"
    LOBBY = "lobby"
    RESTROOM = "restroom"
    MECHANICAL = "mechanical"
    ELECTRICAL = "electrical"
    STAIRWELL = "stairwell"
    LAB = "lab"
    KITCHEN = "kitchen"
    DATA_CENTER = "dataCenter"
    RETAIL = "retail"
    WAREHOUSE = "warehouse"
    PATIENT_ROOM = "patientRoom"
    OPERATING_ROOM = "operatingRoom"
    ATRIUM = "atrium"
    OTHER = "other"


class SmokeZoneRole(StrEnum):
    """Role a space plays in a smoke control sequence.

    Present in the spatial model, not just the safety model, because smoke control is
    inherently spatial: pressurizing a stairwell means exhausting the zone of fire
    origin and supplying the adjacent zones. A point's UUKL status is often only
    derivable through the space it serves.
    """

    NONE = "none"
    SMOKE_ZONE = "smokeZone"
    PRESSURIZED_STAIRWELL = "pressurizedStairwell"
    PRESSURIZED_VESTIBULE = "pressurizedVestibule"
    ATRIUM_EXHAUST = "atriumExhaust"
    ELEVATOR_HOISTWAY = "elevatorHoistway"
    REFUGE_AREA = "refugeArea"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class GeoLocation:
    """Where the site is. Needed for weather normalization and degree-day analytics."""

    latitude: float | None = None
    longitude: float | None = None
    elevation_m: float | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    postal_code: str | None = None
    climate_zone: str | None = None


@dataclass(frozen=True, slots=True)
class Site:
    """Top-level customer premises. Timezone lives here and governs all history."""

    id: str
    name: str
    timezone: str
    geo: GeoLocation
    area_sqft: float | None = None
    building_ids: tuple[str, ...] = ()
    vendor_systems: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Building:
    """One structure on a site."""

    id: str
    name: str
    site_id: str
    floor_ids: tuple[str, ...] = ()
    area_sqft: float | None = None
    year_built: int | None = None
    stories_above_grade: int | None = None
    stories_below_grade: int | None = None


@dataclass(frozen=True, slots=True)
class Floor:
    """One level of a building. Ordering matters for stack-effect and smoke reasoning."""

    id: str
    name: str
    building_id: str
    level: int
    space_ids: tuple[str, ...] = ()
    area_sqft: float | None = None


@dataclass(frozen=True, slots=True)
class Space:
    """An architectural space — a room or an area with real boundaries."""

    id: str
    name: str
    floor_id: str
    space_type: SpaceType = SpaceType.OTHER
    area_sqft: float | None = None
    volume_cuft: float | None = None
    design_occupancy: int | None = None
    smoke_zone_role: SmokeZoneRole = SmokeZoneRole.UNKNOWN
    domain_space_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DomainSpace:
    """A 223P DomainSpace: the volume a domain (air, water, lighting) actually acts on.

    A thermal zone is the canonical HVAC case. It references the architectural spaces it
    overlaps and is referenced by `topology.ServesSpace` relations from equipment.
    """

    id: str
    name: str
    domain: str
    space_ids: tuple[str, ...] = ()
    served_by_equip_ids: tuple[str, ...] = ()


def resolve_space_path(space_id: str, spaces: dict[str, Space], floors: dict[str, Floor]) -> str:
    """Return a human-readable path like "HQ / Bldg A / Floor 2 / Room 214".

    TODO: Walk space -> floor -> building -> site and join with a separator.
    What's missing: the building/site lookup arguments (this signature is incomplete on
        purpose — decide in phase 2 whether to pass four dicts or a resolved `SiteGraph`
        object, and prefer the latter), plus handling of orphaned spaces.
    Acceptance: a known space returns the full path; an orphaned space returns its own
        name without raising.
    Depends on: `Space`, `Floor`, `Building`, `Site`.
    """
    raise NotImplementedError("site graph traversal not yet implemented")


def ventilation_rate_cfm(space: Space, standard: str = "62.1-2019") -> float | None:
    """Required outdoor airflow for a space under ASHRAE 62.1, or None if underspecified.

    TODO: Apply Vbz = Rp*Pz + Ra*Az using the standard's Table 6-2 rates for the space
        type, and return None when area or occupancy is unknown.
    What's missing: the Rp/Ra table per `SpaceType`, and an explicit decision that this
        is an ADVISORY calculation. It is a compliance signal for analytics ("this AHU
        cannot be delivering code minimum OA at these damper positions"), never an input
        to a control action — we do not write ventilation setpoints.
    Acceptance: an office with 5 people and 1000 sqft under 62.1-2019 returns
        5*5 + 0.06*1000 = 85 cfm; an unknown space type returns None.
    Depends on: `SpaceType`, `model.units`.
    """
    raise NotImplementedError("ASHRAE 62.1 rate table not yet populated")
