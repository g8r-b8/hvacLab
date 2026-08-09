"""Per-vendor tagging profiles.

A profile turns discovered BACnet objects into Haystack tag candidates using naming
heuristics, object-type priors, unit priors, and equipment context. Profiles are
deliberately per-vendor: Trane's abbreviation style ("DA-T", "SA-FLOW", "ZN-T") and
Automated Logic's camelCase style ("dischargeAirTemp", "supplyAirFlow", "zoneTemp") need
different tokenizers, and a single "smart" regex set that tries to cover both is how you
get 40% coverage instead of 80%.

Expect 70-85% coverage. The tail is a workflow (`base.ReviewQueue`), not a defect.
"""

from __future__ import annotations

__all__ = ["base", "carrier_alc", "trane"]
