"""Canonical internal model.

Deliberately richer than Haystack tags: alongside points and equipment we retain
223P-shaped topology (substances, connection points with direction, connections,
junctions, served domain spaces) so Brick and ASHRAE 223P can be emitted later
from the same store without a rewrite.

Everything here is a value object. No I/O, no protocol knowledge, no vendor names.
"""

from __future__ import annotations

__all__ = [
    "alarm",
    "equip",
    "history",
    "point",
    "site",
    "topology",
    "units",
]
