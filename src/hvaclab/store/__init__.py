"""Persistence: the entity/tag store and the DuckDB historian.

`tagstore` holds entities (sites, equipment, points, spaces) with their Haystack tags and
topology, and executes Haystack filter queries against them.

`historian` holds time series in DuckDB — chosen because it is embedded (no server for a
site appliance), columnar (trend queries are overwhelmingly scans and aggregates over one
point over a time range), and handles the analytic SQL a BAS dataset needs without a
separate warehouse.

Both share one database file, which also holds the audit log. One file is one backup.
"""

from __future__ import annotations

__all__ = ["historian", "tagstore"]
