"""TrunkBudget — MS/TP bandwidth math, and the saturation guard.

BACnet MS/TP is a token-passing protocol over RS-485. Only the node holding the token may
initiate a request. The token rotates through the masters in MAC address order, so the
time between two opportunities for one node to speak is the **token rotation time**, and
that — not raw baud — is what actually limits throughput.

Key parameters (ASHRAE 135 Clause 9):

* `baud` — 9600, 19200, 38400 (most common), 76800.
* `max_master` — highest MAC address the token is offered to. **Default 127.**
* `max_info_frames` — how many requests a node may send per token hold. Default 1.
* Actual node count and their MAC addresses.

The `max_master` problem, concretely: after passing the token, a node polls for the next
master by sending Poll For Master frames to successive MACs until one answers. If
`max_master` is 127 but the highest actual MAC is 12, every rotation wanders through
MACs 13..127 looking for nodes that do not exist. Each Poll For Master and its timeout
costs real milliseconds. On a lightly populated trunk this can consume a large fraction of
available bandwidth — and it is a free fix: set `max_master` to the highest actual MAC.
Detecting and reporting it is a genuine, zero-risk finding for a customer.

Practical ceilings to sanity-check any model against:

    9600 baud     ~5-10 reads/sec
    19200 baud    ~10-20 reads/sec
    38400 baud    ~20-40 reads/sec      <- the common case
    76800 baud    ~40-80 reads/sec

These are *total trunk* figures, shared with the native BAS. Budget for a fraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

MSTP_HEADER_BYTES: int = 8
"""Preamble (2) + frame type (1) + destination (1) + source (1) + length (2) + header CRC (1)."""

MSTP_FRAME_OVERHEAD_BYTES: int = 10
"""Header plus data CRC (2). Every frame pays this before any payload."""

BITS_PER_OCTET: int = 10
"""8 data bits + start + stop. RS-485 async framing — not 8."""


class TrunkHealth(StrEnum):
    """Assessment of a trunk's headroom."""

    HEALTHY = "healthy"
    LOADED = "loaded"
    SATURATED = "saturated"
    MISCONFIGURED = "misconfigured"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TrunkConfig:
    """Physical and configured parameters of one MS/TP segment.

    `native_bas_utilization` is the share the supervisor's own polling already consumes.
    It is an estimate, and being wrong about it in the optimistic direction is how you
    disturb a building — so default it high and measure it before lowering it.
    """

    trunk_id: str
    baud: int = 38400
    max_master: int = 127
    actual_highest_mac: int | None = None
    node_count: int = 0
    max_info_frames: int = 1
    device_ids: tuple[str, ...] = ()
    native_bas_utilization: float = 0.5
    our_utilization_cap: float = 0.2
    supervisor_device_id: str | None = None


@dataclass(frozen=True, slots=True)
class BudgetAssessment:
    """The computed budget and any findings worth telling an operator about."""

    trunk_id: str
    theoretical_reads_per_sec: float
    usable_reads_per_sec: float
    our_reads_per_sec: float
    token_rotation_ms: float
    poll_for_master_overhead_fraction: float
    health: TrunkHealth
    findings: tuple[str, ...] = ()


class TrunkBudget:
    """Models one MS/TP trunk and enforces our share of it."""

    def __init__(self, config: TrunkConfig) -> None:
        """Bind a budget to a trunk configuration.

        TODO: Store config and precompute the static frame timings for the baud rate.
        What's missing: nothing beyond the config; all derived values are computed lazily
            so a corrected `actual_highest_mac` can be applied without rebuilding.
        Acceptance: constructing does no I/O and cannot raise on a plausible config.
        Depends on: `TrunkConfig`.
        """
        raise NotImplementedError("trunk budget construction not yet implemented")

    def frame_time(self, payload_bytes: int) -> timedelta:
        """Wire time for one MS/TP frame of a given payload size.

        TODO: (MSTP_FRAME_OVERHEAD_BYTES + payload_bytes) * BITS_PER_OCTET / baud.
        What's missing: the inter-frame turnaround. RS-485 is half-duplex, so a node must
            wait for the line to settle (Tturnaround, 40 bit times) before transmitting;
            omitting it underestimates every timing by a consistent and optimistic margin,
            which is the wrong direction to be wrong in.
        Acceptance: a 50-byte payload at 38400 baud is about 15.6ms including overhead and
            turnaround; halving the baud doubles the time.
        Depends on: `TrunkConfig.baud`.
        """
        raise NotImplementedError("MS/TP frame timing not yet implemented")

    def token_rotation_time(self) -> timedelta:
        """Time for the token to complete one circuit of the trunk.

        TODO: Sum per-node token-pass time plus each node's `max_info_frames` allowance
            plus Poll For Master overhead for the unpopulated MAC range.
        What's missing: the Poll For Master model, which is the entire point. For each
            gap between consecutive actual MACs, and for the range above the highest MAC
            up to `max_master`, the token holder sends a Poll For Master and waits
            Tusage_timeout (20ms) for a reply that never comes. With max_master=127 and 12
            actual nodes, that is over a hundred timeouts per rotation — seconds, not
            milliseconds.
        Acceptance: a 12-node trunk with max_master=12 rotates in tens of milliseconds; the
            same trunk with max_master=127 rotates an order of magnitude slower.
        Depends on: `frame_time`, `TrunkConfig`.
        """
        raise NotImplementedError("token rotation model not yet implemented")

    def theoretical_reads_per_sec(self, points_per_request: int = 10) -> float:
        """Upper-bound read throughput assuming exclusive use of the trunk.

        TODO: Requests per second from token rotation and `max_info_frames`, times
            `points_per_request`.
        What's missing: `points_per_request` cannot exceed what the device's APDU allows —
            a 128-byte APDU holds about five analog values — so the caller must pass a
            realistic number or the ceiling is fiction. Consider taking `DeviceInfo`
            instead of an int in phase 3.
        Acceptance: a healthy 38.4k trunk lands in the 20-40 reads/sec band from the module
            docstring; a 9600 trunk lands in 5-10.
        Depends on: `token_rotation_time`, `frame_time`.
        """
        raise NotImplementedError("throughput model not yet implemented")

    def our_budget_reads_per_sec(self) -> float:
        """Reads per second WE may use, after the native BAS's share and our cap.

        TODO: theoretical * (1 - native_bas_utilization) * our_utilization_cap.
        What's missing: nothing arithmetically, but the policy deserves emphasis in code —
            this number should feel uncomfortably small. On a typical 38.4k trunk with the
            defaults it is a couple of reads per second, which is the honest answer, and
            is precisely why `adapters.supervisor` is the preferred path rather than an
            optimization.
        Acceptance: with defaults on a 38.4k trunk the result is single-digit reads/sec.
        Depends on: `theoretical_reads_per_sec`, `TrunkConfig`.
        """
        raise NotImplementedError("budget allocation not yet implemented")

    def assess(self) -> BudgetAssessment:
        """Produce a full assessment with operator-facing findings.

        TODO: Compute all metrics, classify health, and emit findings.
        What's missing: the findings are the deliverable. At minimum: "max_master is 127
            but the highest MAC is 12 — setting max_master to 12 recovers roughly N% of
            trunk bandwidth", "max_info_frames is 1; raising it to 4 on the supervisor
            improves batch efficiency", "38 nodes on one 38.4k trunk exceeds the practical
            limit of ~30", and "baud is 9600 on a trunk with 25 terminal units". Each
            should quantify the recovery, because a number gets acted on and an adjective
            does not.
        Acceptance: a trunk with max_master=127 and highest MAC 12 yields MISCONFIGURED
            with a quantified finding.
        Depends on: `token_rotation_time`, `our_budget_reads_per_sec`.
        """
        raise NotImplementedError("trunk assessment not yet implemented")

    def can_afford(self, point_count: int, within: timedelta) -> bool:
        """Whether a read of N points fits our budget in the given window.

        TODO: Compare `point_count / within` against `our_budget_reads_per_sec`.
        What's missing: nothing — but this must be consulted BEFORE issuing reads, not
            after. A poller that discovers it is over budget by observing timeouts has
            already done the damage.
        Acceptance: 100 points in 1s on a 38.4k trunk returns False; 5 points in 10s
            returns True.
        Depends on: `our_budget_reads_per_sec`.
        """
        raise NotImplementedError("budget affordability check not yet implemented")

    def recommended_max_master(self) -> int | None:
        """The `max_master` value that would eliminate wasted Poll For Master frames.

        TODO: Return `actual_highest_mac` when it is known and lower than `max_master`.
        What's missing: the caveat, which must appear in the recommendation text: raising
            max_master later is required before adding a device with a higher MAC, and a
            device added above max_master will simply never get the token — it appears
            dead. This is a change with a footgun, so recommend it with the caveat attached
            rather than silently applying it (and we never apply it; it is a write).
        Acceptance: max_master=127 with highest MAC 12 recommends 12; an already-correct
            trunk returns None.
        Depends on: `TrunkConfig.actual_highest_mac`.
        """
        raise NotImplementedError("max_master recommendation not yet implemented")


class BudgetRegistry:
    """All trunks on a site, and the routing decision of trunk-vs-supervisor."""

    def __init__(self, budgets: tuple[TrunkBudget, ...] = ()) -> None:
        """Index budgets by trunk id.

        TODO: Build the index and a device-id -> trunk-id reverse map.
        What's missing: the reverse map's source — `adapters.supervisor.map_trunk_topology`
            is the only reliable way to learn which devices share a segment. Without it,
            every device looks independent and budgeting silently over-allocates.
        Acceptance: constructing empty succeeds; a device on a known trunk resolves.
        Depends on: `TrunkBudget`.
        """
        raise NotImplementedError("budget registry not yet implemented")

    def trunk_for_device(self, device_id: str) -> TrunkBudget | None:
        """The trunk a device sits on, or None for IP-resident devices.

        TODO: Reverse-map lookup.
        What's missing: None must mean "on IP", and an unknown device must NOT return
            None — it must return the most constrained trunk or raise, because assuming a
            device is on IP when it is not is exactly the assumption that saturates a
            trunk.
        Acceptance: an MS/TP device resolves to its trunk; an unknown device does not
            silently resolve to None.
        Depends on: `BudgetRegistry.__init__`.
        """
        raise NotImplementedError("device-to-trunk mapping not yet implemented")

    def assess_all(self) -> tuple[BudgetAssessment, ...]:
        """Assess every trunk, worst first.

        TODO: Run `assess` per trunk and sort by health severity.
        What's missing: nothing.
        Acceptance: a site with one misconfigured trunk reports it first.
        Depends on: `TrunkBudget.assess`.
        """
        raise NotImplementedError("site-wide assessment not yet implemented")
