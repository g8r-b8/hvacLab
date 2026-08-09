"""Brick Schema (RDF) export — the translatability proof.

Phase 1 ships this as a stub on purpose. Its existence forces the internal model to keep
what Haystack tags alone would discard: substances, directed connection points,
connections, junctions, and served domain spaces (`model.topology`). If Brick can be
emitted from that model, ASHRAE 223P is a second vocabulary over the same graph rather
than a rewrite of the store.

Brick vs Haystack, in one line each:

* Haystack: flat markers on entities, association by ref tags. Fast to write, lossy.
* Brick: an RDF/OWL class hierarchy with explicit relationships (`brick:feeds`,
  `brick:hasPart`, `brick:isPointOf`, `brick:hasLocation`). Queryable with SPARQL.
* 223P: adds physical modelling — `s223:Substance`, `s223:ConnectionPoint`,
  `s223:Connection`, `s223:cnx`, `s223:hasMedium`, `s223:DomainSpace`. Strictly richer
  than Brick on flow topology, which is exactly what `model.topology` mirrors.

The lossy direction is Haystack -> Brick (association is not flow). The reason we survey
topology at tagging time is to avoid ever having to make that inference in anger.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from hvaclab.model.topology import TopologyGraph
from hvaclab.semantic.tags import TagSet

BRICK_NS = "https://brickschema.org/schema/Brick#"
REF_NS = "https://brickschema.org/schema/Brick/ref#"
S223_NS = "http://data.ashrae.org/standard223#"
QUDT_NS = "http://qudt.org/schema/qudt/"
UNIT_NS = "http://qudt.org/vocab/unit/"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"


class RdfFormat(StrEnum):
    """Serialization formats for the emitted graph."""

    TURTLE = "turtle"
    NTRIPLES = "ntriples"
    JSONLD = "json-ld"
    XML = "xml"


@dataclass(frozen=True, slots=True)
class Triple:
    """One RDF triple as plain strings, so the stub has no rdflib dependency.

    Phase 6 may swap this for `rdflib.Graph` wholesale; keeping the interface at triples
    means that swap does not change any caller.
    """

    subject: str
    predicate: str
    obj: str
    is_literal: bool = False
    datatype: str | None = None


@dataclass(frozen=True, slots=True)
class BrickGraph:
    """An emitted graph plus the entities that could not be translated."""

    triples: tuple[Triple, ...] = ()
    prefixes: tuple[tuple[str, str], ...] = ()
    untranslated: tuple[str, ...] = ()

    def coverage(self) -> float:
        """Fraction of source entities that produced at least one class assertion.

        TODO: Count distinct subjects with an rdf:type triple against total attempted.
        What's missing: the denominator must be passed in or stored — a graph alone
            cannot know how many entities were attempted. Add a field in phase 6.
        Acceptance: a fully translated fixture returns 1.0.
        Depends on: `to_brick`.
        """
        raise NotImplementedError("Brick coverage metric not yet implemented")


def haystack_to_brick_class(tags: TagSet) -> str | None:
    """Map a Haystack tag set to the most specific Brick class URI.

    TODO: Match marker combinations against a Brick class table — {ahu} -> brick:AHU,
        {vav} -> brick:VAV, {discharge,air,temp,sensor} ->
        brick:Discharge_Air_Temperature_Sensor, and so on.
    What's missing: the table, and the specificity rule. Brick class names are ordered
        modifier-then-noun, and picking the most specific matching class (rather than the
        first match) is what makes the export useful; falling back to a general class is
        acceptable, guessing a specific one is not.
    Acceptance: a discharge air temp sensor maps to the specific Brick class; an untagged
        entity returns None rather than brick:Point.
    Depends on: `semantic.tags`.
    """
    raise NotImplementedError("Haystack-to-Brick class table not yet built")


def to_brick(
    entities: tuple[tuple[str, TagSet], ...],
    topology: TopologyGraph | None = None,
    base_uri: str = "http://example.org/site#",
) -> BrickGraph:
    """Emit a Brick graph from tagged entities and, optionally, surveyed topology.

    TODO: Emit rdf:type assertions from `haystack_to_brick_class`, rdfs:label from `dis`,
        brick:isPointOf / brick:hasPoint from equipRef, brick:hasLocation from spaceRef,
        and brick:feeds from topology connections.
    What's missing: the fact that `brick:feeds` can ONLY come from topology. Deriving it
        from `equipRef` would encode the association-equals-flow assumption this whole
        module exists to avoid — if `topology` is None, emit no feeds edges at all and
        list the affected equipment in `untranslated`.
    Acceptance: the Trane and Carrier fixtures emit isomorphic graphs; running with
        topology=None emits zero brick:feeds triples.
    Depends on: `haystack_to_brick_class`, `model.topology`.
    """
    raise NotImplementedError("Brick emission not yet implemented")


def to_223p(
    entities: tuple[tuple[str, TagSet], ...],
    topology: TopologyGraph,
    base_uri: str = "http://example.org/site#",
) -> BrickGraph:
    """Emit an ASHRAE 223P graph. Phase 6 — signature reserved now to constrain the model.

    TODO: Emit s223:Equipment, s223:ConnectionPoint (with s223:hasMedium and inlet/outlet
        subclasses), s223:Connection, s223:Junction, s223:DomainSpace, and s223:cnx
        linkage from `model.topology`.
    What's missing: everything. It is here in phase 1 as a design constraint — if a future
        change to `model.topology` would make this function unimplementable, that change
        is wrong. `topology` is a required argument, not optional, because 223P without
        flow topology is meaningless.
    Acceptance: a 223P SHACL validation of the emitted graph passes on the fixtures.
    Depends on: `model.topology`, `to_brick` infrastructure.
    """
    raise NotImplementedError("223P emission deferred to phase 6")


def serialize(graph: BrickGraph, fmt: RdfFormat = RdfFormat.TURTLE) -> str:
    """Serialize a graph to an RDF text format.

    TODO: Emit prefix declarations then triples; use rdflib when the optional `rdf` extra
        is installed, and a minimal hand-rolled Turtle writer otherwise.
    What's missing: literal escaping and datatype suffixes (`"55.2"^^xsd:double`), plus
        IRI escaping for entity ids that contain characters legal in Haystack refs but
        not in an IRI.
    Acceptance: output parses in rdflib; round-trips to an isomorphic graph.
    Depends on: `BrickGraph`, optional rdflib.
    """
    raise NotImplementedError("RDF serialization not yet implemented")
