"""TagStore — entities, tags, topology, and Haystack filter query execution.

The store holds every entity in the model (site, building, floor, space, domain space,
equip, point, device, connection, junction) as an id plus a `TagSet` plus its topology
edges. It is the `FilterContext` the Haystack filter language evaluates against.

Two properties that matter more than they look:

**Refs must be resolvable in both directions.** `equipRef` on a point gives point ->
equip; the store must also answer equip -> points without a scan, because that is the
single most common query in the entire product ("show me this AHU").

**The store keeps topology alongside tags.** `model.topology` edges are not derived from
tags and cannot be recovered from them (see `semantic.export.brick`), so they are stored
as first-class edges. Every export — Haystack, Brick, 223P — reads from this one store.

Phase 2 can implement this entirely in memory over the fixtures. The interface is written
so that swapping to DuckDB-backed storage later changes no caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from hvaclab.model.topology import Relation, TopologyGraph
from hvaclab.semantic.tags import TagSet


class EntityKind(StrEnum):
    """What kind of thing an entity is. Redundant with tags, indexed for speed."""

    SITE = "site"
    BUILDING = "building"
    FLOOR = "floor"
    SPACE = "space"
    DOMAIN_SPACE = "domainSpace"
    EQUIP = "equip"
    POINT = "point"
    DEVICE = "device"
    CONNECTION = "connection"
    JUNCTION = "junction"
    TRUNK = "trunk"


@dataclass(frozen=True, slots=True)
class Entity:
    """One stored entity: identity, kind, tags, and provenance.

    `tag_source` and `tagged_at` exist so a low-confidence auto-tag is distinguishable
    from a human decision forever — without that, a review queue resolution is
    indistinguishable from a guess a week later.
    """

    id: str
    kind: EntityKind
    tags: TagSet
    dis: str = ""
    tag_source: str = ""
    tag_confidence: float | None = None
    tagged_at: datetime | None = None
    vendor_name: str = ""
    adapter: str = ""


class TagStore:
    """Entity + tag storage with Haystack filter query execution.

    Implements `semantic.filter.FilterContext`.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        """Create a store, in memory when `db_path` is None.

        TODO: Initialize entity, tag, ref, and topology indexes; open DuckDB when a path
            is given.
        What's missing: the index set, which determines whether filters are usable at
            scale. At minimum: id -> Entity, tag -> set of ids (inverted index for marker
            conjunctions), (ref tag, target id) -> set of source ids (reverse refs), and
            kind -> set of ids.
        Acceptance: an in-memory store constructs with no arguments and no I/O.
        Depends on: `Entity`.
        """
        raise NotImplementedError("tag store indexes not yet built")

    def put(self, entity: Entity) -> None:
        """Insert or replace an entity, maintaining every index.

        TODO: Write the entity and update all indexes, removing stale index entries when
            replacing.
        What's missing: stale index cleanup on replace, which is the classic bug — an
            entity re-tagged without `co2` still appears in the `co2` inverted index and
            silently pollutes every query that uses it.
        Acceptance: replacing an entity with fewer tags removes it from the dropped tags'
            indexes.
        Depends on: `TagStore.__init__`.
        """
        raise NotImplementedError("entity upsert not yet implemented")

    def get(self, entity_id: str) -> Entity | None:
        """Fetch one entity by id, or None.

        TODO: Index lookup.
        What's missing: nothing.
        Acceptance: a stored entity round-trips; an unknown id returns None.
        Depends on: `put`.
        """
        raise NotImplementedError("entity lookup not yet implemented")

    def tags_of(self, entity_id: str) -> frozenset[str]:
        """All tags on an entity with conjunct implications expanded (FilterContext).

        TODO: Return the precomputed implication closure of the entity's tags.
        What's missing: precomputation at `put` time rather than per query — filters call
            this for every candidate entity, so recomputing the closure here would make
            every query quadratic in the vocabulary.
        Acceptance: an entity tagged with a conjunct answers for all its implied tags;
            unknown entity returns an empty frozenset, not an exception.
        Depends on: `semantic.tags.TagVocabulary.implied_tags`.
        """
        raise NotImplementedError("tag closure lookup not yet implemented")

    def value_of(self, entity_id: str, tag: str) -> Any | None:
        """A value tag's payload (FilterContext).

        TODO: Delegate to the entity's `TagSet.get`.
        What's missing: nothing.
        Acceptance: agrees with `TagSet.get`; unknown entity returns None.
        Depends on: `get`.
        """
        raise NotImplementedError("value tag lookup not yet implemented")

    def deref(self, entity_id: str, ref_tag: str) -> str | None:
        """Follow a ref tag to another entity id (FilterContext).

        TODO: Read the ref tag and return the target id when the target exists.
        What's missing: the decision on dangling refs. Return the id even if the target is
            missing, or return None? Return None — `filter.HasNode` documents that a broken
            ref evaluates False, and returning a phantom id would make it evaluate against
            an empty tag set, which happens to give the same answer but for the wrong
            reason and breaks the moment someone adds a `not` in front of it.
        Acceptance: a valid equipRef resolves; a dangling one returns None.
        Depends on: `get`.
        """
        raise NotImplementedError("ref dereference not yet implemented")

    def all_entity_ids(self) -> tuple[str, ...]:
        """Every entity id (FilterContext).

        TODO: Return the id index's keys in a stable order.
        What's missing: stable ordering, so query results are reproducible in tests.
        Acceptance: order is deterministic across runs.
        Depends on: `put`.
        """
        raise NotImplementedError("entity enumeration not yet implemented")

    def read(self, filter_source: str, limit: int | None = None) -> tuple[Entity, ...]:
        """Execute a Haystack filter and return matching entities.

        TODO: Parse the filter, use the inverted index to narrow marker conjunctions, then
            evaluate the residual filter over the narrowed candidate set.
        What's missing: the index push-down. `semantic.filter.select` does a full scan by
            design; this method is where that becomes fast. Extract the top-level marker
            conjunction from the AST, intersect the inverted-index sets, and only then
            evaluate — on a 5,000-point site the difference is milliseconds versus seconds.
        Acceptance: `read("point and discharge and air and temp")` returns the same set for
            the Trane and Carrier fixtures — the headline normalization test.
        Depends on: `semantic.filter.parse`, `tags_of`, `deref`.
        """
        raise NotImplementedError("filter query execution not yet implemented")

    def points_of(self, equip_id: str) -> tuple[Entity, ...]:
        """Every point whose `equipRef` targets this equipment.

        TODO: Reverse-ref index lookup.
        What's missing: nothing — but this must be an index hit, never a scan. It is the
            most-called query in the product.
        Acceptance: an AHU returns exactly its points; ordering is stable.
        Depends on: `put` reverse-ref index.
        """
        raise NotImplementedError("reverse ref lookup not yet implemented")

    def put_relation(self, relation: Relation) -> None:
        """Store a topology edge.

        TODO: Append to the relation index in both directions.
        What's missing: nothing — but note relations are stored, never inferred from tags,
            for the reasons in `semantic.export.brick`.
        Acceptance: a stored FEEDS relation is retrievable from both endpoints.
        Depends on: `TagStore.__init__`.
        """
        raise NotImplementedError("relation storage not yet implemented")

    def topology(self, site_id: str) -> TopologyGraph:
        """Assemble the topology graph for a site.

        TODO: Collect connection points, connections, junctions, and relations for the site
            into a `TopologyGraph`.
        What's missing: nothing structural — but the assembled graph should be cached and
            invalidated on write, because Brick/223P export and every upstream/downstream
            query rebuild it otherwise.
        Acceptance: the assembled graph passes `TopologyGraph.validate()` on the fixtures.
        Depends on: `put_relation`, `model.topology`.
        """
        raise NotImplementedError("topology assembly not yet implemented")

    def apply_candidates(
        self,
        candidates: tuple[Any, ...],
        threshold: float = 0.6,
    ) -> tuple[int, int]:
        """Apply auto-applicable tag candidates, returning (applied, deferred) counts.

        TODO: For each `TagCandidate`, apply when `is_auto_applicable(threshold)`, else
            defer to the review queue.
        What's missing: the provenance stamp. Every applied candidate must record
            `tag_source` (the profile name), `tag_confidence`, and `tagged_at` on the
            Entity, so a later coverage audit can distinguish 3,000 human-reviewed points
            from 3,000 guesses.
        Acceptance: a 0.95-confidence candidate applies with provenance; a 0.4-confidence
            one defers; a lifeSafety-tagged candidate always defers.
        Depends on: `semantic.profiles.base.TagCandidate`, `put`.
        """
        raise NotImplementedError("candidate application not yet implemented")

    def snapshot(self, path: Path) -> int:
        """Persist the whole store to disk, returning the entity count.

        TODO: Write entities, tags, and relations to DuckDB tables (or JSON in phase 2).
        What's missing: a schema version stamp, so a store written by an older phase can be
            detected and migrated rather than misread.
        Acceptance: `snapshot` then `load` round-trips every entity and relation.
        Depends on: `all_entity_ids`, `topology`.
        """
        raise NotImplementedError("store snapshot not yet implemented")

    def load(self, path: Path) -> int:
        """Load a persisted store, returning the entity count.

        TODO: Read the tables back and rebuild every index.
        What's missing: index rebuild must be complete — a store loaded with a stale or
            partial inverted index produces silently wrong query results, which is worse
            than failing to load.
        Acceptance: a loaded store answers the same filters as the store that wrote it.
        Depends on: `snapshot`, `put`.
        """
        raise NotImplementedError("store load not yet implemented")
