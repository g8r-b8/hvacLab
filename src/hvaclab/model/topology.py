"""Topology: substances, connection points, connections, junctions, and served spaces.

This is the module that makes the "tags today, Brick and 223P tomorrow" claim credible.

Haystack tags are essentially flat assertions about a point ("this is a discharge air
temp on ahu-1"). They cannot express that ahu-1's supply duct splits at a junction, that
one branch feeds vav-2-14 and the other vav-2-15, or that the substance flowing is
return air rather than outside air. ASHRAE 223P can, and Brick partially can.

So we capture it now, at discovery/tagging time, when a human is already looking at the
mechanical schedules. Reconstructing topology later from tags alone is not possible.

223P vocabulary mapped here:
    Substance          what flows (air, chilled water, electricity)
    ConnectionPoint    a port on equipment, with a direction (inlet/outlet/bidirectional)
    Connection         a medium joining two or more connection points (duct, pipe, wire)
    Junction           a point where connections split or merge (tee, plenum, panel)
    DomainSpace        (in site.py) what a connection ultimately serves
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Substance(StrEnum):
    """What flows through a connection.

    Air subtypes are distinct members rather than a marker on a generic AIR because the
    distinction is load-bearing for every airside analytic: an economizer sequence is
    entirely a statement about the ratio of OUTSIDE_AIR to RETURN_AIR in MIXED_AIR.
    """

    AIR = "air"
    OUTSIDE_AIR = "outsideAir"
    RETURN_AIR = "returnAir"
    MIXED_AIR = "mixedAir"
    DISCHARGE_AIR = "dischargeAir"
    SUPPLY_AIR = "supplyAir"
    EXHAUST_AIR = "exhaustAir"
    RELIEF_AIR = "reliefAir"

    WATER = "water"
    CHILLED_WATER = "chilledWater"
    HOT_WATER = "hotWater"
    CONDENSER_WATER = "condenserWater"
    DOMESTIC_WATER = "domesticWater"

    STEAM = "steam"
    CONDENSATE = "condensate"
    REFRIGERANT = "refrigerant"
    GLYCOL_SOLUTION = "glycolSolution"
    NATURAL_GAS = "naturalGas"
    ELECTRICITY = "electricity"
    UNKNOWN = "unknown"


class FlowDirection(StrEnum):
    """Direction of substance flow relative to the equipment owning the connection point."""

    INLET = "inlet"
    OUTLET = "outlet"
    BIDIRECTIONAL = "bidirectional"
    UNKNOWN = "unknown"


class ConnectionMedium(StrEnum):
    """The physical conduit a connection represents."""

    DUCT = "duct"
    PIPE = "pipe"
    WIRE = "wire"
    PLENUM = "plenum"
    OPENING = "opening"
    VIRTUAL = "virtual"


class JunctionKind(StrEnum):
    """How a junction combines or divides flow."""

    TEE = "tee"
    SPLITTER = "splitter"
    MIXER = "mixer"
    HEADER = "header"
    PLENUM = "plenum"
    PANEL = "panel"
    UNKNOWN = "unknown"


class RelationKind(StrEnum):
    """Non-flow relations we retain alongside the flow graph."""

    FEEDS = "feeds"
    SERVES_SPACE = "servesSpace"
    CONTAINS = "contains"
    HAS_PART = "hasPart"
    METERS = "meters"
    CONTROLS = "controls"


@dataclass(frozen=True, slots=True)
class ConnectionPoint:
    """A port on a piece of equipment where a substance enters or leaves.

    `medium_role` distinguishes, say, an AHU's four air ports (outside air inlet, return
    air inlet, supply air outlet, relief air outlet) which would otherwise be
    indistinguishable by substance and direction alone.
    """

    id: str
    equip_id: str
    substance: Substance
    direction: FlowDirection
    medium_role: str = ""
    connection_id: str | None = None


@dataclass(frozen=True, slots=True)
class Connection:
    """A duct/pipe/wire joining connection points. May be many-to-many via junctions."""

    id: str
    substance: Substance
    medium: ConnectionMedium
    source_point_ids: tuple[str, ...] = ()
    target_point_ids: tuple[str, ...] = ()
    junction_ids: tuple[str, ...] = ()
    design_flow: float | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class Junction:
    """Where connections split or merge — a duct tee, a hydronic header, a panel."""

    id: str
    kind: JunctionKind
    substance: Substance
    inlet_connection_ids: tuple[str, ...] = ()
    outlet_connection_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Relation:
    """A typed edge between two model entities (equip, space, domain space, point)."""

    kind: RelationKind
    source_id: str
    target_id: str
    substance: Substance | None = None


@dataclass(frozen=True, slots=True)
class TopologyGraph:
    """The whole flow graph for a site, as an immutable snapshot."""

    site_id: str
    connection_points: tuple[ConnectionPoint, ...] = ()
    connections: tuple[Connection, ...] = ()
    junctions: tuple[Junction, ...] = ()
    relations: tuple[Relation, ...] = ()

    def downstream_equip(
        self,
        equip_id: str,
        substance: Substance | None = None,
    ) -> tuple[str, ...]:
        """Equipment fed by the given equipment, following outlet flow.

        TODO: Walk outlet connection points -> connections -> junctions -> inlet points,
            optionally filtering by substance, and return the reachable equip ids.
        What's missing: cycle handling. Airside loops are real (return air recirculated
            into mixed air), so this must be a visited-set traversal, not recursion.
        Acceptance: on the fixtures, `downstream_equip("ahu-1", Substance.SUPPLY_AIR)`
            returns exactly the VAVs on that AHU's trunk; a cyclic return path
            terminates.
        Depends on: `TopologyGraph` members.
        """
        raise NotImplementedError("flow graph traversal not yet implemented")

    def upstream_equip(self, equip_id: str, substance: Substance | None = None) -> tuple[str, ...]:
        """Equipment feeding the given equipment, following inlet flow.

        TODO: Mirror of `downstream_equip` in the inlet direction.
        What's missing: same cycle handling; plus the answer must be ordered nearest-first
            so the caller can attribute a fault to the closest plausible cause.
        Acceptance: `upstream_equip("vav-2-14")` returns ("ahu-1",) on the fixtures.
        Depends on: `downstream_equip` traversal helpers.
        """
        raise NotImplementedError("flow graph traversal not yet implemented")

    def spaces_served(self, equip_id: str, transitive: bool = True) -> tuple[str, ...]:
        """Domain spaces this equipment conditions, directly or through downstream equip.

        TODO: Collect SERVES_SPACE relations for the equipment and, when transitive,
            for everything `downstream_equip` reaches.
        What's missing: deduplication and the transitive policy. An AHU serves every
            space its VAVs serve, which is what makes "which tenants does this fault
            affect?" answerable — but only transitively.
        Acceptance: an AHU with transitive=True returns the union of its VAVs' spaces;
            with transitive=False returns only its own direct relations.
        Depends on: `downstream_equip`.
        """
        raise NotImplementedError("served-space resolution not yet implemented")

    def validate(self) -> tuple[str, ...]:
        """Return human-readable structural problems in the graph.

        TODO: Detect dangling connection point references, connections with no source or
            no target, substance mismatches across a connection, junctions whose inlet
            and outlet substances differ, and equipment with outlets but no inlets.
        What's missing: severity levels. A substance mismatch is an error; an AHU with no
            modelled outside air inlet is a warning, because plenty of real fixtures are
            partially modelled and we must not refuse to load them.
        Acceptance: a well-formed fixture returns (); deleting one connection point from
            a fixture produces exactly one message naming that id.
        Depends on: all topology dataclasses.
        """
        raise NotImplementedError("topology validation rules not yet defined")


def infer_topology_from_tags(
    equip_ids: tuple[str, ...],
    tag_lookup: dict[str, frozenset[str]],
) -> TopologyGraph:
    """Bootstrap a topology graph from Haystack tags and reference tags alone.

    TODO: Derive connection points and connections from `equipRef`, `ahuRef`, `siteRef`,
        `chilledWaterRef` and friends, so a site tagged only in Haystack still yields a
        partial 223P-shaped graph.
    What's missing: an honest confidence marker on every inferred edge. Tags assert
        association, not flow — `ahuRef` on a VAV means "belongs to", and 95% of the time
        that is also "is fed by", but the 5% (retrofits, cross-connected trunks) is
        exactly where an analytic would confidently blame the wrong AHU. Inferred edges
        must be distinguishable from surveyed ones downstream.
    Acceptance: running this on the Trane fixture and on the Carrier fixture produces
        isomorphic graphs — that isomorphism is the normalization proof.
    Depends on: `semantic.tags`, `store.tagstore`.
    """
    raise NotImplementedError("tag-to-topology inference not yet implemented")
