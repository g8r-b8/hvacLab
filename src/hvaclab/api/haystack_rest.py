"""Project Haystack REST operations.

Every op takes a request `Grid` and returns a response `Grid`. Content negotiation covers
Zinc (`text/zinc`) and Hayson JSON (`application/json`). Errors are returned as 200 with
an `err` marker in grid metadata, which is the Haystack convention and surprises everyone
the first time.

Ops implemented here:

    about        server identity and version
    ops          which ops this server supports
    formats      which MIME types this server can read/write
    read         entities matching a filter, or by id
    nav          hierarchical navigation (site -> equip -> point)
    hisRead      history for a point over a range
    hisWrite     write history (import) — gated, phase 5+
    watchSub     create or extend a watch on a set of points
    watchPoll    poll a watch for changed values
    watchUnsub   close a watch
    pointWrite   read or set a priority array slot — GATED, refuses on day one

The **watch** model is the important one and the most commonly misimplemented. A watch is
a server-side subscription: the client subscribes once with `watchSub`, then calls
`watchPoll` repeatedly and receives only what CHANGED. Getting this right is what lets a
dashboard with 500 points refresh every 5 seconds without 500 reads — the server serves
from the poller's cache and the trunk never sees the dashboard at all. A naive
implementation that reads the field devices on every `watchPoll` turns one browser tab
into a saturated MS/TP trunk.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from hvaclab.safety.write_gate import WriteGate
from hvaclab.semantic.export.haystack import Grid
from hvaclab.store.historian import Historian
from hvaclab.store.tagstore import TagStore

SERVER_NAME: str = "hvacLab"
HAYSTACK_VERSION: str = "3.0"
DEFAULT_WATCH_LEASE: timedelta = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class Watch:
    """A server-side watch: a client's subscription to a set of points.

    `lease` must be renewed by each `watchPoll`; an unrenewed watch expires so an
    abandoned browser tab does not hold subscriptions forever. This is exactly the same
    leak pattern as an unreleased COV subscription, one layer up.
    """

    watch_id: str
    dis: str
    point_ids: tuple[str, ...]
    lease: timedelta
    created_at: datetime
    last_poll: datetime
    curval_cache: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class ApiContext:
    """Everything the ops need. Explicit rather than global, so tests can build one."""

    store: TagStore
    historian: Historian
    gate: WriteGate
    read_only: bool = True
    server_version: str = "0.1.0"


def op_about(ctx: ApiContext) -> Grid:
    """`about` — one row describing this server.

    TODO: Return a grid with haystackVersion, serverName, serverTime, serverBootTime,
        productName, productVersion, productUri, tz, and vendorName.
    What's missing: `tz` must be the SITE timezone, not the server's — a site appliance in
        a different timezone from the building it serves is common in hosted deployments,
        and clients render history according to this value.
    Acceptance: returns exactly one row; `haystackVersion` is "3.0"; `tz` is a valid IANA
        name.
    Depends on: `ApiContext`, `semantic.export.haystack.Grid`.
    """
    raise NotImplementedError("about op not yet implemented")


def op_ops(ctx: ApiContext) -> Grid:
    """`ops` — the operations this server supports.

    TODO: Return one row per supported op with `name` and `doc`.
    What's missing: honesty about `pointWrite`. It must be listed (clients need to know the
        endpoint exists and what it does) with documentation stating it refuses in
        read-only mode — omitting it makes clients guess, listing it as fully functional
        makes them fail confusingly.
    Acceptance: every op in this module appears; `pointWrite`'s doc states the day-one
        refusal.
    Depends on: `ApiContext`.
    """
    raise NotImplementedError("ops op not yet implemented")


def op_formats(ctx: ApiContext) -> Grid:
    """`formats` — MIME types this server can read and write.

    TODO: Return rows for text/zinc and application/json with read/write markers.
    What's missing: nothing.
    Acceptance: both formats listed with correct capability markers.
    Depends on: `semantic.export.haystack`.
    """
    raise NotImplementedError("formats op not yet implemented")


def op_read(ctx: ApiContext, request: Grid) -> Grid:
    """`read` — entities by Haystack filter, or by id.

    TODO: Accept either a `filter` (with optional `limit`) in grid meta or a column of
        `id` refs, and return the matching entities as a tagged grid.
    What's missing: the by-id form must return a row for every requested id in the SAME
        ORDER, with an `err` marker on rows whose id was not found — not a shorter grid.
        Clients zip the response against their request, so a silently shorter grid
        misaligns every subsequent column.
    Acceptance: `filter="point and discharge and air and temp"` returns the same logical
        points for the Trane and Carrier fixtures; a by-id read of three ids where one is
        missing returns three rows.
    Depends on: `store.tagstore.TagStore.read`, `semantic.export.haystack.grid_from_tagsets`.
    """
    raise NotImplementedError("read op not yet implemented")


def op_nav(ctx: ApiContext, request: Grid) -> Grid:
    """`nav` — hierarchical navigation for tree UIs.

    TODO: With no `navId`, return sites; with a navId, return that entity's children
        (site -> buildings -> floors -> equip -> points).
    What's missing: the navigation hierarchy must follow the SPATIAL and equipment
        containment model, not the network topology. An operator navigating a building
        does not think "device 1201, object AI:12"; they think "Floor 2, VAV 2-14,
        zone temp". The network view is a separate, diagnostic tree.
    Acceptance: navigating from a site reaches a point in four steps; every returned row
        carries a `navId` for the next level unless it is a leaf.
    Depends on: `store.tagstore.TagStore`, `model.site`.
    """
    raise NotImplementedError("nav op not yet implemented")


def op_his_read(ctx: ApiContext, request: Grid) -> Grid:
    """`hisRead` — history for a point over a range.

    TODO: Parse the `id` and `range` (today, yesterday, an ISO date, a date span, or an
        absolute datetime span), query the historian, and return ts/val rows.
    What's missing: two things. (1) The relative range keywords resolve in SITE LOCAL time
        — "today" for a building in Chicago is not the server's today. (2) Gaps must be
        conveyed. Haystack has no native gap concept, so emit `NA` values at gap boundaries
        and put a coverage note in grid meta; returning only the rows that exist would let
        every client interpolate straight through an outage.
    Acceptance: `range="today"` resolves against the site timezone; a range spanning an
        outage returns a grid whose meta reports coverage < 1.0.
    Depends on: `store.historian.Historian.his_read`, `store.historian.local_day_bounds`.
    """
    raise NotImplementedError("hisRead op not yet implemented")


def op_his_write(ctx: ApiContext, request: Grid) -> Grid:
    """`hisWrite` — import history. Gated; refuses in read-only mode.

    TODO: Refuse with an explanatory error grid while `ctx.read_only`; in phase 5, validate
        and insert via the historian.
    What's missing: even when enabled, this must never overwrite device-sourced samples
        with client-supplied ones without marking provenance. An imported sample and a
        device-read sample are not the same evidentiary quality, and a later dispute about
        what the equipment actually did depends on being able to tell them apart.
    Acceptance: returns an error grid naming read-only mode; never writes while read-only.
    Depends on: `store.historian.Historian.write_samples`, `semantic.export.haystack.error_grid`.
    """
    raise NotImplementedError("hisWrite op not yet implemented")


def op_watch_sub(ctx: ApiContext, request: Grid) -> Grid:
    """`watchSub` — create a watch, or add points to an existing one.

    TODO: With `watchDis` in meta, create a watch and return its `watchId`, `lease`, and
        the current values; with `watchId`, add the requested ids to that watch.
    What's missing: the watch must subscribe through the POLLER, not issue reads itself. A
        new watch on 500 points should register interest with `AdaptivePoller` and serve
        from its cache — if `watchSub` reads the field directly, a dashboard refresh
        becomes a trunk saturation event. Also, watched points should get a `priority_boost`
        in the poller so a human actively looking at a screen gets fresher data than a
        background trend.
    Acceptance: creating a watch on 500 points issues no direct field reads; watched points
        show a poller priority boost.
    Depends on: `transport.polling.AdaptivePoller.register`, `store.tagstore.TagStore`.
    """
    raise NotImplementedError("watchSub op not yet implemented")


def op_watch_poll(ctx: ApiContext, request: Grid) -> Grid:
    """`watchPoll` — return values that CHANGED since the last poll.

    TODO: Look up the watch, renew its lease, diff current values against
        `curval_cache`, and return only changed rows; return all rows when `refresh` is
        marked in meta.
    What's missing: the diff is the entire value of the op, and serving it from the
        poller's cache is what keeps the trunk quiet. Also: an expired or unknown
        `watchId` must return the specific `watchId not found` error the Haystack spec
        defines, because well-behaved clients use that to re-subscribe automatically —
        returning a generic error makes them retry a dead watch forever.
    Acceptance: an unchanged poll returns zero rows; `refresh` returns all; an expired
        watchId returns the specific error.
    Depends on: `op_watch_sub`, `transport.polling.AdaptivePoller`.
    """
    raise NotImplementedError("watchPoll op not yet implemented")


def op_watch_unsub(ctx: ApiContext, request: Grid) -> Grid:
    """`watchUnsub` — close a watch, or remove points from it.

    TODO: With `close` marked, delete the watch and deregister its poller interest; with a
        list of ids, remove just those.
    What's missing: deregistration must actually release the poller's interest and any COV
        slots taken on the watch's behalf. A watch that is closed but leaves its
        subscriptions alive is the same leak as an unreleased COV subscription, and it
        accumulates one browser tab at a time.
    Acceptance: closing a watch releases its COV slots and removes its priority boosts.
    Depends on: `transport.cov.CovManager`, `transport.polling.AdaptivePoller`.
    """
    raise NotImplementedError("watchUnsub op not yet implemented")


def op_point_write(ctx: ApiContext, request: Grid) -> Grid:
    """`pointWrite` — read or set a priority array slot. GATED. Refuses on day one.

    TODO: With only an `id`, return the point's 16-slot priority array (READ — this is
        allowed and valuable). With `level` and `val`, route through
        `WriteGate.request_write` and refuse while `ctx.read_only`.
    What's missing: the asymmetry is deliberate and must be preserved. The READ form of
        `pointWrite` is a legitimate day-one feature — it exposes every override on the
        site, which is the orphaned-override product feature, and it risks nothing. The
        WRITE form must refuse with an explicit error naming read-only mode, and even in
        phase 5 must never construct a ticket itself: it calls the gate, which checks the
        blocklist, validates the priority (never 1 or 2), and audits both outcomes. The
        HTTP layer must not be able to reach an adapter's `write` by any other path.
    Acceptance: the read form returns 16 levels for a commandable point; the write form
        returns an error grid while read-only; a request for level 1 or 2 is refused even
        after writes are enabled.
    Depends on: `safety.write_gate.WriteGate.request_write`,
        `safety.write_gate.validate_priority`, `safety.blocklist.LifeSafetyBlocklist`,
        `safety.audit.AuditLog`.
    """
    raise NotImplementedError("pointWrite op not yet implemented")


def dispatch(ctx: ApiContext, op: str, request: Grid) -> Grid:
    """Route an op name to its handler, returning an error grid for unknown ops.

    TODO: Map names to the `op_*` functions and invoke.
    What's missing: uniform error handling — an unexpected exception in any op must become
        a Haystack error grid, not a 500 with a traceback, and must never leak internal
        paths or device addresses (see `semantic.export.haystack.error_grid`).
    Acceptance: every op in `op_ops` dispatches; an unknown op returns an error grid, not
        an exception.
    Depends on: all `op_*` functions, `semantic.export.haystack.error_grid`.
    """
    raise NotImplementedError("op dispatch not yet implemented")


def parse_range(range_str: str, tz: str, now: datetime) -> tuple[datetime, datetime]:
    """Parse a Haystack `hisRead` range expression into UTC bounds.

    TODO: Handle "today", "yesterday", "2026-08-09", "2026-08-01,2026-08-09", and absolute
        datetime spans.
    What's missing: everything relative resolves in SITE LOCAL time and must survive DST —
        reuse `store.historian.local_day_bounds` rather than reimplementing date
        arithmetic, because "yesterday" on a fall-back day is 25 hours long.
    Acceptance: "today" for a Chicago site returns that site's local midnight bounds in
        UTC; a DST day returns 23 or 25 hours.
    Depends on: `store.historian.local_day_bounds`.
    """
    raise NotImplementedError("range parsing not yet implemented")
