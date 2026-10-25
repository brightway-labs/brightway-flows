"""A curator can answer a factor collision, and the answer is checked against
the numbers it was made about.

Two Stepwise rows -- `Particulates` at 0.157 and `Particulates, unspecified` at
0.536 -- reach one flow, and `settle` publishes neither.  A ruling names the row
whose number is taken; the finding is still written, with the ruling on it; and a
ruling made about other numbers, or about fewer rows than collide, is not obeyed.

The same for EF 3.1, where three implementations ship rows and a ruling names
the one whose rows collided (#444).  GreenDelta's two `Chromium III` rows in
rural air, `017c1ca1` and `d43572af`, both reach `Chromium(3+)` and state 333.75
and 4,292.06 for freshwater ecotoxicity (#445).  GreenDelta files the category
under the JRC's ILCD identifier, which is what the matching groups its rows on,
so the ruling has to be found under that and not under a name.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from brightway_flows.domain.lcia.crosswalk import ef_method, lcia_method
from brightway_flows.domain.lcia.records import StatedFactor, stated_category
from brightway_flows.lcia.collision_rulings import (
    COLLISION_RULINGS_FILEPATH,
    COLLISION_RULINGS_FILEPATHS,
    STEPWISE_COLLISION_RULINGS_FILEPATH,
    CollisionRuling,
    CollisionRulingError,
    load_collision_rulings,
)
from brightway_flows.lcia.collisions import settle
from brightway_flows.lcia.conversion import UnitCrossing
from brightway_flows.lcia.matching import MatchedFactor, MergeTarget, match
from brightway_flows.lcia.pipeline import _collision_rulings_by_flow
from brightway_flows.lcia.report import FindingKind
from brightway_flows.lcia.sources import FactorSource

FLOW = "flow-unsized-air"
PLAIN = "091b4543-a1fd-57c4-a373-c451dbc9ae0c"
UNSPECIFIED = "b36a7cfe-f045-5aa3-9eee-fbc276a2770d"


def _candidate(source_uuid, amount):
    return MatchedFactor(
        elementary_flow_uuid=FLOW,
        factor=StatedFactor(
            category=stated_category(uuid="ri", name="Respiratory inorganics"),
            flow_uuid=source_uuid,
            amount=amount,
        ),
        source_flow_uuid=source_uuid,
    )


def _ruling(**overrides):
    row = {
        "implemented_by": "2.-0 LCA consultants",
        "flow_object_id": "fo-777f2e757f3ff45a",
        "category_slug": "respiratory-inorganics",
        "context_iri": "https://vocab.brightway.one/flow-contexts/envi-air-unkn",
        "publish_source_flow_uuid": PLAIN,
        "ruled_about": {PLAIN: 0.157142857, UNSPECIFIED: 0.535714286},
        "comment": "because",
    }
    row.update(overrides)
    return row


def _document(*rulings, method="stepwise-2006"):
    return {"schema_version": 2, "method": method, "rulings": list(rulings)}


def _record(row=None):
    row = row or _ruling()
    return CollisionRuling(
        method="stepwise-2006",
        implemented_by=row["implemented_by"],
        flow_object_id=row["flow_object_id"],
        category_slug=row["category_slug"],
        context_iri=row["context_iri"],
        publish_source_flow_uuid=row["publish_source_flow_uuid"],
        ruled_about=dict(row["ruled_about"]),
        comment=row["comment"],
    )


class LoadingTest(unittest.TestCase):
    def _load(self, document, method=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rulings.json"
            path.write_text(json.dumps(document))
            return load_collision_rulings(path, method=method)

    def test_a_well_formed_file_reads_as_records(self):
        index = self._load(_document(_ruling()))
        (ruling,) = index.values()
        self.assertEqual(ruling.publish_source_flow_uuid, PLAIN)
        self.assertEqual(ruling.key[0], "2.-0 LCA consultants")
        self.assertEqual(ruling.key[2], "respiratory-inorganics")
        self.assertEqual(ruling.ruled_about[UNSPECIFIED], 0.535714286)

    def test_it_is_read_for_its_own_method_only(self):
        self.assertEqual(self._load(_document(_ruling()), method="ef"), {})
        self.assertEqual(len(self._load(_document(_ruling()), method="stepwise-2006")), 1)

    def test_the_published_row_must_be_one_it_was_made_about(self):
        with self.assertRaises(CollisionRulingError):
            self._load(_document(_ruling(publish_source_flow_uuid="somebody-else")))

    def test_it_must_say_what_every_colliding_row_stated(self):
        with self.assertRaises(CollisionRulingError):
            self._load(_document(_ruling(ruled_about={PLAIN: 0.157})))
        with self.assertRaises(CollisionRulingError):
            self._load(_document(_ruling(ruled_about={})))

    def test_a_comment_is_required(self):
        with self.assertRaises(CollisionRulingError):
            self._load(_document(_ruling(comment="")))

    def test_a_question_is_answered_once(self):
        with self.assertRaises(CollisionRulingError):
            self._load(_document(_ruling(), _ruling()))

    def test_it_must_name_the_implementation_whose_rows_collided(self):
        with self.assertRaises(CollisionRulingError):
            self._load(_document(_ruling(implemented_by="")))

    def test_the_implementation_must_be_one_of_the_methods(self):
        """GreenDelta implements EF 3.1, not Stepwise, and the consensus
        implementation has no rows of its own to collide."""
        with self.assertRaises(CollisionRulingError):
            self._load(_document(_ruling(implemented_by="GreenDelta")))
        with self.assertRaises(CollisionRulingError):
            self._load(_document(_ruling(implemented_by="brightway-flows")))

    def test_the_category_must_be_one_the_implementation_states(self):
        with self.assertRaises(CollisionRulingError):
            self._load(_document(_ruling(category_slug="respiratory-inorganic")))

    def test_a_file_of_the_first_shape_is_refused(self):
        """Version 1 named no implementation."""
        document = _document(_ruling())
        document["schema_version"] = 1
        with self.assertRaises(CollisionRulingError):
            self._load(document)

    def test_an_ef_ruling_names_an_ef_implementation(self):
        (ruling,) = self._load(_document(_ef_ruling(), method="ef"), method="ef").values()
        self.assertEqual(ruling.implemented_by, "GreenDelta")
        self.assertEqual(ruling.method, "ef")
        with self.assertRaises(CollisionRulingError):
            self._load(
                _document(_ef_ruling(implemented_by="2.-0 LCA consultants"), method="ef")
            )

    def test_a_file_with_no_method_raises(self):
        """The method-scope rule every curated factor file follows (rule 14):
        a file about no method, or about one nothing registers, raises where
        it is read rather than quietly ruling on nothing."""
        with self.assertRaises(ValueError):
            self._load({"schema_version": 2, "rulings": []})
        with self.assertRaises(ValueError):
            self._load(_document(_ruling(), method="stepwize"))

    def test_the_shipped_files_load(self):
        for filepath in COLLISION_RULINGS_FILEPATHS:
            self.assertTrue(filepath.exists(), filepath.name)
        index = load_collision_rulings(method="stepwise-2006")
        self.assertEqual(len(index), 1)
        self.assertEqual(load_collision_rulings(STEPWISE_COLLISION_RULINGS_FILEPATH), index)
        self.assertEqual(
            load_collision_rulings(COLLISION_RULINGS_FILEPATH),
            load_collision_rulings(method="ef"),
        )

    def test_each_file_is_read_for_its_own_method(self):
        for method in ("ef", "stepwise-2006"):
            self.assertTrue(
                all(
                    ruling.method == method
                    for ruling in load_collision_rulings(method=method).values()
                ),
                method,
            )


class SettleWithARulingTest(unittest.TestCase):
    def test_the_ruled_row_is_published_and_the_finding_says_so(self):
        candidates = [_candidate(PLAIN, 0.157142857), _candidate(UNSPECIFIED, 0.535714286)]
        kept, finding = settle(
            candidates,
            elementary_flow_uuid=FLOW,
            implemented_by="2.-0 LCA consultants",
            category="Respiratory inorganics",
            geography=None,
            ruling=_record(),
        )
        self.assertIsNotNone(kept)
        self.assertEqual(kept.source_flow_uuid, PLAIN)
        self.assertEqual(kept.factor.amount, 0.157142857)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.kind, FindingKind.FACTOR_COLLISION)
        self.assertIn("ruled", finding.detail)
        self.assertEqual(finding.context["ruled"]["published"], PLAIN)

    def test_a_ruling_about_other_numbers_is_not_obeyed(self):
        candidates = [_candidate(PLAIN, 0.2), _candidate(UNSPECIFIED, 0.535714286)]
        kept, finding = settle(
            candidates,
            elementary_flow_uuid=FLOW,
            implemented_by="2.-0 LCA consultants",
            category="Respiratory inorganics",
            geography=None,
            ruling=_record(),
        )
        self.assertIsNone(kept)
        self.assertNotIn("ruled", finding.context)

    def test_a_ruling_about_fewer_rows_than_collide_is_not_obeyed(self):
        candidates = [
            _candidate(PLAIN, 0.157142857),
            _candidate(UNSPECIFIED, 0.535714286),
            _candidate("a-third-row", 9.0),
        ]
        kept, _ = settle(
            candidates,
            elementary_flow_uuid=FLOW,
            implemented_by="2.-0 LCA consultants",
            category="Respiratory inorganics",
            geography=None,
            ruling=_record(),
        )
        self.assertIsNone(kept)

    def test_rows_that_agree_need_no_ruling(self):
        kept, finding = settle(
            [_candidate(PLAIN, 0.5), _candidate(UNSPECIFIED, 0.5)],
            elementary_flow_uuid=FLOW,
            implemented_by="2.-0 LCA consultants",
            category="Respiratory inorganics",
            geography=None,
            ruling=_record(),
        )
        self.assertIsNotNone(kept)
        self.assertIsNone(finding)


# GreenDelta's two `Chromium III` rows in Emission to air/low population density
# (#445), on the six-list build of 3b6528e.
CHROMIUM = "4d9a8790-3ddd-11dd-8fcf-0050c2490048"
CHROMIUM_FLOW_OBJECT = "fo-cc41dd8cd4558176"
RURAL_AIR = "https://vocab.brightway.one/flow-contexts/envi-air-mest15me-ru10pesq"
FIRST = "017c1ca1-8e93-3c85-b743-c8676bfd305a"
SECOND = "d43572af-d023-443b-9fad-d56ffc0adc53"
#: What GreenDelta's rows, and the JRC's, file freshwater ecotoxicity under.
FRESHWATER = "05316e7a-b254-4bea-9cf0-6bf33eb5c630"


def _ef_ruling(**overrides):
    row = {
        "implemented_by": "GreenDelta",
        "flow_object_id": CHROMIUM_FLOW_OBJECT,
        "category_slug": "ecotoxicity-freshwater",
        "context_iri": RURAL_AIR,
        "publish_source_flow_uuid": FIRST,
        "ruled_about": {FIRST: 333.7474653, SECOND: 4292.0565976},
        "comment": "because",
    }
    row.update(overrides)
    return row


def _ef_record(**overrides):
    row = _ef_ruling(**overrides)
    return CollisionRuling(
        method="ef",
        implemented_by=row["implemented_by"],
        flow_object_id=row["flow_object_id"],
        category_slug=row["category_slug"],
        context_iri=row["context_iri"],
        publish_source_flow_uuid=row["publish_source_flow_uuid"],
        ruled_about=dict(row["ruled_about"]),
        comment=row["comment"],
    )


class GreenDeltaRulingTest(unittest.TestCase):
    """An EF ruling, from its key to the number `match` publishes for
    GreenDelta's rows."""

    FLOWS = {CHROMIUM: {"flow_object_id": CHROMIUM_FLOW_OBJECT, "context_iri": RURAL_AIR}}

    def setUp(self):
        self.method = ef_method()
        self.greendelta = self.method.implementation("greendelta")

    def _rulings(self, ruling=None, flows=None):
        ruling = ruling or _ef_record()
        return _collision_rulings_by_flow(
            self.method, {ruling.key: ruling}, flows=flows or self.FLOWS
        )

    def _match(self, rows, rulings):
        """GreenDelta's *rows* -- (source uuid, amount) -- for freshwater
        ecotoxicity, each merged onto `Chromium(3+)` in rural air."""
        source = FactorSource(
            implementation=self.greendelta,
            by_flow={
                uuid: [
                    StatedFactor(
                        category=stated_category(
                            uuid=FRESHWATER, name="Ecotoxicity freshwater"
                        ),
                        flow_uuid=uuid,
                        amount=amount,
                    )
                ]
                for uuid, amount in rows
            },
            flows_are_consensus=False,
            read_from="test",
        )
        return match(
            source,
            index={
                uuid: MergeTarget(CHROMIUM, UnitCrossing("kg", "kg")) for uuid, _ in rows
            },
            collision_rulings=rulings.get(self.greendelta.name, {}),
        )

    def test_the_ruling_is_found_under_the_identifier_greendelta_states(self):
        self.assertIn((CHROMIUM, FRESHWATER), self._rulings()["GreenDelta"])

    def test_the_ruling_is_not_handed_to_another_implementation(self):
        """The JRC files freshwater ecotoxicity under the same identifier, and
        an answer about GreenDelta's two rows is not an answer about the JRC's."""
        self.assertEqual(set(self._rulings()), {"GreenDelta"})

    def test_a_deprecated_flow_answers_to_nothing(self):
        flows = {CHROMIUM: {**self.FLOWS[CHROMIUM], "deprecated": True}}
        self.assertEqual(self._rulings(flows=flows), {})

    def test_without_a_ruling_neither_number_is_published(self):
        matched, findings = self._match(
            [(FIRST, 333.7474653), (SECOND, 4292.0565976)], {}
        )
        self.assertEqual(matched, [])
        (finding,) = findings
        self.assertEqual(finding.kind, FindingKind.FACTOR_COLLISION)
        self.assertNotIn("ruled", finding.context)

    def test_the_ruled_row_is_published_and_the_finding_says_so(self):
        matched, findings = self._match(
            [(FIRST, 333.7474653), (SECOND, 4292.0565976)], self._rulings()
        )
        (kept,) = matched
        self.assertEqual(kept.source_flow_uuid, FIRST)
        self.assertEqual(kept.factor.amount, 333.7474653)
        (finding,) = findings
        self.assertEqual(finding.kind, FindingKind.FACTOR_COLLISION)
        self.assertEqual(finding.implemented_by, "GreenDelta")
        self.assertEqual(finding.context["ruled"]["published"], FIRST)

    def test_a_moved_number_is_a_new_question(self):
        matched, findings = self._match(
            [(FIRST, 333.7474653), (SECOND, 4300.0)], self._rulings()
        )
        self.assertEqual(matched, [])
        (finding,) = findings
        self.assertNotIn("ruled", finding.context)

    def test_a_third_row_is_a_new_question(self):
        matched, findings = self._match(
            [(FIRST, 333.7474653), (SECOND, 4292.0565976), ("a-third-row", 1000.0)],
            self._rulings(),
        )
        self.assertEqual(matched, [])
        (finding,) = findings
        self.assertNotIn("ruled", finding.context)

    def test_a_ruling_about_another_category_is_not_obeyed(self):
        """The inorganics half of freshwater ecotoxicity is a category of its
        own, filed under an identifier of its own."""
        matched, _ = self._match(
            [(FIRST, 333.7474653), (SECOND, 4292.0565976)],
            self._rulings(_ef_record(category_slug="ecotoxicity-freshwater-inorganics")),
        )
        self.assertEqual(matched, [])


class StepwiseRulingIsFoundByNameTest(unittest.TestCase):
    """Stepwise's rows carry no category identifier, only the name, and the
    shipped ruling is found under the name 2.-0 LCA consultants states."""

    def test_the_shipped_ruling_resolves_onto_its_flow(self):
        rulings = load_collision_rulings(method="stepwise-2006")
        (ruling,) = rulings.values()
        flows = {
            FLOW: {"flow_object_id": ruling.flow_object_id, "context_iri": ruling.context_iri}
        }
        self.assertEqual(
            _collision_rulings_by_flow(lcia_method("stepwise-2006"), rulings, flows=flows),
            {"2.-0 LCA consultants": {(FLOW, "respiratory inorganics"): ruling}},
        )


if __name__ == "__main__":
    unittest.main()
