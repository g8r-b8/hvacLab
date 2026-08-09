"""Haystack filter language: parser and evaluator.

The query surface of the whole system. A filter like

    point and discharge and air and temp and equipRef->ahu

means: entities that are points, tagged discharge+air+temp, whose `equipRef` resolves to
an entity tagged `ahu`. The `->` is a *dereference*, and it is what makes the language
worth implementing rather than replacing with SQL — it walks the entity graph.

Grammar (Haystack 3/4 filter, simplified but faithful):

    filter    := condOr
    condOr    := condAnd ("or" condAnd)*
    condAnd   := term ("and" term)*
    term      := "not" term | "(" filter ")" | has | missing | cmp
    has       := path
    missing   := "not" path
    cmp       := path ("==" | "!=" | "<" | "<=" | ">" | ">=") val
    path      := name ("->" name)*
    val       := bool | num unit? | str | ref | date | time | uri

Precedence: `not` > `and` > `or`. Note that a bare `path` is a *has* test, so
`equipRef->ahu` tests "the entity referenced by equipRef has the tag ahu" — dereference
then presence, not equality.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class TokenKind(StrEnum):
    """Lexical token classes."""

    NAME = "name"
    NUMBER = "number"
    STRING = "string"
    REF = "ref"
    URI = "uri"
    DATE = "date"
    TIME = "time"
    BOOL = "bool"
    AND = "and"
    OR = "or"
    NOT = "not"
    ARROW = "arrow"
    LPAREN = "lparen"
    RPAREN = "rparen"
    CMP = "cmp"
    EOF = "eof"


@dataclass(frozen=True, slots=True)
class Token:
    """One lexical token with its source position, for useful error messages."""

    kind: TokenKind
    text: str
    pos: int
    value: Any = None


class FilterNode(Protocol):
    """AST node interface. Every node can evaluate itself against an entity."""

    def evaluate(self, entity_id: str, ctx: FilterContext) -> bool:
        """Return whether the entity satisfies this node."""
        ...

    def describe(self) -> str:
        """Return a canonical filter string for this subtree."""
        ...


class FilterContext(Protocol):
    """What an evaluator needs from the store — deliberately minimal so tests can fake it."""

    def tags_of(self, entity_id: str) -> frozenset[str]:
        """All tags on an entity, with conjunct implications already expanded."""
        ...

    def value_of(self, entity_id: str, tag: str) -> Any | None:
        """A value tag's payload, or None."""
        ...

    def deref(self, entity_id: str, ref_tag: str) -> str | None:
        """Follow a ref tag to another entity id, or None."""
        ...

    def all_entity_ids(self) -> tuple[str, ...]:
        """Every entity id available to the query."""
        ...


@dataclass(frozen=True, slots=True)
class HasNode:
    """`path` — the entity (or the entity at the end of the path) has the tag."""

    path: tuple[str, ...]

    def evaluate(self, entity_id: str, ctx: FilterContext) -> bool:
        """Resolve the path and test presence of its final segment.

        TODO: Walk all but the last segment via `ctx.deref`, then test the last segment
            against `ctx.tags_of` on the resolved entity.
        What's missing: the broken-ref policy. A `equipRef` pointing at a deleted entity
            must evaluate False, not raise — half-tagged sites are the normal case and a
            query that explodes on one bad ref is useless.
        Acceptance: `equipRef->ahu` is True for a VAV whose equipRef target is tagged ahu;
            False when the target is missing.
        Depends on: `FilterContext`.
        """
        raise NotImplementedError("has-path evaluation not yet implemented")

    def describe(self) -> str:
        """Render as `a->b->c`.

        TODO: Join path segments with "->".
        What's missing: nothing.
        Acceptance: round-trips through the parser to an equal AST.
        Depends on: nothing.
        """
        raise NotImplementedError("node rendering not yet implemented")


@dataclass(frozen=True, slots=True)
class MissingNode:
    """`not path` — the tag is absent."""

    path: tuple[str, ...]

    def evaluate(self, entity_id: str, ctx: FilterContext) -> bool:
        """Negation of `HasNode`, with the same broken-ref policy.

        TODO: Delegate to `HasNode(self.path).evaluate` and invert.
        What's missing: the subtle bit — under a broken ref, `not equipRef->ahu` is True
            (the tag is indeed not present). Confirm that is the desired semantics and
            document it, because it makes `not` non-symmetric with `has` for bad data.
        Acceptance: an entity with no `co2` tag matches `not co2`.
        Depends on: `HasNode.evaluate`.
        """
        raise NotImplementedError("missing-path evaluation not yet implemented")

    def describe(self) -> str:
        """Render as `not a->b`.

        TODO: Prefix "not " to the joined path.
        What's missing: nothing.
        Acceptance: round-trips through the parser.
        Depends on: nothing.
        """
        raise NotImplementedError("node rendering not yet implemented")


@dataclass(frozen=True, slots=True)
class CmpNode:
    """`path op value` — compare a value tag against a literal."""

    path: tuple[str, ...]
    op: str
    value: Any

    def evaluate(self, entity_id: str, ctx: FilterContext) -> bool:
        """Resolve the path, fetch the value tag, and compare.

        TODO: Implement ==, !=, <, <=, >, >= with Haystack's type rules.
        What's missing: unit-aware numeric comparison. `temp > 75°F` against a value
            stored canonically in degC must convert, not compare raw floats — this is the
            exact bug class `model.units` exists to prevent. Also: comparing a missing
            tag is False for all ops including `!=`, per Haystack semantics.
        Acceptance: `unit == "°F"` matches; `area > 1000` matches a 2000 sqft space;
            any comparison against a missing tag is False.
        Depends on: `FilterContext.value_of`, `model.units.UnitConverter`.
        """
        raise NotImplementedError("comparison evaluation not yet implemented")

    def describe(self) -> str:
        """Render as `path op literal`.

        TODO: Join the path, then the operator, then the Zinc-encoded literal.
        What's missing: literal encoding shared with the Zinc writer.
        Acceptance: round-trips through the parser.
        Depends on: `semantic.export.haystack`.
        """
        raise NotImplementedError("node rendering not yet implemented")


@dataclass(frozen=True, slots=True)
class AndNode:
    """Conjunction of subterms."""

    terms: tuple[FilterNode, ...]

    def evaluate(self, entity_id: str, ctx: FilterContext) -> bool:
        """True when every subterm is true.

        TODO: Short-circuit on the first False.
        What's missing: ordering for performance — cheap marker tests should run before
            dereferences, so consider sorting terms by estimated cost at parse time.
        Acceptance: empty conjunction is True; short-circuits (assert via a counting fake
            context).
        Depends on: subnode evaluation.
        """
        raise NotImplementedError("conjunction evaluation not yet implemented")

    def describe(self) -> str:
        """Render subterms joined by " and ", parenthesizing where precedence requires.

        TODO: Join with " and ".
        What's missing: parenthesization when a subterm is an `OrNode`.
        Acceptance: round-trips through the parser.
        Depends on: nothing.
        """
        raise NotImplementedError("node rendering not yet implemented")


@dataclass(frozen=True, slots=True)
class OrNode:
    """Disjunction of subterms."""

    terms: tuple[FilterNode, ...]

    def evaluate(self, entity_id: str, ctx: FilterContext) -> bool:
        """True when any subterm is true.

        TODO: Short-circuit on the first True.
        What's missing: nothing beyond `AndNode`'s considerations.
        Acceptance: empty disjunction is False; short-circuits.
        Depends on: subnode evaluation.
        """
        raise NotImplementedError("disjunction evaluation not yet implemented")

    def describe(self) -> str:
        """Render subterms joined by " or ".

        TODO: Join with " or ".
        What's missing: nothing.
        Acceptance: round-trips through the parser.
        Depends on: nothing.
        """
        raise NotImplementedError("node rendering not yet implemented")


@dataclass(frozen=True, slots=True)
class NotNode:
    """Logical negation of a subterm."""

    term: FilterNode

    def evaluate(self, entity_id: str, ctx: FilterContext) -> bool:
        """Invert the subterm.

        TODO: Return `not self.term.evaluate(...)`.
        What's missing: nothing.
        Acceptance: double negation is identity.
        Depends on: subnode evaluation.
        """
        raise NotImplementedError("negation evaluation not yet implemented")

    def describe(self) -> str:
        """Render as `not (...)`.

        TODO: Wrap the subterm.
        What's missing: dropping redundant parentheses for atomic subterms.
        Acceptance: round-trips through the parser.
        Depends on: nothing.
        """
        raise NotImplementedError("node rendering not yet implemented")


class FilterParseError(ValueError):
    """Raised on a malformed filter, carrying the source position."""


def tokenize(source: str) -> tuple[Token, ...]:
    """Lex a filter string into tokens.

    TODO: Implement the lexer for names, numbers with optional units, quoted strings with
        escapes, `@refs`, dates, times, `->`, parentheses, comparison operators, and the
        keywords and/or/not.
    What's missing: the ambiguity between the keyword `not` and a tag literally named
        "not" (rare but legal), and number-with-unit lexing where the unit is a symbol
        like `°F` or `m³/h` — the unit is glued to the number with no space.
    Acceptance: tokenizing "point and equipRef->ahu" yields NAME AND NAME ARROW NAME EOF;
        an unterminated string raises `FilterParseError` with the correct position.
    Depends on: `model.units.UnitRegistry.from_text`.
    """
    raise NotImplementedError("filter lexer not yet implemented")


def parse(source: str) -> FilterNode:
    """Parse a Haystack filter string into an AST.

    TODO: Recursive-descent over the grammar in the module docstring, honouring
        not > and > or precedence.
    What's missing: the has-vs-cmp disambiguation — the parser cannot know whether a path
        is a `has` test or the left side of a comparison until it sees (or fails to see)
        an operator, so it must parse the path first and then peek.
    Acceptance: `parse(s).describe()` re-parses to an equal AST for every fixture query;
        "point and" raises `FilterParseError`.
    Depends on: `tokenize`.
    """
    raise NotImplementedError("filter parser not yet implemented")


def evaluate(node: FilterNode, entity_id: str, ctx: FilterContext) -> bool:
    """Evaluate a parsed filter against one entity.

    TODO: Delegate to `node.evaluate`; exists as a free function so callers need not
        depend on the Protocol.
    What's missing: nothing.
    Acceptance: agrees with `node.evaluate` for all fixtures.
    Depends on: AST node evaluation.
    """
    raise NotImplementedError("filter evaluation dispatch not yet implemented")


def select(source: str, ctx: FilterContext) -> tuple[str, ...]:
    """Parse a filter and return every matching entity id.

    TODO: Parse once, then evaluate against `ctx.all_entity_ids()`.
    What's missing: this is the naive full scan. The tag store should eventually push
        marker conjunctions down to an inverted index and only evaluate the residual
        filter — keep this signature stable so that optimization is invisible to callers.
    Acceptance: `select("point and discharge and air and temp", ctx)` returns the same
        set of *logical* points for both the Trane and the Carrier fixture. That equality
        is the headline normalization test for the whole project.
    Depends on: `parse`, `evaluate`, `store.tagstore`.
    """
    raise NotImplementedError("filter selection not yet implemented")
