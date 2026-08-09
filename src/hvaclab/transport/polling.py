"""AdaptivePoller — volatility-tiered scheduling inside a hard bandwidth budget.

The naive design is a loop that reads every point every N seconds. On an MS/TP site that
saturates the trunk, starves the native BAS control loops, and gets the product removed
from the building. This module exists to make that outcome structurally impossible.

Priority order for acquiring data, cheapest first:

1. **Supervisor cache** (`adapters.supervisor`) — zero trunk cost. Always prefer it.
2. **RPM batching** — one request for many points, bounded by APDU size.
3. **COV** (`transport.cov`) — device pushes changes; slots are scarce (4-8).
4. **TrendLog + ReadRange** — bulk history, far cheaper than replaying polls.
5. **Direct polling** — last resort, strictly within `TrunkBudget`.

Scheduling model: points are assigned to `Volatility` tiers, each tier has a target
cadence, and the scheduler fills the available budget in tier order. When the budget
cannot cover all tiers — which is the normal case on a busy trunk — SLOW and STATIC tiers
degrade first, and the degradation is *reported*, not hidden. A poller that silently
falls behind produces data that looks current and is not, which is worse than data that is
openly stale.

Adaptivity: a point that has not changed in an hour is demoted a tier; a point that
changes every sample is promoted. This recovers a surprising amount of budget, because on
a real site most points are boring most of the time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from hvaclab.adapters.base import HVACAdapter
from hvaclab.model.point import PointRef, PointValue, Volatility
from hvaclab.transport.budget import BudgetRegistry


class PollStrategy(StrEnum):
    """How a point's data is acquired. Ordered cheapest to most expensive."""

    SUPERVISOR_CACHE = "supervisorCache"
    COV = "cov"
    RPM_BATCH = "rpmBatch"
    TREND_BACKFILL = "trendBackfill"
    DIRECT_POLL = "directPoll"
    NONE = "none"


class DegradationLevel(StrEnum):
    """How far the schedule has been cut back from its target."""

    NONE = "none"
    SLOW_TIER_DROPPED = "slowTierDropped"
    MEDIUM_TIER_STRETCHED = "mediumTierStretched"
    FAST_TIER_STRETCHED = "fastTierStretched"
    CRITICAL_ONLY = "criticalOnly"


@dataclass(frozen=True, slots=True)
class TierPolicy:
    """Target cadence and minimum acceptable cadence per volatility tier.

    `min_interval_s` is the floor below which polling this tier is pointless; `max_interval_s`
    is the point at which the data stops being useful and the tier should be reported as
    degraded rather than quietly stretched further.
    """

    volatility: Volatility
    target_interval_s: float
    min_interval_s: float
    max_interval_s: float
    droppable: bool = True


@dataclass(frozen=True, slots=True)
class PollEntry:
    """One point's scheduling state."""

    ref: PointRef
    volatility: Volatility
    strategy: PollStrategy
    device_id: str
    trunk_id: str | None = None
    interval_s: float = 60.0
    last_polled: datetime | None = None
    last_changed: datetime | None = None
    last_value: float | bool | int | str | None = None
    consecutive_unchanged: int = 0
    consecutive_errors: int = 0
    priority_boost: int = 0


@dataclass(frozen=True, slots=True)
class ScheduleReport:
    """What the scheduler is actually achieving, versus what was asked for.

    This is an operator-facing artifact. Honest degradation reporting is the difference
    between a trustworthy dataset and a plausible one.
    """

    at: datetime
    total_points: int
    points_by_strategy: tuple[tuple[PollStrategy, int], ...] = ()
    achieved_reads_per_sec: tuple[tuple[str, float], ...] = ()
    budget_reads_per_sec: tuple[tuple[str, float], ...] = ()
    degradation: DegradationLevel = DegradationLevel.NONE
    dropped_point_count: int = 0
    stale_point_count: int = 0
    notes: tuple[str, ...] = ()


class AdaptivePoller:
    """Schedules reads across strategies and tiers, never exceeding the trunk budget."""

    def __init__(
        self,
        adapters: tuple[HVACAdapter, ...],
        budgets: BudgetRegistry,
        policies: tuple[TierPolicy, ...] = (),
    ) -> None:
        """Build a poller over a set of adapters and a budget registry.

        TODO: Index adapters by kind, store the budget registry, and default the tier
            policies to the cadences documented on `model.point.Volatility`.
        What's missing: nothing beyond defaults — but the constructor must not start any
            task. Scheduling begins only at `run`, so a poller can be constructed and
            inspected in a test without ever touching a network.
        Acceptance: constructing with an empty adapter tuple succeeds and schedules
            nothing.
        Depends on: `adapters.base.HVACAdapter`, `transport.budget.BudgetRegistry`.
        """
        raise NotImplementedError("poller construction not yet implemented")

    def register(self, ref: PointRef, volatility: Volatility, device_id: str) -> PollEntry:
        """Add a point to the schedule, choosing its cheapest viable strategy.

        TODO: Determine the strategy by asking each adapter's `read_cost`, preferring
            supervisor cache, then COV if a slot is available, then RPM batching.
        What's missing: the strategy choice must be revisited over time, not fixed at
            registration — a COV slot freed by another point should be offered to the
            highest-volatility direct-polled point, which means `register` sets an initial
            strategy and `rebalance` owns the ongoing decision.
        Acceptance: a point available from the supervisor is assigned SUPERVISOR_CACHE; an
            MS/TP-only fast point competes for a COV slot.
        Depends on: `HVACAdapter.read_cost`, `transport.cov.CovManager`.
        """
        raise NotImplementedError("point registration not yet implemented")

    def plan_cycle(
        self,
        now: datetime,
        horizon: timedelta,
    ) -> tuple[tuple[PointRef, ...], ScheduleReport]:
        """Choose which points to read in the next horizon, within budget.

        TODO: Select due points by tier, group by device and trunk, drop or stretch tiers
            until every trunk's `can_afford` passes, and report the degradation.
        What's missing: the tie-break when a trunk is over budget. Drop STATIC first, then
            stretch SLOW, then stretch MEDIUM, and never drop FAST or any point with a
            `priority_boost` — because a fast point that stops updating looks to every
            downstream analytic like equipment that stopped changing, which is a
            *different* and alarming conclusion. Degradation must be visible in the report,
            never silent.
        Acceptance: a 1000-point site on a 38.4k trunk plans a cycle that
            `TrunkBudget.can_afford` accepts, and reports a non-NONE degradation level.
        Depends on: `transport.budget.TrunkBudget.can_afford`, `TierPolicy`.
        """
        raise NotImplementedError("cycle planning not yet implemented")

    async def run_cycle(self, now: datetime) -> tuple[tuple[PointValue, ...], ScheduleReport]:
        """Execute one planned cycle and update adaptive state.

        TODO: Plan, dispatch batched reads per adapter, update `PollEntry` change tracking,
            and return the values with the report.
        What's missing: error backoff. A device that times out must be backed off
            exponentially rather than retried every cycle — a dead controller retried at
            full cadence consumes trunk bandwidth producing nothing, which is the worst
            possible use of a scarce resource.
        Acceptance: a cycle against the simulator returns values for reachable points and
            backs off unreachable ones; the report's achieved rate never exceeds budget.
        Depends on: `plan_cycle`, `adapters.base.read_all_batched`.
        """
        raise NotImplementedError("cycle execution not yet implemented")

    def observe(self, ref: PointRef, value: PointValue) -> PollEntry:
        """Record an observation and update the point's volatility estimate.

        TODO: Compare against `last_value`, update `consecutive_unchanged`, and adjust the
            estimated volatility.
        What's missing: the promotion/demotion hysteresis. Without it a point oscillates
            between tiers every few cycles, which churns the schedule and the COV slots for
            no benefit. Require several consecutive cycles in one direction before moving a
            tier, and never demote below a point's declared `Volatility` floor — a damper
            command that happens to be quiet overnight is still a fast point at 8am.
        Acceptance: twenty unchanged samples demote one tier; a change promotes
            immediately; the declared floor is never breached.
        Depends on: `PollEntry`, `model.point.Volatility`.
        """
        raise NotImplementedError("volatility adaptation not yet implemented")

    def rebalance(self) -> ScheduleReport:
        """Reassign strategies and tiers across the whole schedule.

        TODO: Reconsider COV slot allocation, supervisor availability, and tier
            assignments; return the resulting report.
        What's missing: the COV reallocation policy, which is the highest-leverage decision
            here. Slots should go to the points with the highest change frequency AND the
            highest cost to poll — a fast-changing point already free from the supervisor
            does not need a slot; a fast-changing MS/TP-only point badly does.
        Acceptance: freeing a COV slot reassigns it to the highest-value candidate;
            rebalancing is idempotent when nothing has changed.
        Depends on: `transport.cov.CovManager`, `register`.
        """
        raise NotImplementedError("schedule rebalancing not yet implemented")

    def stale_points(self, now: datetime) -> tuple[tuple[PointRef, timedelta], ...]:
        """Points whose data is older than their tier's `max_interval_s`.

        TODO: Return (ref, age) for every entry exceeding its tier's maximum, worst first.
        What's missing: nothing — but this feeds the API's data-quality surface. A consumer
            must be able to ask "how old is this really?" and get an honest answer rather
            than a value with a fresh-looking timestamp.
        Acceptance: a dropped STATIC tier produces stale entries; a healthy schedule
            produces none.
        Depends on: `TierPolicy`, `PollEntry`.
        """
        raise NotImplementedError("staleness reporting not yet implemented")
