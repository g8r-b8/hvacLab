"""Supervisor adapter — the PREFERRED read path. Read the cache, not the trunk.

Both target systems put a supervisory controller between the IP network and the MS/TP
trunks:

* **Trane Tracer SC+** — polls its downstream UC400/UC600/Symbio devices on its own
  schedule and republishes their points as its own BACnet objects, typically named
  `EQUIP/POINT` (e.g. `VAV_2_14/ZN-T`).
* **Carrier i-Vu / ALC WebCTRL** — same idea; the i-Vu router/controller holds a cached
  copy of downstream data and exposes it over BACnet/IP, plus a tree path that hands over
  the whole site hierarchy for free.

Why this is the default rather than an optimization: a read against the supervisor's
cache costs the MS/TP trunk **nothing**. The supervisor is already polling those points
for its own control and graphics. Routing our own read down to a VAV adds token time to a
trunk that a control loop is depending on. On a 38.4k trunk with 30 devices, our polling
and the BAS's polling are drawing from the same ~20-40 reads/sec, and the BAS wins that
argument by right.

The cost is **staleness**. The supervisor's cache is as old as its own poll cycle —
typically 30-300 seconds for terminal unit data. So the adapter must report cache age
honestly (`PointValue.timestamp` is the CACHE timestamp, not the read time) and the
scheduler must decide when staleness justifies a direct read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

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


class SupervisorVendor(StrEnum):
    """Which supervisory product we are talking to."""

    TRANE_TRACER_SC = "traneTracerSC"
    CARRIER_IVU = "carrierIvu"
    ALC_WEBCTRL = "alcWebCTRL"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CachePolicy:
    """When cached data is good enough, and when to pay for a direct read.

    `max_stale_s` is per volatility tier. A space temperature five minutes old is fine; a
    damper command five minutes old is not the same datum.
    """

    max_stale_fast_s: float = 30.0
    max_stale_medium_s: float = 120.0
    max_stale_slow_s: float = 600.0
    max_stale_static_s: float = 86400.0
    allow_direct_fallback: bool = False
    direct_read_budget_per_min: int = 0


@dataclass(frozen=True, slots=True)
class SupervisorConfig:
    """Connection and behaviour configuration for a supervisory controller."""

    address: str
    device_instance: int
    vendor: SupervisorVendor = SupervisorVendor.UNKNOWN
    cache_policy: CachePolicy | None = None
    trunk_ids: tuple[str, ...] = ()
    read_only: bool = True


@dataclass(frozen=True, slots=True)
class CachedPoint:
    """A supervisor-republished point and what it stands in for downstream."""

    supervisor_ref: PointRef
    downstream_ref: PointRef | None
    equip_prefix: str | None
    cache_age_s: float | None
    trunk_id: str | None


class SupervisorAdapter:
    """Reads a Tracer SC+ or i-Vu cache over BACnet/IP. Conforms to `HVACAdapter`."""

    kind: AdapterKind = AdapterKind.SUPERVISOR
    name: str = "supervisor"

    def __init__(self, config: SupervisorConfig) -> None:
        """Store configuration without touching the network.

        TODO: Retain config and prepare an empty republish map.
        What's missing: nothing beyond the no-I/O-in-constructor discipline.
        Acceptance: construction binds no socket.
        Depends on: `SupervisorConfig`.
        """
        raise NotImplementedError("supervisor adapter construction not yet implemented")

    async def connect(self) -> None:
        """Attach to the supervisor and detect its vendor and republishing convention.

        TODO: Read the supervisor's device object, identify vendor from vendor-id plus
            model name, and set the naming convention used to parse republished points.
        What's missing: vendor detection must not be config-only. Sites get integrated,
            replaced, and upgraded; detecting a Symbio behind what the config calls a
            Tracer SC saves a confusing afternoon.
        Acceptance: connecting to the Trane fixture detects TRANE_TRACER_SC and its
            `EQUIP/POINT` convention.
        Depends on: `adapters.bacnet.BACnetAdapter`.
        """
        raise NotImplementedError("supervisor attach not yet implemented")

    async def close(self) -> None:
        """Release the underlying BACnet stack and any subscriptions.

        TODO: Unsubscribe then close the transport.
        What's missing: nothing.
        Acceptance: idempotent.
        Depends on: `connect`.
        """
        raise NotImplementedError("supervisor teardown not yet implemented")

    async def discover_devices(self, timeout_s: float = 10.0) -> tuple[DeviceInfo, ...]:
        """Enumerate downstream devices as the supervisor knows them.

        TODO: Read the supervisor's device list (its downstream inventory) and emit
            `DeviceInfo` with `behind_supervisor` set and the trunk identified.
        What's missing: the vendor-specific inventory source. Trane exposes downstream
            devices as structured view objects; i-Vu exposes them through the tree. Both
            beat a Who-Is sweep, because they tell you the trunk topology — which devices
            share which RS-485 segment — and that is precisely what `transport.budget`
            needs and what Who-Is cannot tell you.
        Acceptance: discovered terminal units carry a non-null `network_number` and a
            trunk assignment.
        Depends on: `connect`, `map_trunk_topology`.
        """
        raise NotImplementedError("supervisor device inventory not yet implemented")

    async def discover_objects(self, device_id: str) -> tuple[DiscoveredObject, ...]:
        """Enumerate the supervisor's republished objects for a downstream device.

        TODO: List supervisor objects whose republish prefix matches the device, and
            return them with the original downstream names preserved.
        What's missing: the name is doubly informative here — the prefix gives equipment
            identity, the suffix gives the point. Preserve BOTH in `DiscoveredObject`
            (prefix in `device_name`, bare point in `object_name`) so profiles get the
            vendor's real point name rather than a mangled composite.
        Acceptance: `VAV_2_14/ZN-T` yields object_name "ZN-T" and device_name "VAV_2_14".
        Depends on: `semantic.profiles.trane.TraneProfile.parse_republish_prefix`.
        """
        raise NotImplementedError("republished object enumeration not yet implemented")

    async def read(self, ref: PointRef) -> PointValue:
        """Read one point from the supervisor's cache.

        TODO: Delegate to `read_many`.
        What's missing: nothing.
        Acceptance: agrees with `read_many`.
        Depends on: `read_many`.
        """
        raise NotImplementedError("supervisor single read not yet implemented")

    async def read_many(self, refs: tuple[PointRef, ...]) -> tuple[PointValue, ...]:
        """Read many points from the cache via RPM against the supervisor.

        TODO: Translate downstream refs to supervisor refs via the republish map, batch
            with RPM (the supervisor typically accepts a full 1476-byte APDU, so batches
            here can be large), and stamp each `PointValue` with the CACHE timestamp.
        What's missing: the timestamp discipline. Stamping `datetime.now()` would make
            five-minute-old data look fresh and would poison every analytic downstream.
            Where the supervisor exposes a per-point update time, use it; where it does
            not, stamp with the supervisor's known poll cycle as a conservative lower
            bound on freshness and mark the value `source="supervisorCache"`.
        Acceptance: values carry `source="supervisorCache"` and a timestamp no newer than
            the supervisor's last poll; a 200-point batch issues few requests and adds
            zero MS/TP traffic.
        Depends on: `connect`, `build_republish_map`, `CachePolicy`.
        """
        raise NotImplementedError("supervisor cached read not yet implemented")

    async def subscribe(
        self,
        refs: tuple[PointRef, ...],
        lifetime_s: int = 300,
        confirmed: bool = True,
    ) -> tuple[Subscription, ...]:
        """Subscribe to COV on the SUPERVISOR's republished objects.

        TODO: Subscribe against the supervisor rather than the downstream device.
        What's missing: the reason this is strictly better, which should be documented for
            operators: a COV subscription on the supervisor consumes a supervisor slot,
            not one of the terminal unit's precious 4-8 slots, and generates no MS/TP
            traffic at all. Supervisors typically allow far more subscriptions. The
            trade-off is that COV then fires on CACHE change, so it inherits the poll
            cycle's latency.
        Acceptance: subscribing to 50 downstream points consumes zero terminal-unit slots.
        Depends on: `transport.cov.CovManager`, `connect`.
        """
        raise NotImplementedError("supervisor COV subscription not yet implemented")

    async def unsubscribe(self, subscriptions: tuple[Subscription, ...]) -> None:
        """Cancel supervisor-side subscriptions.

        TODO: Cancel and free local slot accounting.
        What's missing: nothing.
        Acceptance: idempotent; slots freed even on device timeout.
        Depends on: `subscribe`.
        """
        raise NotImplementedError("supervisor unsubscribe not yet implemented")

    async def read_history(
        self,
        ref: PointRef,
        start: datetime,
        end: datetime,
        max_samples: int | None = None,
    ) -> TrendSeries:
        """Read trend history from the supervisor's own historian.

        TODO: Use the supervisor's TrendLog objects (or vendor history API) via ReadRange.
        What's missing: the observation that makes this the best backfill path available —
            the supervisor has been trending these points since commissioning, often for
            months, at a resolution the terminal unit's tiny buffer could never hold. One
            ReadRange against the supervisor can backfill more history than any amount of
            polling, at zero trunk cost. This should be the first thing run against a new
            site.
        Acceptance: a 30-day backfill for a VAV zone temp completes without MS/TP traffic.
        Depends on: `adapters.bacnet.BACnetAdapter.read_history`, `store.historian`.
        """
        raise NotImplementedError("supervisor history retrieval not yet implemented")

    async def write(self, ticket: WriteTicket) -> WriteResult:
        """Gated write, routed through the supervisor.

        TODO: Verify ticket, then write to the supervisor's republished object.
        What's missing: a serious caveat that must be documented and enforced. Writing to
            a supervisor's republished object is NOT equivalent to writing to the
            downstream device — the supervisor may apply its own logic, may write at its
            own priority rather than ours, or may reject silently. Where the mapping is not
            known to be transparent, refuse and require the direct BACnet path, so an
            operator never believes they released an override they did not.
        Acceptance: an opaque republish mapping raises `WriteRefusedError` rather than
            writing; a verified-transparent mapping writes and reads back.
        Depends on: `safety.write_gate.WriteGate`, `adapters.bacnet`.
        """
        raise NotImplementedError("gated supervisor write not yet implemented")

    async def release(self, ticket: WriteTicket) -> WriteResult:
        """Gated release through the supervisor, with the same transparency caveat.

        TODO: Verify ticket, write null, and read back the downstream priority array.
        What's missing: the read-back must target the DOWNSTREAM object where possible. A
            release that only clears the supervisor's copy while the terminal unit stays
            overridden is the worst possible outcome: the UI says released, the coil stays
            shut.
        Acceptance: release is confirmed against the downstream priority array, or the
            result reports `succeeded=False` with an explanatory error.
        Depends on: `write`, `adapters.bacnet.BACnetAdapter.read_priority_array`.
        """
        raise NotImplementedError("gated supervisor release not yet implemented")

    def read_cost(self, ref: PointRef) -> ReadCost:
        """Cached points are FREE; anything requiring a route-through is COSTLY.

        TODO: Return FREE when the ref is in the republish map and within the cache
            policy's staleness limit, COSTLY otherwise.
        What's missing: nothing — this is the function the whole scheduler leans on to
            prefer the cheap path.
        Acceptance: a mapped, fresh point returns FREE; an unmapped one returns COSTLY.
        Depends on: `build_republish_map`, `CachePolicy`.
        """
        raise NotImplementedError("supervisor read cost not yet implemented")

    async def build_republish_map(self) -> tuple[CachedPoint, ...]:
        """Map supervisor objects to the downstream points they mirror.

        TODO: Enumerate supervisor objects, parse republish prefixes, and correlate to
            downstream device/object pairs discovered directly or from the inventory.
        What's missing: correlation confidence. The mapping is inferred from names on
            Trane and from the tree on i-Vu, and a wrong mapping means reading the wrong
            VAV — which is invisible until someone notices zone 14's temperature tracking
            zone 15's setpoint. Where a mapping is uncertain, mark it and prefer a direct
            read.
        Acceptance: every mapped pair verifies by reading both and comparing within the
            cache staleness window.
        Depends on: `discover_objects`, `semantic.profiles`.
        """
        raise NotImplementedError("republish mapping not yet implemented")

    async def map_trunk_topology(self) -> dict[str, tuple[str, ...]]:
        """Group downstream devices by the MS/TP trunk they share.

        TODO: Read the supervisor's link/trunk configuration and return
            trunk id -> device ids, with baud and max-master where exposed.
        What's missing: this is the single most valuable thing the supervisor gives us
            that Who-Is cannot. `transport.budget` cannot compute a reads-per-second
            ceiling without knowing which devices contend for the same RS-485 segment;
            without it, budgeting is guesswork and the guess is always optimistic.
        Acceptance: returns each configured trunk with its member devices; the Trane
            fixture yields two trunks with the expected membership.
        Depends on: `connect`, `transport.budget.TrunkBudget`.
        """
        raise NotImplementedError("trunk topology mapping not yet implemented")

    def cache_age(self, ref: PointRef) -> timedelta | None:
        """How stale the supervisor's copy of a point is, or None if unknown.

        TODO: Return the elapsed time since the supervisor last refreshed the point.
        What's missing: unknown must return None, never zero. A None that gets treated as
            fresh is how stale data silently enters analytics; callers must handle the
            unknown case explicitly.
        Acceptance: a just-refreshed point returns a small timedelta; an unmapped point
            returns None.
        Depends on: `build_republish_map`.
        """
        raise NotImplementedError("cache age tracking not yet implemented")
