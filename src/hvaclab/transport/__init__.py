"""Transport scheduling: bandwidth budgeting, adaptive polling, COV slot management.

The constraint this package exists for: a BACnet MS/TP trunk at 38400 baud sustains
roughly 20-40 point reads per second when healthy, and the native BAS is already using
most of that for its own control loops. We are a guest on that wire.

`budget` models the wire. `polling` schedules within the model. `cov` manages the scarce
subscription slots. All three assume the preferred path is not to touch the trunk at all
(`adapters.supervisor`).
"""

from __future__ import annotations

__all__ = ["budget", "cov", "polling"]
