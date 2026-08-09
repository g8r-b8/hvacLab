"""DuckDB historian — trend storage, backfill, gap detection, and timezone handling.

Why DuckDB: embedded (a site appliance should not need a database server), columnar (BAS
trend queries are almost entirely scans and aggregates over one point across a time
range), and capable of real analytic SQL without a warehouse. One file holds trends, the
tag store snapshot, and the audit log — one file is one backup.

Three things this module must get right, in order of how badly they bite:

**1. Timezones and DST.** Storage is UTC, always, tz-aware. Site local time is applied at
query time from `Site.timezone`. BAS trend logs are natively in device local wall time, so
ingest must convert — and a US spring-forward produces a one-hour hole in local time while
a fall-back produces an hour of *duplicate* local timestamps that will violate a naive
(point, local_ts) primary key. Key on (point, utc_ts). Every scheduled analytic that
buckets by "day" or "occupied hours" must bucket in local time, which means a "day" is
occasionally 23 or 25 hours long, and an energy total that ignores this is wrong twice a
year in a way nobody notices until an audit.

**2. Gaps.** Stored explicitly (`model.history.Gap`), never implied by absent rows. A
query that returns rows must also return the gaps in its interval, or every consumer
interpolates across an outage.

**3. Backfill ordering.** The cheapest history is the supervisor's own historian, then
device TrendLogs via ReadRange, then our own polling. Backfill should always try in that
order — one ReadRange against a Tracer SC+ can retrieve months of trend at zero MS/TP
cost, which no amount of polling will ever match.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from hvaclab.adapters.base import HVACAdapter
from hvaclab.model.history import Gap, TrendSample, TrendSeries
from hvaclab.model.point import PointRef
from hvaclab.model.units import Unit


class BackfillSource(StrEnum):
    """Where backfilled history came from. Cheapest first."""

    SUPERVISOR_HISTORIAN = "supervisorHistorian"
    DEVICE_TREND_LOG = "deviceTrendLog"
    LOCAL_POLL = "localPoll"
    IMPORT_FILE = "importFile"


class RollupInterval(StrEnum):
    """Precomputed rollup grains. Raw data stays raw; rollups accelerate long queries."""

    RAW = "raw"
    MINUTE_15 = "15m"
    HOUR = "1h"
    DAY = "1d"


@dataclass(frozen=True, slots=True)
class HistorianConfig:
    """Storage and retention configuration."""

    db_path: Path
    site_timezone: str = "UTC"
    raw_retention_days: int = 400
    rollup_intervals: tuple[RollupInterval, ...] = (RollupInterval.MINUTE_15, RollupInterval.HOUR)
    batch_insert_size: int = 5000
    compress: bool = True


@dataclass(frozen=True, slots=True)
class BackfillResult:
    """Outcome of a backfill attempt."""

    ref: PointRef
    source: BackfillSource
    samples_written: int
    gaps_closed: int
    gaps_remaining: tuple[Gap, ...] = ()
    start: datetime | None = None
    end: datetime | None = None
    error: str = ""


class Historian:
    """DuckDB-backed trend storage."""

    def __init__(self, config: HistorianConfig) -> None:
        """Open the database and ensure the schema exists.

        TODO: Connect to DuckDB, create the samples, gaps, and rollup tables if absent, and
            stamp a schema version.
        What's missing: the schema itself. Proposal — `samples(point_key VARCHAR, ts
            TIMESTAMPTZ, num DOUBLE, bool BOOLEAN, str VARCHAR, quality VARCHAR, status
            USMALLINT)` with a primary key on (point_key, ts), and `gaps(point_key, start
            TIMESTAMPTZ, end TIMESTAMPTZ, reason VARCHAR, backfill_attempted BOOLEAN)`.
            Separate typed value columns rather than one VARCHAR, because a columnar store
            aggregating over a cast VARCHAR gives up its main advantage.
        Acceptance: opening a fresh path creates the schema; reopening is idempotent; a
            newer schema version raises rather than silently misreading.
        Depends on: `HistorianConfig`.
        """
        raise NotImplementedError("historian schema not yet defined")

    def close(self) -> None:
        """Flush and close the database.

        TODO: Flush pending batches, checkpoint, and close.
        What's missing: the pending-batch flush. Losing a buffered batch on shutdown means
            a gap that no backfill can close for Modbus points, which have no device-side
            history to recover from.
        Acceptance: close is idempotent; buffered samples are durable afterwards.
        Depends on: `write_samples`.
        """
        raise NotImplementedError("historian close not yet implemented")

    def write_samples(self, ref: PointRef, samples: tuple[TrendSample, ...], unit: Unit) -> int:
        """Insert samples, returning the number written.

        TODO: Batch-insert with conflict handling on (point_key, ts), converting values to
            the canonical unit first.
        What's missing: the conflict policy and the unit conversion. A re-poll or a backfill
            can produce a sample at an existing timestamp; the policy from
            `model.history.merge_series` applies (prefer device-side truth, never overwrite
            an OVERRIDDEN sample). And samples MUST be normalized to the canonical unit
            before storage, or a controller swapped from degF to degC mid-year produces a
            trend with a 40-degree step that looks like an equipment fault.
        Acceptance: inserting a duplicate timestamp does not create a second row; a degF
            sample stored to a degC-canonical point is converted.
        Depends on: `model.units.UnitConverter.normalize`, `Historian.__init__`.
        """
        raise NotImplementedError("sample insertion not yet implemented")

    def write_gap(self, ref: PointRef, gap: Gap) -> None:
        """Record a known gap.

        TODO: Insert or merge the gap, coalescing with adjacent gaps for the same point.
        What's missing: coalescing. Repeated detection of the same outage across successive
            collector cycles produces dozens of overlapping gap rows unless adjacent and
            overlapping ranges are merged on write.
        Acceptance: writing two overlapping gaps yields one merged row.
        Depends on: `model.history.Gap`.
        """
        raise NotImplementedError("gap recording not yet implemented")

    def read_series(
        self,
        ref: PointRef,
        start: datetime,
        end: datetime,
        rollup: RollupInterval = RollupInterval.RAW,
        tz: str | None = None,
    ) -> TrendSeries:
        """Read a series with its gaps, optionally rolled up and rendered in local time.

        TODO: Select samples and overlapping gaps for the interval, apply the rollup, and
            build a `TrendSeries`.
        What's missing: gaps MUST be returned alongside samples — a `TrendSeries` with
            samples and an empty `gaps` tuple asserts full coverage, so omitting them here
            silently lies to every consumer. Also, rollups must be gap-aware: a 1h rollup
            bucket that overlaps an outage is absent, not an average of the three samples
            that happened to arrive.
        Acceptance: a query spanning a known outage returns `coverage_ratio() < 1.0` and a
            populated `gaps`; a rollup bucket inside a gap is absent.
        Depends on: `write_samples`, `write_gap`, `model.history.TrendSeries.resample`.
        """
        raise NotImplementedError("series read not yet implemented")

    def detect_and_record_gaps(
        self,
        ref: PointRef,
        start: datetime,
        end: datetime,
    ) -> tuple[Gap, ...]:
        """Scan an interval for gaps and record them.

        TODO: Read samples, call `model.history.detect_gaps` with the point's expected
            cadence, and write the results.
        What's missing: the expected cadence must come from the poller's tier assignment,
            not be guessed from the data — inferring cadence from data that has gaps in it
            is circular and will classify a sparse-but-healthy COV series as one continuous
            gap.
        Acceptance: an interval with a 2h outage yields one gap; a healthy COV series with
            no changes yields none.
        Depends on: `model.history.detect_gaps`, `transport.polling.AdaptivePoller`.
        """
        raise NotImplementedError("gap detection pass not yet implemented")

    async def backfill(
        self,
        ref: PointRef,
        adapters: tuple[HVACAdapter, ...],
        start: datetime,
        end: datetime,
    ) -> BackfillResult:
        """Fill gaps for a point, trying the cheapest source first.

        TODO: Try supervisor historian, then device TrendLog via ReadRange, then give up;
            merge results and close the gaps that are now covered.
        What's missing: the source ordering must be enforced, not merely documented. Also
            handle the partial case honestly — a TrendLog whose buffer wrapped can only
            supply part of the range, and the uncovered remainder must stay recorded as a
            BUFFER_WRAP gap rather than being quietly forgotten because a backfill "ran".
        Acceptance: a 30-day backfill prefers the supervisor and generates zero MS/TP
            traffic; a partially covered range leaves the remainder as a gap with the right
            reason.
        Depends on: `adapters.supervisor.SupervisorAdapter.read_history`,
            `adapters.bacnet.BACnetAdapter.read_history`, `model.history.merge_series`.
        """
        raise NotImplementedError("tiered backfill not yet implemented")

    def build_rollups(
        self,
        ref: PointRef,
        interval: RollupInterval,
        start: datetime,
        end: datetime,
    ) -> int:
        """Compute and store rollups for an interval, returning rows written.

        TODO: Aggregate raw samples into the interval grain (mean, min, max, count,
            time-weighted mean) and store them.
        What's missing: two things. (1) Time-weighted mean, not arithmetic mean, for COV
            series — a step signal averaged arithmetically is wrong in proportion to how
            unevenly it was sampled. (2) Bucket boundaries must be computed in *local* time
            for daily grains, so a DST day is correctly 23 or 25 hours, not always 24.
        Acceptance: an hourly rollup of a 1-minute series matches a direct aggregate; a
            DST-transition day produces the right number of hourly buckets.
        Depends on: `read_series`, `model.history.LoggingMethod`.
        """
        raise NotImplementedError("rollup computation not yet implemented")

    def his_read(
        self,
        refs: tuple[PointRef, ...],
        start: datetime,
        end: datetime,
        rollup: RollupInterval = RollupInterval.RAW,
    ) -> dict[str, TrendSeries]:
        """Multi-point history read backing the Haystack `hisRead` op.

        TODO: Read all requested series efficiently in one pass and key them by point key.
        What's missing: a result size guard. A `hisRead` for 500 points over a year at raw
            resolution is hundreds of millions of rows and will exhaust memory; enforce a
            maximum and either auto-select a coarser rollup or return an error grid
            explaining the limit — silently truncating would be the worst of the three.
        Acceptance: a multi-point read returns one series per ref; an oversized request is
            rejected or downsampled explicitly, never truncated.
        Depends on: `read_series`, `api.haystack_rest.op_his_read`.
        """
        raise NotImplementedError("multi-point history read not yet implemented")

    def retention_sweep(self, now: datetime) -> int:
        """Delete raw samples past retention, returning rows deleted.

        TODO: Delete raw samples older than `raw_retention_days` where a rollup exists.
        What's missing: the guard — never delete raw data for an interval that has no
            rollup, or the history is simply gone. And never touch the audit table, which
            shares this database and has no retention.
        Acceptance: raw data with rollups is deleted; raw data without rollups survives;
            audit rows are untouched.
        Depends on: `build_rollups`, `safety.audit.AuditLog`.
        """
        raise NotImplementedError("retention sweep not yet implemented")

    def coverage(self, ref: PointRef, start: datetime, end: datetime) -> float:
        """Fraction of an interval actually covered by data, 0..1.

        TODO: Delegate to `read_series(...).coverage_ratio()` without materializing samples.
        What's missing: the SQL-side computation — computing coverage by loading every
            sample defeats the purpose when the caller is auditing a whole site.
        Acceptance: agrees with `TrendSeries.coverage_ratio` on the same interval.
        Depends on: `read_series`, `model.history.TrendSeries.coverage_ratio`.
        """
        raise NotImplementedError("coverage query not yet implemented")


def local_day_bounds(day: datetime, tz: str) -> tuple[datetime, datetime]:
    """UTC bounds of a local calendar day, correct across DST transitions.

    TODO: Localize midnight-to-midnight in `tz` and convert both ends to UTC.
    What's missing: the DST cases, which are the entire reason this function exists. A
        spring-forward day is 23 hours, a fall-back day is 25, and the local midnight on a
        spring-forward day in some zones does not exist. Use zoneinfo with explicit fold
        handling; do not add `timedelta(days=1)` to a local timestamp, which is the bug
        this function exists to prevent.
    Acceptance: a US spring-forward day spans 23 hours in UTC; a fall-back day spans 25.
    Depends on: nothing (zoneinfo only).
    """
    raise NotImplementedError("DST-correct day bounds not yet implemented")
