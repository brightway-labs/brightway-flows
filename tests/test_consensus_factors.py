"""The consensus implementation publishes what nobody disputes, and asks the rest.

Two implementations of one method agree about almost everything: over a full build
of 2026-08-17, 297,468 of the 323,947 (flow, category, place) triples they state
between them have one witness and 21,965 have two that agree. Those 319,433 are
published.

The other 4,514 were questions on that build, and the point of this module is
that a question is not a number:

* 142 factors where both state a number and the two differ beyond `FACTOR_TOLERANCE`
  — 36 questions over 14 substances, the widest kresoxim-methyl at 397× (#64);
* 4,372 only ecoinvent states — 3,455 questions over 1,018 substances, 3,990 of the
  factors in the three compartments EF's flow list cannot express (#84).

Taking the method's own publisher by default would have published 142 numbers
nobody had looked at, under a label saying a decision was made, so those go to a
curator. Of the factors only ecoinvent states, what this list already publishes
in the same category — the same substance in another context within tolerance,
or any flow bit for bit — is `restated` rather than asked, because ecoinvent is
carrying this list's own number rather than proposing one; a number of
ecoinvent's own still goes to a curator.

What is tested here is the comparison, the grouping into questions, and the one
thing that would silently break the whole design: comparing on the publisher's own
category name rather than on ours.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.lcia.records import StatedFactor, stated_category
from brightway_flows.lcia.adoptions import FactorAdoption, Relationship
from brightway_flows.lcia.adoptions import Verdict as AdoptionVerdict
from brightway_flows.domain.lcia.crosswalk import ef_method
from brightway_flows.lcia.consensus import (
    Derivation,
    derive,
    queue_items,
)
from brightway_flows.lcia.matching import MatchedFactor
from brightway_flows.pipeline.review_records import ReviewQueue, Severity

#: EF 3.1's three implementations, read from its method file rather than from an
#: enum: an implementation belongs to a method, and which three these are is what
#: `data/lcia-impact-categories.json` says.
_METHOD = ef_method()
JRC_IMPL = _METHOD.reference
ECOINVENT_IMPL = _METHOD.implementation("ecoinvent-centre")
CONSENSUS_IMPL = _METHOD.consensus
IMPLEMENTATION_NAMES = {row.name for row in _METHOD.implementations}


def _derive(*, jrc, ecoinvent, **kwargs):
    """`derive`, given the two implementations this list publishes today.

    A mapping keyed by implementation is what it takes, because every source list
    that ships factors is one and there will be more than two; these tests are
    about what gets published, so they say the two by name here and once.
    """
    return derive(
        stated={
            JRC_IMPL: jrc,
            ECOINVENT_IMPL: ecoinvent,
        },
        reference=JRC_IMPL,
        **kwargs,
    )

SLUG = "ecotoxicity-freshwater"
NAMES = {SLUG: "Ecotoxicity, freshwater"}


def _factor(amount, *, geography=None, name="Ecotoxicity, freshwater", uuid="ef-m1"):
    return StatedFactor(
        category=stated_category(uuid=uuid, name=name),
        flow_uuid="",
        amount=amount,
        geography=geography,
    )


def _matched(amount, *, flow="cf-1", geography=None, source=None, ecoinvent=False):
    return MatchedFactor(
        elementary_flow_uuid=flow,
        factor=_factor(
            amount,
            geography=geography,
            name="ecotoxicity: freshwater" if ecoinvent else "Ecotoxicity, freshwater",
            uuid=None if ecoinvent else "ef-m1",
        ),
        source_flow_uuid=source,
    )


def _keyed(rows, *, geography=""):
    return {
        (row.elementary_flow_uuid, SLUG, row.factor.geography or ""): row
        for row in rows
    }


FLOWS = {
    "cf-1": {
        "flow_object_id": "fo-1",
        "label": "Kresoxim-methyl",
        "context_display": "Environmental → Ground → Agricultural",
    },
    "cf-2": {
        "flow_object_id": "fo-1",
        "label": "Kresoxim-methyl",
        "context_display": "Environmental → Ground → Unknown",
    },
    "cf-3": {
        "flow_object_id": "fo-2",
        "label": "Atrazine",
        "context_display": "Environmental → Ground → Silvicultural",
    },
}


class TheDerivationsAreClosedTestCase(unittest.TestCase):
    """The set is a decision rather than a stage, and `inherited` is not in it.

    `inherited` was planned -- a factor taken from a broader context of the same
    substance *where neither implementation states one* -- and measuring it after
    the queues existed is what stopped it: 4,626 factors rather than the 145 the
    plan estimated, and 92% of them in the three compartments EF's flow list
    cannot express, where publishing the broader number is the coarsening #84
    removed. A test rather than a comment, because the next person to read §4.3's
    first draft will find the rung listed there.

    `restated` is not that rung arriving by another name, and this asserts the
    difference where a reader will see it: it publishes a number ecoinvent
    states, never one nobody states.

    `carried`, `moved` and `refined` are the three passes that run after
    `derive()`, each reading a curated file that names what it may touch; they
    are in the enum so that one loop counts every route, and `carried` is the
    one that fills a flow nobody characterised -- by a rule that names the pair
    of contexts, never by a broader context being nearer (#152, and
    `plans/lcia-consensus-decisions.md` §5).
    """

    def test_the_derivations_are_the_eight_that_are_meant(self):
        self.assertEqual(
            sorted(str(member) for member in Derivation),
            ["adopted", "agreed", "carried", "moved", "refined", "restated", "ruled", "sole"],
        )

    def test_nothing_is_inherited(self):
        self.assertNotIn("inherited", {str(member) for member in Derivation})

    def test_every_published_factor_carries_one_of_them(self):
        published, _questions, _applied = _derive(jrc=_keyed([_matched(134.73)]), ecoinvent={})
        self.assertIn(
            published[0].derivation, {str(member) for member in Derivation}
        )


class WhatIsPublishedTestCase(unittest.TestCase):
    def test_a_factor_only_the_jrc_states_is_sole(self):
        published, questions, _applied = _derive(jrc=_keyed([_matched(134.73)]), ecoinvent={})
        self.assertEqual(questions, [])
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0].derivation, str(Derivation.SOLE))
        self.assertEqual(published[0].factor.amount, 134.73)

    def test_two_identical_numbers_are_agreed(self):
        published, questions, _applied = _derive(jrc=_keyed([_matched(3.02)]), ecoinvent=_keyed([_matched(3.02, ecoinvent=True, source="ei-1")]),
        )
        self.assertEqual(questions, [])
        self.assertEqual(published[0].derivation, str(Derivation.AGREED))
        self.assertEqual(published[0].factor.amount, 3.02)

    def test_one_number_written_twice_keeps_the_precise_one(self):
        """`0.000118` and `0.00011755` are one number, and the same judgement
        `deduplication` makes about two rows that turn out to be one flow."""
        published, questions, _applied = _derive(jrc=_keyed([_matched(0.000118)]), ecoinvent=_keyed([_matched(0.00011755, ecoinvent=True, source="ei-1")]),
        )
        self.assertEqual(questions, [])
        self.assertEqual(published[0].factor.amount, 0.00011755)
        self.assertEqual(published[0].derivation, str(Derivation.AGREED))
        self.assertEqual(published[0].also_stated, 0.000118)

    def test_two_places_are_two_factors(self):
        published, questions, _applied = _derive(
            jrc=_keyed([_matched(-522.81, geography="ES-CA"),
                        _matched(-227.0, geography="YE")]),
            ecoinvent={},
        )
        self.assertEqual(questions, [])
        self.assertEqual(
            sorted(row.factor.geography for row in published), ["ES-CA", "YE"]
        )


class WhatIsNotPublishedTestCase(unittest.TestCase):
    def test_a_disagreement_publishes_nothing_and_asks(self):
        published, questions, _applied = _derive(jrc=_keyed([_matched(134.73)]), ecoinvent=_keyed([_matched(53540.0, ecoinvent=True, source="ei-1")]),
        )
        self.assertEqual(published, [])
        self.assertEqual(len(questions), 1)
        queue, slug, evidence = questions[0]
        self.assertEqual(queue, str(ReviewQueue.CONTESTED_FACTOR))
        self.assertEqual(slug, SLUG)
        self.assertEqual(
            {row["implemented_by"]: row["amount"] for row in evidence["stated"]},
            {
                JRC_IMPL.name: 134.73,
                ECOINVENT_IMPL.name: 53540.0,
            },
        )
        self.assertEqual(round(evidence["ratio"]), 397)

    def test_a_stated_zero_against_a_number_is_a_disagreement(self):
        """Not a rounding of anything: two implementations disagreeing about
        whether the substance has an effect at all."""
        published, questions, _applied = _derive(jrc=_keyed([_matched(0.0)]), ecoinvent=_keyed([_matched(0.5, ecoinvent=True, source="ei-1")]),
        )
        self.assertEqual(published, [])
        self.assertEqual(questions[0][0], str(ReviewQueue.CONTESTED_FACTOR))
        self.assertIsNone(questions[0][2]["ratio"])

    def test_a_factor_only_ecoinvent_states_is_proposed(self):
        published, questions, _applied = _derive(jrc={}, ecoinvent=_keyed([_matched(9.9, flow="cf-3", ecoinvent=True, source="ei-1")]),
        )
        self.assertEqual(published, [])
        self.assertEqual(questions[0][0], str(ReviewQueue.PROPOSED_FACTOR))
        stated = questions[0][2]["stated"]
        self.assertEqual(len(stated), 1)
        self.assertEqual(stated[0]["implemented_by"], ECOINVENT_IMPL.name)
        self.assertEqual(stated[0]["amount"], 9.9)
        self.assertEqual(stated[0]["source_flow_uuid"], "ei-1")


class TheComparisonIsOnOurCategoryTestCase(unittest.TestCase):
    """The failure this design dies of quietly, if the key is wrong.

    The JRC calls it `Ecotoxicity, freshwater` and ecoinvent calls it
    `ecotoxicity: freshwater`. Keyed on either publisher's own name, nothing is
    ever compared: every JRC factor comes out `sole`, every ecoinvent factor is
    proposed, and the implementation looks plausible having compared no numbers at
    all. It happened on the first run of this code, and the numbers looked fine.
    """

    def test_two_publishers_names_meet_on_one_key(self):
        jrc = _matched(3.02)
        ecoinvent = _matched(3.02, ecoinvent=True, source="ei-1")
        self.assertNotEqual(jrc.factor.category.name, ecoinvent.factor.category.name)
        published, questions, _applied = _derive(jrc=_keyed([jrc]), ecoinvent=_keyed([ecoinvent])
        )
        self.assertEqual(questions, [])
        self.assertEqual(published[0].derivation, str(Derivation.AGREED))

    def test_nothing_compared_would_look_like_this(self):
        """The shape of the bug, stated so a reader can recognise it: keyed
        apart, one agreement becomes one `sole` and one proposal."""
        jrc = {("cf-1", "Ecotoxicity, freshwater", ""): _matched(3.02)}
        ecoinvent = {
            ("cf-1", "ecotoxicity: freshwater", ""): _matched(
                3.02, ecoinvent=True, source="ei-1"
            )
        }
        published, questions, _applied = _derive(jrc=jrc, ecoinvent=ecoinvent)
        self.assertEqual([row.derivation for row in published], [str(Derivation.SOLE)])
        self.assertEqual(questions[0][0], str(ReviewQueue.PROPOSED_FACTOR))


class TheQuestionsAreGroupedTestCase(unittest.TestCase):
    """One question per (substance, category), however many contexts it is in."""

    def _questions(self):
        _published, questions, _applied = _derive(
            jrc=_keyed([_matched(134.73), _matched(134.73, flow="cf-2")]),
            ecoinvent=_keyed([
                _matched(53540.0, ecoinvent=True, source="ei-1"),
                _matched(53540.0, flow="cf-2", ecoinvent=True, source="ei-2"),
            ]),
        )
        return questions

    def test_two_contexts_of_one_substance_are_one_question(self):
        items = queue_items(
            self._questions(),
            method=_METHOD.slug,
            flows=FLOWS,
            category_names=NAMES,
        )
        rows = items[ReviewQueue.CONTESTED_FACTOR]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].payload["factor_count"], 2)
        self.assertEqual(len(rows[0].payload["contexts"]), 2)

    def test_the_item_key_is_the_slug_not_the_display_name(self):
        """A publisher can re-spell a name; a ruling has to survive that."""
        rows = queue_items(
            self._questions(),
            method=_METHOD.slug,
            flows=FLOWS,
            category_names=NAMES,
        )[ReviewQueue.CONTESTED_FACTOR]
        self.assertEqual(rows[0].item_key, f"{_METHOD.slug}|fo-1|{SLUG}")

    def test_the_question_is_titled_with_our_name_for_the_category(self):
        """A question about `ecotoxicity: freshwater` and one about
        `Ecotoxicity, freshwater` would read as two questions about two
        categories, and they are one."""
        _published, questions, _applied = _derive(
            jrc={},
            ecoinvent=_keyed([
                _matched(9.9, flow="cf-3", ecoinvent=True, source="ei-1")
            ]),
        )
        rows = queue_items(questions, method=_METHOD.slug, flows=FLOWS, category_names=NAMES)[
            ReviewQueue.PROPOSED_FACTOR
        ]
        self.assertEqual(rows[0].payload["category"], "Ecotoxicity, freshwater")

    def test_a_question_is_blocking(self):
        """The pipeline could not act and will not until somebody rules, which is
        what `blocking` means -- and a factor neither published nor refused is a
        factor waiting."""
        rows = queue_items(
            self._questions(),
            method=_METHOD.slug,
            flows=FLOWS,
            category_names=NAMES,
        )[ReviewQueue.CONTESTED_FACTOR]
        self.assertEqual(rows[0].severity, Severity.BLOCKING)

    def test_one_number_in_every_context_is_on_the_row(self):
        """The fact that makes a ruling about a compartment possible rather than
        one about 4,372 flows: 2,914 of the 3,455 proposals are this."""
        _published, questions, _applied = _derive(
            jrc={},
            ecoinvent=_keyed([
                _matched(9.9, flow="cf-3", ecoinvent=True, source="ei-1"),
                _matched(9.9, flow="cf-1", ecoinvent=True, source="ei-2"),
            ]),
        )
        rows = queue_items(questions, method=_METHOD.slug, flows=FLOWS, category_names=NAMES)[
            ReviewQueue.PROPOSED_FACTOR
        ]
        by_substance = {row.flow_object_id: row for row in rows}
        self.assertTrue(by_substance["fo-2"].payload["one_value_everywhere"])
        self.assertEqual(by_substance["fo-2"].payload["stated_values"], [9.9])

    def test_different_numbers_across_contexts_say_so(self):
        _published, questions, _applied = _derive(
            jrc={},
            ecoinvent=_keyed([
                _matched(9.9, flow="cf-1", ecoinvent=True, source="ei-1"),
                _matched(1.1, flow="cf-2", ecoinvent=True, source="ei-2"),
            ]),
        )
        rows = queue_items(questions, method=_METHOD.slug, flows=FLOWS, category_names=NAMES)[
            ReviewQueue.PROPOSED_FACTOR
        ]
        self.assertFalse(rows[0].payload["one_value_everywhere"])
        self.assertEqual(rows[0].payload["stated_values"], [1.1, 9.9])

    def test_the_widest_disagreement_sorts_first(self):
        _published, questions, _applied = _derive(
            jrc=_keyed([_matched(1.0), _matched(1.0, flow="cf-3")]),
            ecoinvent=_keyed([
                _matched(2.0, ecoinvent=True, source="ei-1"),
                _matched(1000.0, flow="cf-3", ecoinvent=True, source="ei-2"),
            ]),
        )
        rows = queue_items(questions, method=_METHOD.slug, flows=FLOWS, category_names=NAMES)[
            ReviewQueue.CONTESTED_FACTOR
        ]
        self.assertEqual([row.flow_object_id for row in rows], ["fo-2", "fo-1"])
        self.assertEqual([row.item_index for row in rows], [0, 1])


if __name__ == "__main__":
    unittest.main()


#: Two flows of one substance, which is what the restating rule is about: a
#: number published on one of them and proposed on the other.
SUBSTANCES = {"cf-1": "fo-1", "cf-2": "fo-1", "cf-3": "fo-2"}


class RestatingANumberTheSubstanceAlreadyCarriesTestCase(unittest.TestCase):
    """A factor only ecoinvent states, whose value this list already publishes.

    EF 3.1's flow list has no silvicultural soil, no industrial soil, no
    groundwater and no ion flows, so its publisher states nothing for them and
    only ecoinvent does.  Nearly all of what ecoinvent proposes there is not a
    number of its own: it is one this list already publishes, either for *the
    same substance in another context of the same category* -- within
    `FACTOR_TOLERANCE`, because two spellings of one number are one number --
    or, across an identity boundary like `Copper, Ion` against `Copper`, the
    very same number bit for bit on another flow of the category.  Publishing
    either is not deciding anything about somebody else's science; it is
    carrying a number this list already stands behind.

    What makes it safe is what it refuses to do, and the boundary tests are
    that: the amount published is always one an implementation stated, a number
    nothing anywhere carries stays a question, and across substances neither a
    2% neighbour nor a shared zero is evidence -- only the number itself.
    """

    def test_a_number_the_substance_carries_elsewhere_is_published(self):
        published, questions, _applied = _derive(
            jrc=_keyed([_matched(134.73, flow="cf-1")]),
            ecoinvent=_keyed([_matched(134.73, flow="cf-2", ecoinvent=True)]),
            substances=SUBSTANCES,
        )
        self.assertEqual(len(published), 2)
        restated = [f for f in published if f.elementary_flow_uuid == "cf-2"]
        self.assertEqual(len(restated), 1)
        self.assertEqual(restated[0].derivation, str(Derivation.RESTATED))
        self.assertEqual(restated[0].factor.amount, 134.73)
        self.assertEqual(questions, [])

    def test_the_published_amount_is_the_one_ecoinvent_stated(self):
        """Never a number nobody stated, which is the rung §4.3 rejected."""
        published, _questions, _applied = _derive(
            jrc=_keyed([_matched(134.73, flow="cf-1")]),
            ecoinvent=_keyed([_matched(134.73, flow="cf-2", ecoinvent=True)]),
            substances=SUBSTANCES,
        )
        restated = next(f for f in published if f.elementary_flow_uuid == "cf-2")
        self.assertIsNone(restated.also_stated)
        self.assertEqual(restated.source_flow_uuid, None)

    def test_a_number_written_to_a_different_precision_is_the_same_number(self):
        """The twin match is `FACTOR_TOLERANCE`, not bit equality.

        ecoinvent states 12274.01347021746 for hexavalent chromium in an
        unconfined aquifer, and this list publishes 12274.013470217462 for its
        surface water -- one number, apart by the last bit of a double after the
        merge's unit conversion.  Demanding exactness left it in the queue, and
        `_all_agree` already knew better: two spellings of one number are one
        number.
        """
        published, questions, _applied = _derive(
            jrc=_keyed([_matched(12274.013470217462, flow="cf-1")]),
            ecoinvent=_keyed(
                [_matched(12274.01347021746, flow="cf-2", ecoinvent=True)]
            ),
            substances=SUBSTANCES,
        )
        restated = next(f for f in published if f.elementary_flow_uuid == "cf-2")
        self.assertEqual(restated.derivation, str(Derivation.RESTATED))
        self.assertEqual(restated.factor.amount, 12274.01347021746)
        self.assertEqual(questions, [])

    def test_a_different_number_is_still_a_question(self):
        """The boundary: a number of ecoinvent's own stays in the queue."""
        published, questions, _applied = _derive(
            jrc=_keyed([_matched(134.73, flow="cf-1")]),
            ecoinvent=_keyed([_matched(53540.0, flow="cf-2", ecoinvent=True)]),
            substances=SUBSTANCES,
        )
        self.assertEqual([f.elementary_flow_uuid for f in published], ["cf-1"])
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0][0], str(ReviewQueue.PROPOSED_FACTOR))

    def test_another_substances_identical_number_is_not_a_reason(self):
        """`fo-2` carrying the very same 134.73 vouches for nothing on `fo-1`.

        This was the identity-crossing half of the rule (#145): where any flow
        of the category published the proposed number bit for bit, the factor
        was a restatement.  It carried copper's numbers onto its ion -- and
        lindane's onto its manufacturing contaminants, which EF's own numbers
        hold 21 to 34 times apart (#131).  The digits cannot tell the two apart,
        so the rule is gone (#156): a number crosses a substance boundary by a
        signed entry in `lcia-factor-adoptions.json`, or it stays a question.
        """
        published, questions, _applied = _derive(
            jrc=_keyed([_matched(134.73, flow="cf-3")]),
            ecoinvent=_keyed([_matched(134.73, flow="cf-2", ecoinvent=True)]),
            substances=SUBSTANCES,
        )
        self.assertEqual([f.elementary_flow_uuid for f in published], ["cf-3"])
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0][0], str(ReviewQueue.PROPOSED_FACTOR))

    def test_another_substances_nearby_number_is_not_a_reason(self):
        """Across an identity boundary, only the very number counts.

        134.0 on `fo-2` is within 2% of the proposed 134.73, and 2% across
        substances is how O-cresol's ecotoxicity would come to vouch for
        copper's: two substances land near each other by coincidence all the
        time.  The tolerance that reads two spellings of one number belongs to
        the substance's own twin; a stranger's number is evidence only bit for
        bit.
        """
        published, questions, _applied = _derive(
            jrc=_keyed([_matched(134.0, flow="cf-3")]),
            ecoinvent=_keyed([_matched(134.73, flow="cf-2", ecoinvent=True)]),
            substances=SUBSTANCES,
        )
        self.assertEqual([f.elementary_flow_uuid for f in published], ["cf-3"])
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0][0], str(ReviewQueue.PROPOSED_FACTOR))

    def test_another_substances_zero_is_not_a_reason(self):
        """A published zero matches any proposed zero exactly, and proves
        nothing: every category publishes thousands of them."""
        published, questions, _applied = _derive(
            jrc=_keyed([_matched(0.0, flow="cf-3")]),
            ecoinvent=_keyed([_matched(0.0, flow="cf-2", ecoinvent=True)]),
            substances=SUBSTANCES,
        )
        self.assertEqual([f.elementary_flow_uuid for f in published], ["cf-3"])
        self.assertEqual(len(questions), 1)

    def test_the_same_flow_is_not_another_context(self):
        """A number published on the very flow under question is not evidence.

        It cannot arise from `derive` -- one key is decided once -- and the guard
        is here because the index is keyed on the substance, and a substance with
        one flow would otherwise match itself.
        """
        published, questions, _applied = _derive(
            jrc={},
            ecoinvent=_keyed([_matched(134.73, flow="cf-2", ecoinvent=True)]),
            substances=SUBSTANCES,
        )
        self.assertEqual(published, [])
        self.assertEqual(len(questions), 1)


class ApprovingAPopulationTestCase(unittest.TestCase):
    """The 62 pesticides whose proposed numbers are a catch-all's.

    ecoinvent's correspondence routes them into `Insecticides, unspecified` and
    its implementation characterises them there, so what it states for the named
    substance is the bucket's number.  This project publishes them under their
    own names (#76), which leaves EF's publisher silent about them.  Approved as
    a population, in a curated file, because what makes them acceptable is a fact
    about these substances rather than about their numbers.
    """

    def _approval(self, **kwargs):
        defaults = dict(
            flow_object_id="fo-1",
            substance="Alanycarb",
            categories=frozenset({SLUG}),
            catch_all="Insecticides, Unspecified",
            relationship=Relationship.CATCH_ALL,
            verdict=AdoptionVerdict.ADOPT,
            comment="Measured: every proposed number is the bucket's.",
            implemented_by=frozenset({ECOINVENT_IMPL.name}),
        )
        return {"fo-1": FactorAdoption(**{**defaults, **kwargs})}

    def test_a_decline_publishes_nothing_and_answers_the_row(self):
        """The record that somebody looked and said no: the row stays on the
        proposed-factor page carrying the decision, the way a ruled decline
        does, and nothing is published."""
        published, questions, _applied = _derive(
            jrc={},
            ecoinvent=_keyed([_matched(53540.0, flow="cf-2", ecoinvent=True)]),
            substances=SUBSTANCES,
            adoptions=self._approval(verdict=AdoptionVerdict.DECLINE),
        )
        self.assertEqual(published, [])
        self.assertEqual(len(questions), 1)
        queue, _slug, evidence = questions[0]
        self.assertEqual(queue, str(ReviewQueue.PROPOSED_FACTOR))
        self.assertEqual(evidence["ruled"]["decision"], "decline")
        self.assertEqual(evidence["ruled"]["file"], "lcia-factor-adoptions.json")
        self.assertIsNone(evidence["ruled"]["published"])

    def test_an_adoption_never_overwrites_a_stated_value(self):
        """An adoption answers a row the reference is silent about, and nothing
        else.  Where the JRC states a number for the same flow the row is
        `agreed` or contested before the file is read, and where the two
        disagree the adoption does not pick the transcription's side."""
        published, questions, _applied = _derive(
            jrc=_keyed([_matched(53540.0, flow="cf-2")]),
            ecoinvent=_keyed([_matched(53540.0, flow="cf-2", ecoinvent=True)]),
            substances=SUBSTANCES,
            adoptions=self._approval(),
        )
        self.assertEqual([f.derivation for f in published], [str(Derivation.AGREED)])
        published, questions, _applied = _derive(
            jrc=_keyed([_matched(134.73, flow="cf-2")]),
            ecoinvent=_keyed([_matched(53540.0, flow="cf-2", ecoinvent=True)]),
            substances=SUBSTANCES,
            adoptions=self._approval(),
        )
        self.assertEqual(published, [])
        self.assertEqual(questions[0][0], str(ReviewQueue.CONTESTED_FACTOR))

    def test_an_approved_substance_publishes_ecoinvents_number(self):
        published, questions, _applied = _derive(
            jrc={},
            ecoinvent=_keyed([_matched(53540.0, flow="cf-2", ecoinvent=True)]),
            substances=SUBSTANCES,
            adoptions=self._approval(),
        )
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0].derivation, str(Derivation.ADOPTED))
        self.assertEqual(published[0].factor.amount, 53540.0)
        self.assertEqual(questions, [])

    def test_a_category_the_approval_does_not_name_is_still_a_question(self):
        """Bounded deliberately: a category arriving later is a new question."""
        published, questions, _applied = _derive(
            jrc={},
            ecoinvent=_keyed([_matched(53540.0, flow="cf-2", ecoinvent=True)]),
            substances=SUBSTANCES,
            adoptions=self._approval(categories=frozenset({"land-use"})),
        )
        self.assertEqual(published, [])
        self.assertEqual(len(questions), 1)

    def test_an_implementation_the_approval_never_heard_from_is_a_question(self):
        """An approval of ecoinvent's number is not an approval of a third
        implementation's arriving later, which is the rule a ruling's
        `ruled_about` enforces for the same reason."""
        published, questions, _applied = _derive(
            jrc={},
            ecoinvent=_keyed([_matched(53540.0, flow="cf-2", ecoinvent=True)]),
            substances=SUBSTANCES,
            adoptions=self._approval(implemented_by=frozenset({"Somebody else"})),
        )
        self.assertEqual(published, [])
        self.assertEqual(len(questions), 1)

    def test_an_approval_that_recorded_its_numbers_covers_only_those(self):
        """The minerals' reason is an arithmetic on today's element factors, so
        the number is the approval's whole content: a revised number is a new
        question, the way a ruling written about other numbers is not obeyed."""
        approvals = self._approval(
            catch_all="",
            relationship=Relationship.FORMULA_WEIGHTED,
            adopted_about={ECOINVENT_IMPL.name: (53540.0,)},
        )
        published, questions, _applied = _derive(
            jrc={},
            ecoinvent=_keyed([_matched(53540.0, flow="cf-2", ecoinvent=True)]),
            substances=SUBSTANCES,
            adoptions=approvals,
        )
        self.assertEqual([f.derivation for f in published], [str(Derivation.ADOPTED)])
        self.assertEqual(questions, [])
        published, questions, _applied = _derive(
            jrc={},
            ecoinvent=_keyed([_matched(53541.0, flow="cf-2", ecoinvent=True)]),
            substances=SUBSTANCES,
            adoptions=approvals,
        )
        self.assertEqual(published, [])
        self.assertEqual(len(questions), 1)

    def test_restating_wins_over_an_approval(self):
        """Both would publish the same number; the narrower reason is the true
        one, and a reader of the factor should be told the number was already
        this list's rather than that a curator waved it through."""
        published, _questions, _applied = _derive(
            jrc=_keyed([_matched(134.73, flow="cf-1")]),
            ecoinvent=_keyed([_matched(134.73, flow="cf-2", ecoinvent=True)]),
            substances=SUBSTANCES,
            adoptions=self._approval(),
        )
        restated = next(f for f in published if f.elementary_flow_uuid == "cf-2")
        self.assertEqual(restated.derivation, str(Derivation.RESTATED))

    def test_an_approval_wins_over_another_substances_number(self):
        """The catch-all pesticides are the case: every number ecoinvent states
        for `Alanycarb` is the bucket's, published bit for bit on `Insecticides,
        unspecified` -- so the category-wide twin would reach them all.  The
        approval names the mechanism and the curator, and that record is the one
        a reader should find, not a mechanical match that happens to agree.
        """
        published, _questions, _applied = _derive(
            jrc=_keyed([_matched(53540.0, flow="cf-3")]),
            ecoinvent=_keyed([_matched(53540.0, flow="cf-2", ecoinvent=True)]),
            substances=SUBSTANCES,
            adoptions=self._approval(),
        )
        approved = next(f for f in published if f.elementary_flow_uuid == "cf-2")
        self.assertEqual(approved.derivation, str(Derivation.ADOPTED))
