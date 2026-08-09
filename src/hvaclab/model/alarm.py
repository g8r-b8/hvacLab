"""Alarms: BACnet intrinsic and algorithmic reporting, normalized.

BACnet has two distinct alarm mechanisms and they behave differently enough that
flattening them loses information:

* **Intrinsic reporting** — the alarm logic lives *on the object* (an Analog Input with
  `high-limit`, `low-limit`, `deadband`, `time-delay`, `event-enable`, `notification-class`).
  Simple, and readable straight off the object's properties.
* **Algorithmic change reporting** — a separate Event Enrollment object watches another
  object and applies an event algorithm (OUT_OF_RANGE, CHANGE_OF_STATE, FLOATING_LIMIT,
  COMMAND_FAILURE...). The alarm's identity is the Event Enrollment, not the monitored
  point, so naive code attributes the alarm to the wrong object.

Notification Classes hold the recipient lists, per-priority routing, and ack
requirements. Priority here is BACnet event priority (0-255, lower = more urgent), NOT
the write priority array — different concept, same word, endless confusion.

We do not silence, acknowledge, or write to alarms on day one. Reading only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from hvaclab.model.point import PointRef


class EventState(StrEnum):
    """BACnet `event-state` — the current condition of the monitored object."""

    NORMAL = "normal"
    FAULT = "fault"
    OFFNORMAL = "offnormal"
    HIGH_LIMIT = "highLimit"
    LOW_LIMIT = "lowLimit"
    LIFE_SAFETY_ALARM = "lifeSafetyAlarm"


class AlarmState(StrEnum):
    """Normalized lifecycle state, combining event state with acknowledgement."""

    NORMAL = "normal"
    ACTIVE_UNACKED = "activeUnacked"
    ACTIVE_ACKED = "activeAcked"
    RETURNED_UNACKED = "returnedUnacked"
    CLEARED = "cleared"
    SHELVED = "shelved"
    UNKNOWN = "unknown"


class ReportingMechanism(StrEnum):
    """How the alarm is generated on the device."""

    INTRINSIC = "intrinsic"
    ALGORITHMIC = "algorithmic"
    DERIVED = "derived"


class EventAlgorithm(StrEnum):
    """BACnet event algorithms used by Event Enrollment objects (ASHRAE 135 Clause 13)."""

    CHANGE_OF_BITSTRING = "changeOfBitstring"
    CHANGE_OF_STATE = "changeOfState"
    CHANGE_OF_VALUE = "changeOfValue"
    COMMAND_FAILURE = "commandFailure"
    FLOATING_LIMIT = "floatingLimit"
    OUT_OF_RANGE = "outOfRange"
    CHANGE_OF_LIFE_SAFETY = "changeOfLifeSafety"
    BUFFER_READY = "bufferReady"
    UNSIGNED_RANGE = "unsignedRange"
    CHANGE_OF_RELIABILITY = "changeOfReliability"
    NONE = "none"


class AlarmSeverity(StrEnum):
    """Operator-facing severity, derived from BACnet event priority bands."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class NotificationClass:
    """A BACnet Notification Class object: routing and acknowledgement policy.

    `priority` is a 3-tuple (to-offnormal, to-fault, to-normal) of BACnet event
    priorities 0-255. `ack_required` is the matching 3-tuple of booleans.
    """

    device_id: str
    instance: int
    name: str
    priority: tuple[int, int, int]
    ack_required: tuple[bool, bool, bool]
    recipient_count: int = 0
    description: str = ""


@dataclass(frozen=True, slots=True)
class IntrinsicConfig:
    """Intrinsic reporting properties read off the monitored object itself."""

    high_limit: float | None = None
    low_limit: float | None = None
    deadband: float | None = None
    time_delay_s: float | None = None
    time_delay_normal_s: float | None = None
    limit_enable_high: bool = False
    limit_enable_low: bool = False
    event_enable_offnormal: bool = False
    event_enable_fault: bool = False
    event_enable_normal: bool = False
    notification_class_instance: int | None = None


@dataclass(frozen=True, slots=True)
class Alarm:
    """One alarm definition plus its current state.

    `source_ref` is the monitored point. `enrollment_ref` is the Event Enrollment object
    for algorithmic alarms and None for intrinsic ones — keeping both is what lets the UI
    say "AHU-1 discharge air temp is in alarm" rather than "EE:7 is in alarm".
    """

    id: str
    source_ref: PointRef
    mechanism: ReportingMechanism
    event_state: EventState = EventState.NORMAL
    alarm_state: AlarmState = AlarmState.UNKNOWN
    severity: AlarmSeverity = AlarmSeverity.INFO
    message: str = ""
    equip_id: str | None = None
    enrollment_ref: PointRef | None = None
    algorithm: EventAlgorithm = EventAlgorithm.NONE
    intrinsic: IntrinsicConfig | None = None
    notification_class_instance: int | None = None
    bacnet_priority: int | None = None
    life_safety: bool = False
    timestamp_offnormal: datetime | None = None
    timestamp_fault: datetime | None = None
    timestamp_normal: datetime | None = None
    acked_transitions: tuple[bool, bool, bool] = (True, True, True)


@dataclass(frozen=True, slots=True)
class AlarmEvent:
    """An immutable transition record — the historian's unit of alarm history."""

    alarm_id: str
    at: datetime
    from_state: EventState
    to_state: EventState
    value_at_transition: float | bool | int | str | None = None
    message: str = ""
    acked: bool = False
    tags: frozenset[str] = field(default_factory=frozenset)


def severity_from_priority(bacnet_priority: int) -> AlarmSeverity:
    """Map a BACnet event priority (0-255, lower is more urgent) to operator severity.

    TODO: Band the 0-255 range into the five `AlarmSeverity` levels.
    What's missing: the band edges, and the fact that ASHRAE 135 only *recommends*
        conventions (life safety 0-63, property 64-127, supervisory 128-191, maintenance
        192-255) which integrators routinely ignore — one large Trane site had every
        alarm at priority 255. So bands must be overridable per site, defaulting to the
        recommendation.
    Acceptance: 0 -> CRITICAL, 255 -> INFO, monotonic non-increasing severity as the
        number rises.
    Depends on: `AlarmSeverity`.
    """
    raise NotImplementedError("event priority banding not yet defined")


def normalize_alarm_state(alarm: Alarm) -> AlarmState:
    """Collapse event state plus acked transitions into a single lifecycle state.

    TODO: Combine `event_state` with `acked_transitions` and the notification class's
        `ack_required` to produce the operator-facing `AlarmState`.
    What's missing: the truth table, particularly RETURNED_UNACKED — an alarm whose
        condition cleared but whose to-normal transition was never acknowledged is still
        actionable and must not be hidden.
    Acceptance: offnormal + unacked -> ACTIVE_UNACKED; normal + to-normal unacked and
        ack required -> RETURNED_UNACKED; normal + all acked -> NORMAL.
    Depends on: `Alarm`, `NotificationClass`.
    """
    raise NotImplementedError("alarm lifecycle truth table not yet defined")


def is_life_safety_alarm(alarm: Alarm, blocked_device_ids: frozenset[str]) -> bool:
    """Whether this alarm belongs to a UUKL-listed life safety sequence.

    TODO: Return True when the event state is LIFE_SAFETY_ALARM, the algorithm is
        CHANGE_OF_LIFE_SAFETY, the source device is on the UUKL blocklist, or the alarm
        is explicitly flagged.
    What's missing: nothing structural — but the DEFAULT must be conservative. This
        predicate gates whether the UI offers any interaction at all, so an alarm of
        unknown provenance on a device that also hosts smoke control points must return
        True.
    Acceptance: an alarm on a blocklisted device returns True even with
        `life_safety=False` on the dataclass.
    Depends on: `safety.blocklist.LifeSafetyBlocklist`.
    """
    raise NotImplementedError("life safety alarm classification not yet implemented")
