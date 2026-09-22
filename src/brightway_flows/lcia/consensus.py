"""The third implementation: what this list says, and what it declines to say.

The other two are transcriptions and carry no judgment of ours.  This one is
entirely judgment, which is why most of it is not made here.

**It publishes what nobody disputes.**  Per (flow, category, place):

| `derivation` | when | factors |
|---|---|---:|
| `sole` | only the JRC states it | 297,544 |
| `agreed` | both state it and agree, identically or within `FACTOR_TOLERANCE` | 21,770 |
| `restated` | only ecoinvent states it, and the number is one this list already publishes in the same category -- for the same substance in another context within `FACTOR_TOLERANCE` | 4,402 on 2026-08-24, when it still had a second half |
| `adopted` | only a transcription states it, and a person signed for the substance taking another substance's number in `data/lcia-factor-adoptions.json` -- 62 pesticides carrying a catch-all's numbers, 23 minerals carrying the JRC's element factors weighted by their formula, ten ions carrying their element's, 53 land classes carrying their family's | 899 on 2026-08-24, before the ions and land classes were signed |
| `ruled` | a curator answered the question in `data/lcia-factor-rulings.json` | 32 |

324,629 factors on the 2026-08-24 build, 92% of them `sole` -- because ecoinvent's
flow list reaches 9,407 of our 95,454 flows and the JRC's reaches all of them.  The
consensus implementation is mostly the JRC's implementation, and it should be.

**`restated` is the one that needs reading twice**, because it looks like the
inheritance rung §4.3 rejected and is not.  It publishes only a number ecoinvent
stated, on the strength of this list already publishing that number *for the
same substance*: EF 3.1's flow list has no silvicultural soil, no industrial soil
and no groundwater; ecoinvent has all three and characterises them with the value
it states for the nearest compartment EF does have.  Where that value is one this
list already publishes for the same substance in another context of the category
-- within `FACTOR_TOLERANCE`, because 12274.01347021746 through a unit conversion
and a published 12274.013470217462 are one number -- publishing it decides
nothing new.  The amount is always ecoinvent's own stated row; nothing is
inherited, interpolated or coarsened, which is the difference between this and
the rung.

**A number never crosses a substance boundary on its own.**  `restated` once had
a second half (#145): where *any* flow of the category published the proposed
number bit for bit, the factor was a restatement across an identity boundary --
which is how `Copper, Ion` took copper's numbers, and also how lindane's numbers
reached its manufacturing contaminants, which EF's own numbers hold 21 to 34
times apart (#131).  The digits cannot tell the two apart, so that half is gone
(#156).  The ion's factors publish as `adopted`, on a signed entry in
`data/lcia-factor-adoptions.json` naming the donor and the relationship; the
contaminants' entries say `decline`, and their rows stay on the page answered.

**A ruled question becomes a number, and says who ruled.**
`data/lcia-factor-rulings.json` answers a queue item by its own key, and a factor
published from one carries `derivation: ruled` -- distinguishable from `agreed`,
which is the pipeline finding nothing to decide, and from `sole`, which is nobody
else having spoken.  A ruling written about numbers the build no longer states is
not applied; that row asks again.

**Everything else is a question, and a question is not a number.**  Three
populations need a curator, and until one rules, this implementation publishes
nothing for them:

* 142 factors where both implementations state a number and the two differ
  beyond tolerance.  A default -- "take the method's own publisher" -- would
  publish 142 numbers nobody had looked at, under a label saying a decision was
  made.  `pipeline.collisions` exists for exactly this shape of problem, and the
  answer there is the same: report the question.
* Factors only ecoinvent states, and which neither `restated` nor an adoption
  reaches: the number is ecoinvent's own rather than one this list carries
  anywhere.  On the 2026-08-24 build, 34 of the 38 open questions were mineral
  depletion -- granite, gypsum, talc -- where ecoinvent extends `Resource use,
  minerals and metals` to minerals EF never priced; 23 of those whose number is
  the JRC's element factors weighted by the formula were approved on 2026-08-25
  (#155), leaving the rocks with no formula to check, feldspar and olivine,
  peat, and coal-mine off-gas.
  Adopting one is a decision about somebody else's numbers, on a flow the
  method's publisher did not characterise, so it goes to a curator.
* 988 factors over 38 substances where **USEtox 2.1, the model EF 3.1's toxicity
  categories are derived from, states something more than a hundredfold away in
  every compartment** -- biphenyl by 1,400,000x, which puts an ordinary
  industrial chemical third of the 3,380 substances EF characterises for
  non-cancer human toxicity in urban air.  Neither transcription can see this and
  both state EF's number, so this is the one question `agreed` gets wrong:
  agreement between two copies of one file is not evidence about the file.
  `lcia.contradictions` measures it; #107 found it.

All three become `review_queue` rows, grouped by (substance, category) because
that is the unit a curator decides in: kresoxim-methyl's freshwater ecotoxicity is
one question asked about two compartments, not two questions.

``plans/lcia-factors.md`` §4.3 is the design, §4.5 is the third queue, and the
revision that made this a set of questions rather than a ladder is in both.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import replace
from enum import StrEnum
from typing import Any

import structlog

from brightway_flows.flow_layers.contested_cas import (
    FACTOR_TOLERANCE,
    more_precise_value,
)
from brightway_flows.lcia.adoptions import FactorAdoption
from brightway_flows.lcia.adoptions import Verdict as AdoptionVerdict
from brightway_flows.domain.lcia.crosswalk import MethodImplementation
from brightway_flows.lcia.contradictions import Contradiction
from brightway_flows.lcia.matching import MatchedFactor
from brightway_flows.lcia.rulings import FactorRuling, Verdict
from brightway_flows.pipeline.review_records import (
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)

logger = structlog.get_logger(__name__)


class Derivation(StrEnum):
    """How a factor of the consensus implementation was arrived at.

    Five are `derive()`'s own: three it can reach without a curator, and two
    that are a curator's file.  The last three are written by the passes that
    run after it -- a move, a printing, a carry -- and are here so that one loop
    over this enum counts every route a number takes onto the implementation.

    **`restated` is not the inheritance rule §4.3 rejected, and the difference is
    the whole of why it is allowed.**  That rule would have *invented* a factor
    for a context nobody characterised, by copying the broader context's number
    -- publishing a number nobody stated, under a label saying this list decided,
    which is the coarsening #84 removed.  This one publishes a number ecoinvent
    **does** state, and uses the match only as evidence about what the number is:
    where this list already publishes that number in the same category --
    for the same substance in another context within `FACTOR_TOLERANCE` --
    ecoinvent is not proposing new science but carrying
    EF's own number onto a compartment EF's list cannot express (silvicultural
    soil, industrial soil, an unconfined aquifer).  A number on *another
    substance* is never that evidence: `Copper, Ion` takes copper's numbers by a
    signed entry in `data/lcia-factor-adoptions.json`, as `adopted`, or not at
    all (#156).  Measured on the
    2026-08-24 build that is 4,402 factors, 3,950 of them the three missing
    compartments.
    """

    #: Only the JRC states it.  Most of the implementation.
    SOLE = "sole"
    #: Both state it and they agree.  The more precise number is kept, which is
    #: the same judgement `pipeline.deduplication` makes about two rows that
    #: turn out to be one flow: `0.000118` and `0.00011755` are one number.
    AGREED = "agreed"
    #: A curator ruled, in `data/lcia-factor-rulings.json`.  Its own value rather
    #: than folding into `agreed`, because a reader has to be able to tell a
    #: number nobody disputed from one somebody decided between two disputed
    #: ones -- and the second carries a comment saying why.
    RULED = "ruled"
    #: Only ecoinvent states it, and this list already publishes *that same
    #: number* in the same category -- for the same substance in another context
    #: within `FACTOR_TOLERANCE`.  Its own value
    #: because it is neither of the others: nobody disputed it, and no curator
    #: looked at it individually.
    RESTATED = "restated"
    #: A person signed for this substance taking another substance's number, in
    #: `data/lcia-factor-adoptions.json` -- an ion its element's, a named
    #: pesticide a catch-all's, a subtype of land its family's.  Distinct from
    #: `ruled` so a reader who goes looking for the reasoning finds the file it
    #: is in, and the only way a number crosses a substance boundary.
    ADOPTED = "adopted"
    #: Nobody characterised this flow; the number is the one this list publishes
    #: for the same substance in a neighbouring context, carried by a rule that
    #: names the pair (`lcia.context_carry`; #152 was the first such rule).
    CARRIED = "carried"
    #: Published by `derive()` on another flow and moved to the one it is about,
    #: by `data/lcia-misattributed-factors.json` (`lcia.misattributions`, #126).
    MOVED = "moved"
    #: A rounded printing replaced by the precise one, by
    #: `data/lcia-rounded-printings.json` (`lcia.precision`, #342).
    REFINED = "refined"


#: What makes two factors of two implementations the same factor: our flow, our
#: category, and the place.  **Our** category, not the publisher's: the JRC calls
#: it `Ecotoxicity, freshwater` and ecoinvent calls it `ecotoxicity: freshwater`,
#: and the crosswalk is the only thing that knows those are one category.  Keying
#: on either publisher's name would compare nothing with nothing -- every factor
#: `sole`, every ecoinvent factor proposed, and a consensus implementation that
#: looked plausible and had compared no numbers at all.
FactorKey = tuple[str, str, str]


#: How far apart two amounts can be, relatively, and still be one number that
#: crossed a unit conversion.  Far tighter than `FACTOR_TOLERANCE`, because it
#: answers a different question: 2% is the line between a rounding and a
#: disagreement when the *substance* is known to be the same, and this is the
#: line between a copied number and an independent one when it is not.  A
#: multiplier recorded by the merge turns 12274.013470217462 into
#: 12274.01347021746 -- the last bit of a double -- and nothing else does: two
#: publishers deriving a factor independently do not land within a billionth of
#: each other.
RESTATED_PRECISION = 1e-9


def _all_agree(
    amounts: Iterable[float], *, tolerance: float = FACTOR_TOLERANCE
) -> bool:
    """Whether every implementation is saying one number.

    Identical, or within *tolerance* -- by default `FACTOR_TOLERANCE`, the same
    2% `contested_cas` uses to decide whether two source lists are saying the
    same thing about a substance.  Not defined across zero or a sign change, and
    those go to the curator: a stated zero against a number is not a rounding of
    anything, it is two implementations disagreeing about whether something has
    an effect.

    Over the extremes, so that three implementations agree only if the widest pair
    among them does.
    """
    values = list(amounts)
    low, high = min(values), max(values)
    if low == high:
        return True
    if 0 in values or (low > 0) != (high > 0):
        return False
    smallest, largest = sorted((abs(low), abs(high)))
    return largest / smallest - 1 <= tolerance


def _ratio(amounts: Iterable[float]) -> float | None:
    """How far apart the widest pair is, or ``None`` where that is not defined."""
    values = list(amounts)
    low, high = min(values), max(values)
    if not low or not high or (low > 0) != (high > 0):
        return None
    smallest, largest = sorted((abs(low), abs(high)))
    return largest / smallest


def _most_precise(
    speaking: list[tuple[MethodImplementation, MatchedFactor]],
) -> tuple[MethodImplementation, MatchedFactor]:
    """The implementation whose number carries the most of it.

    `0.000118` and `0.00011755` are one number written twice, and this keeps the
    second -- the same judgement `pipeline.deduplication` makes about two rows that
    turn out to be one flow.  Folded left over the implementations rather than
    written for a pair, because agreement is not a two-sided thing.
    """
    best = speaking[0]
    for candidate in speaking[1:]:
        if (
            more_precise_value(best[1].factor.amount, candidate[1].factor.amount)
            == candidate[1].factor.amount
        ):
            best = candidate
    return best


def _ruling_for(
    rulings: dict[tuple[str, str, str], FactorRuling],
    substances: dict[str, str],
    *,
    queue: ReviewQueue,
    key: FactorKey,
    stated: dict[str, float],
) -> FactorRuling | None:
    """The ruling that answers this row, if a curator wrote one.

    Two things have to hold.  The ruling has to answer this queue's question about
    this substance and category -- the queue is part of its key, because one
    substance and category can be contested in one compartment and proposed in
    another, and a `proposed-factor` ruling was written without a second number in
    front of it and cannot settle a contested row.  And it has to have been written
    about the numbers the build now states, *all* of them: `stated` is every
    implementation's amount for this row, so a third implementation appearing is a
    row the ruling was not written about.
    """
    ruling = rulings.get((str(queue), substances.get(key[0], ""), key[1]))
    if ruling is None:
        return None
    if not ruling.covers(stated=stated):
        logger.warning(
            "factor_ruling_numbers_changed",
            item_key=ruling.item_key,
            ruled_about=ruling.ruled_about,
            found=stated,
        )
        return None
    return ruling


def _ruled(ruling: FactorRuling, amount: float | None) -> dict[str, Any]:
    """A ruling as a queue row carries it.

    The verdict, whose number it published and what that number was -- ``None``
    where it published none -- and the reasoning, which is the part a reader of the
    row came for.
    """
    return {
        "decision": str(ruling.verdict),
        "implemented_by": ruling.implemented_by,
        "published": amount,
        "comment": ruling.comment,
    }


def _stated(
    rows: list[tuple[MethodImplementation, MatchedFactor]],
) -> list[dict[str, Any]]:
    """What each implementation says about one triple, as a queue row holds it.

    A list rather than a key per implementation, for the reason the difference
    report is long-form: a question about three implementations is the same
    question, and a payload with a `jrc` key and an `ecoinvent` key could not hold
    it.
    """
    return [
        {
            "implemented_by": implementation.name,
            "amount": matched.factor.amount,
            "source_flow_uuid": matched.source_flow_uuid,
        }
        for implementation, matched in rows
    ]


def _twin_of_the_substance(
    entries: list[tuple[str, float]], *, flow: str, amount: float
) -> bool:
    """Whether the substance already carries this number in another context.

    Within `FACTOR_TOLERANCE`, the same 2% `_all_agree` draws between a rounding
    and a disagreement -- because the question is the same one: is ecoinvent's
    number for the compartment EF cannot express the number this list already
    publishes next door, written to a different precision?  12274.01347021746
    against a published 12274.013470217462 is one number that crossed a unit
    conversion, and demanding bit equality of it was what left hexavalent
    chromium's aquifer factor in the queue while the same number stood published
    for its surface water.

    Never the flow's own factors: the index is keyed on the substance, and a
    substance with one flow would otherwise match itself.
    """
    return any(
        other != flow and _all_agree((stated, amount)) for other, stated in entries
    )


def _adopted(adoption: FactorAdoption, amount: float | None) -> dict[str, Any]:
    """An adoption as a queue row carries it, in the shape a ruling has.

    The same keys, so the page shows a declined adoption the way it shows a
    declined ruling -- the decision above the evidence, the row `info` rather
    than `blocking` -- plus the file it came from and the donor, which is what a
    reader of a decline wants to know.
    """
    return {
        "decision": str(adoption.verdict),
        "implemented_by": ", ".join(sorted(adoption.implemented_by)),
        "published": amount,
        "comment": adoption.comment,
        "file": "lcia-factor-adoptions.json",
        "relationship": str(adoption.relationship),
        "donor": adoption.donor_name,
    }


def _settle_proposed(
    deferred: list[tuple[FactorKey, MatchedFactor, dict[str, Any]]],
    *,
    published: list[MatchedFactor],
    elsewhere: Mapping[tuple[str, str], list[tuple[str, float]]],
    substances: Mapping[str, str],
    adoptions: Mapping[str, FactorAdoption],
) -> tuple[list[MatchedFactor], int, int, list[tuple[str, str, dict[str, Any]]]]:
    """Decide the rows only a transcription states, against what the rest of the
    run did and what a person signed.

    Two things can settle one, and they are tried in this order.

    **The number is already published for this substance, in another context of
    the same category** -- within `FACTOR_TOLERANCE`, because two spellings of
    one number are one number (see :func:`_twin_of_the_substance`).  Then the
    transcription is not proposing a number: it is restating one this list
    already carries, in a compartment the reference's flow list cannot express.
    The row still says so: `derivation` is `restated`, and a reader can find the
    twin by looking up the same substance, category and amount.  *elsewhere* is
    that index, keyed on (substance, our category slug) and filled as the main
    loop publishes -- the publisher's own category name would compare nothing
    with nothing, which is the mistake `FactorKey` exists to prevent.  A twin
    restates only off `sole`, `agreed` and `ruled` factors, never off another
    restated row, so no chain of restatements can walk a number away from
    anything an implementation stated.

    **Or a person signed for it**, in `data/lcia-factor-adoptions.json`: the
    substance takes another substance's number -- an ion its element's, a named
    pesticide a catch-all's, a subtype of land its family's -- and the entry says
    which, why, and for which categories.  `adopt` publishes the row as
    `adopted`; `decline` publishes nothing and marks the row with the decision,
    so the page shows it answered rather than asking.  An entry that recorded
    its numbers answers only a row stating one of them.

    What no rule does any more is read the digits: the rule that published a
    proposed number because *some* flow of the category carried the same
    number bit for bit (#145) carried lindane's numbers onto its manufacturing
    contaminants, and is gone (#156).  A number crosses a substance boundary by
    signature or not at all.

    Note what neither route does.  It never publishes a number nobody stated;
    the amount is always the transcription's own.  And it never overwrites a
    value: every row here is one the reference is silent about and nobody
    disputes, because the main loop settled the others before deferring these.

    Whatever neither settles is a question, and stays one -- a transcription
    stating a number of its own, on a flow nothing else characterises anywhere,
    and those are exactly the rows worth a curator's time.
    """
    if not deferred:
        return published, 0, 0, []

    restated = adopted = 0
    questions: list[tuple[str, str, dict[str, Any]]] = []
    for key, matched, evidence in deferred:
        substance = substances.get(key[0], "")
        if _twin_of_the_substance(
            elsewhere.get((substance, key[1]), []),
            flow=key[0],
            amount=matched.factor.amount,
        ):
            published.append(replace(matched, derivation=str(Derivation.RESTATED)))
            restated += 1
            continue
        adoption = adoptions.get(substance)
        if adoption is not None and adoption.covers(
            category_slug=key[1],
            speaking={entry["implemented_by"] for entry in evidence["stated"]},
            stated={
                entry["implemented_by"]: entry["amount"] for entry in evidence["stated"]
            },
        ):
            if adoption.verdict is AdoptionVerdict.ADOPT:
                published.append(replace(matched, derivation=str(Derivation.ADOPTED)))
                adopted += 1
                continue
            # A decline publishes nothing and answers the row on the record.
            evidence = {**evidence, "ruled": _adopted(adoption, None)}
        questions.append((str(ReviewQueue.PROPOSED_FACTOR), key[1], evidence))
    return published, restated, adopted, questions


def derive(
    *,
    stated: Mapping[MethodImplementation, dict[FactorKey, MatchedFactor]],
    reference: MethodImplementation,
    substances: dict[str, str] | None = None,
    rulings: dict[tuple[str, str, str], FactorRuling] | None = None,
    adoptions: Mapping[str, FactorAdoption] | None = None,
    contradicted: Mapping[tuple[str, str], Contradiction] | None = None,
) -> tuple[
    list[MatchedFactor],
    list[tuple[str, str, dict[str, Any]]],
    dict[tuple[str, str, str], int],
]:
    """What this list publishes, what a curator ruled, and what is still asked.

    *stated* is each published implementation's factors, keyed on
    :data:`FactorKey` by the caller because it is the caller that holds the
    crosswalk: this compares numbers and does not decide what makes two of them
    comparable.  A mapping rather than one argument per implementation, because
    every source list shipping factors is one and there will be more than two.

    *reference* is the implementation the method's own publisher wrote -- the JRC
    for EF 3.1, and `LCIAMethodDefinition.reference` for any method.  It is a
    role rather than a name, and it decides one thing: a
    factor only the reference states is `sole` and needs no curator, while one the
    reference is silent about is `proposed` and needs one.  That asymmetry is real
    and worth spelling out: adopting a number for a flow the method's publisher
    never characterised is a decision, and adopting the publisher's own is not.

    *substances* maps a consensus flow to the substance it is an occurrence of,
    which is what a ruling is keyed on: kresoxim-methyl's freshwater ecotoxicity
    is one decision, taken about the substance rather than about each compartment.
    *rulings* defaults to none rather than to the curated file, so that a caller
    with no rulings and a caller with a test's rulings both say what they mean.

    *contradicted* is the (substance, category) pairs where the model this method
    is derived from states something more than a hundredfold away, computed by
    :mod:`brightway_flows.lcia.contradictions` against the numbers this build
    states.  A pair in it publishes nothing whatever the implementations say --
    including where they agree, because two transcriptions of one file agreeing is
    not evidence about the file.

    Returns the published factors, every row that reached a queue as
    ``(queue, category slug, evidence)`` triples, and how many rows each ruling
    settled.  A ruled row is in the second list too, carrying the ruling under
    ``ruled``: the answer belongs on the page the question was asked on, and
    :func:`queue_items` marks such a group `info` rather than `blocking`.  The
    third is so a caller can say that a ruling applied to nothing, which is what
    a ruling written about data that has moved on looks like.
    """
    substances = substances or {}
    rulings = rulings or {}
    adoptions = adoptions or {}
    contradicted = contradicted or {}
    published: list[MatchedFactor] = []
    questions: list[tuple[str, str, dict[str, Any]]] = []
    applied: Counter[tuple[str, str, str]] = Counter()
    #: Rows only ecoinvent states and no curator ruled on.  Held rather than
    #: decided in the loop, because whether one is `restated` depends on what
    #: this list publishes for the *same substance elsewhere*, and that is not
    #: known until every key has been seen.
    deferred: list[tuple[FactorKey, MatchedFactor, dict[str, Any]]] = []
    #: What this list publishes on each (substance, category), as (flow, amount)
    #: pairs, filled as the loop publishes so that a deferred row can ask
    #: whether its number is one already carried somewhere else -- by the same
    #: substance within tolerance, or by any flow of the category to bit
    #: precision.
    elsewhere: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)

    keys: set[FactorKey] = set()
    for factors in stated.values():
        keys.update(factors)

    for key in sorted(keys):
        speaking = [
            (implementation, factors[key])
            for implementation, factors in stated.items()
            if key in factors
        ]
        amounts = {
            implementation.name: matched.factor.amount
            for implementation, matched in speaking
        }
        from_reference = next(
            (matched for impl, matched in speaking if impl is reference), None
        )
        contradiction = contradicted.get((substances.get(key[0], ""), key[1]))

        if contradiction is None and len(speaking) == 1 and from_reference is not None:
            published.append(replace(from_reference, derivation=str(Derivation.SOLE)))
            elsewhere[(substances.get(key[0], ""), key[1])].append(
                (key[0], from_reference.factor.amount)
            )
            continue

        if (
            contradiction is None
            and len(speaking) > 1
            and _all_agree(amounts.values())
        ):
            keeps = _most_precise(speaking)
            published.append(
                replace(
                    keeps[1],
                    derivation=str(Derivation.AGREED),
                    also_stated=next(
                        matched.factor.amount
                        for implementation, matched in speaking
                        if implementation is not keeps[0]
                    ),
                )
            )
            elsewhere[(substances.get(key[0], ""), key[1])].append(
                (key[0], keeps[1].factor.amount)
            )
            continue

        # Three things can have happened, and each is a different question.  They
        # disagree; the method's own publisher is silent; or the model the method
        # is derived from states something more than a hundredfold away.
        #
        # The third takes precedence over both, and deliberately.  Where the two
        # transcriptions disagree *and* the underlying model contradicts both,
        # asking which of the two readings is right is asking the smaller question
        # first: a curator who settles it has published a number USEtox says is
        # wrong by 10^5.  The same holds for a row only ecoinvent states -- a
        # contradicted substance's factor in a compartment EF's flow list cannot
        # express is ecoinvent's transcription of the same contradicted number,
        # and "should this list adopt it" is not the question to ask about it.
        # A ruling written for either of the other queues stops applying, because
        # a ruling is keyed on its queue -- the same thing that happens to one
        # whose numbers have moved, and for the same reason.
        queue = (
            ReviewQueue.CONTRADICTED_FACTOR
            if contradiction is not None
            else ReviewQueue.CONTESTED_FACTOR
            if len(speaking) > 1
            else ReviewQueue.PROPOSED_FACTOR
        )
        ruling = _ruling_for(
            rulings, substances, queue=queue, key=key, stated=amounts
        )
        first = speaking[0][1]
        evidence: dict[str, Any] = {
            "elementary_flow_uuid": first.elementary_flow_uuid,
            "geography": first.factor.geography,
            "category": first.factor.category.name,
            "stated": _stated(speaking),
            "ratio": _ratio(amounts.values()),
        }
        if contradiction is not None:
            evidence["contradicts"] = contradiction.as_evidence()
        if ruling is not None:
            applied[ruling.key] += 1
            amount = None
            if ruling.verdict is Verdict.PUBLISH:
                keeps = next(
                    (
                        matched
                        for implementation, matched in speaking
                        if implementation.name == ruling.implemented_by
                    ),
                    None,
                )
                if keeps is None:
                    logger.warning(
                        "factor_ruling_names_a_silent_implementation",
                        item_key=ruling.item_key,
                        implemented_by=ruling.implemented_by,
                        stated=sorted(amounts),
                    )
                else:
                    amount = keeps.factor.amount
                    elsewhere[(substances.get(key[0], ""), key[1])].append(
                        (key[0], amount)
                    )
                    published.append(
                        replace(
                            keeps,
                            derivation=str(Derivation.RULED),
                            also_stated=next(
                                (
                                    other
                                    for name, other in amounts.items()
                                    if name != ruling.implemented_by
                                ),
                                None,
                            ),
                        )
                    )
            # A `decline` publishes nothing.  The row stays on the page it was
            # asked on, marked with the decision and the reasoning: 3,455
            # questions is too many to leave a curator no way of saying "looked
            # at, and no".
            evidence["ruled"] = _ruled(ruling, amount)
        elif queue is ReviewQueue.PROPOSED_FACTOR:
            # Nobody disputes it and no curator has answered it individually.
            # Two things can still settle it without one, and both are decided
            # after the loop: this list may already publish the same number for
            # the same substance in another context, or a person may have signed
            # for the substance taking another substance's number.
            deferred.append((key, speaking[0][1], evidence))
            continue
        questions.append((str(queue), key[1], evidence))

    published, restated, adopted, still_asked = _settle_proposed(
        deferred,
        published=published,
        elsewhere=elsewhere,
        substances=substances,
        adoptions=adoptions,
    )
    questions.extend(still_asked)

    for key, ruling in rulings.items():
        if not applied.get(key):
            logger.warning(
                "factor_ruling_applied_to_nothing",
                item_key=ruling.item_key,
                queue=ruling.queue,
                verdict=str(ruling.verdict),
            )
    logger.info(
        "derived_consensus_factors",
        implementations=len(stated),
        published=len(published),
        sole=sum(1 for f in published if f.derivation == Derivation.SOLE),
        agreed=sum(1 for f in published if f.derivation == Derivation.AGREED),
        ruled=sum(1 for f in published if f.derivation == Derivation.RULED),
        restated=restated,
        adopted=adopted,
        rulings=len(rulings),
        rulings_applied=len(applied),
        contradicted=len(contradicted),
        questions=len(questions),
    )
    return published, questions, dict(applied)


def queue_items(
    questions: list[tuple[str, str, dict[str, Any]]],
    *,
    method: str,
    flows: dict[str, dict[str, Any]],
    category_names: dict[str, str],
) -> dict[ReviewQueue, list[ReviewQueueItem]]:
    """The questions, as rows a curator can work through.

    Grouped by (substance, category): one question, however many contexts it is
    asked in.  142 contested factors are 36 questions over 14 substances, and on
    the 2026-08-24 build the 40 open proposed ones are 38 questions over 37
    substances -- every one of which proposes one number in every context it
    appears in, which is the fact that makes a broad ruling possible and so is
    on the row rather than left to be discovered.

    A group whose every row a curator has ruled on is `info` rather than
    `blocking`, and carries the decision and its reasoning: the queue is a work
    list, and an answered question is a record.

    *method* is the method the questions are about, and it is the first segment
    of the item key: the three factor queues hold every method's questions, and
    two methods can spell one category slug, so a key without it would let one
    method's question overwrite another's.

    *flows* maps a consensus flow uuid to what a reader needs to recognise it:
    its substance, its label, its compartment.  *category_names* maps a slug to
    the name **this list** publishes the category under, which is what a question
    is titled with: a question about `ecotoxicity: freshwater` and one about
    `Ecotoxicity, freshwater` would read as two questions about two categories,
    and they are one.  The item key is the slug rather than either name, because
    a display name is the publisher's and can be re-spelled, and a key has to
    survive that or a ruling stops matching the question it answered.
    """
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for queue, slug, evidence in questions:
        flow = flows.get(evidence["elementary_flow_uuid"], {})
        grouped[(queue, str(flow.get("flow_object_id") or ""), slug)].append(
            {**evidence, **flow}
        )

    items: dict[ReviewQueue, list[ReviewQueueItem]] = defaultdict(list)
    for (queue, flow_object_id, slug), rows in sorted(grouped.items()):
        rows.sort(
            key=lambda row: (
                str(row.get("context_display") or ""),
                str(row.get("geography") or ""),
            )
        )
        first = rows[0]
        name = category_names.get(slug, str(first.get("category") or slug))
        substance = str(first.get("label") or "")
        # Every implementation that speaks about this question, and every distinct
        # set of numbers they state.  Keyed by implementation rather than named
        # after one, so a question about a third is the same question.
        implementations: list[str] = []
        for row in rows:
            for entry in row.get("stated") or ():
                if entry["implemented_by"] not in implementations:
                    implementations.append(entry["implemented_by"])
        values = sorted({
            entry["amount"]
            for row in rows
            for entry in row.get("stated") or ()
        })
        worst = max((row.get("ratio") or 0 for row in rows), default=0)
        # A group every row of which was ruled is answered.  A group with some
        # ruled rows and some not is the shape a ruling written about numbers that
        # have since moved makes -- the rows it was written about are settled and
        # the new one asks again -- so it stays `blocking` on the strength of the
        # row that is still a question.
        ruled = [row["ruled"] for row in rows if row.get("ruled")]
        answered = len(ruled) == len(rows)
        payload: dict[str, Any] = {
            "category": name,
            "substance": substance,
            "contexts": sorted({str(row.get("context_display") or "") for row in rows}),
            "factor_count": len(rows),
            "rows": rows,
            "implementations": sorted(implementations),
            "ruled_count": len(ruled),
            # One decision per group, so the first is the decision; a group whose
            # rows carried two different ones would be two rulings on one key,
            # which the loader refuses.
            "ruling": ruled[0] if ruled else None,
            # The two facts a broad ruling turns on, computed here so the page
            # states them rather than a reader deriving them from the rows.
            "one_value_everywhere": len(values) == 1,
            "stated_values": values,
        }
        if queue == str(ReviewQueue.CONTRADICTED_FACTOR):
            # One contradiction per group, because it is keyed on exactly what the
            # group is: this substance and this category.  It goes on the item as
            # well as on each row so that a page can state the question -- "the
            # model says a millionth of this" -- without unpicking the rows.
            contradicts = next(
                (row["contradicts"] for row in rows if row.get("contradicts")), None
            )
            payload["contradicts"] = contradicts
            # The gap the queue sorts on is the model's, not the two
            # transcriptions': where both state a number here they state the same
            # one, and it is the one under question.
            payload["worst_ratio"] = (
                (contradicts or {}).get("widest_ratio") or worst or None
            )
            title = (
                f"{substance or flow_object_id}: {name}, {len(rows)} "
                f"contradicted by {(contradicts or {}).get('model') or 'the model'}"
            )
        elif queue == str(ReviewQueue.CONTESTED_FACTOR):
            payload["worst_ratio"] = worst or None
            title = f"{substance or flow_object_id}: {name}, {len(rows)} disputed"
        else:
            title = f"{substance or flow_object_id}: {name}, {len(rows)} proposed"
        if answered:
            title = f"{title} — ruled {payload['ruling']['decision']}"
        items[ReviewQueue(queue)].append(
            ReviewQueueItem(
                queue_name=ReviewQueue(queue),
                item_key=f"{method}|{flow_object_id}|{slug}",
                title=title,
                # The pipeline could not act and will not until somebody rules,
                # which is what `blocking` means.  Both queues are that: a factor
                # neither published nor refused is a factor waiting.  A ruled
                # group is `info`: nobody is being asked for anything, and the row
                # is there because the answer belongs where the question was.
                severity=Severity.INFO if answered else Severity.BLOCKING,
                uuid=str(first.get("elementary_flow_uuid") or ""),
                flow_object_id=flow_object_id,
                cas=str(first.get("cas") or ""),
                payload=payload,
            )
        )

    for rows_of_queue in items.values():
        rows_of_queue.sort(
            key=lambda item: (
                # Unanswered first, whatever their ratio: the queue is a work
                # list, and a settled row is a record rather than work.
                item.severity == Severity.INFO,
                -(item.payload.get("worst_ratio") or 0),
                -item.payload["factor_count"],
                item.payload["substance"],
                item.payload["category"],
            )
        )
        for index, item in enumerate(rows_of_queue):
            item.item_index = index
    return dict(items)
