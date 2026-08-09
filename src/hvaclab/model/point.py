"""Points: the atoms of a BAS.

A point is one readable (and sometimes writable) datum on a controller. The model here
is deliberately protocol-agnostic at the top and protocol-specific only inside
`PointRef`, so a Modbus register and a BACnet AI can coexist in one tag store.

Two design decisions worth stating:

* `Volatility` is part of the model, not the transport layer. It is a property of what
  the point measures (a damper command changes on the second, an outside air temp on
  the minute), and it is the input the adaptive poller schedules against. Storing it on
  the point means it survives a restart and can be tuned per site.
* `PointValue` carries reliability and priority-array state, not just a number. On real
  gear, `present-value` without `status-flags` and `reliability` is a lie: a failed
  sensor still reports a plausible-looking float.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from hvaclab.model.units import Unit


class PointKind(StrEnum):
    """What role a point plays in a control sequence.

    Maps onto Haystack's `sensor` / `cmd` / `sp` markers, which are mutually exclusive.
    """

    SENSOR = "sensor"
    CMD = "cmd"
    SP = "sp"


class PointType(StrEnum):
    """Value domain of the point, independent of the wire protocol."""

    ANALOG = "analog"
    BINARY = "binary"
    MULTISTATE = "multistate"
    STRING = "string"


class Volatility(StrEnum):
    """How fast a point's value meaningfully changes — the adaptive poller's input.

    Suggested default cadences (tunable per site, and always subject to the trunk
    budget, which may starve a tier entirely):

        FAST    ~5s    damper/valve position, fan speed cmd, active alarms
        MEDIUM  ~30s   discharge air temp, static pressure, airflow
        SLOW    ~300s  space temp, setpoints, outside air temp
        STATIC  ~1h    nameplate values, config, design airflow, schedule refs
    """

    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"
    STATIC = "static"


class Reliability(StrEnum):
    """Subset of BACnet `reliability` (ASHRAE 135) plus a transport-level unreachable.

    NO_FAULT_DETECTED does not mean "good" on its own — `status_flags.out_of_service`
    can still be set, which means the value is a technician's simulation.
    """

    NO_FAULT_DETECTED = "noFaultDetected"
    NO_SENSOR = "noSensor"
    OVER_RANGE = "overRange"
    UNDER_RANGE = "underRange"
    OPEN_LOOP = "openLoop"
    SHORTED_LOOP = "shortedLoop"
    UNRELIABLE_OTHER = "unreliableOther"
    COMMUNICATION_FAILURE = "communicationFailure"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True, slots=True)
class StatusFlags:
    """BACnet `status-flags` bit string, unpacked.

    `out_of_service` is the one that silently ruins analytics: the value is whatever a
    technician last wrote for testing and has no relationship to the physical world.
    Any historian rollup must exclude these samples or flag them.
    """

    in_alarm: bool = False
    fault: bool = False
    overridden: bool = False
    out_of_service: bool = False


@dataclass(frozen=True, slots=True)
class PointRef:
    """Protocol-level address of a point, stable across restarts.

    For BACnet this is (device instance, object type, object instance, property,
    optional array index). Device instance rather than MAC/IP because addresses move;
    device instance is the identity BACnet actually guarantees.
    """

    protocol: str
    device_id: str
    object_type: str
    object_instance: int
    property_id: str = "present-value"
    array_index: int | None = None
    network_number: int | None = None
    mac_address: str | None = None

    def key(self) -> str:
        """Return a stable string key for maps, caches, and DuckDB primary keys.

        TODO: Format a canonical, collision-free key such as
            `bacnet:1201:analog-input:12:present-value` including array index when set.
        What's missing: the exact separator/escaping rule. Object names can contain
            colons on ALC gear, so the key must be built from structured fields only,
            never from the display name.
        Acceptance: two `PointRef`s are equal iff their keys are equal; the key is stable
            across processes and Python versions (no `hash()`, no `id()`).
        Depends on: nothing.
        """
        raise NotImplementedError("stable point key format not yet decided")


@dataclass(frozen=True, slots=True)
class PointValue:
    """One observation of a point, with everything needed to judge whether to trust it."""

    ref: PointRef
    value: float | bool | int | str | None
    unit: Unit
    timestamp: datetime
    status: StatusFlags = field(default_factory=StatusFlags)
    reliability: Reliability = Reliability.NO_FAULT_DETECTED
    priority_in_effect: int | None = None
    source: str = "poll"

    def is_trustworthy(self) -> bool:
        """Whether this sample should feed analytics and history.

        TODO: Return False when fault or out_of_service is set, when reliability is
            anything other than NO_FAULT_DETECTED, or when value is None.
        What's missing: the policy on `overridden`. An overridden value is real (the
            equipment is genuinely doing that), so it should be trusted for history but
            flagged for the orphaned-override detector — do not silently drop it.
        Acceptance: a fault sample returns False; an overridden-but-healthy sample
            returns True; a None value returns False.
        Depends on: `StatusFlags`, `Reliability`.
        """
        raise NotImplementedError("sample trust policy not yet implemented")


@dataclass(frozen=True, slots=True)
class EnumStateText:
    """Human-readable state names for binary and multistate points.

    BACnet multistate is 1-indexed; off-by-one here means reporting "Cooling" when the
    unit is in "Heating". Trane and ALC both ship `state-text` arrays; read them, do not
    assume a convention.
    """

    states: tuple[str, ...]
    one_indexed: bool = True

    def text_for(self, raw: int) -> str | None:
        """Map a raw state number to its label.

        TODO: Index into `states` respecting `one_indexed`; return None when out of range.
        What's missing: nothing conceptually — but out-of-range must return None rather
            than clamp, because a state number beyond `number-of-states` signals a
            controller/state-text mismatch that a human needs to see.
        Acceptance: with states ("Off","Heat","Cool") and one_indexed, 1 -> "Off",
            3 -> "Cool", 0 and 4 -> None.
        Depends on: nothing.
        """
        raise NotImplementedError("state text indexing not yet implemented")


@dataclass(frozen=True, slots=True)
class Point:
    """A point as the tag store knows it: identity, semantics, and polling policy."""

    id: str
    ref: PointRef
    display_name: str
    vendor_name: str
    kind: PointKind
    point_type: PointType
    unit: Unit
    equip_id: str | None = None
    volatility: Volatility = Volatility.MEDIUM
    writable: bool = False
    life_safety: bool = False
    min_value: float | None = None
    max_value: float | None = None
    resolution: float | None = None
    state_text: EnumStateText | None = None
    cov_increment: float | None = None
    description: str = ""

    def suggested_poll_interval_s(self) -> float:
        """Baseline poll interval implied by volatility, before budget clamping.

        TODO: Map `Volatility` to the cadences documented on the enum.
        What's missing: the cadences must be overridable per site — a lab or a data
            centre wants FAST on points a school would poll SLOW — so this returns a
            default that `AdaptivePoller` may override, never a hard rule.
        Acceptance: FAST < MEDIUM < SLOW < STATIC; all values positive and finite.
        Depends on: `Volatility`.
        """
        raise NotImplementedError("volatility-to-cadence mapping not yet implemented")

    def default_cov_increment(self) -> float | None:
        """A sensible COV increment for this point, or None if COV is inappropriate.

        TODO: Derive from unit, resolution, and range — e.g. 0.5 degF for temperature,
            1% for a damper, no increment (binary COV) for binary points.
        What's missing: the guard against COV storms. An increment smaller than the
            sensor's noise floor turns one subscription into a continuous unconfirmed
            broadcast flood, which is worse for the trunk than polling. Increment must be
            at least a few times `resolution`.
        Acceptance: an analog temperature point yields >= 2 * resolution; a binary point
            yields None; a STATIC point yields None.
        Depends on: `model.units`, `Point.resolution`.
        """
        raise NotImplementedError("COV increment heuristics not yet implemented")
