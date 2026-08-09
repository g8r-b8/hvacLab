"""SimAdapter — fixture-driven and replay-driven simulation. The day-one target.

Everything above the adapter layer (semantics, tag store, filter, historian, REST API,
write gate) can be built and tested against this with zero hardware, zero site access,
and zero risk of disturbing a live building. That is not a convenience; commercial BAS
access is scarce, scheduled weeks out, and every mistake is physical.

Three modes:

* **STATIC**   — objects and values straight from a fixture. Deterministic.
* **PHYSICS**  — a crude but directionally honest model: a damper command moves airflow,
                 airflow and valve position move discharge air temp, discharge air temp
                 drags zone temp with a lag. Enough to make control-loop analytics
                 meaningful and to make a broken analytic obviously broken.
* **REPLAY**   — replay a recorded capture from a real site at wall-clock or accelerated
                 speed. The highest-fidelity mode and the one that catches the ugly
                 cases: comms dropouts, out-of-service flags, stuck values.

The simulator MUST also simulate failure, or it teaches the wrong lessons: configurable
comms loss, response latency, MS/TP-shaped throughput limits, out-of-service flags,
reliability faults, and COV slot exhaustion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from hvaclab.adapters.base import (
    AdapterKind,
    DeviceInfo,
    ReadCost,
    Subscription,
    WriteResult,
    WriteTicket,
)
from hvaclab.model.history import TrendSeries
from hvaclab.model.point import PointRef, PointValue
from hvaclab.semantic.profiles.base import DiscoveredObject


class SimMode(StrEnum):
    """How the simulator produces values."""

    STATIC = "static"
    PHYSICS = "physics"
    REPLAY = "replay"


@dataclass(frozen=True, slots=True)
class FaultInjection:
    """Configurable misbehaviour, so the stack is tested against reality not a happy path."""

    comms_loss_probability: float = 0.0
    latency_ms_mean: float = 20.0
    latency_ms_jitter: float = 5.0
    reads_per_second_ceiling: float | None = None
    out_of_service_refs: tuple[str, ...] = ()
    stuck_value_refs: tuple[str, ...] = ()
    max_cov_subscriptions_per_device: int = 6
    apdu_abort_above_points: int | None = None


@dataclass(frozen=True, slots=True)
class SimConfig:
    """Simulator configuration."""

    fixture_path: Path
    mode: SimMode = SimMode.STATIC
    faults: FaultInjection = field(default_factory=FaultInjection)
    time_scale: float = 1.0
    seed: int = 0
    start_time: datetime | None = None


class SimAdapter:
    """In-process adapter backed by a JSON fixture. Conforms to `HVACAdapter`."""

    kind: AdapterKind = AdapterKind.SIM
    name: str = "sim"

    def __init__(self, config: SimConfig) -> None:
        """Create a simulator bound to a fixture, without loading it yet.

        TODO: Store config, seed the RNG deterministically, and leave loading to
            `connect` so construction cannot raise on a missing file.
        What's missing: nothing beyond the constructor discipline — determinism from the
            seed is essential, because a flaky simulator makes every downstream test
            untrustworthy.
        Acceptance: constructing with a nonexistent fixture path succeeds; two adapters
            with the same seed produce identical value sequences in PHYSICS mode.
        Depends on: `SimConfig`.
        """
        raise NotImplementedError("simulator construction not yet implemented")

    async def connect(self) -> None:
        """Load and validate the fixture, building the in-memory device/object model.

        TODO: Parse the fixture JSON into devices, objects, and initial values; validate
            against the fixture schema; initialize the physics or replay clock.
        What's missing: fixture schema validation with useful errors. A hand-edited
            fixture with a typo must fail loudly at connect, not produce a half-populated
            site that silently breaks a tagging test twenty modules away.
        Acceptance: connecting to `fixtures/trane_tracer_sc.json` yields the expected
            device and object counts; a malformed fixture raises with the offending path.
        Depends on: `SimConfig.fixture_path`.
        """
        raise NotImplementedError("fixture loading not yet implemented")

    async def close(self) -> None:
        """Drop simulated subscriptions and release the fixture model.

        TODO: Clear subscriptions and cached state.
        What's missing: nothing.
        Acceptance: close is idempotent; reads after close raise `NotConnectedError`.
        Depends on: `connect`.
        """
        raise NotImplementedError("simulator teardown not yet implemented")

    async def discover_devices(self, timeout_s: float = 10.0) -> tuple[DeviceInfo, ...]:
        """Return devices from the fixture, honouring simulated latency.

        TODO: Map fixture device entries to `DeviceInfo`, applying `FaultInjection`
            latency and comms loss.
        What's missing: realistic `max_apdu_length_accepted` values in the fixture (480
            for the supervisor, 128-480 for MS/TP terminal units) so batching logic is
            exercised against realistic ceilings rather than an unlimited one.
        Acceptance: the Trane fixture yields one supervisor plus its terminal units;
            comms_loss_probability=1.0 yields an empty tuple, not an exception.
        Depends on: `connect`.
        """
        raise NotImplementedError("simulated device discovery not yet implemented")

    async def discover_objects(self, device_id: str) -> tuple[DiscoveredObject, ...]:
        """Return a device's objects as a tagging profile would see them.

        TODO: Map fixture object entries to `DiscoveredObject`, preserving the vendor's
            raw naming exactly.
        What's missing: nothing — but the fidelity requirement is absolute. If the fixture
            "helpfully" normalizes a Trane name, the profile under test is being handed
            the answer and the coverage number becomes fiction.
        Acceptance: names returned from the Trane fixture are terse hyphenated
            abbreviations; the Carrier fixture returns camelCase for the same equipment.
        Depends on: `connect`.
        """
        raise NotImplementedError("simulated object discovery not yet implemented")

    async def read(self, ref: PointRef) -> PointValue:
        """Read one simulated point.

        TODO: Delegate to `read_many((ref,))` and unwrap.
        What's missing: nothing.
        Acceptance: agrees with `read_many` for the same ref.
        Depends on: `read_many`.
        """
        raise NotImplementedError("simulated single read not yet implemented")

    async def read_many(self, refs: tuple[PointRef, ...]) -> tuple[PointValue, ...]:
        """Read many simulated points, applying mode, faults, and throughput ceiling.

        TODO: Produce values per `SimMode`, stamp status flags and reliability from the
            fault config, and sleep to honour latency and `reads_per_second_ceiling`.
        What's missing: the throughput ceiling behaviour, which is the most valuable thing
            this class does. When a caller exceeds the ceiling the simulator must degrade
            the way a real trunk does — rising latency, then timeouts on some refs, NOT a
            clean exception. Code that only ever meets a clean exception will melt a real
            trunk.
        Acceptance: reading 200 points with a 30/s ceiling takes about 6.7s and returns
            some refs with reliability COMMUNICATION_FAILURE.
        Depends on: `connect`, `FaultInjection`, `_step_physics`.
        """
        raise NotImplementedError("simulated batch read not yet implemented")

    async def subscribe(
        self,
        refs: tuple[PointRef, ...],
        lifetime_s: int = 300,
        confirmed: bool = True,
    ) -> tuple[Subscription, ...]:
        """Establish simulated COV subscriptions, enforcing the per-device slot limit.

        TODO: Allocate process ids, honour `max_cov_subscriptions_per_device`, and set
            `renew_at` before `lifetime_s` elapses.
        What's missing: the over-subscription behaviour. A real device does not politely
            queue the 7th subscription — it returns a `resources` error, or worse, accepts
            it and silently drops an older one. Simulate the error case by default and
            make the silent-drop case configurable, because both exist in the field.
        Acceptance: requesting 10 subscriptions on a 6-slot device returns 6 and raises or
            reports failure for 4.
        Depends on: `connect`, `transport.cov.CovManager`.
        """
        raise NotImplementedError("simulated COV subscription not yet implemented")

    async def unsubscribe(self, subscriptions: tuple[Subscription, ...]) -> None:
        """Release simulated subscription slots.

        TODO: Free the slots and drop the subscriptions.
        What's missing: nothing.
        Acceptance: after unsubscribing, the freed slots can be reallocated.
        Depends on: `subscribe`.
        """
        raise NotImplementedError("simulated unsubscribe not yet implemented")

    async def read_history(
        self,
        ref: PointRef,
        start: datetime,
        end: datetime,
        max_samples: int | None = None,
    ) -> TrendSeries:
        """Return simulated trend history, including deliberate gaps.

        TODO: Generate or replay samples across the interval, honouring `max_samples`.
        What's missing: deliberate gap generation. The historian's gap detection and
            backfill logic cannot be developed against perfect data, so the simulator must
            emit buffer-wrap and comms-loss gaps that `history.detect_gaps` should find.
        Acceptance: a 24h request on a fixture with a configured 2h outage returns a
            series whose `coverage_ratio()` is about 0.917 and whose `gaps` has one entry.
        Depends on: `connect`, `model.history`.
        """
        raise NotImplementedError("simulated history not yet implemented")

    async def write(self, ticket: WriteTicket) -> WriteResult:
        """Apply a gated write to the simulated priority array.

        TODO: Validate the ticket signature and expiry, then set the value at
            `ticket.priority` in the simulated point's 16-slot priority array.
        What's missing: full priority array semantics — the effective value is the
            highest-priority (lowest-index) non-null slot, and slots 1 and 2 are reserved
            for manual-life-safety and automatic-life-safety. The simulator must refuse
            priorities 1 and 2 outright, and must let an override persist so the orphaned-
            override detector has something real to find.
        Acceptance: an unsigned ticket raises `WriteRefusedError`; writing at 16 then at 8
            makes 8 effective; writing at priority 1 is refused.
        Depends on: `safety.write_gate.WriteGate`, `safety.audit`.
        """
        raise NotImplementedError("simulated gated write not yet implemented")

    async def release(self, ticket: WriteTicket) -> WriteResult:
        """Write null at a priority, relinquishing the simulated slot.

        TODO: Validate the ticket, clear the slot, and report the newly effective priority.
        What's missing: the relinquish-default behaviour — when every slot is null the
            effective value falls back to `relinquish-default`, which is a real property
            with a real (often surprising) value, not zero.
        Acceptance: releasing the only claim returns `priority_in_effect_after=None` and a
            value equal to the fixture's relinquish default.
        Depends on: `write`.
        """
        raise NotImplementedError("simulated release not yet implemented")

    def read_cost(self, ref: PointRef) -> ReadCost:
        """Simulated read cost, mirroring the fixture's topology.

        TODO: Return FREE for supervisor-cached points, COSTLY for MS/TP-resident ones.
        What's missing: nothing — but the fixture must actually mark which points live
            behind an MS/TP trunk, or the scheduler is being tested against a world where
            every read is free.
        Acceptance: a VAV point behind the simulated trunk returns COSTLY; an AHU point on
            the supervisor returns CHEAP or FREE.
        Depends on: `connect`.
        """
        raise NotImplementedError("simulated read cost not yet implemented")

    def _step_physics(self, elapsed_s: float) -> None:
        """Advance the crude physical model by an elapsed interval.

        TODO: Update airflow from damper position, discharge air temp from valve position
            and airflow, and zone temp as a first-order lag on discharge air temp.
        What's missing: the model constants and a decision on ambition. Keep it
            first-order and directionally correct — the goal is that a stuck damper
            produces a zone that drifts, not that the numbers match a real coil. An
            over-ambitious model becomes its own maintenance burden.
        Acceptance: closing a damper to 0% drives airflow to 0 and zone temp toward
            ambient over minutes, not instantly.
        Depends on: `SimMode.PHYSICS`.
        """
        raise NotImplementedError("simulated physics model not yet implemented")


def load_fixture(path: Path) -> dict[str, object]:
    """Load and validate a simulator fixture.

    TODO: Read JSON, validate structure (site, devices, objects, trunks, history), and
        return the parsed document.
    What's missing: the schema. Both shipped fixtures must validate against it, and the
        validator must enforce that `fixtures/trane_tracer_sc.json` and
        `fixtures/carrier_ivu.json` describe the SAME equipment — same equipment ids,
        same logical points, different vendor names. That equivalence is what makes them
        a normalization test rather than two unrelated files.
    Acceptance: both shipped fixtures load; a fixture missing a required key raises with
        the JSON path to the problem.
    Depends on: nothing.
    """
    raise NotImplementedError("fixture schema and loader not yet implemented")
