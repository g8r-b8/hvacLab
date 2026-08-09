"""Modbus adapter (pymodbus) — secondary path for meters and packaged equipment.

Modbus shows up in commercial HVAC where BACnet does not reach: electric and BTU meters,
chiller and boiler manufacturer gateways, VFDs, and generator controllers. It is a much
poorer protocol for this purpose and the model must not pretend otherwise:

* **No self-description.** There is no object list, no names, no units, no discovery. A
  register map is a PDF from the manufacturer, transcribed by hand. Every point here is
  configured, never discovered — so `discover_objects` returns the configured map and
  `discover_devices` can only probe for responsiveness.
* **No COV.** Polling only. `subscribe` raises `UnsupportedOperationError`.
* **No history.** No trend logs. `read_history` raises; history for Modbus points exists
  only because our historian recorded it.
* **No priority array.** A write is a write; there is no arbitration, no release, and no
  record of who else is writing. This makes Modbus writes *more* dangerous than BACnet
  writes, not less, and the gate must treat them accordingly.
* **Encoding ambiguity is the norm.** A 32-bit float across two 16-bit registers has four
  plausible byte/word orders, and manufacturers use all four. Guessing produces
  beautifully plausible garbage.
* **RTU is a serial bus** with the same contention properties as MS/TP: one transaction at
  a time, and inter-frame silence requirements. It needs budgeting too.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
from hvaclab.model.units import Unit
from hvaclab.semantic.profiles.base import DiscoveredObject


class RegisterKind(StrEnum):
    """Modbus data model areas."""

    COIL = "coil"
    DISCRETE_INPUT = "discreteInput"
    INPUT_REGISTER = "inputRegister"
    HOLDING_REGISTER = "holdingRegister"


class DataEncoding(StrEnum):
    """How a value is laid out across registers. Getting this wrong yields plausible junk."""

    UINT16 = "uint16"
    INT16 = "int16"
    UINT32_BE_WORD = "uint32BeWord"
    UINT32_LE_WORD = "uint32LeWord"
    INT32_BE_WORD = "int32BeWord"
    INT32_LE_WORD = "int32LeWord"
    FLOAT32_BE_WORD = "float32BeWord"
    FLOAT32_LE_WORD = "float32LeWord"
    FLOAT64_BE_WORD = "float64BeWord"
    BITFIELD = "bitfield"
    STRING = "string"


@dataclass(frozen=True, slots=True)
class RegisterSpec:
    """One transcribed register-map entry. This is configuration, never discovery."""

    name: str
    kind: RegisterKind
    address: int
    encoding: DataEncoding = DataEncoding.UINT16
    register_count: int = 1
    scale: float = 1.0
    offset: float = 0.0
    unit: Unit = Unit.NONE
    bit: int | None = None
    writable: bool = False
    description: str = ""


@dataclass(frozen=True, slots=True)
class ModbusDeviceConfig:
    """A Modbus device and its register map."""

    device_id: str
    unit_id: int
    name: str
    registers: tuple[RegisterSpec, ...] = ()
    equip_id: str | None = None
    zero_based_addressing: bool = True
    max_registers_per_read: int = 125


@dataclass(frozen=True, slots=True)
class ModbusConfig:
    """Transport configuration for TCP or RTU."""

    transport: AdapterKind = AdapterKind.MODBUS_TCP
    host: str | None = None
    port: int = 502
    serial_port: str | None = None
    baud: int = 9600
    parity: str = "N"
    stop_bits: int = 1
    timeout_s: float = 3.0
    retries: int = 2
    devices: tuple[ModbusDeviceConfig, ...] = ()
    read_only: bool = True


class ModbusAdapter:
    """pymodbus-backed adapter. Conforms to `HVACAdapter`, with documented gaps."""

    kind: AdapterKind = AdapterKind.MODBUS_TCP
    name: str = "modbus"

    def __init__(self, config: ModbusConfig) -> None:
        """Store configuration without opening the transport.

        TODO: Retain config and index registers by device and by name.
        What's missing: validation that no two registers overlap in a way that makes a
            batched read ambiguous, and that `register_count` matches `encoding` (a
            FLOAT32 with count 1 is a transcription error and will silently read half a
            number).
        Acceptance: construction opens no socket or serial port; a mismatched
            encoding/count raises at construction, where a human is looking.
        Depends on: `ModbusConfig`.
        """
        raise NotImplementedError("Modbus adapter construction not yet implemented")

    async def connect(self) -> None:
        """Open the TCP socket or serial port.

        TODO: Build the pymodbus async client for the configured transport and connect.
        What's missing: RTU-specific setup — inter-frame delay derived from baud (3.5
            character times), and the fact that an RTU bus permits exactly one outstanding
            transaction, so the client must serialize requests across all devices on the
            bus, not just per device.
        Acceptance: TCP connect succeeds against a local simulator; RTU serializes
            concurrent requests.
        Depends on: `ModbusConfig`.
        """
        raise NotImplementedError("Modbus connect not yet implemented")

    async def close(self) -> None:
        """Close the transport.

        TODO: Close the pymodbus client.
        What's missing: nothing.
        Acceptance: idempotent.
        Depends on: `connect`.
        """
        raise NotImplementedError("Modbus teardown not yet implemented")

    async def discover_devices(self, timeout_s: float = 10.0) -> tuple[DeviceInfo, ...]:
        """Probe configured unit ids for responsiveness. There is no real discovery.

        TODO: For each configured device, issue a cheap read and report reachability.
        What's missing: an explicit refusal to scan unit ids that are not configured.
            Sweeping unit ids on a live RTU bus can hang a device that responds badly to
            unexpected function codes, and on a shared bus that is somebody's chiller.
        Acceptance: returns only configured devices, with reachability reflected; never
            probes an unconfigured unit id.
        Depends on: `connect`, `ModbusConfig.devices`.
        """
        raise NotImplementedError("Modbus device probing not yet implemented")

    async def discover_objects(self, device_id: str) -> tuple[DiscoveredObject, ...]:
        """Return the configured register map as discovered objects.

        TODO: Map each `RegisterSpec` to a `DiscoveredObject` with its configured name,
            unit, and writability.
        What's missing: nothing structurally — but tagging profiles must know these names
            came from a hand-transcribed PDF, not a controller, so confidence should not be
            inflated by the tidy names a transcriber chose. Consider a dedicated
            `MatchSource` for configured maps.
        Acceptance: a device with 20 configured registers returns 20 objects.
        Depends on: `ModbusConfig`.
        """
        raise NotImplementedError("Modbus register map projection not yet implemented")

    async def read(self, ref: PointRef) -> PointValue:
        """Read one register-backed point.

        TODO: Delegate to `read_many`.
        What's missing: nothing.
        Acceptance: agrees with `read_many`.
        Depends on: `read_many`.
        """
        raise NotImplementedError("Modbus single read not yet implemented")

    async def read_many(self, refs: tuple[PointRef, ...]) -> tuple[PointValue, ...]:
        """Read many points, coalescing contiguous registers into block reads.

        TODO: Group refs by device and register kind, coalesce into contiguous blocks up
            to `max_registers_per_read`, issue the reads, and decode per `RegisterSpec`.
        What's missing: the coalescing gap policy. Reading across a small hole between two
            wanted registers is usually cheaper than two requests — but some devices fault
            on a read that touches an unimplemented address, so the gap tolerance must be
            per-device and default to conservative (no holes).
        Acceptance: ten contiguous registers issue one request; two registers 500 apart
            issue two; a device with gap tolerance 0 never reads an unmapped address.
        Depends on: `connect`, `decode_registers`.
        """
        raise NotImplementedError("Modbus batched read not yet implemented")

    async def subscribe(
        self,
        refs: tuple[PointRef, ...],
        lifetime_s: int = 300,
        confirmed: bool = True,
    ) -> tuple[Subscription, ...]:
        """Not supported — Modbus has no change-of-value mechanism.

        TODO: Raise `UnsupportedOperationError` with a message pointing at the poller.
        What's missing: nothing. Raising is correct; emulating COV by polling here would
            hide the cost from the scheduler, which is exactly the wrong place to hide it.
        Acceptance: always raises `UnsupportedOperationError`.
        Depends on: `adapters.base.UnsupportedOperationError`.
        """
        raise NotImplementedError("Modbus has no COV; must raise UnsupportedOperationError")

    async def unsubscribe(self, subscriptions: tuple[Subscription, ...]) -> None:
        """No-op — there is nothing to unsubscribe from.

        TODO: Return without action.
        What's missing: nothing. A no-op is correct so shutdown paths need no special case.
        Acceptance: never raises.
        Depends on: nothing.
        """
        raise NotImplementedError("Modbus unsubscribe no-op not yet implemented")

    async def read_history(
        self,
        ref: PointRef,
        start: datetime,
        end: datetime,
        max_samples: int | None = None,
    ) -> TrendSeries:
        """Not supported — Modbus devices have no trend logs.

        TODO: Raise `UnsupportedOperationError`; history for Modbus points comes from our
            own historian.
        What's missing: nothing, but the caller-facing consequence is worth stating —
            Modbus points have no backfill, so their history starts the day we start
            polling, and any gap in our collector is permanent data loss.
        Acceptance: always raises `UnsupportedOperationError`.
        Depends on: `store.historian`.
        """
        raise NotImplementedError("Modbus has no trend logs; must raise UnsupportedOperationError")

    async def write(self, ticket: WriteTicket) -> WriteResult:
        """Gated write to a holding register or coil.

        TODO: Verify the ticket, refuse if `read_only`, encode per `RegisterSpec`, and
            issue write-single or write-multiple.
        What's missing: the priority problem. Modbus has no priority array, so a write is
            absolute and unarbitrated — the equipment's own controller may fight it, and
            there is no way to know who else is writing. The gate must therefore treat a
            Modbus write as permanent-until-manually-reverted and require a stronger
            justification and a shorter expiry than a BACnet write.
        Acceptance: `ticket.priority` other than the configured Modbus pseudo-priority is
            refused; a write on a `read_only` adapter raises before any bus traffic.
        Depends on: `safety.write_gate.WriteGate`, `encode_registers`.
        """
        raise NotImplementedError("gated Modbus write not yet implemented")

    async def release(self, ticket: WriteTicket) -> WriteResult:
        """There is no release on Modbus. Restore the recorded prior value instead.

        TODO: Look up the pre-write value captured by the write gate and write it back.
        What's missing: the pre-write capture, which must therefore happen in `write` —
            read the register before writing and hand the value to the audit log, or
            release is impossible. This is a hard requirement, not an optimization: without
            it a Modbus write cannot be undone at all.
        Acceptance: release after a write restores the exact pre-write raw register value;
            release without a recorded prior value fails loudly.
        Depends on: `write`, `safety.audit`.
        """
        raise NotImplementedError("Modbus restore-prior-value not yet implemented")

    def read_cost(self, ref: PointRef) -> ReadCost:
        """RTU reads are trunk-costly; TCP reads are cheap.

        TODO: Return COSTLY for MODBUS_RTU, CHEAP for MODBUS_TCP.
        What's missing: nothing — but note that an RTU bus behind a TCP gateway is COSTLY
            despite looking like TCP, so this must key on the configured device's actual
            bus, not the adapter's transport.
        Acceptance: RTU returns COSTLY; direct TCP returns CHEAP.
        Depends on: `ModbusConfig`.
        """
        raise NotImplementedError("Modbus read cost not yet implemented")


def decode_registers(raw: tuple[int, ...], spec: RegisterSpec) -> float | bool | int | str | None:
    """Decode raw 16-bit register words into a typed value per the spec.

    TODO: Handle every `DataEncoding`, then apply `scale` and `offset`.
    What's missing: the word/byte order matrix, which is where every Modbus integration
        loses a day. A 32-bit float has four plausible orders (ABCD, CDAB, BADC, DCBA) and
        manufacturers use all four; a wrong order does not error, it returns a number that
        looks like data. Provide a `guess_word_order` helper that tries all four against a
        plausible range and reports which fit — and require a human to confirm.
    Acceptance: known byte sequences decode to known values for all four float orders;
        a BITFIELD with `bit` set returns a bool.
    Depends on: `RegisterSpec`, `DataEncoding`.
    """
    raise NotImplementedError("Modbus register decoding not yet implemented")


def encode_registers(value: float | bool | int | str, spec: RegisterSpec) -> tuple[int, ...]:
    """Encode a typed value into raw register words per the spec.

    TODO: Invert `decode_registers`, applying scale and offset in reverse.
    What's missing: range and precision checks. Writing a value that does not fit the
        encoding must raise before it reaches the bus, and rounding a scaled integer must
        be explicit — a 0.5 rounding difference on a setpoint register is a real
        temperature difference in a real room.
    Acceptance: `decode_registers(encode_registers(v, s), s) == v` within the encoding's
        precision for every encoding; an out-of-range value raises.
    Depends on: `decode_registers`.
    """
    raise NotImplementedError("Modbus register encoding not yet implemented")
