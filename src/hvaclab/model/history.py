"""Trend history: samples, series, and — critically — explicit gaps.

The single most important design decision in this module: **a gap is a first-class
value, not an absence of rows.** BAS trend data is full of holes (controller reboot,
trunk saturation, TrendLog buffer wrap, a technician clearing the log). If a gap is
represented only by missing rows, every consumer silently interpolates across it, and
an eight-hour comms outage becomes a beautifully smooth temperature ramp.

Timezone policy: every timestamp in this model is timezone-AWARE and stored in UTC. The
site's IANA timezone (`Site.timezone`) is applied only at query and render time. This
matters more than it sounds — BAS trend logs are natively in local wall time, so a
US DST spring-forward produces a one-hour hole and a fall-back produces an hour of
duplicate local timestamps that will violate a naive primary key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from hvaclab.model.point import PointRef, Reliability, StatusFlags
from hvaclab.model.units import Unit


class SampleQuality(StrEnum):
    """Provenance and trustworthiness of a stored sample."""

    GOOD = "good"
    UNCERTAIN = "uncertain"
    BAD = "bad"
    OUT_OF_SERVICE = "outOfService"
    OVERRIDDEN = "overridden"
    INTERPOLATED = "interpolated"
    BACKFILLED = "backfilled"


class GapReason(StrEnum):
    """Why a stretch of time has no data. Drives whether a backfill is worth attempting."""

    COMMS_LOSS = "commsLoss"
    DEVICE_RESTART = "deviceRestart"
    BUFFER_WRAP = "bufferWrap"
    LOG_DISABLED = "logDisabled"
    COLLECTOR_DOWN = "collectorDown"
    TRUNK_SATURATED = "trunkSaturated"
    DST_TRANSITION = "dstTransition"
    NOT_YET_BACKFILLED = "notYetBackfilled"
    UNKNOWN = "unknown"


class LoggingMethod(StrEnum):
    """How the source produced the samples — governs how they may be resampled."""

    POLLED = "polled"
    COV = "cov"
    TREND_LOG_POLLED = "trendLogPolled"
    TREND_LOG_COV = "trendLogCov"
    TREND_LOG_TRIGGERED = "trendLogTriggered"
    SIMULATED = "simulated"


@dataclass(frozen=True, slots=True)
class TrendSample:
    """One timestamped observation in a series. Always UTC, always aware."""

    ts: datetime
    value: float | bool | int | str | None
    quality: SampleQuality = SampleQuality.GOOD
    status: StatusFlags = field(default_factory=StatusFlags)
    reliability: Reliability = Reliability.NO_FAULT_DETECTED


@dataclass(frozen=True, slots=True)
class Gap:
    """A known interval with no valid data.

    Half-open [start, end). A gap with `end is None` is open-ended — the data simply has
    not arrived yet, which is different from knowing it never will.
    """

    start: datetime
    end: datetime | None
    reason: GapReason = GapReason.UNKNOWN
    detected_at: datetime | None = None
    backfill_attempted: bool = False

    def duration(self) -> timedelta | None:
        """Length of the gap, or None if open-ended.

        TODO: Return `end - start`, or None when `end is None`.
        What's missing: nothing beyond the None guard.
        Acceptance: a closed gap returns a positive timedelta; an open gap returns None.
        Depends on: nothing.
        """
        raise NotImplementedError("gap duration not yet implemented")


@dataclass(frozen=True, slots=True)
class TrendSeries:
    """A point's history over an interval, with its gaps carried alongside.

    Invariant to enforce in phase 2: no sample timestamp may fall inside any gap, and
    `samples` is sorted ascending by `ts` with no duplicates.
    """

    ref: PointRef
    unit: Unit
    timezone: str
    start: datetime
    end: datetime
    samples: tuple[TrendSample, ...] = ()
    gaps: tuple[Gap, ...] = ()
    method: LoggingMethod = LoggingMethod.POLLED
    interval_s: float | None = None

    def coverage_ratio(self) -> float:
        """Fraction of the requested interval actually covered by data, 0..1.

        TODO: Compute (interval length - total gap duration) / interval length.
        What's missing: clamping open-ended gaps to `end`, and merging overlapping gaps
            before summing so double-counting cannot push the ratio negative.
        Acceptance: no gaps -> 1.0; a gap covering the whole interval -> 0.0; result
            always in [0.0, 1.0].
        Depends on: `Gap.duration`.
        """
        raise NotImplementedError("coverage computation not yet implemented")

    def resample(self, interval: timedelta, agg: str = "mean") -> TrendSeries:
        """Resample onto a fixed grid without interpolating across gaps.

        TODO: Bucket samples onto the grid, aggregate per bucket, and emit no sample for
            buckets that fall inside a gap.
        What's missing: the aggregation set (mean/min/max/first/last/sum) and — the real
            subtlety — COV series are *step* signals, not point samples. A COV series
            must be time-weighted (each value holds until the next), so a plain
            arithmetic mean of COV samples is wrong. Branch on `method`.
        Acceptance: resampling a 1-minute polled series to 15 minutes yields 4 samples
            per hour; a bucket overlapping a gap is absent, not zero and not interpolated.
        Depends on: `Gap`, `LoggingMethod`, `coverage_ratio`.
        """
        raise NotImplementedError("gap-aware resampling not yet implemented")

    def to_local(self) -> TrendSeries:
        """Return a copy with timestamps rendered in the series' site timezone.

        TODO: Convert every timestamp from UTC to the IANA `timezone` using zoneinfo.
        What's missing: an explicit decision about ambiguous and nonexistent local times
            at DST boundaries. Since we convert FROM unambiguous UTC, this direction is
            always well-defined — which is precisely why storage is UTC. Document that
            the reverse direction is not offered.
        Acceptance: a series spanning a fall-back transition renders two distinct samples
            at the same local wall clock hour, with distinct UTC offsets.
        Depends on: `TrendSeries` members, `Site.timezone`.
        """
        raise NotImplementedError("timezone rendering not yet implemented")


def detect_gaps(
    samples: tuple[TrendSample, ...],
    expected_interval: timedelta,
    tolerance: float = 1.5,
) -> tuple[Gap, ...]:
    """Find intervals where samples are missing relative to an expected cadence.

    TODO: Walk consecutive samples and emit a `Gap` wherever the delta exceeds
        `expected_interval * tolerance`.
    What's missing: distinguishing a genuine gap from a legitimately quiet COV series —
        a space temp that simply did not move produces no COV samples for an hour and
        that is not a gap. For COV series, fall back to the subscription's lifetime and
        the device's heartbeat rather than an expected interval.
    Acceptance: an evenly spaced series yields (); removing a contiguous block yields
        exactly one gap with matching bounds; tolerance=1.5 does not flag normal jitter.
    Depends on: `TrendSample`, `Gap`, `LoggingMethod`.
    """
    raise NotImplementedError("gap detection heuristics not yet implemented")


def merge_series(primary: TrendSeries, backfill: TrendSeries) -> TrendSeries:
    """Merge a backfilled series into a primary one, closing gaps where covered.

    TODO: Union the samples (primary wins on timestamp collision), mark backfilled
        samples with SampleQuality.BACKFILLED, and shrink or drop gaps now covered.
    What's missing: the collision policy justification. A TrendLog ReadRange backfill and
        a live poll can disagree at the same timestamp because the TrendLog logged the
        controller's value at its own instant; prefer the TrendLog (device-side truth)
        for historical accuracy but never let a backfill overwrite a live sample marked
        OVERRIDDEN, since that flag is evidence for the orphaned-override detector.
    Acceptance: merging into a series with one gap fully covered by the backfill leaves
        zero gaps; sample count equals the union, not the sum.
    Depends on: `TrendSeries`, `Gap`, `detect_gaps`.
    """
    raise NotImplementedError("series merge policy not yet implemented")
