"""HTTP API: a Project Haystack REST server over the tag store and historian.

Haystack REST is chosen rather than a bespoke API because it is what the tools in this
industry already speak — SkySpark, Haxall, and a range of analytics products can point at
a Haystack endpoint and work immediately. Implementing the standard ops means the product
is consumable on day one without anyone writing an integration.

`haystack_rest` implements the ops; `server.py` is the FastAPI app factory.

Day-one scope is read-only. `pointWrite` is implemented as a *refusal* that explains
itself, so that clients see a well-formed, documented error rather than a 404 — and so
that enabling writes in phase 5 is a configuration change through the safety layer, not a
new code path.
"""

from __future__ import annotations

__all__ = ["haystack_rest", "server"]
