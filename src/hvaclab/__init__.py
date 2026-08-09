"""hvacLab — vendor-neutral read-first frontend/backend for commercial HVAC BAS.

Layering (lowest to highest):

    adapters/   protocol-facing I/O (sim, supervisor, bacnet, modbus)
    safety/     UUKL blocklist -> write gate -> audit; every write funnels here
    transport/  MS/TP budget math, adaptive polling, COV slot budgeting
    model/      canonical value objects, 223P-shaped topology
    semantic/   Haystack tags, filter language, per-vendor tagging profiles, exports
    store/      tag store + DuckDB historian
    api/        FastAPI app exposing Project Haystack REST ops

Day-one scope is READ-ONLY. Importing this package must never touch a network,
open a socket, or read a file; all such work happens behind explicit calls.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
