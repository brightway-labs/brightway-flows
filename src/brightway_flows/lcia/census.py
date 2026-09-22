"""The census of our taxonomy's blanks: where a substance is characterised in
one context and nothing is stated for it in a neighbouring one.

Ammonium emitted to surface water is characterised at 2,493.2 CTUe/kg for
freshwater ecotoxicity.  Ammonium emitted to a river -- which is surface water
-- carries no factor, because no implementation ships a river flow for it and
this list publishes only what somebody stated (#159).  That triple is a
**blank**: the flow exists in our published list, the same category already
characterises the same substance next door, and nobody said anything here.

This module counts the blanks and decides nothing about them.  Which context
takes which neighbour's number is a convention written by people, as data, from
the tables this produces (``plans/lcia-consensus-decisions.md`` §4.1 and §5).
So the census is written per **ordered pair** of contexts -- donor, recipient --
inside a class of our taxonomy, and for each pair it reports the three things a
person writing that convention needs:

* how many blanks the pair would fill -- substances published in the donor with
  a live flow in the recipient and nothing stated there;
* where an implementation characterised **both**, how often the two numbers are
  one number within `FACTOR_TOLERANCE` -- the evidence about whether the
  contexts differ for the model;
* where the recipient's published number is `restated` -- ecoinvent's own
  statement for a compartment EF's flow list cannot express -- whether it is the
  donor's number.  Measured on the 2026-09-01 build this is what showed that
  ecoinvent's silvicultural and industrial soil take EF's *non-agricultural*
  number in every row and its aquifer takes *surface water's*: a fixed
  correspondence, and not the sibling agreement the first draft assumed.

And one thing the taxonomy says rather than the data: whether the donor is the
recipient's broader context, its narrower one, or a sibling.  The water
vocabulary files lake and river under surface water, and every class has an
`Unknown` that is the parent of the rest; that is stated here as a small table
because ``domain.context`` records the values and not their containment.

**Walls** are contexts the census never pairs: long-term air and water (EF states
literal zero there in every toxicity category, #158), indoor air, and the ocean
against anything fresh.  A rule naming one is a decision this plan does not
make, so the census does not count what it would do.

**A second kind of blank sits beside a substance rather than beside a context.**
Stepwise 2006 characterises zinc emitted to water at 133.39 for non-cancer human
toxicity; `Zinc(2+)`, the dissolved ion, has a flow in the very same context and
nobody states anything for it, because Stepwise's export never names the ion
(#197).  Every ecoinvent zinc emission lands on the ion, so it scores nothing.
The context census cannot see that -- the ion is a different substance, and
nothing is characterised for it next door -- so :func:`identity_census` counts
it separately: a live flow of a substance the build records as an ion of an
element, no factor on it, and the element published in the same context and
category.  It, too, decides nothing; whether an ion takes its element's number
is a signed entry in ``data/lcia-factor-adoptions.json`` or nothing.

Read by ``characterise`` to write one coverage row per recipient context and
one per blank ion, so the number of blanks of each kind is a number of the run
and cannot drift unnoticed, and by ``tools/count_context_blanks.py`` to print
the per-pair tables.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import structlog

from brightway_flows.flow_layers.contested_cas import FACTOR_TOLERANCE

logger = structlog.get_logger(__name__)

#: The separator `context_display` is written with.
ARROW = " → "

#: What the census calls a class of contexts.  Values are what a reader sees,
#: so they are words rather than slugs.
class ContextClass(StrEnum):
    SOIL = "soil"
    FRESH_WATER = "fresh water"
    AIR = "air"
    RESOURCE_WATER = "resource water"


class Relation(StrEnum):
    """What the taxonomy says about a (donor, recipient) pair."""

    #: The donor is the recipient's parent: unspecified soil → silvicultural.
    BROADER = "broader"
    #: The donor is a child of the recipient: surface water → unspecified water.
    NARROWER = "narrower"
    #: Neither contains the other.
    SIBLING = "sibling"


#: The coverage dimension a blank count is written under.
BLANK_DIMENSION = "blank"

#: The coverage dimension a blank ion is written under: a substance with no
#: factor beside its element, which has one in the same context.
IDENTITY_BLANK_DIMENSION = "identity-blank"

#: The last segment of a display name that puts a context behind a wall.
LONG_TERM = "Long-term"
INDOOR = "Indoor"
OCEAN = "Ocean"
UNKNOWN = "Unknown"

#: The contexts of `Environmental → Water` that are fresh.  Everything else in
#: that medium -- ocean, long-term, treatment plants -- is outside the class.
FRESH_WATER_BODIES = frozenset({
    UNKNOWN,
    "Surface water",
    "River",
    "Lake",
    "Unconfined aquifer",
    "Confined aquifer with fossil groundwater",
})

#: Containment our taxonomy states inside a class, as child → parent, by the
#: last segment of the display name.  `Unknown` is every class's root and is
#: not listed: anything not listed here is a child of `Unknown`.
PARENT_OF: Mapping[str, str] = {
    "River": "Surface water",
    "Lake": "Surface water",
}


@dataclass(frozen=True, slots=True)
class PublishedFactor:
    """One factor of the consensus implementation, as the census reads it."""

    elementary_flow_uuid: str
    category_slug: str
    geography: str
    amount: float
    derivation: str | None


@dataclass(frozen=True, slots=True)
class ContextPair:
    """One row of the census: what one ordered pair of contexts would do."""

    method: str
    context_class: ContextClass
    donor: str
    recipient: str
    relation: Relation
    #: (substance, category, place) triples published in the donor, with a
    #: live flow in the recipient, and nothing stated for it there.
    blanks: int
    #: Triples published in both contexts.
    both: int
    #: Of `both`, within `FACTOR_TOLERANCE`.
    agree: int
    #: Triples whose recipient number is `restated` and whose donor number is
    #: published by somebody's own statement -- `sole`, `agreed` or `ruled`.
    restated_rows: int
    #: Of `restated_rows`, within `FACTOR_TOLERANCE` of the donor.
    restated_matches: int

    @property
    def agreement(self) -> float | None:
        return self.agree / self.both if self.both else None


@dataclass(frozen=True, slots=True)
class BlankContext:
    """How many blanks one recipient context holds, over every donor of its class."""

    method: str
    context_class: ContextClass
    recipient: str
    #: (substance, category, place) triples with a live flow here, a published
    #: number in at least one other context of the class, and nothing stated.
    blanks: int
    #: Of those, triples where exactly one context of the class is published --
    #: a copy from one donor, with no second number to compare it to.
    single_donor: int


@dataclass(frozen=True, slots=True)
class SubstanceRelative:
    """What the build records one substance as, relative to another.

    `Zinc(2+)` is an ion of `Zinc`: the element enrichment writes that on the
    ion's flow object (`flow_layers.ions`), and this is that record read back
    for the census.  The relationship is a word a reader sees -- ``ion of`` --
    rather than the record's own key, and one word per recipient, because the
    census asks one question of it: is the donor characterised where the
    recipient is not?
    """

    #: The substance whose number the recipient would take.
    donor: str
    #: How the recipient stands to the donor, in words: ``ion of``.
    relationship: str


@dataclass(frozen=True, slots=True)
class IdentityBlank:
    """How many pairs one substance leaves blank beside its relative."""

    method: str
    recipient: str
    recipient_label: str
    donor: str
    donor_label: str
    relationship: str
    #: (flow, category, place) triples with a live flow of the recipient, the
    #: donor published in the same context and category, and nothing stated for
    #: the recipient.
    blanks: int
    #: The contexts those triples are in.
    contexts: int
    #: The categories those triples are in.
    categories: int

    @property
    def value(self) -> str:
        """What the coverage row calls this: `Zinc(2+) — ion of Zinc`."""
        return f"{self.recipient_label} — {self.relationship} {self.donor_label}"


def _parts(display: str) -> list[str]:
    return display.split(ARROW)


def context_class_of(display: str) -> ContextClass | None:
    """Which class a context is in, or ``None`` if the census does not pair it.

    Read off the display name rather than the context's fields because the run
    hands the census the same flow descriptions every other pass reads, and
    those carry the display.  A wall -- long-term, indoor, the ocean -- is
    ``None`` on purpose.
    """
    parts = _parts(display)
    if len(parts) < 3:
        return None
    dimension, media, rest = parts[0], parts[1], parts[2:]
    if LONG_TERM in rest or INDOOR in rest:
        return None
    if dimension == "Environmental":
        if media == "Ground":
            return ContextClass.SOIL
        if media == "Water":
            return ContextClass.FRESH_WATER if rest[0] in FRESH_WATER_BODIES else None
        if media == "Air":
            return ContextClass.AIR
        return None
    if dimension == "Resource" and media == "Water":
        return None if rest[0] == OCEAN else ContextClass.RESOURCE_WATER
    return None


def relation_of(donor: str, recipient: str) -> Relation:
    """What the taxonomy says about the pair, by the display names' last segments."""
    donor_leaf, recipient_leaf = _parts(donor)[-1], _parts(recipient)[-1]
    donor_key = ARROW.join(_parts(donor)[2:])
    recipient_key = ARROW.join(_parts(recipient)[2:])
    if _is_ancestor(donor_key, donor_leaf, recipient_key, recipient_leaf):
        return Relation.BROADER
    if _is_ancestor(recipient_key, recipient_leaf, donor_key, donor_leaf):
        return Relation.NARROWER
    return Relation.SIBLING


def _is_ancestor(
    candidate_key: str, candidate_leaf: str, other_key: str, other_leaf: str
) -> bool:
    """Whether *candidate* contains *other*: it is the class's `Unknown`, it is
    the stated parent, or -- for air -- it is a prefix of the other's path
    (`Ground level` contains `Ground level → Urban`)."""
    if candidate_key == other_key:
        return False
    if candidate_leaf == UNKNOWN and candidate_key == UNKNOWN:
        return True
    if PARENT_OF.get(other_leaf) == candidate_leaf:
        return True
    return other_key.startswith(candidate_key + ARROW)


def _one_number(a: float, b: float) -> bool:
    if a == b:
        return True
    if a == 0 or b == 0 or (a > 0) != (b > 0):
        return False
    low, high = sorted((abs(a), abs(b)))
    return high / low - 1 <= FACTOR_TOLERANCE


#: Derivations that are somebody's own statement for the flow, which is what a
#: restated row is measured against.  Not `restated` itself -- a restatement
#: matching a restatement says nothing about where either came from.
OWN_STATEMENT = frozenset({"sole", "agreed", "ruled"})


def context_census(
    *,
    method: str,
    published: Iterable[PublishedFactor],
    stated: Iterable[tuple[str, str, str]],
    flows: Mapping[str, Mapping[str, Any]],
) -> tuple[list[ContextPair], list[BlankContext]]:
    """Count the blanks of every class, per ordered pair and per recipient.

    *published* is the consensus implementation's factors after every pass has
    run; *stated* is every ``(flow uuid, category slug, geography)`` any
    deciding implementation states -- the test for "nobody spoke", so a
    compartment a queue is holding is never a blank; *flows* describes every
    published flow (`lcia.sources.flow_descriptions`).

    Returns the pairs, sorted by class and then by blanks descending, and the
    per-recipient counts in the same order.
    """
    spoken = set(stated)
    #: substance → class → context display → flow uuid, live flows only.
    live: dict[str, dict[ContextClass, dict[str, str]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    class_of_flow: dict[str, tuple[str, ContextClass, str]] = {}
    for uuid, flow in flows.items():
        if flow.get("deprecated"):
            continue
        display = str(flow.get("context_display") or "")
        context_class = context_class_of(display)
        if context_class is None:
            continue
        substance = str(flow.get("flow_object_id") or "")
        live[substance][context_class][display] = uuid
        class_of_flow[uuid] = (substance, context_class, display)

    #: (substance, slug, geography, class) → context display → (amount, derivation)
    groups: dict[tuple[str, str, str, ContextClass], dict[str, tuple[float, str | None]]]
    groups = defaultdict(dict)
    for row in published:
        placed = class_of_flow.get(row.elementary_flow_uuid)
        if placed is None:
            continue
        substance, context_class, display = placed
        groups[(substance, row.category_slug, row.geography, context_class)][display] = (
            row.amount,
            row.derivation,
        )

    pairs: Counter[tuple[ContextClass, str, str, str]] = Counter()
    per_recipient: Counter[tuple[ContextClass, str, str]] = Counter()
    for (substance, slug, geography, context_class), by_context in groups.items():
        contexts = live[substance][context_class]
        blank_here: set[str] = set()
        for recipient, uuid in contexts.items():
            if recipient in by_context or (uuid, slug, geography) in spoken:
                continue
            blank_here.add(recipient)
        for donor, (amount, derivation) in by_context.items():
            for recipient in blank_here:
                pairs[(context_class, donor, recipient, "blanks")] += 1
            for recipient, (other, other_derivation) in by_context.items():
                if recipient == donor:
                    continue
                pairs[(context_class, donor, recipient, "both")] += 1
                if _one_number(amount, other):
                    pairs[(context_class, donor, recipient, "agree")] += 1
                if other_derivation == "restated" and derivation in OWN_STATEMENT:
                    pairs[(context_class, donor, recipient, "restated_rows")] += 1
                    if _one_number(amount, other):
                        pairs[(context_class, donor, recipient, "restated_matches")] += 1
        for recipient in blank_here:
            per_recipient[(context_class, recipient, "blanks")] += 1
            if len(by_context) == 1:
                per_recipient[(context_class, recipient, "single_donor")] += 1

    keys = {(context_class, donor, recipient) for context_class, donor, recipient, _ in pairs}
    rows = [
        ContextPair(
            method=method,
            context_class=context_class,
            donor=donor,
            recipient=recipient,
            relation=relation_of(donor, recipient),
            blanks=pairs[(context_class, donor, recipient, "blanks")],
            both=pairs[(context_class, donor, recipient, "both")],
            agree=pairs[(context_class, donor, recipient, "agree")],
            restated_rows=pairs[(context_class, donor, recipient, "restated_rows")],
            restated_matches=pairs[(context_class, donor, recipient, "restated_matches")],
        )
        for context_class, donor, recipient in keys
    ]
    rows.sort(key=lambda row: (str(row.context_class), -row.blanks, -row.both, row.donor, row.recipient))
    recipients = [
        BlankContext(
            method=method,
            context_class=context_class,
            recipient=recipient,
            blanks=per_recipient[(context_class, recipient, "blanks")],
            single_donor=per_recipient[(context_class, recipient, "single_donor")],
        )
        for context_class, recipient in sorted({
            (context_class, recipient) for context_class, recipient, _ in per_recipient
        })
    ]
    recipients.sort(key=lambda row: (str(row.context_class), -row.blanks, row.recipient))
    logger.info(
        "counted_context_blanks",
        method=method,
        pairs=len(rows),
        blanks=sum(row.blanks for row in recipients),
    )
    return rows, recipients


def identity_census(
    *,
    method: str,
    published: Iterable[PublishedFactor],
    stated: Iterable[tuple[str, str, str]],
    flows: Mapping[str, Mapping[str, Any]],
    relatives: Mapping[str, SubstanceRelative],
) -> list[IdentityBlank]:
    """Count, per substance, the pairs it leaves blank beside its relative.

    *relatives* is recipient substance → the donor the build records for it
    (`lcia.sources.substance_relatives`): the ion and its element.  A triple is
    blank when the recipient has a live flow in a context, no consensus factor
    for the category and place, nothing stated for it by a deciding
    implementation, and the donor **is** published for the same category and
    place in a flow of the same context.  Same context, deliberately: a blank
    beside a neighbouring context is the other census's, and a number crossing
    both a substance and a context at once is two decisions.

    Returns one row per recipient with at least one blank, most blanks first.
    Nothing is published; nothing is decided.
    """
    spoken = set(stated)
    #: substance → context IRI → live flows there.
    live: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    labels: dict[str, str] = {}
    for uuid, flow in flows.items():
        if flow.get("deprecated"):
            continue
        substance = str(flow.get("flow_object_id") or "")
        context = str(flow.get("context_iri") or "")
        if not substance or not context:
            continue
        live[substance][context].append(uuid)
        labels.setdefault(substance, str(flow.get("label") or substance))
    #: (substance, context IRI, slug, geography) → published.
    filled: set[tuple[str, str, str, str]] = set()
    context_of = {
        uuid: context
        for substance, by_context in live.items()
        for context, uuids in by_context.items()
        for uuid in uuids
    }
    for row in published:
        context = context_of.get(row.elementary_flow_uuid)
        if context is None:
            continue
        substance = str(flows[row.elementary_flow_uuid].get("flow_object_id") or "")
        filled.add((substance, context, row.category_slug, row.geography))
    #: donor substance → context → the (slug, geography) pairs published there.
    donor_pairs: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    donors = {relative.donor for relative in relatives.values()}
    for substance, context, slug, geography in filled:
        if substance in donors:
            donor_pairs[(substance, context)].add((slug, geography))

    rows: list[IdentityBlank] = []
    for recipient, relative in relatives.items():
        blanks = 0
        contexts: set[str] = set()
        categories: set[str] = set()
        for context, uuids in live.get(recipient, {}).items():
            for slug, geography in donor_pairs.get((relative.donor, context), ()):
                if (recipient, context, slug, geography) in filled:
                    continue
                empty = [uuid for uuid in uuids if (uuid, slug, geography) not in spoken]
                if not empty:
                    continue
                blanks += len(empty)
                contexts.add(context)
                categories.add(slug)
        if blanks:
            rows.append(
                IdentityBlank(
                    method=method,
                    recipient=recipient,
                    recipient_label=labels.get(recipient, recipient),
                    donor=relative.donor,
                    donor_label=labels.get(relative.donor, relative.donor),
                    relationship=relative.relationship,
                    blanks=blanks,
                    contexts=len(contexts),
                    categories=len(categories),
                )
            )
    rows.sort(key=lambda row: (-row.blanks, row.recipient_label))
    logger.info(
        "counted_identity_blanks",
        method=method,
        substances=len(rows),
        blanks=sum(row.blanks for row in rows),
    )
    return rows
