"""Taking a published row away, for a flow the target list has nowhere to put.

An override rewrites a target: "the table sent this flow to the wrong place,
send it *there* instead".  That answer needs somewhere right to point, and for
the flows this exists for there is nowhere.  EF 3.1 carries `Trifloxystrobin` in
agricultural soil and non-urban air and nowhere else, so ecoinvent's
correspondence table routes the two water flows onto `Fungicides, unspecified` --
not because a bucket is the right answer but because it had no third option.

A decline is the third option: the row goes away, the flow reaches the merge
looking like one the table never mentioned, and the addition path mints a
consensus flow for it.  That is already what happens to `Trifloxystrobin` in
`water/unspecified`, which the table does not mention and which is published
under its own name today -- so a decline makes the four contexts agree rather
than introducing a new behaviour.

What is checked here: that a decline removes every row for its flow and not one
fewer, that it is never appended for a flow the table omits, that it survives a
second application unchanged, that it cannot also name a target, and that a
flow nobody declined is untouched.
"""

import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.match_overrides import (
    apply_match_overrides,
    load_match_overrides,
)


def _decline(**fields):
    row = {
        "source_uuid": "s-1",
        "source_name": "Trifloxystrobin",
        "decline": True,
        "comment": (
            "EF 3.1 has no trifloxystrobin flow in water, so the table's "
            "`Fungicides, unspecified` is a bucket rather than a target."
        ),
    }
    row.update(fields)
    return row


def _rewrite(**fields):
    row = {
        "source_uuid": "s-2",
        "source_name": "Something",
        "target_uuid": "t-new",
        "target_name": "something else",
        "comment": "Because the published table is wrong about this one.",
    }
    row.update(fields)
    return row


def _source_uuid(row):
    side = row.get("source") or {}
    return str(side.get("uuid") or side.get("identifier") or "")


class DeclineTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _file(self, *overrides):
        path = self.dir / "overrides.json"
        path.write_bytes(orjson.dumps({"overrides": list(overrides)}))
        return path

    def test_the_row_is_taken_away(self):
        rows = [{"source": {"uuid": "s-1"}, "target": {"uuid": "t-bucket"}}]
        self.assertEqual(apply_match_overrides(rows, self._file(_decline())), [])

    def test_every_row_for_the_flow_goes(self):
        """Not the first.  The merge refuses a source flow whose prepared rows
        disagree, so one left behind would turn a decline into an unmatched row
        that still carries the bucket."""
        rows = [
            {"source": {"uuid": "s-1"}, "target": {"uuid": "t-bucket"}},
            {"source": {"uuid": "s-1"}, "target": {"uuid": "t-bucket"}},
        ]
        self.assertEqual(apply_match_overrides(rows, self._file(_decline())), [])

    def test_other_flows_are_untouched(self):
        rows = [
            {"source": {"uuid": "s-1"}, "target": {"uuid": "t-bucket"}},
            {"source": {"uuid": "s-9"}, "target": {"uuid": "t-keep"}},
        ]
        result = apply_match_overrides(rows, self._file(_decline()))
        self.assertEqual([_source_uuid(r) for r in result], ["s-9"])

    def test_it_is_not_appended_when_the_table_omits_the_flow(self):
        """A rewrite is appended there, because the flow would otherwise never
        see the decision.  A decline for a flow the table does not mention has
        already got exactly what it asked for."""
        rows = [{"source": {"uuid": "s-9"}, "target": {"uuid": "t-keep"}}]
        result = apply_match_overrides(rows, self._file(_decline()))
        self.assertEqual([_source_uuid(r) for r in result], ["s-9"])

    def test_applying_twice_is_applying_once(self):
        """The file is applied at load time and again by the 3.8 composition."""
        rows = [
            {"source": {"uuid": "s-1"}, "target": {"uuid": "t-bucket"}},
            {"source": {"uuid": "s-9"}, "target": {"uuid": "t-keep"}},
        ]
        path = self._file(_decline())
        once = apply_match_overrides(rows, path)
        self.assertEqual(apply_match_overrides(once, path), once)

    def test_declines_and_rewrites_coexist(self):
        rows = [
            {"source": {"uuid": "s-1"}, "target": {"uuid": "t-bucket"}},
            {"source": {"uuid": "s-2"}, "target": {"uuid": "t-old"}},
        ]
        result = apply_match_overrides(rows, self._file(_decline(), _rewrite()))
        self.assertEqual([_source_uuid(r) for r in result], ["s-2"])
        self.assertEqual(result[0]["target"]["uuid"], "t-new")

    def test_the_table_is_not_mutated(self):
        rows = [{"source": {"uuid": "s-1"}, "target": {"uuid": "t-bucket"}}]
        apply_match_overrides(rows, self._file(_decline()))
        self.assertEqual(len(rows), 1)


class DeclineValidationTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _file(self, *overrides):
        path = self.dir / "overrides.json"
        path.write_bytes(orjson.dumps({"overrides": list(overrides)}))
        return path

    def test_a_decline_needs_no_target(self):
        rows = load_match_overrides(self._file(_decline()))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].decline)

    def test_a_decline_still_needs_its_reasoning(self):
        """Declining a published row is an assertion about the vendor's table,
        and one with no reasoning cannot be re-checked against the next
        release."""
        with self.assertRaises(ValueError) as caught:
            load_match_overrides(self._file(_decline(comment="")))
        self.assertIn("comment", str(caught.exception))

    def test_a_decline_still_needs_a_source(self):
        with self.assertRaises(ValueError) as caught:
            load_match_overrides(self._file(_decline(source_uuid="")))
        self.assertIn("source_uuid", str(caught.exception))

    def test_a_decline_may_not_also_name_a_target(self):
        """A contradiction rather than a redundancy: a row cannot both take the
        table's answer away and supply one."""
        with self.assertRaises(ValueError) as caught:
            load_match_overrides(self._file(_decline(target_uuid="t-new")))
        self.assertIn("target_uuid", str(caught.exception))

    def test_a_decline_may_not_state_a_conversion(self):
        """A factor is a statement about a pair this row declines to form."""
        with self.assertRaises(ValueError) as caught:
            load_match_overrides(self._file(_decline(
                conversion_factor=0.5, source_unit="kg", target_unit="m2*a",
            )))
        self.assertIn("conversion_factor", str(caught.exception))

    def test_decline_must_be_a_boolean(self):
        with self.assertRaises(ValueError) as caught:
            load_match_overrides(self._file(_decline(decline="yes")))
        self.assertIn("decline", str(caught.exception))

    def test_decline_false_is_an_ordinary_rewrite(self):
        """Spelled out rather than left to fall through: `false` has to mean the
        row is a rewrite, so it still needs a target."""
        rows = load_match_overrides(self._file(_rewrite(decline=False)))
        self.assertFalse(rows[0].decline)
        with self.assertRaises(ValueError):
            load_match_overrides(self._file(_decline(decline=False)))

    def test_two_rows_may_not_claim_one_flow(self):
        """One flow, one decision -- a decline and a rewrite for the same flow
        would mean the last one read wins."""
        with self.assertRaises(ValueError):
            load_match_overrides(self._file(_decline(), _rewrite(source_uuid="s-1")))


class ShippedFileTestCase(unittest.TestCase):
    def test_the_shipped_file_still_loads(self):
        from brightway_flows.sources import PACKAGE_DATA_DIR

        rows = load_match_overrides(PACKAGE_DATA_DIR / "ecoinvent-match-overrides.json")
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(row.source_uuid):
                if row.decline:
                    self.assertFalse(row.target_uuid)
                else:
                    self.assertTrue(row.target_uuid)


if __name__ == "__main__":
    unittest.main()
