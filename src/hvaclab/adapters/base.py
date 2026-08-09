"""The adapter Protocol: discover, read, subscribe, history, and gated write.

Two structural decisions:

**1. Writes require a ticket.** `write()` takes a `WriteTicket`, which only
`safety.write_gate.WriteGate` can mint, and which encodes the point, value, priority,
requester, and expiry. An adapter therefore cannot be asked to write by code that has not
gone through the blocklist and the gate. This is a type-level guarantee, not a
convention, and it is why there is no `write(ref, value)` overload anywhere in this
package.

**2. Reads are batch-first.** The primary read verb is `read_many`, not `read`. On
BACnet, one ReadPropertyMultiple for forty points costs a fraction of forty
ReadProperty requests, and on an MS/TP trunk that difference is the difference between
working and being asked to leave the site. `read()` exists for convenience and is defined
as `read_many` of one.

All methods are async. Every I/O path here can block for seconds on a slow trunk.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol, runtime_checkable

from hvaclab.model.history import TrendSeries
from hvaclab.model.point import PointRef, PointValue
from hvaclab.semantic.profiles.base import DiscoveredObject


class AdapterKind(StrEnum):
    """Which transport an adapter speaks — used for budgeting and routing."""

    SIM = "sim"
    BACNET_IP = "bacnetIp"
    BACNET_MSTP = "bacnetMstp"
    SUPERVISOR = "supervisor"
    MODBUS_TCP = "modbusTcp"
    MODBUS_RTU = "modbusRtu"


class ReadCost(StrEnum):
    """How expensive a read is, so the scheduler can prefer cheap paths.

    FREE     served from an already-fresh cache
    CHEAP    BACnet/IP to a supervisor, no trunk traffic
    COSTLY   routed to MS/TP, consumes trunk token time
    """

    FREE = "free"
    CHEAP = "cheap"
    COSTLY = "costly"


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """A discovered device.

    `max_apdu_length_accepted` and `segmentation_supported` are not trivia — they set the
    hard ceiling on ReadPropertyMultiple batch size. An MS/TP device commonly accepts 480
    or even 128 bytes, which is four to twelve points per request, not forty.
    """

    device_id: str
    device_instance: int
    name: str
    vendor_id: int | None = None
    vendor_name: str = ""
    model_name: str = ""
    firmware_revision: str = ""
    address: str = ""
    network_number: int | None = None
    mac_address: str | None = None
    max_apdu_length_accepted: int | None = None
    segmentation_supported: str | None = None
    kind: AdapterKind = AdapterKind.BACNET_IP
    is_router: bool = False
    behind_supervisor: str | None = None
    object_count: int | None = None


@dataclass(frozen=True, slots=True)
class Subscription:
    """An active change-of-value subscription.

    `process_id` is the BACnet subscriberProcessIdentifier and must be unique per
    subscription per device; reusing one silently replaces the existing subscription,
    which is a favourite way to lose half your data.
    """

    id: str
    ref: PointRef
    process_id: int
    confirmed: bool
    lifetime_s: int
    established_at: datetime
    increment: float | None = None
    renew_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class WriteTicket:
    """Authorization to perform exactly one write. Minted only by `WriteGate`.

    `gate_signature` is checked by the adapter before acting. It exists so that an
    adapter can refuse a hand-constructed ticket — the gate is the only thing that can
    produce a valid signature, which makes bypassing the safety layer a runtime failure
    rather than a code review finding.
    """

    ticket_id: str
    ref: PointRef
    value: float | bool | int | str | None
    priority: int
    requester: str
    reason: str
    issued_at: datetime
    expires_at: datetime
    is_release: bool = False
    gate_signature: str = ""


@dataclass(frozen=True, slots=True)
class WriteResult:
    """Outcome of a write attempt, always recorded to the audit log."""

    ticket_id: str
    ref: PointRef
    succeeded: bool
    error: str = ""
    completed_at: datetime | None = None
    priority_in_effect_after: int | None = None
    value_after: float | bool | int | str | None = None


@runtime_checkable
class HVACAdapter(Protocol):
    """What every adapter must provide. Read-first, batch-first, write-gated."""

    kind: AdapterKind
    name: str

    async def connect(self) -> None:
        """Establish transport (bind socket, register as foreign device, open port)."""
        ...

    async def close(self) -> None:
        """Tear down transport, unsubscribing any live COV subscriptions first."""
        ...

    async def discover_devices(self, timeout_s: float = 10.0) -> tuple[DeviceInfo, ...]:
        """Enumerate reachable devices."""
        ...

    async def discover_objects(self, device_id: str) -> tuple[DiscoveredObject, ...]:
        """Enumerate a device's objects with the properties a tagging profile needs."""
        ...

    async def read(self, ref: PointRef) -> PointValue:
        """Read one point. Defined as `read_many` of one; prefer `read_many`."""
        ...

    async def read_many(self, refs: tuple[PointRef, ...]) -> tuple[PointValue, ...]:
        """Read many points, batching per device within protocol limits."""
        ...

    async def subscribe(
        self,
        refs: tuple[PointRef, ...],
        lifetime_s: int = 300,
        confirmed: bool = True,
    ) -> tuple[Subscription, ...]:
        """Establish change-of-value subscriptions, respecting per-device slot limits."""
        ...

    async def unsubscribe(self, subscriptions: tuple[Subscription, ...]) -> None:
        """Cancel subscriptions. Must be called on shutdown or slots leak until expiry."""
        ...

    async def read_history(
        self,
        ref: PointRef,
        start: datetime,
        end: datetime,
        max_samples: int | None = None,
    ) -> TrendSeries:
        """Read logged history for a point, gaps included."""
        ...

    async def write(self, ticket: WriteTicket) -> WriteResult:
        """Perform a gated write. MUST reject a ticket with an invalid signature."""
        ...

    async def release(self, ticket: WriteTicket) -> WriteResult:
        """Relinquish a priority slot by writing null. MUST also be ticketed."""
        ...

    def read_cost(self, ref: PointRef) -> ReadCost:
        """How expensive reading this point is, for the scheduler."""
        ...


class AdapterError(Exception):
    """Base for adapter failures."""


class NotConnectedError(AdapterError):
    """Raised when an operation is attempted before `connect`."""


class UnsupportedOperationError(AdapterError):
    """Raised when an adapter cannot perform an operation (e.g. Modbus has no COV)."""


class WriteRefusedError(AdapterError):
    """Raised when an adapter refuses a write — invalid, expired, or unsigned ticket."""


async def read_all_batched(
    adapter: HVACAdapter,
    refs: tuple[PointRef, ...],
    max_batch: int = 20,
) -> tuple[PointValue, ...]:
    """Read many points across devices, batching per device and respecting APDU limits.

    TODO: Group refs by device, chunk each group to the smaller of `max_batch` and what
        the device's `max_apdu_length_accepted` allows, then issue `read_many` per chunk.
    What's missing: the APDU size estimate, which is the whole point of the function. A
        ReadPropertyMultiple response carries roughly 10-20 bytes per analog value plus
        overhead, so a 480-byte APDU holds ~20-25 points and a 128-byte APDU holds ~5.
        Exceeding it does not fail cleanly — the device returns an abort with reason
        `segmentation-not-supported` and you lose the whole batch, so estimate
        conservatively and shrink adaptively on abort.
    Acceptance: forty points across two devices issue at most four requests; a device
        reporting 128-byte APDU is never sent more than five points per request.
    Depends on: `HVACAdapter.read_many`, `DeviceInfo.max_apdu_length_accepted`,
        `transport.budget.TrunkBudget`.
    """
    raise NotImplementedError("APDU-aware batching not yet implemented")


def estimate_read_duration(
    refs: tuple[PointRef, ...],
    kind: AdapterKind,
    baud: int = 38400,
) -> timedelta:
    """Estimate wall-clock time to read a set of points on a given transport.

    TODO: For MS/TP, derive from `transport.budget` token rotation math; for IP, use a
        flat per-request latency.
    What's missing: the MS/TP model, which is not simply bytes/baud — a request must wait
        for the token, and token rotation time scales with the number of masters on the
        trunk. This function is what lets the poller refuse a schedule it cannot meet
        instead of silently falling behind.
    Acceptance: 100 points on a 38.4k MS/TP trunk estimates in the seconds, not
        milliseconds; the same 100 on BACnet/IP estimates well under a second.
    Depends on: `transport.budget.TrunkBudget`.
    """
    raise NotImplementedError("read duration model not yet implemented")
