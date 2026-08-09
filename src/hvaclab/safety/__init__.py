"""Safety layer. Every write in the system passes through here or does not happen.

Three components, in mandatory order:

1. `blocklist.LifeSafetyBlocklist` — UL 864 / UUKL deny-by-default. An unknown point is
   blocked, not allowed. This is a structural gate at the adapter boundary, never a UI
   toggle.
2. `write_gate.WriteGate` — the only thing that can mint a `WriteTicket`. Tracks priority
   array claims (1-16), enforces release, and detects orphaned overrides.
3. `audit.AuditLog` — an append-only record of every write attempt, allowed or denied.

The ordering is not advisory. `WriteGate` consults the blocklist before minting, and the
adapter re-checks the blocklist before touching the wire (defence in depth), and the
audit log is written on both the allow and the deny path.

Day-one scope is read-only. This layer exists in phase 1 so that when writes are enabled
in phase 5, there is no plausible code path that bypasses it.
"""

from __future__ import annotations

__all__ = ["audit", "blocklist", "write_gate"]
