r"""Haystack grid encoding: Zinc (text) and Hayson (JSON).

A Haystack *grid* is the universal payload: grid-level metadata, typed columns, rows of
tagged values. Every REST op consumes and produces grids, so this module is the
serialization boundary for the entire API.

Zinc example:

    ver:"3.0" projName:"hq"
    id,dis,point,unit,curVal
    @p1,"AHU-1 DAT",M,"°F",55.2
    @p2,"AHU-1 DAT SP",M,"°F",55.0

Zinc traps:

* `M` is the marker literal; `N` is null; `R` is remove; `NA` is not-available. A missing
  cell and an `N` cell are the same on read but a Python `None` and an absent key must
  encode identically.
* Numbers carry units with no separator: `55.2°F`, `1200cfm`. Unit symbols may contain
  `/`, `³`, `°`, and `_`.
* Strings use backslash escapes and `\\uXXXX`; Zinc is UTF-8 and the degree sign appears
  constantly, so byte-level handling must never assume ASCII.
* `ver:"3.0"` must be the first token. Haystack 4 servers still emit 3.0 grids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hvaclab.semantic.tags import Ref, TagSet


@dataclass(frozen=True, slots=True)
class GridColumn:
    """One grid column: a name plus its own metadata tags."""

    name: str
    meta: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class Grid:
    """A Haystack grid — the universal request/response payload.

    Rows are dicts keyed by column name. A key absent from a row is null.
    """

    columns: tuple[GridColumn, ...] = ()
    rows: tuple[dict[str, Any], ...] = ()
    meta: tuple[tuple[str, Any], ...] = ()
    version: str = "3.0"

    def column_names(self) -> tuple[str, ...]:
        """Column names in declaration order.

        TODO: Project `name` from `columns`.
        What's missing: nothing.
        Acceptance: order matches declaration, not row-key insertion order.
        Depends on: nothing.
        """
        raise NotImplementedError("grid column projection not yet implemented")

    def is_error(self) -> bool:
        """Whether this grid is a Haystack error response.

        TODO: Test for an `err` marker in grid metadata.
        What's missing: nothing — but note that Haystack signals errors *inside* a 200
            grid via `err`, `dis`, and `errTrace` meta, so HTTP status alone is not
            sufficient error detection for a client.
        Acceptance: a grid built by `error_grid` returns True.
        Depends on: `error_grid`.
        """
        raise NotImplementedError("error grid detection not yet implemented")


def grid_from_tagsets(
    tagsets: tuple[tuple[str, TagSet], ...],
    columns: tuple[str, ...] | None = None,
) -> Grid:
    """Build a grid from (entity id, TagSet) pairs.

    TODO: Union all tag names into columns (or use the supplied order), then emit one row
        per entity with an `id` ref column first.
    What's missing: column ordering policy. Haystack clients render columns in grid order,
        so `id`, `dis`, then markers, then values, then refs reads far better than the
        arbitrary union order — and `dis` must always be present even when empty, because
        many clients key their display on it.
    Acceptance: a grid from three points has an `id` column first and one row each;
        entities missing a tag produce absent keys, not None-valued keys.
    Depends on: `semantic.tags.TagSet`.
    """
    raise NotImplementedError("tagset-to-grid construction not yet implemented")


def error_grid(message: str, trace: str = "") -> Grid:
    """Build a Haystack error grid.

    TODO: Emit an empty grid with `err` marker, `dis` message, and optional `errTrace`
        in metadata.
    What's missing: the policy on `errTrace` — never include a Python traceback in a
        response reachable by an untrusted client, since it leaks module paths and, on a
        BAS, sometimes device addresses. Gate it behind a debug flag.
    Acceptance: `is_error()` is True; the grid encodes to valid Zinc.
    Depends on: `Grid`.
    """
    raise NotImplementedError("error grid construction not yet implemented")


def to_zinc(grid: Grid) -> str:
    """Encode a grid as Zinc text.

    TODO: Emit the version/meta line, the column line with per-column meta, then rows.
    What's missing: complete scalar encoding — Ref (`@id "dis"`), Str with escapes, Number
        with glued unit, Bool (`T`/`F`), Marker (`M`), Null (`N`), NA, Remove (`R`),
        DateTime with timezone name (`2026-08-09T14:30:00-05:00 Chicago` — the trailing
        IANA city name is required and is the piece everyone forgets), Date, Time, Uri,
        Coord, XStr, and nested List/Dict.
    Acceptance: `from_zinc(to_zinc(g)) == g` for every fixture grid; a value containing a
        comma, a quote, and a newline round-trips.
    Depends on: `Grid`, `semantic.tags.Ref`.
    """
    raise NotImplementedError("Zinc writer not yet implemented")


def from_zinc(text: str) -> Grid:
    """Parse Zinc text into a grid.

    TODO: Implement the Zinc reader — version line, meta, columns, rows, scalar literals.
    What's missing: strictness policy. Real servers emit slightly nonconforming Zinc
        (unquoted units, missing timezone names on DateTime). Parse leniently, but record
        deviations rather than silently normalizing them, so integration bugs stay
        visible.
    Acceptance: round-trips with `to_zinc`; a malformed grid raises a
        `ZincParseError` carrying the line and column.
    Depends on: `Grid`.
    """
    raise NotImplementedError("Zinc reader not yet implemented")


def to_hayson(grid: Grid) -> dict[str, Any]:
    """Encode a grid as Hayson (Haystack JSON v4).

    TODO: Emit `{"_kind":"grid","meta":{...},"cols":[...],"rows":[...]}` with scalars in
        Hayson form.
    What's missing: the v3-vs-v4 distinction. Haystack 3 JSON encoded scalars as prefixed
        strings ("n:55.2 °F", "r:p1 dis"); Hayson uses `{"_kind":"number","val":55.2,
        "unit":"°F"}`. Emit Hayson, but the reader should accept both, since plenty of
        deployed servers still speak v3.
    Acceptance: `json.dumps` succeeds; `from_hayson(to_hayson(g)) == g`.
    Depends on: `Grid`.
    """
    raise NotImplementedError("Hayson writer not yet implemented")


def from_hayson(payload: dict[str, Any]) -> Grid:
    """Parse a Hayson (or Haystack 3 JSON) payload into a grid.

    TODO: Detect the encoding version and decode scalars accordingly.
    What's missing: the v3 string-prefix decoder and its ambiguity — a v3 `"s:hello"` and
        a plain `"hello"` both mean the string "hello", but a plain `"n:5"` from a v4
        payload is literally the string "n:5". Version detection must be explicit, not
        heuristic per-value.
    Acceptance: round-trips with `to_hayson`; a v3 payload decodes to the same grid as its
        v4 equivalent.
    Depends on: `Grid`, `semantic.tags.Ref`.
    """
    raise NotImplementedError("Hayson reader not yet implemented")


def encode_scalar_zinc(value: Any) -> str:
    """Encode one Python value as a Zinc scalar literal.

    TODO: Dispatch on type across the full Zinc scalar set.
    What's missing: the `Measurement`/unit path — a `model.units.Measurement` must encode
        as a Zinc number with glued unit, which is the whole reason units are modelled
        rather than stringly typed.
    Acceptance: True -> "T"; None -> "N"; Ref("p1") -> "@p1"; a marker sentinel -> "M";
        55.2 with °F -> "55.2°F".
    Depends on: `model.units`, `semantic.tags.Ref`.
    """
    raise NotImplementedError("Zinc scalar encoder not yet implemented")


class ZincParseError(ValueError):
    """Raised on malformed Zinc, carrying line and column."""


@dataclass(frozen=True, slots=True)
class Marker:
    """Singleton sentinel for the Zinc marker value `M`."""

    _tag: str = field(default="marker", repr=False)


MARKER = Marker()
"""The marker sentinel. Use this, not `True`, for Haystack marker tag values."""

__all__ = [
    "MARKER",
    "Grid",
    "GridColumn",
    "Marker",
    "Ref",
    "ZincParseError",
    "encode_scalar_zinc",
    "error_grid",
    "from_hayson",
    "from_zinc",
    "grid_from_tagsets",
    "to_hayson",
    "to_zinc",
]
