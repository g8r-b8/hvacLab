"""Protocol-facing adapters.

One Protocol (`base.HVACAdapter`), four implementations:

* `sim`         — fixture/replay, zero hardware. THE day-one development target.
* `supervisor`  — PREFERRED production read path: Tracer SC+ / i-Vu cached objects over
                  BACnet/IP, avoiding a route down to MS/TP entirely.
* `bacnet`      — direct bacpypes3 BACnet/IP + MS/TP, for what the supervisor won't expose.
* `modbus`      — secondary, for meters and chiller gateways.

Every adapter's `write` is gated: it must delegate to `safety.write_gate.WriteGate` and
must not expose a raw write path. The Protocol is written so that a conforming adapter
cannot accept a write without a `WriteTicket` issued by the gate.
"""

from __future__ import annotations

__all__ = ["bacnet", "base", "modbus", "sim", "supervisor"]
