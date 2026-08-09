"""CovManager — change-of-value subscription budgeting and lifetime renewal.

COV is the cheapest way to track a fast-changing point: the device sends a notification
when the value moves by more than the COV increment, instead of us asking repeatedly. On a
constrained MS/TP trunk it is the difference between tracking a damper and not.

The constraints that make this a management problem rather than a call:

* **Slots are scarce.** Terminal-unit controllers typically support **4-8 concurrent
  subscriptions total**, across all clients. The native BAS may already be using several.
  Requesting a ninth returns a `resources` error at best; some devices silently evict an
  older subscription, so a subscription you believe is live is quietly gone.
* **Lifetimes expire.** `lifetime` is in seconds and must be renewed before it elapses. A
  lifetime of **0 means indefinite**, which sounds convenient and is a trap: the
  subscription survives our process crashing and leaks the slot until the device reboots.
  Never use 0.
* **Confirmed vs unconfirmed.** Confirmed COV notifications are acknowledged, so delivery
  is reliable but each notification costs a round trip. Unconfirmed is a single frame and
  cheaper, but a lost notification is lost silently — and on a busy trunk, notifications do
  get lost. Rule of thumb: confirmed for anything a control decision or an alarm depends
  on, unconfirmed for trending where an occasional miss is tolerable.
* **COV storms.** An increment smaller than the sensor's noise floor turns one subscription
  into a continuous notification flood — worse for the trunk than the polling it replaced.
  Increments must be validated against the point's resolution.
* **Prefer subscribing at the supervisor.** A subscription on a Tracer SC+ or i-Vu
  republished object consumes a supervisor slot (plentiful) instead of a terminal unit slot
  (4-8), and generates no MS/TP traffic at all. The cost is cache latency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from hvaclab.adapters.base import HVACAdapter, Subscription
from hvaclab.model.point import PointRef, PointValue

DEFAULT_LIFETIME_S: int = 300
"""Five minutes. Long enough to be cheap, short enough that a crash leaks briefly."""

RENEWAL_MARGIN_FRACTION: float = 0.5
"""Renew at half the lifetime. A margin this generous survives a slow trunk and a retry."""

INDEFINITE_LIFETIME: int = 0
"""BACnet's 'never expires'. Documented here so it is recognizable, never so it is used."""


class SlotPolicy(StrEnum):
    """What to do when a device has no free subscription slots."""

    REFUSE = "refuse"
    EVICT_LOWEST_VALUE = "evictLowestValue"
    FALL_BACK_TO_POLL = "fallBackToPoll"
    ESCALATE_TO_SUPERVISOR = "escalateToSupervisor"


class SubscriptionHealth(StrEnum):
    """Observed state of a subscription."""

    ACTIVE = "active"
    RENEWAL_DUE = "renewalDue"
    RENEWAL_FAILED = "renewalFailed"
    SILENT = "silent"
    EVICTED = "evicted"
    STORMING = "storming"


@dataclass(frozen=True, slots=True)
class DeviceSlotBudget:
    """How many COV slots a device has, and how many we may take.

    `total_slots` should be discovered rather than assumed where possible, but most
    devices do not advertise it — so default conservatively (4) and raise it only on
    evidence. `reserved_for_native_bas` acknowledges that the building's own system was
    here first and has a better claim than we do.
    """

    device_id: str
    total_slots: int = 4
    reserved_for_native_bas: int = 2
    our_slots_used: int = 0
    supports_cov_property: bool = False
    supports_confirmed: bool = True

    def available(self) -> int:
        """Slots we may still take.

        TODO: total_slots - reserved_for_native_bas - our_slots_used, floored at 0.
        What's missing: nothing arithmetically — but the reservation must not be
            configurable down to zero from an API request. Taking every slot on a
            controller can prevent the building's own supervisor from subscribing, which is
            an outage we caused.
        Acceptance: a 6-slot device with 2 reserved and 3 used returns 1; never negative.
        Depends on: nothing.
        """
        raise NotImplementedError("slot availability calculation not yet implemented")


@dataclass(frozen=True, slots=True)
class CovSubscriptionState:
    """Our record of one subscription and how it is behaving."""

    subscription: Subscription
    health: SubscriptionHealth = SubscriptionHealth.ACTIVE
    notifications_received: int = 0
    last_notification: datetime | None = None
    renewal_attempts: int = 0
    value_score: float = 0.0
    increment: float | None = None


@dataclass(frozen=True, slots=True)
class CovReport:
    """Operator-facing summary of subscription health across a site."""

    at: datetime
    total_subscriptions: int
    by_health: tuple[tuple[SubscriptionHealth, int], ...] = ()
    devices_at_capacity: tuple[str, ...] = ()
    storming_refs: tuple[PointRef, ...] = ()
    silent_refs: tuple[PointRef, ...] = ()
    notes: tuple[str, ...] = ()


class CovManager:
    """Allocates scarce COV slots, renews lifetimes, and detects storms and silence."""

    def __init__(
        self,
        adapters: tuple[HVACAdapter, ...],
        slot_policy: SlotPolicy = SlotPolicy.ESCALATE_TO_SUPERVISOR,
        default_lifetime_s: int = DEFAULT_LIFETIME_S,
    ) -> None:
        """Build a manager over a set of adapters.

        TODO: Index adapters, initialize empty slot budgets and subscription state.
        What's missing: `default_lifetime_s` must be validated as non-zero at construction.
            Accepting 0 here would silently arm the leak described in the module docstring.
        Acceptance: constructing with `default_lifetime_s=0` raises; construction performs
            no network I/O.
        Depends on: `adapters.base.HVACAdapter`.
        """
        raise NotImplementedError("COV manager construction not yet implemented")

    def register_device_budget(self, budget: DeviceSlotBudget) -> None:
        """Record how many slots a device has and how many are ours to use.

        TODO: Store the budget, keyed by device.
        What's missing: discovery of `total_slots`. Where a device exposes
            `max-cov-subscriptions` (rare), read it; otherwise probe cautiously by
            subscribing until refused ONCE at commissioning time, record the answer, and
            never probe again on a live system.
        Acceptance: registering a budget makes `can_subscribe` reflect it.
        Depends on: `DeviceSlotBudget`.
        """
        raise NotImplementedError("device slot budget registration not yet implemented")

    def can_subscribe(self, device_id: str, count: int = 1) -> bool:
        """Whether `count` more subscriptions fit within the device's budget.

        TODO: Compare against `DeviceSlotBudget.available`.
        What's missing: the unknown-device case, which must return False. Assuming a device
            we know nothing about has free slots is how a silent eviction of the building's
            own subscription happens.
        Acceptance: an unregistered device returns False; a device with 2 free returns True
            for count<=2.
        Depends on: `DeviceSlotBudget.available`.
        """
        raise NotImplementedError("slot availability check not yet implemented")

    async def subscribe(
        self,
        refs: tuple[PointRef, ...],
        confirmed: bool = True,
        increments: dict[str, float] | None = None,
    ) -> tuple[CovSubscriptionState, ...]:
        """Subscribe within budget, applying `slot_policy` when a device is at capacity.

        TODO: Group refs by device, validate increments, subscribe up to the budget, and
            apply the slot policy to the remainder.
        What's missing: the ESCALATE_TO_SUPERVISOR path, which should be the default
            behaviour and not an afterthought — when a terminal unit is out of slots, try
            subscribing to the supervisor's republished object for the same point instead
            of falling back to polling. That converts a hard failure into a slightly stale
            success at zero trunk cost.
        Acceptance: subscribing to 10 points on a 4-slot device yields subscriptions for
            all 10, with the overflow escalated to the supervisor; increments smaller than
            the point's resolution are rejected before any request is sent.
        Depends on: `can_subscribe`, `validate_increment`,
            `adapters.supervisor.SupervisorAdapter.subscribe`.
        """
        raise NotImplementedError("budgeted COV subscription not yet implemented")

    async def renew_due(self, now: datetime) -> tuple[CovSubscriptionState, ...]:
        """Renew subscriptions approaching expiry.

        TODO: Find subscriptions past `RENEWAL_MARGIN_FRACTION` of their lifetime and
            re-issue SubscribeCOV.
        What's missing: failure handling. A failed renewal means the subscription will
            lapse, so it must fall back to polling immediately rather than at expiry —
            waiting until the lifetime elapses guarantees a gap. Also, renewal must be
            resilient to our own process being paused (container throttling, GC pause): if
            `now` is already past expiry, treat it as a new subscription, not a renewal.
        Acceptance: a subscription at 60% of lifetime is renewed; a renewal failure
            immediately re-registers the point for polling.
        Depends on: `subscribe`, `transport.polling.AdaptivePoller.register`.
        """
        raise NotImplementedError("subscription renewal not yet implemented")

    def on_notification(
        self,
        ref: PointRef,
        value: PointValue,
        at: datetime,
    ) -> CovSubscriptionState:
        """Record an incoming COV notification and update health.

        TODO: Increment counters, update `last_notification`, and detect storming.
        What's missing: storm detection thresholds. A subscription delivering notifications
            faster than a few per second for a point that should be slow is storming, and
            the correct response is to unsubscribe and increase the increment, not to keep
            accepting the flood — the flood is consuming the trunk we were trying to
            protect.
        Acceptance: 100 notifications in 10 seconds on a temperature point marks STORMING
            and triggers unsubscription.
        Depends on: `CovSubscriptionState`, `validate_increment`.
        """
        raise NotImplementedError("notification handling not yet implemented")

    def detect_silent(
        self,
        now: datetime,
        threshold: timedelta = timedelta(minutes=30),
    ) -> tuple[PointRef, ...]:
        """Subscriptions that have delivered nothing for suspiciously long.

        TODO: Return refs whose `last_notification` is older than the threshold.
        What's missing: the crucial ambiguity — silence means either the value genuinely
            has not moved, or the subscription was silently evicted. These are
            indistinguishable from the notification stream alone, so a silent subscription
            must be *verified* with a single direct read. If the value moved but no
            notification arrived, the subscription is gone and must be re-established.
            Treating silence as "no change" is how a COV-based system quietly stops
            working while looking healthy.
        Acceptance: a subscription with no notifications for 30 minutes is returned and
            triggers a verification read.
        Depends on: `on_notification`, `adapters.base.HVACAdapter.read`.
        """
        raise NotImplementedError("silent subscription detection not yet implemented")

    async def unsubscribe_all(self) -> None:
        """Cancel every subscription. MUST be called on shutdown.

        TODO: Cancel all subscriptions across all adapters and clear slot accounting.
        What's missing: this must run even on abnormal shutdown paths (signal handlers,
            container SIGTERM). A process that exits without unsubscribing leaves slots
            held for the full lifetime, and on a 4-slot controller that can lock out the
            building's own supervisor for minutes. Register it as an atexit/signal handler,
            not merely in a happy-path `finally`.
        Acceptance: after `unsubscribe_all`, every device budget shows zero of our slots
            used; the method is idempotent and never raises.
        Depends on: `adapters.base.HVACAdapter.unsubscribe`.
        """
        raise NotImplementedError("bulk unsubscribe not yet implemented")

    def report(self, now: datetime) -> CovReport:
        """Summarize subscription health for an operator.

        TODO: Tally by health, list devices at capacity, storming refs, and silent refs.
        What's missing: nothing — but the notes should quantify the alternative, e.g.
            "12 points fell back to polling because 3 devices are at slot capacity; this
            consumes 0.4 reads/sec of a 2.1 reads/sec trunk budget", so the operator can
            see what the scarcity is actually costing.
        Acceptance: counts sum to `total_subscriptions`; a healthy site reports no storms.
        Depends on: `CovSubscriptionState`, `transport.budget.TrunkBudget`.
        """
        raise NotImplementedError("COV health reporting not yet implemented")


def validate_increment(
    increment: float,
    resolution: float | None,
    unit_span: float | None,
) -> tuple[bool, str]:
    """Check that a COV increment will not cause a notification storm.

    TODO: Require the increment to be at least a small multiple of the point's resolution,
        and a sensible fraction of its span; return (ok, explanation).
    What's missing: the multiples. A sensible starting rule is increment >= 2 * resolution
        and increment >= 0.1% of span — but the real driver is the sensor's noise, which
        is larger than its resolution. A 0.1 degF increment on a thermistor that jitters
        0.3 degF produces a continuous stream of notifications reporting nothing.
    Acceptance: a 0.1 increment on a 0.1-resolution point is rejected with an explanation;
        0.5 on the same point is accepted.
    Depends on: `model.point.Point.default_cov_increment`.
    """
    raise NotImplementedError("COV increment validation not yet implemented")
