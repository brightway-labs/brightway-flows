"""Curated answers to the two factor queues.

The mechanism has to hold three lines, and each is a way a decisions file can
lie:

* **A ruling is applied where it was written and nowhere else.** Keyed on the
  queue *and* the queue item, because the item key alone is not unique across the
  two -- one substance and category can be contested in one compartment and
  proposed in another, and a `proposed-factor` ruling was written with one number
  in front of it and cannot settle a row with two.
* **A ruling written about numbers that have moved is not obeyed.** It says what
  every implementation stated when it was made; a row stating something else --
  a different number, an implementation that has appeared, one that has gone
  silent -- asks again rather than being settled by a decision taken about
  something else. And `ruled_about` is required, because a ruling without it
  could never fail that check.
* **No verdict names a source list.** `publish` names the implementation whose
  number to take and `decline` takes nobody's, so comparing a third
  implementation needs no third verdict.
* **A malformed ruling raises rather than being skipped.** A curator's decision
  that looks applied and is not is the failure every decisions file in this
  project is written to avoid, so a missing comment, an unknown verdict and a
  verdict belonging to the other queue are all refusals at load.

The fourteen real rulings in `data/lcia-factor-rulings.json` are checked here too --
not their reasoning, which is a curator's, but that they answer questions the
build actually asks and were written about the numbers it actually states.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.lcia.records import StatedFactor, stated_category
from brightway_flows.domain.lcia.crosswalk import ef_method
from brightway_flows.lcia.consensus import Derivation, derive, queue_items
from brightway_flows.lcia.matching import MatchedFactor
from brightway_flows.lcia.rulings import (
    FactorRuling,
    FactorRulingError,
    Verdict,
    load_factor_rulings,
)
from brightway_flows.pipeline.review_records import ReviewQueue, Severity

#: EF 3.1's three implementations, read from its method file rather than from an
#: enum: an implementation belongs to a method, and which three these are is what
#: `data/lcia-impact-categories.json` says.
_METHOD = ef_method()
JRC_IMPL = _METHOD.reference
ECOINVENT_IMPL = _METHOD.implementation("ecoinvent-centre")
CONSENSUS_IMPL = _METHOD.consensus
IMPLEMENTATION_NAMES = {row.name for row in _METHOD.implementations}

SLUG = "ecotoxicity-freshwater"
SUBSTANCE = "fo-1"


def _matched(uuid: str, amount: float) -> MatchedFactor:
    return MatchedFactor(
        elementary_flow_uuid=uuid,
        factor=StatedFactor(
            category=stated_category(uuid="m-1", name="Ecotoxicity, freshwater"),
            flow_uuid="",
            amount=amount,
        ),
        source_flow_uuid="ei-1",
    )


def _keyed(rows: dict[str, float]) -> dict:
    return {(uuid, SLUG, ""): _matched(uuid, amount) for uuid, amount in rows.items()}


JRC = JRC_IMPL.name
ECOINVENT = ECOINVENT_IMPL.name


def _ruling(**overrides) -> FactorRuling:
    fields = {
        "method": _METHOD.slug,
        "flow_object_id": SUBSTANCE,
        "category_slug": SLUG,
        "queue": str(ReviewQueue.CONTESTED_FACTOR),
        "verdict": Verdict.PUBLISH,
        "implemented_by": JRC,
        "comment": "because the evidence says so",
        "ruled_about": {JRC: (1.0,), ECOINVENT: (100.0,)},
    }
    fields.update(overrides)
    return FactorRuling(**fields)


def _derive(rulings, *, jrc, ecoinvent):
    return derive(
        stated={
            JRC_IMPL: _keyed(jrc),
            ECOINVENT_IMPL: _keyed(ecoinvent),
        },
        reference=JRC_IMPL,
        substances={"cf-1": SUBSTANCE, "cf-2": SUBSTANCE},
        rulings={ruling.key: ruling for ruling in rulings},
    )


class ARuledContestedFactorTestCase(unittest.TestCase):
    def test_the_ruling_chooses_whose_number_is_published(self):
        """By naming an implementation, not by having a verdict per source list:
        `jrc` and `ecoinvent` as verdicts could not express a third."""
        for implemented_by, expected in ((JRC, 1.0), (ECOINVENT, 100.0)):
            with self.subTest(implemented_by=implemented_by):
                published, _questions, applied = _derive(
                    [_ruling(implemented_by=implemented_by)],
                    jrc={"cf-1": 1.0}, ecoinvent={"cf-1": 100.0},
                )
                self.assertEqual(
                    [(row.factor.amount, row.derivation) for row in published],
                    [(expected, str(Derivation.RULED))],
                )
                self.assertEqual(sum(applied.values()), 1)

    def test_the_other_number_is_kept_beside_it(self):
        """A reader of a ruled factor should be able to see what was ruled
        against without opening the rulings file."""
        published, _questions, _applied = _derive(
            [_ruling()], jrc={"cf-1": 1.0}, ecoinvent={"cf-1": 100.0}
        )
        self.assertEqual(published[0].also_stated, 100.0)

    def test_a_ruled_row_stays_on_the_page_it_was_asked_on(self):
        _published, questions, _applied = _derive(
            [_ruling()], jrc={"cf-1": 1.0}, ecoinvent={"cf-1": 100.0}
        )
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0][2]["ruled"]["decision"], "publish")
        self.assertEqual(questions[0][2]["ruled"]["implemented_by"], JRC)
        self.assertEqual(questions[0][2]["ruled"]["published"], 1.0)
        self.assertIn("evidence", questions[0][2]["ruled"]["comment"])

    def test_an_unruled_disagreement_still_publishes_nothing(self):
        published, questions, applied = _derive(
            [], jrc={"cf-1": 1.0}, ecoinvent={"cf-1": 100.0}
        )
        self.assertEqual(published, [])
        self.assertEqual(len(questions), 1)
        self.assertNotIn("ruled", questions[0][2])
        self.assertEqual(applied, {})

    def test_a_ruling_about_other_numbers_is_not_obeyed(self):
        """The rule `collision_decisions` applies to a collision whose flows have
        changed: a ruling written about different data does not go on being
        followed silently."""
        published, questions, applied = _derive(
            [_ruling(ruled_about={JRC: (1.0,), ECOINVENT: (100.0,)})],
            jrc={"cf-1": 1.0}, ecoinvent={"cf-1": 999.0},
        )
        self.assertEqual(published, [])
        self.assertNotIn("ruled", questions[0][2])
        self.assertEqual(applied, {})

    def test_a_ruling_covering_some_rows_settles_only_those(self):
        """And the group stays blocking on the strength of the row that is still
        a question, which is what a half-stale ruling should look like."""
        published, questions, _applied = _derive(
            [_ruling(ruled_about={JRC: (1.0,), ECOINVENT: (100.0,)})],
            jrc={"cf-1": 1.0, "cf-2": 1.0},
            ecoinvent={"cf-1": 100.0, "cf-2": 999.0},
        )
        self.assertEqual(len(published), 1)
        items = queue_items(
            questions,
            method=_METHOD.slug,
            flows={
                "cf-1": {"flow_object_id": SUBSTANCE, "label": "Something"},
                "cf-2": {"flow_object_id": SUBSTANCE, "label": "Something"},
            },
            category_names={SLUG: "Ecotoxicity, freshwater"},
        )
        item = items[ReviewQueue.CONTESTED_FACTOR][0]
        self.assertEqual(item.severity, Severity.BLOCKING)
        self.assertEqual(item.payload["ruled_count"], 1)
        self.assertEqual(item.payload["factor_count"], 2)


class ARuledProposedFactorTestCase(unittest.TestCase):
    def _derive(self, rulings):
        return derive(
            stated={
                JRC_IMPL: {},
                ECOINVENT_IMPL: _keyed({"cf-1": 6.0}),
            },
            reference=JRC_IMPL,
            substances={"cf-1": SUBSTANCE},
            rulings={ruling.key: ruling for ruling in rulings},
        )

    def _proposed(self, **overrides) -> FactorRuling:
        fields = {
            "queue": str(ReviewQueue.PROPOSED_FACTOR),
            "verdict": Verdict.PUBLISH,
            "implemented_by": ECOINVENT,
            "ruled_about": {ECOINVENT: (6.0,)},
        }
        fields.update(overrides)
        return _ruling(**fields)

    def test_publishing_takes_the_number_nobody_else_states(self):
        published, questions, applied = self._derive([self._proposed()])
        self.assertEqual(
            [(row.factor.amount, row.derivation) for row in published],
            [(6.0, str(Derivation.RULED))],
        )
        self.assertEqual(questions[0][2]["ruled"]["published"], 6.0)
        self.assertEqual(sum(applied.values()), 1)

    def test_decline_publishes_nothing_and_says_so(self):
        """3,455 open questions is too many to leave a curator no way of saying
        "looked at, and no"."""
        published, questions, applied = self._derive(
            [self._proposed(verdict=Verdict.DECLINE, implemented_by="")]
        )
        self.assertEqual(published, [])
        self.assertEqual(questions[0][2]["ruled"]["decision"], "decline")
        self.assertIsNone(questions[0][2]["ruled"]["published"])
        self.assertEqual(sum(applied.values()), 1)

    def test_a_declined_group_is_a_record_rather_than_work(self):
        _published, questions, _applied = self._derive(
            [self._proposed(verdict=Verdict.DECLINE, implemented_by="")]
        )
        items = queue_items(
            questions,
            method=_METHOD.slug,
            flows={"cf-1": {"flow_object_id": SUBSTANCE, "label": "Something"}},
            category_names={SLUG: "Ecotoxicity, freshwater"},
        )
        item = items[ReviewQueue.PROPOSED_FACTOR][0]
        self.assertEqual(item.severity, Severity.INFO)
        self.assertIn("ruled decline", item.title)
        self.assertEqual(item.payload["ruling"]["decision"], "decline")

    def test_a_contested_ruling_does_not_settle_a_proposed_question(self):
        """It was written with two numbers in front of it; this row has one."""
        published, questions, applied = self._derive([
            _ruling(queue=str(ReviewQueue.CONTESTED_FACTOR))
        ])
        self.assertEqual(published, [])
        self.assertNotIn("ruled", questions[0][2])
        self.assertEqual(applied, {})


class TheFileTestCase(unittest.TestCase):
    def _write(self, payload) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "rulings.json"
        path.write_bytes(orjson.dumps(payload))
        return path

    def _one(self, **overrides):
        row = {
            "flow_object_id": SUBSTANCE,
            "category_slug": SLUG,
            "queue": str(ReviewQueue.CONTESTED_FACTOR),
            "decision": "publish",
            "implemented_by": JRC,
            "comment": "the evidence, written down",
            "ruled_about": {JRC: [1.0], ECOINVENT: [100.0]},
        }
        row.update(overrides)
        return {"schema_version": 1, "method": _METHOD.slug, "rulings": [row]}

    def test_a_ruling_round_trips(self):
        rulings = load_factor_rulings(self._write(self._one()))
        ruling = next(iter(rulings.values()))
        self.assertEqual(ruling.verdict, Verdict.PUBLISH)
        self.assertEqual(ruling.implemented_by, JRC)
        self.assertEqual(ruling.item_key, f"{_METHOD.slug}|{SUBSTANCE}|{SLUG}")
        self.assertEqual(ruling.ruled_about[ECOINVENT], (100.0,))

    def test_a_missing_file_is_no_rulings_rather_than_an_error(self):
        self.assertEqual(load_factor_rulings(Path("/nonexistent.json")), {})

    def test_a_ruling_with_no_comment_is_refused(self):
        """Every entry is a statement about somebody else's science, and one with
        no reasoning is unreviewable."""
        with self.assertRaises(FactorRulingError) as caught:
            load_factor_rulings(self._write(self._one(comment="   ")))
        self.assertIn("comment", str(caught.exception))

    def test_an_unknown_verdict_is_refused(self):
        with self.assertRaises(FactorRulingError):
            load_factor_rulings(self._write(self._one(decision="whatever")))

    def test_publishing_an_implementation_the_question_is_not_about_is_refused(self):
        """A ruling that names a number nobody in the question stated."""
        with self.assertRaises(FactorRulingError) as caught:
            load_factor_rulings(
                self._write(self._one(implemented_by="Somebody Else"))
            )
        self.assertIn("not among the implementations", str(caught.exception))

    def test_publishing_nobody_is_refused(self):
        with self.assertRaises(FactorRulingError) as caught:
            load_factor_rulings(self._write(self._one(implemented_by="")))
        self.assertIn("names no implementation", str(caught.exception))

    def test_declining_somebody_is_refused(self):
        """A decline publishes nobody's number, so naming one is a ruling that
        means two things."""
        with self.assertRaises(FactorRulingError) as caught:
            load_factor_rulings(self._write(self._one(decision="decline")))
        self.assertIn("publishes nobody", str(caught.exception))

    def test_a_ruling_with_no_ruled_about_is_refused(self):
        """It would be a ruling the staleness check could never fail, which is
        the same as not having the check."""
        for empty in ({}, None):
            with self.subTest(ruled_about=empty):
                with self.assertRaises(FactorRulingError) as caught:
                    load_factor_rulings(
                        self._write(self._one(ruled_about=empty))
                    )
                self.assertIn("ruled_about", str(caught.exception))

    def test_an_unknown_queue_is_refused(self):
        with self.assertRaises(FactorRulingError):
            load_factor_rulings(self._write(self._one(queue="contested-cas")))

    def test_two_rulings_on_one_question_are_refused(self):
        payload = self._one()
        payload["rulings"].append(
            dict(payload["rulings"][0], implemented_by=ECOINVENT)
        )
        with self.assertRaises(FactorRulingError) as caught:
            load_factor_rulings(self._write(payload))
        self.assertIn("a second time", str(caught.exception))

    def test_one_question_in_each_queue_is_two_rulings(self):
        """The same substance and category, contested in one compartment and
        proposed in another: two questions, two answers, one item key."""
        payload = self._one()
        payload["rulings"].append(dict(
            payload["rulings"][0],
            queue=str(ReviewQueue.PROPOSED_FACTOR),
            implemented_by=ECOINVENT,
            ruled_about={ECOINVENT: [6.0]},
        ))
        self.assertEqual(len(load_factor_rulings(self._write(payload))), 2)

    def test_a_newer_schema_version_is_refused(self):
        payload = self._one()
        payload["schema_version"] = 99
        with self.assertRaises(FactorRulingError):
            load_factor_rulings(self._write(payload))

    def test_a_non_numeric_ruled_about_value_is_refused(self):
        with self.assertRaises(FactorRulingError):
            load_factor_rulings(
                self._write(self._one(ruled_about={JRC: ["134.73"]}))
            )


class TheCuratedRulingsTestCase(unittest.TestCase):
    """The fourteen real ones. Their reasoning is a curator's; their shape is not."""

    def setUp(self):
        self.rulings = load_factor_rulings()

    def test_nine_substances_are_ruled(self):
        substances = {ruling.substance for ruling in self.rulings.values()}
        self.assertEqual(
            substances,
            {
                "Particles (PM2.5 - PM10)",
                "Kresoxim-methyl",
                "Carbon Dioxide, To Soil Or Biomass Stock",
                "Carnallite",
                "Sulphuryl Difluoride",
                "Sulfur hexafluoride",
                "Water vapour",
                "Peat, Horticulture",
                "Gas, Mine, Off-gas, Process, Coal Mining",
            },
        )

    def test_each_substance_answers_the_queue_its_question_is_in(self):
        """Six substances, two queues, and the pairing is not incidental.

        Kresoxim-methyl is contested: both implementations state a number and the
        ruling picks one.  Carbon into a land pool is proposed: only the ecoinvent
        Centre states a number, because EF's carbon model has no row for it, and
        the ruling adopts theirs.  Carnallite from water is proposed too -- again
        only the ecoinvent Centre speaks -- and the ruling declines it (#148).
        Sulphuryl difluoride is proposed and adopted (#151): ecoinvent added AR6's
        own GWP100 for a gas EF never characterised for climate at all.  A ruling
        filed under the other queue would answer a question nobody asked, which
        is what keying on the queue is for.  Sulfur hexafluoride is contested
        like kresoxim-methyl, and unlike it the two numbers are two assessments
        rather than one file read twice: AR6's lifetime against a newer one
        (#342).  Water vapour under `Water use` is proposed and declined (#154):
        the ecoinvent Centre counts consumption on the evaporated water and the
        JRC counts it on the withdrawal less the return, and publishing both
        counted every consumed cubic metre twice.  Horticultural peat under
        `Resource use, fossils` is proposed and declined (#160): EF files it as a
        renewable material from the biosphere, measured in kilograms, beside the
        fuel peat it files from the ground in megajoules, and the ecoinvent
        Centre's 9.76 is the fuel's calorific value on the growing medium.  Coal
        mine off-gas is the same queue and the opposite verdict (#161): EF files
        a fossil fuel among the material resources, in standard cubic metres, so
        neither resource indicator reaches it, and the ruling publishes the 36
        the JRC's own rule produces.
        """
        by_substance: dict[str, set[str]] = {}
        for ruling in self.rulings.values():
            by_substance.setdefault(ruling.substance, set()).add(ruling.queue)
        self.assertEqual(
            by_substance,
            {
                "Kresoxim-methyl": {str(ReviewQueue.CONTESTED_FACTOR)},
                # The coarse band is proposed: only the ecoinvent Centre states a
                # number there since #37's rows were retired, and the owner's
                # ruling that the band takes PM10's number (#196) publishes it.
                "Particles (PM2.5 - PM10)": {str(ReviewQueue.PROPOSED_FACTOR)},
                "Carbon Dioxide, To Soil Or Biomass Stock": {
                    str(ReviewQueue.PROPOSED_FACTOR)
                },
                "Carnallite": {str(ReviewQueue.PROPOSED_FACTOR)},
                "Sulphuryl Difluoride": {str(ReviewQueue.PROPOSED_FACTOR)},
                "Sulfur hexafluoride": {str(ReviewQueue.CONTESTED_FACTOR)},
                "Water vapour": {str(ReviewQueue.PROPOSED_FACTOR)},
                "Peat, Horticulture": {str(ReviewQueue.PROPOSED_FACTOR)},
                "Gas, Mine, Off-gas, Process, Coal Mining": {
                    str(ReviewQueue.PROPOSED_FACTOR)
                },
            },
        )

    def test_every_one_carries_the_numbers_of_the_implementations_it_is_about(self):
        """Without them a ruling cannot be checked against a later build, which
        is the whole of the staleness contract.

        *Which* implementations those are is the queue's business.  A contested
        question is two implementations disagreeing, so both are recorded; a
        proposed one is a number only ecoinvent states, and recording a second
        implementation would be recording a silence as a number.  `covers()`
        compares the two sets exactly, so a ruling that named the JRC on a
        proposed question would stop applying the moment the build agreed with it.
        """
        expected = {
            str(ReviewQueue.CONTESTED_FACTOR): {JRC, ECOINVENT},
            str(ReviewQueue.PROPOSED_FACTOR): {ECOINVENT},
        }
        for ruling in self.rulings.values():
            with self.subTest(ruling=ruling.item_key):
                self.assertEqual(set(ruling.ruled_about), expected[ruling.queue])
                self.assertTrue(all(ruling.ruled_about.values()))

    def test_every_one_cites_the_issue_it_came_from(self):
        for ruling in self.rulings.values():
            with self.subTest(ruling=ruling.item_key):
                self.assertRegex(ruling.comment, r"#\d+")

    def test_the_category_twins_are_ruled_the_same_way(self):
        """EF ships an aggregate category and its organics or inorganics half,
        and the same disagreement appears in both. A ruling on one and not the
        other would publish two different numbers for one substance."""
        by_substance: dict[str, set[str]] = {}
        for ruling in self.rulings.values():
            by_substance.setdefault(ruling.substance, set()).add(
                f"{ruling.verdict}:{ruling.implemented_by}"
            )
        for substance, verdicts in by_substance.items():
            with self.subTest(substance=substance):
                self.assertEqual(len(verdicts), 1)

    def test_vanadium_is_no_longer_ruled_about(self):
        """It was, in five compartments where the ratio was exactly 10, and the
        ruling recorded both sides so that a build where it stopped being 10
        would ask again. What asked again was the routing, not the ratio.

        EF 3.1 ships two vanadium flows in every context and states 1.3532e-06
        for `vanadium` and 1.3532e-05 for `vanadium (v)` in its own workbook:
        the ten is EF's speciation factor for vanadium(V), which is why the
        mantissa survived it. ecoinvent was reading the right EF row; this
        project was comparing it against the element, because its `Vanadium V`
        flows were routed there. With the routing corrected (#49) the two
        implementations agree to every digit and there is nothing to rule, so
        both rulings are withdrawn -- and this case is inverted rather than
        deleted, because "we once ruled here and stopped" is the part a later
        reader needs.
        """
        self.assertEqual(
            [row for row in self.rulings.values() if row.substance == "Vanadium"],
            [],
        )


if __name__ == "__main__":
    unittest.main()
