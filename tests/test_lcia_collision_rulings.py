"""A curator can answer a factor collision, and the answer is checked against
the numbers it was made about.

Two Stepwise rows -- `Particulates` at 0.157 and `Particulates, unspecified` at
0.536 -- reach one flow, and `settle` publishes neither.  A ruling names the row
whose number is taken; the finding is still written, with the ruling on it; and a
ruling made about other numbers, or about fewer rows than collide, is not obeyed.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from brightway_flows.domain.lcia.records import StatedFactor, stated_category
from brightway_flows.lcia.collision_rulings import (
    COLLISION_RULINGS_FILEPATH,
    CollisionRuling,
    CollisionRulingError,
    load_collision_rulings,
)
from brightway_flows.lcia.collisions import settle
from brightway_flows.lcia.matching import MatchedFactor
from brightway_flows.lcia.report import FindingKind

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
    return {"schema_version": 1, "method": method, "rulings": list(rulings)}


def _record(row=None):
    row = row or _ruling()
    return CollisionRuling(
        method="stepwise-2006",
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
        self.assertEqual(ruling.key[1], "respiratory-inorganics")
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

    def test_a_file_with_no_method_raises(self):
        """The method-scope rule every curated factor file follows (rule 14):
        a file about no method, or about one nothing registers, raises where
        it is read rather than quietly ruling on nothing."""
        with self.assertRaises(ValueError):
            self._load({"schema_version": 1, "rulings": []})
        with self.assertRaises(ValueError):
            self._load(_document(_ruling(), method="stepwize"))

    def test_the_shipped_file_loads(self):
        self.assertTrue(COLLISION_RULINGS_FILEPATH.exists())
        index = load_collision_rulings(method="stepwise-2006")
        self.assertEqual(len(index), 1)


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


if __name__ == "__main__":
    unittest.main()
