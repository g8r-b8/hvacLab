"""Serialization of the semantic model to interchange formats.

`haystack` is the day-one output (Zinc + JSON/Hayson grids, the wire format of the
Haystack REST API). `brick` exists in phase 1 to prove the internal model carries enough
topology to be translated into an RDF ontology — if it can emit Brick, ASHRAE 223P is a
different vocabulary over the same graph, not a rewrite.
"""

from __future__ import annotations

__all__ = ["brick", "haystack"]
