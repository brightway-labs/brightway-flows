"""How strong a mapping is, decided once the whole source list is in view.

`skos:exactMatch` says the two concepts are interchangeable.  It is symmetric
and it chains: asserting it from two of a source list's flows onto the same
consensus flow also asserts that those two source flows are each other.  So the
strength of a pairing is not a property of the row that made it -- it depends on
how many other rows of the same list end up on the same consensus flow, which
nothing knows while that row is being merged.

Merged one row at a time, that came out wrong in the only way it could.  A row
matched through a curated mapping file was written down as exact
(`merge/rows.py`), a row that created a flow was written down as exact
(`merge/creations.py`), and nothing revisited either once the merge had seen the
rest of the list.  On the 2026-08-13 build that published 21 different ecoinvent
3.12 insecticides -- and a clay, kaolin -- as exact matches for one
`Insecticides, unspecified`, which entails that alanycarb is kaolin (#76).

This module makes the decision after the fact instead, from the cardinality of
the pairings, which is what `GladPairs` already did for the SimaPro
correspondence table and what `_match_property` below was written for.  What it
publishes in place of the false claim is the more useful true one: this source
flow is *narrower than* ours, which is how a consumer sees that 21 insecticides
roll up into one category.

Two rules keep it honest:

**Only `skos:exactMatch` is weakened.**  A `skos:closeMatch` written by the
algorithmic fallback means the two were matched by identifier or label and never
asserted equivalent by a curator.  It makes no claim that chains, so it is not
the bug -- and promoting it to `skos:broadMatch`, which asserts a real
subsumption, would state more than the match knows.

**Cardinality is counted per source list.**  Two lists mapping onto one
consensus flow say nothing about each other; only flows of the *same* list
sharing a consensus flow are the ones exactness would equate.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

import structlog

from brightway_flows.domain.vocabulary import (
    SKOS_BROAD_MATCH_CURIE,
    SKOS_CLOSE_MATCH_CURIE,
    SKOS_EXACT_MATCH_CURIE,
    SKOS_NARROW_MATCH_CURIE,
    SKOS_RELATED_MATCH_CURIE,
    XKOS_SOURCE_CONCEPT_CURIE,
    XKOS_TARGET_CONCEPT_CURIE,
    scheme_for_flow_iri,
)

logger = structlog.get_logger(__name__)

#: Every SKOS mapping property a source concept can carry.  A node holds exactly
#: one of them; they are listed together so a rewrite removes whichever one is
#: there rather than leaving two mapping properties on one concept.
MAPPING_PROPERTY_CURIES: tuple[str, ...] = (
    SKOS_EXACT_MATCH_CURIE,
    SKOS_CLOSE_MATCH_CURIE,
    SKOS_BROAD_MATCH_CURIE,
    SKOS_NARROW_MATCH_CURIE,
    SKOS_RELATED_MATCH_CURIE,
)


def match_property_key(source_concept: dict[str, Any]) -> str:
    """The mapping property *source_concept* carries, or ``""`` if it has none."""
    for curie in MAPPING_PROPERTY_CURIES:
        if curie in source_concept:
            return curie
    return ""


def match_property(*, broader_than_target: bool, narrower_than_target: bool) -> str:
    """Which SKOS mapping property this pairing supports.

    `skos:exactMatch` claims the two concepts are interchangeable, and it is
    symmetric and transitive: asserting it from one source flow to two consensus
    flows also asserts that those two are each other.  It is therefore reserved
    for a pairing that is one-to-one on both sides; the rest say what is actually
    known about which concept is wider.

    The property is written *on the source concept*, so `skos:broadMatch` reads
    "the consensus flow is broader than this source flow" -- the statement the
    catch-all flows in #76 needed.
    """
    if broader_than_target and narrower_than_target:
        return SKOS_RELATED_MATCH_CURIE
    if broader_than_target:
        return SKOS_NARROW_MATCH_CURIE
    if narrower_than_target:
        return SKOS_BROAD_MATCH_CURIE
    return SKOS_EXACT_MATCH_CURIE


def published_match(
    current: str, *, shares_target: bool, shares_source: bool
) -> str:
    """The property to publish for a pairing that currently carries *current*.

    Weakening only, never strengthening: a pairing that is one-to-one keeps
    whatever it already says, so an algorithmic `skos:closeMatch` is not
    promoted to exact by the accident of being the only match on its flow.
    """
    if current != SKOS_EXACT_MATCH_CURIE:
        return current
    return match_property(
        broader_than_target=shares_source, narrower_than_target=shares_target
    )


def _pairing(association: Any) -> tuple[dict[str, Any], str, str, str] | None:
    """(*source concept*, scheme slug, source IRI, target IRI) of one association.

    ``None`` when the association is not one this module can place: malformed,
    missing an IRI at either end, carrying no mapping property, or belonging to
    no registered scheme.  Such an association is left exactly as it is -- the
    export drops it or publishes it unchanged, and guessing at a strength for a
    mapping whose list is unknown would be a second wrong claim.
    """
    if not isinstance(association, dict):
        return None
    source = association.get(XKOS_SOURCE_CONCEPT_CURIE)
    target = association.get(XKOS_TARGET_CONCEPT_CURIE)
    if not isinstance(source, dict) or not isinstance(target, dict):
        return None
    source_iri = str(source.get("@id") or "").strip()
    target_iri = str(target.get("@id") or "").strip()
    if not source_iri or not target_iri or not match_property_key(source):
        return None
    scheme = scheme_for_flow_iri(source_iri)
    if scheme is None:
        return None
    return source, scheme.slug, source_iri, target_iri


class Cardinality:
    """How many flows sit on each end of a source list's pairings.

    Built from every association in the run and then asked about one pairing at
    a time, which is the two-pass shape the decision needs: the strength of any
    one pairing depends on pairings this one's flow has never seen.
    """

    def __init__(self) -> None:
        self._targets_per_source: dict[tuple[str, str], set[str]] = defaultdict(set)
        self._sources_per_target: dict[tuple[str, str], set[str]] = defaultdict(set)

    def observe(self, scheme_slug: str, source_iri: str, target_iri: str) -> None:
        self._targets_per_source[(scheme_slug, source_iri)].add(target_iri)
        self._sources_per_target[(scheme_slug, target_iri)].add(source_iri)

    def shares_target(self, scheme_slug: str, target_iri: str) -> bool:
        """Does another flow of the same list map onto this consensus flow?"""
        return len(self._sources_per_target[(scheme_slug, target_iri)]) > 1

    def shares_source(self, scheme_slug: str, source_iri: str) -> bool:
        """Does this source flow map onto more than one consensus flow?"""
        return len(self._targets_per_source[(scheme_slug, source_iri)]) > 1

    def published_match_for(
        self, current: str, scheme_slug: str, source_iri: str, target_iri: str
    ) -> str:
        return published_match(
            current,
            shares_target=self.shares_target(scheme_slug, target_iri),
            shares_source=self.shares_source(scheme_slug, source_iri),
        )


def cardinality_of(association_lists: Iterable[list[dict[str, Any]]]) -> Cardinality:
    """Count both ends of every pairing in *association_lists*."""
    cardinality = Cardinality()
    for associations in association_lists:
        for association in associations or []:
            if (placed := _pairing(association)) is None:
                continue
            _source, slug, source_iri, target_iri = placed
            cardinality.observe(slug, source_iri, target_iri)
    return cardinality


def rewrite_source_concept(
    source_concept: dict[str, Any], published: str
) -> bool:
    """Put *published* on *source_concept*, removing the property it replaces.

    The new property is given the value the old one carried -- the target flow's
    IRI -- so the statement keeps its object and changes only what it claims
    about it.  Returns whether anything changed.
    """
    current = match_property_key(source_concept)
    if not current or current == published:
        return False
    source_concept[published] = source_concept.pop(current)
    return True


def weaken(associations: list[dict[str, Any]], cardinality: Cardinality) -> Counter:
    """Weaken the over-strong matches in one flow's *associations*, in place.

    *cardinality* has to have seen every association in the run: this flow's own
    are never enough to tell whether another flow of the same list holds the
    other end of an exactness that chains.  Returns what it did, counting each
    mapping under `weakened_<list>` or `kept_<property>`, so a caller with rows
    to write knows which ones it has to touch.
    """
    counts: Counter = Counter()
    for association in associations or []:
        if (placed := _pairing(association)) is None:
            counts["unplaced"] += 1
            continue
        source, slug, source_iri, target_iri = placed
        current = match_property_key(source)
        published = cardinality.published_match_for(
            current, slug, source_iri, target_iri
        )
        if rewrite_source_concept(source, published):
            counts[f"weakened_{slug}"] += 1
            counts[f"to_{published.split(':')[-1]}"] += 1
        else:
            counts[f"kept_{current.split(':')[-1]}"] += 1
    return counts


def apply_match_strengths(
    association_lists: Iterable[list[dict[str, Any]]],
) -> Counter:
    """Weaken every over-strong match in *association_lists*, in place.

    Takes the association lists of every flow in the run, because that -- not
    one flow's -- is the smallest view in which the answer exists.  Idempotent:
    re-running over already-weakened associations changes nothing, which is what
    lets it run both on the records in memory and again over what a later merge
    added to the database.
    """
    lists = [entry for entry in association_lists if entry]
    cardinality = cardinality_of(lists)
    counts: Counter = Counter()
    for associations in lists:
        counts.update(weaken(associations, cardinality))
    return counts
