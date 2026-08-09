"""Direct BACnet adapter over bacpypes3 — BACnet/IP and, via a router, MS/TP.

Use this only for what the supervisor will not expose (`adapters/supervisor.py` is the
preferred read path). Every read issued here that routes down to MS/TP consumes token
time on a trunk the native BAS is also using for control.

Services this adapter needs:

* **Who-Is / I-Am** — device discovery. Global broadcast reaches only the local subnet;
  remote networks need a directed broadcast through a router or a BBMD.
* **ReadProperty / ReadPropertyMultiple** — RPM is mandatory for anything at scale, and
  is bounded by the device's `max-apdu-length-accepted` and segmentation support.
* **SubscribeCOV / SubscribeCOVProperty** — 4-8 slots per device, lifetimes must be
  renewed, and unconfirmed COV is cheaper but unacknowledged.
* **ReadRange** — bulk TrendLog retrieval, the correct way to backfill history.
* **WriteProperty with priority** — gated; never called except with a `WriteTicket`.

Networking realities:

* **BBMD / foreign device registration.** BACnet/IP broadcasts do not cross IP subnets.
  Either a BBMD exists on the target subnet and we register as a foreign device (with a
  TTL we must re-register before), or we are blind to everything off-subnet. Getting
  added to a customer's BDT is a political process, so foreign device registration is
  usually the practical path.
* **Device instance collisions.** Two devices sharing an instance number is a real and
  ugly failure mode on merged networks; detect and report it rather than serving whichever
  answered first.
* **max_master.** A misconfigured `max-master` (default 127 against an actual highest MAC
  of 12) wastes a large fraction of trunk bandwidth on Poll For Master frames. This
  adapter should read `max-master` where exposed and report it to `transport.budget`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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


@dataclass(frozen=True, slots=True)
class BBMDConfig:
    """Foreign device registration against a BBMD on a remote subnet.

    `ttl_s` must be re-registered well before expiry — a lapsed registration silently
    stops broadcast delivery, so discovery goes quiet while unicast reads keep working,
    which is a confusing failure to diagnose after the fact.
    """

    bbmd_address: str
    ttl_s: int = 300
    reregister_margin_s: int = 60


@dataclass(frozen=True, slots=True)
class BACnetConfig:
    """Local BACnet stack configuration."""

    local_address: str
    device_instance: int = 599999
    device_name: str = "hvaclab"
    vendor_id: int = 0
    port: int = 47808
    bbmd: BBMDConfig | None = None
    apdu_timeout_ms: int = 3000
    apdu_retries: int = 3
    max_apdu_length: int = 1476
    segmentation_supported: str = "segmentedBoth"
    read_only: bool = True


class BACnetAdapter:
    """bacpypes3-backed BACnet adapter. Conforms to `HVACAdapter`."""

    kind: AdapterKind = AdapterKind.BACNET_IP
    name: str = "bacnet"

    def __init__(self, config: BACnetConfig) -> None:
        """Store configuration without touching the network.

        TODO: Retain config; defer all stack construction to `connect`.
        What's missing: nothing — but the discipline matters, because importing or
            constructing this class must never bind a socket. A stray import that starts
            answering Who-Is on a customer network is a serious incident.
        Acceptance: construction binds no socket and never raises on a bad address.
        Depends on: `BACnetConfig`.
        """
        raise NotImplementedError("BACnet adapter construction not yet implemented")

    async def connect(self) -> None:
        """Build the bacpypes3 application, bind, and register as a foreign device.

        TODO: Construct the bacpypes3 Application from the device object and local
            address, then perform foreign device registration when `config.bbmd` is set,
            scheduling re-registration before TTL expiry.
        What's missing: verification of the current bacpypes3 API — the 0.0.x series has
            changed application construction repeatedly, so pin the version in
            pyproject and check the constructor signature rather than trusting memory.
            Also: the local address must be the actual interface address with prefix
            length (e.g. "10.0.1.50/24"), not just an IP, or broadcasts go nowhere.
        Acceptance: connect against a local simulator device answers Who-Is; TTL
            re-registration fires before expiry in a fast-clock test.
        Depends on: `BACnetConfig`, `BBMDConfig`.
        """
        raise NotImplementedError("BACnet stack initialization not yet implemented")

    async def close(self) -> None:
        """Unsubscribe all COV, deregister as foreign device, and release the socket.

        TODO: Cancel subscriptions, send a foreign device deregistration, close the app.
        What's missing: ordering. Unsubscribe MUST happen before the socket closes, or the
            device holds those slots for the full lifetime — on a 6-slot device that can
            lock out the next session for minutes.
        Acceptance: after close, the device reports zero subscriptions from our process id.
        Depends on: `unsubscribe`, `connect`.
        """
        raise NotImplementedError("BACnet teardown not yet implemented")

    async def discover_devices(self, timeout_s: float = 10.0) -> tuple[DeviceInfo, ...]:
        """Broadcast Who-Is and collect I-Am responses.

        TODO: Emit a global Who-Is (optionally range-limited), collect I-Ams until the
            timeout, then read each device's object-name, model, firmware, and APDU limits.
        What's missing: staged discovery. A single unrestricted global Who-Is on a large
            site produces an I-Am storm that can itself disturb the network; sweep in
            instance ranges with pauses. Also detect duplicate device instances and report
            them rather than silently deduplicating.
        Acceptance: discovers a local simulator device; two devices with the same instance
            produce a diagnostic, not a silent drop.
        Depends on: `connect`.
        """
        raise NotImplementedError("Who-Is discovery not yet implemented")

    async def discover_objects(self, device_id: str) -> tuple[DiscoveredObject, ...]:
        """Enumerate a device's object-list and read the properties profiles need.

        TODO: Read `object-list`, then batch-read object-name, description, units,
            present-value, state-text, min/max present value and priority-array presence
            for each object via RPM.
        What's missing: two things. (1) `object-list` on a large device exceeds one APDU
            and must be read by array index (read index 0 for the count, then elements),
            because a device without segmentation cannot return it whole. (2) The property
            set must be read in batches sized to the device's APDU limit, and a device
            that aborts must be retried with a smaller batch, not abandoned.
        Acceptance: enumerates a 400-object controller without an APDU abort; a device
            reporting no segmentation still enumerates via indexed reads.
        Depends on: `connect`, `adapters.base.read_all_batched`.
        """
        raise NotImplementedError("object enumeration not yet implemented")

    async def read(self, ref: PointRef) -> PointValue:
        """ReadProperty for a single point.

        TODO: Issue ReadProperty and map the result plus status-flags and reliability.
        What's missing: nothing beyond `read_many`; this exists for convenience and should
            delegate so behaviour cannot drift between the two paths.
        Acceptance: agrees with `read_many` for the same ref.
        Depends on: `read_many`.
        """
        raise NotImplementedError("BACnet single read not yet implemented")

    async def read_many(self, refs: tuple[PointRef, ...]) -> tuple[PointValue, ...]:
        """ReadPropertyMultiple across devices, batched to APDU limits.

        TODO: Group by device, build RPM requests within the APDU ceiling, and map results
            back to refs, including per-object error entries.
        What's missing: partial-failure handling. An RPM response can carry an error for
            individual properties while succeeding for others; those must become
            `PointValue`s with reliability set, not a discarded batch. And on an
            `abort: segmentation-not-supported`, halve the batch and retry rather than
            failing the whole read.
        Acceptance: a batch containing one nonexistent object returns values for the rest
            plus one error-flagged value; an oversized batch self-shrinks and completes.
        Depends on: `connect`, `adapters.base.read_all_batched`, `transport.budget`.
        """
        raise NotImplementedError("ReadPropertyMultiple not yet implemented")

    async def subscribe(
        self,
        refs: tuple[PointRef, ...],
        lifetime_s: int = 300,
        confirmed: bool = True,
    ) -> tuple[Subscription, ...]:
        """SubscribeCOV / SubscribeCOVProperty with per-device slot budgeting.

        TODO: Allocate unique subscriber process ids, issue subscriptions, and schedule
            renewal before `lifetime_s` expires.
        What's missing: the slot budget must come from `transport.cov.CovManager`, not be
            attempted blindly — over-subscribing returns a `resources` error at best and
            silently evicts an existing subscription at worst. Also: a lifetime of 0 means
            "indefinite" in BACnet, which sounds convenient and is a trap, because the
            subscription then survives our crash and leaks the slot until device restart.
            Never use 0.
        Acceptance: subscribing beyond a device's capacity yields a partial result and a
            diagnostic; renewal occurs before expiry; lifetime is never 0.
        Depends on: `transport.cov.CovManager`, `connect`.
        """
        raise NotImplementedError("SubscribeCOV not yet implemented")

    async def unsubscribe(self, subscriptions: tuple[Subscription, ...]) -> None:
        """Cancel COV subscriptions by re-issuing SubscribeCOV with no lifetime/process.

        TODO: Issue cancellations for each subscription and free the slots in `CovManager`.
        What's missing: robustness — a cancellation to an unreachable device must still
            free our local slot accounting, or a device that reboots leaves us believing
            slots are consumed forever.
        Acceptance: cancelling frees slots locally even when the device does not respond.
        Depends on: `subscribe`.
        """
        raise NotImplementedError("COV cancellation not yet implemented")

    async def read_history(
        self,
        ref: PointRef,
        start: datetime,
        end: datetime,
        max_samples: int | None = None,
    ) -> TrendSeries:
        """ReadRange against the TrendLog object logging this point.

        TODO: Locate the TrendLog whose `log-device-object-property` targets the ref, then
            page through with ReadRange `byTime` requests until the interval is covered.
        What's missing: three real gotchas. (1) TrendLog buffers wrap — data older than
            the buffer is simply gone, and that must be emitted as a `GapReason.BUFFER_WRAP`,
            not as absent rows. (2) Log records carry `log-status` entries (buffer purged,
            log disabled) interleaved with data; those mark gaps and must not be parsed as
            values. (3) Timestamps are in device local time; convert to UTC using the site
            timezone, and expect a DST discontinuity.
        Acceptance: backfilling 24h from a TrendLog with a 2h purge yields a series with
            one BUFFER_WRAP gap; timestamps are tz-aware UTC.
        Depends on: `model.history`, `store.historian`.
        """
        raise NotImplementedError("ReadRange history retrieval not yet implemented")

    async def write(self, ticket: WriteTicket) -> WriteResult:
        """WriteProperty at a priority. Ticketed only.

        TODO: Verify the ticket signature and expiry, refuse if `config.read_only`, then
            issue WriteProperty with `priority`.
        What's missing: the refusal must come FIRST and be unconditional. This function is
            the last line before a physical actuator moves — verify signature, verify
            expiry, verify the point is not on the UUKL blocklist (defence in depth even
            though the gate already checked), verify the priority is in 3..16, and only
            then touch the wire.
        Acceptance: an unsigned, expired, or blocklisted ticket raises `WriteRefusedError`
            without any network traffic; priority 1 or 2 is always refused.
        Depends on: `safety.write_gate.WriteGate`, `safety.blocklist`, `safety.audit`.
        """
        raise NotImplementedError("gated BACnet write not yet implemented")

    async def release(self, ticket: WriteTicket) -> WriteResult:
        """WriteProperty null at a priority to relinquish the slot. Ticketed only.

        TODO: Same verification as `write`, then write `Null` at `ticket.priority`.
        What's missing: verification that the release actually took effect. Read back the
            priority array afterwards — a release that silently failed leaves a permanent
            override, which is the exact failure `safety.write_gate.find_orphaned_overrides`
            exists to catch, and catching it here is cheaper.
        Acceptance: after release, the read-back priority array slot is null.
        Depends on: `write`, `safety.write_gate`.
        """
        raise NotImplementedError("gated BACnet release not yet implemented")

    def read_cost(self, ref: PointRef) -> ReadCost:
        """Classify a read as free, cheap, or trunk-costly.

        TODO: Return COSTLY when the ref's network number identifies an MS/TP network
            behind a router, CHEAP for direct BACnet/IP.
        What's missing: the network-number-to-transport map, built during discovery from
            router I-Am-Router-To-Network responses. Without it every read looks cheap and
            the scheduler will happily saturate a trunk.
        Acceptance: a ref on a routed MS/TP network returns COSTLY; a ref on the IP
            network returns CHEAP.
        Depends on: `discover_devices`, `transport.budget`.
        """
        raise NotImplementedError("read cost classification not yet implemented")

    async def read_priority_array(self, ref: PointRef) -> tuple[float | bool | int | None, ...]:
        """Read a commandable object's 16-slot priority array.

        TODO: ReadProperty `priority-array` and return 16 slots, null where unclaimed.
        What's missing: nothing technically — but this is the highest-value READ-ONLY
            diagnostic in the whole product. Scanning priority arrays site-wide finds
            every orphaned override left by every contractor who ever touched the building,
            with zero write risk. Ship it early.
        Acceptance: returns exactly 16 entries; an object without a priority array raises
            `UnsupportedOperationError`.
        Depends on: `read`, `safety.write_gate.find_orphaned_overrides`.
        """
        raise NotImplementedError("priority array read not yet implemented")

    async def read_max_master(self, device_id: str) -> int | None:
        """Read a router/device's MS/TP `max-master`, or None if not exposed.

        TODO: ReadProperty `max-master` on the device object.
        What's missing: the interpretation, which belongs in `transport.budget` — a
            `max-master` of 127 against an actual highest MAC of 12 means the trunk spends
            a large share of its time on Poll For Master frames for MACs that do not
            exist. Reporting this is a genuine, free finding for a customer.
        Acceptance: returns an int on gear that exposes it; None (not an exception) on
            gear that does not.
        Depends on: `read`, `transport.budget.TrunkBudget`.
        """
        raise NotImplementedError("max-master read not yet implemented")
