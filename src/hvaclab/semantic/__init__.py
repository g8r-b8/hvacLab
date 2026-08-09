"""Semantic layer: Haystack tag vocabulary, filter language, vendor profiles, exports.

This is where `AI:12 "DA-T"` (Trane) and `AV:301 "dischargeAirTemp"` (Automated Logic)
become the same thing: `point discharge air temp sensor equipRef->@ahu-1`.

Realistic heuristic coverage is 70-85%. The remaining tail is handled as a workflow —
`profiles.base.ReviewQueue` — not as a failure.
"""

from __future__ import annotations

__all__ = ["export", "filter", "profiles", "tags"]
