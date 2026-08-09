"""Equipment: the containers that own points and participate in topology.

Equipment is the level at which a human reasons ("VAV 2-14 is starving"), at which
Haystack `equipRef` points, and at which UUKL participation is usually declared (a
smoke control matrix names AHUs and dampers, not object instances).

Containment is modelled by `Point.equip_id` plus `Equip.parent_equip_id`, which gives
the AHU -> VAV hierarchy Haystack expects. Flow relationships (which AHU actually feeds
which VAV, through which duct) live in `topology.py`, not here — a VAV can be
administratively grouped under one AHU and physically fed by another during a
retrofit, and conflating the two loses that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class EquipType(StrEnum):
    """Equipment archetypes we can tag and, later, model in Brick/223P.

    Deliberately coarse. Sub-variants (single-duct vs fan-powered VAV, series vs
    parallel fan) are expressed as additional Haystack markers, not as new enum members,
    so the enum stays stable while the tag vocabulary grows.
    """

    AHU = "ahu"
    RTU = "rtu"
    DOAS = "doas"
    VAV = "vav"
    CAV = "cav"
    FCU = "fcu"
    UNIT_HEATER = "unitHeater"
    CHILLER = "chiller"
    BOILER = "boiler"
    COOLING_TOWER = "coolingTower"
    PUMP = "pump"
    FAN = "fan"
    HEAT_EXCHANGER = "heatExchanger"
    VFD = "vfd"
    DAMPER = "damper"
    VALVE = "valve"
    METER = "meter"
    ZONE_CONTROLLER = "zoneController"
    SMOKE_CONTROL_PANEL = "smokeControlPanel"
    UNKNOWN = "unknown"


class OperatingState(StrEnum):
    """Coarse runtime state, derived from points rather than stored raw."""

    OFF = "off"
    OCCUPIED = "occupied"
    UNOCCUPIED = "unoccupied"
    WARMUP = "warmup"
    COOLDOWN = "cooldown"
    HEATING = "heating"
    COOLING = "cooling"
    ECONOMIZING = "economizing"
    FAULT = "fault"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Nameplate:
    """Design/nameplate data. Analytics without design intent are just squiggles.

    Fields are optional because this data is rarely available from BACnet — it comes
    from submittals, schedules, or the AV objects a programmer happened to expose.
    """

    manufacturer: str | None = None
    model: str | None = None
    serial: str | None = None
    design_airflow_cfm: float | None = None
    min_airflow_cfm: float | None = None
    max_airflow_cfm: float | None = None
    design_capacity_tons: float | None = None
    design_capacity_mbh: float | None = None
    motor_hp: float | None = None
    install_date: str | None = None


@dataclass(frozen=True, slots=True)
class Equip:
    """One piece of equipment.

    `life_safety` here means "participates in a UUKL-listed smoke control sequence".
    It is a property of the equipment as installed, sourced from the smoke control
    matrix, and it propagates to every point the equipment owns unless explicitly
    narrowed. Defaulting it to False is a deliberate ergonomic choice — the deny-by-
    default guarantee lives in `safety.blocklist`, which treats UNKNOWN provenance as
    blocked, not in this flag.
    """

    id: str
    name: str
    equip_type: EquipType
    site_id: str
    device_id: str | None = None
    parent_equip_id: str | None = None
    space_ids: tuple[str, ...] = ()
    floor_id: str | None = None
    point_ids: tuple[str, ...] = ()
    nameplate: Nameplate = field(default_factory=Nameplate)
    life_safety: bool = False
    vendor: str | None = None
    description: str = ""

    def is_terminal_unit(self) -> bool:
        """Whether this equipment is a zone-level terminal unit.

        TODO: Return True for VAV, CAV, FCU, UNIT_HEATER and any type that serves a
            single zone downstream of an air handler.
        What's missing: the membership set, and the reason it matters — terminal units
            are overwhelmingly the population that lives on MS/TP, so this predicate is
            what `TrunkBudget` and `AdaptivePoller` use to decide whether a read is
            cheap (IP) or expensive (RS-485).
        Acceptance: VAV/CAV/FCU/UNIT_HEATER -> True; AHU/CHILLER/PUMP -> False.
        Depends on: `EquipType`.
        """
        raise NotImplementedError("terminal unit classification set not yet defined")

    def haystack_markers(self) -> tuple[str, ...]:
        """Haystack marker tags implied by the equipment type alone.

        TODO: Emit the marker chain Haystack expects — e.g. VAV -> ("equip","vav","ahu"
            is NOT implied; but "airTerminalUnit","vav"), AHU -> ("equip","ahu","airHandlingEquip").
        What's missing: alignment with the current Haystack 4 def hierarchy rather than
            the older flat 3.x tags; verify against the ph/phIoT namespace and prefer
            emitting the most specific def plus its conformed supertypes.
        Acceptance: every returned tag exists in `semantic.tags`; "equip" is always
            present; output is deterministic and sorted.
        Depends on: `semantic.tags`.
        """
        raise NotImplementedError("equip-type to Haystack marker mapping not yet implemented")

    def derive_state(self, point_values: dict[str, object]) -> OperatingState:
        """Derive a coarse operating state from current point values.

        TODO: Apply per-equip-type rules against the supplied point-id -> value map.
        What's missing: the rules, and their fault handling. An AHU with fan status on,
            cooling valve at 0%, and outside air damper at 100% is ECONOMIZING, not
            COOLING — and if the fan command is on while fan status is off, it is FAULT
            regardless of everything else. Missing points must yield UNKNOWN, never a
            guessed state.
        Acceptance: rules are table-driven and unit-testable from the fixtures;
            an empty value map always returns UNKNOWN.
        Depends on: `model.point`, `store.tagstore`.
        """
        raise NotImplementedError("operating state derivation rules not yet defined")
