"""The verification harness, which `AGENTS.md` makes the protocol for a change.

Two defects, both found by using it on the water taxonomy stack, and both of the
same kind: the tool ran, reported something, and what it reported did not answer
the question asked.

- A comparison called 386 of 389 `flow_object_payloads` rows changed when none
  of them had. JSON key order is not stable between runs, and a report that
  cannot say so buries the row that did change among rows that did not.
- `--max-flows N` samples a prefix of the base list in file order. EF 3.1's
  water withdrawals sit at indices 12,722 to 75,846 of 94,062, so the default
  400-flow run contains none of them — and a change to those flows passed that
  run while aborting the build at 80,000.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _verify_run():
    spec = importlib.util.spec_from_file_location(
        "_verify_run", REPO_ROOT / "tools" / "verify_run.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["_verify_run"] = module
    spec.loader.exec_module(module)
    return module


class ReorderedJsonTestCase(unittest.TestCase):
    """Telling a key-order difference from a content one."""

    def setUp(self):
        self.tool = _verify_run()

    def test_the_same_object_in_a_different_order_is_reordered(self):
        self.assertTrue(
            self.tool.reordered_json('{"a": 1, "b": 2}', '{"b": 2, "a": 1}')
        )

    def test_a_changed_value_is_not(self):
        self.assertFalse(
            self.tool.reordered_json('{"a": 1, "b": 2}', '{"b": 3, "a": 1}')
        )

    def test_a_changed_value_is_not_even_when_the_order_also_moved(self):
        """The case that matters: a real change hiding inside a reordering."""
        self.assertFalse(
            self.tool.reordered_json('{"a": 1, "b": 2}', '{"b": 2, "a": 99}')
        )

    def test_identical_cells_are_not_reported_as_reordered(self):
        self.assertFalse(self.tool.reordered_json('{"a": 1}', '{"a": 1}'))

    def test_a_doubly_encoded_payload_is_unwrapped(self):
        """Several columns hold a JSON *string*, so the cell is a quoted
        document and decoding once yields the document rather than its keys.
        Reading it once is what made the first attempt at this report every
        payload row as changed anyway."""
        left = '"{\\"a\\": 1, \\"b\\": 2}"'
        right = '"{\\"b\\": 2, \\"a\\": 1}"'
        self.assertTrue(self.tool.reordered_json(left, right))

    def test_a_doubly_encoded_content_change_still_shows(self):
        left = '"{\\"a\\": 1, \\"b\\": 2}"'
        right = '"{\\"b\\": 2, \\"a\\": 99}"'
        self.assertFalse(self.tool.reordered_json(left, right))

    def test_plain_strings_and_numbers_are_never_reordered(self):
        for left, right in (('"lake water"', '"river water"'), ("1", "2")):
            with self.subTest(left=left):
                self.assertFalse(self.tool.reordered_json(left, right))


class ClassifyRowsTestCase(unittest.TestCase):
    def setUp(self):
        self.tool = _verify_run()
        self.dir = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))

    def _pair(self, left_body, right_body, suffix=".tsv"):
        left = self.dir / f"left{suffix}"
        right = self.dir / f"right{suffix}"
        left.write_text(left_body)
        right.write_text(right_body)
        return left, right

    def test_a_key_order_only_table_reports_no_real_rows(self):
        left, right = self._pair(
            '# rows: 1\nid\tpayload\n"x"\t"{\\"a\\": 1, \\"b\\": 2}"\n',
            '# rows: 1\nid\tpayload\n"x"\t"{\\"b\\": 2, \\"a\\": 1}"\n',
        )
        self.assertEqual(self.tool.classify_rows(left, right), (0, 1))

    def test_a_real_change_is_counted_separately_from_the_noise(self):
        left, right = self._pair(
            '# rows: 2\nid\tpayload\n"x"\t"{\\"a\\": 1, \\"b\\": 2}"\n"y"\t"{\\"a\\": 1}"\n',
            '# rows: 2\nid\tpayload\n"x"\t"{\\"b\\": 2, \\"a\\": 1}"\n"y"\t"{\\"a\\": 9}"\n',
        )
        self.assertEqual(self.tool.classify_rows(left, right), (1, 1))

    def test_a_row_count_change_is_not_classifiable(self):
        """Rows are compared positionally, so a table that gained or lost one
        cannot be, and the caller falls back to showing the diff."""
        left, right = self._pair(
            '# rows: 1\nid\n"x"\n', '# rows: 2\nid\n"x"\n"y"\n'
        )
        self.assertEqual(self.tool.classify_rows(left, right), (-1, 0))

    def test_a_json_artifact_is_not_classifiable(self):
        left, right = self._pair('{"a": 1}', '{"a": 2}', suffix=".json")
        self.assertEqual(self.tool.classify_rows(left, right), (-1, 0))


class BoundedSampleTestCase(unittest.TestCase):
    """`--max-flows` is a prefix, and a prefix is a sample nobody chose.

    Records, and only records. The first version of this read `flow["uuid"]` and
    was tested with dicts, so the suite passed and the pipeline -- which passes
    `Flow` records -- crashed on the first real run. The fix at the time was to
    read *both* shapes and test both, which left a dict branch that the only
    caller can never reach: `bounded_sample` is fed `_load_transform_inputs()`,
    which returns `list[Flow]`.

    #92 removed that branch, and the fixtures follow it, because this class's
    own docstring already said why -- a test that builds a shape the code under
    test never sees is not a test of it, and that is as true of the dict half
    now as it was of the record half then.
    """

    def setUp(self):
        from brightway_flows.domain.flow import Flow
        from brightway_flows.pipeline.engine import bounded_sample

        self.sample = bounded_sample
        self.flows = [
            Flow.from_dict({"uuid": f"u-{i}", "source": "EF 3.1", "unit": "kg"})
            for i in range(10)
        ]

    def test_a_missing_uuid_is_reported(self):
        with self.assertRaises(ValueError):
            self.sample(self.flows, 3, ["not-a-flow"])

    def test_without_names_it_is_still_the_prefix(self):
        kept, extra = self.sample(self.flows, 3, None)
        self.assertEqual([f.uuid for f in kept], ["u-0", "u-1", "u-2"])
        self.assertEqual(extra, 0)

    def test_a_named_flow_outside_the_prefix_is_kept(self):
        kept, extra = self.sample(self.flows, 3, ["u-8"])
        self.assertEqual([f.uuid for f in kept], ["u-0", "u-1", "u-2", "u-8"])
        self.assertEqual(extra, 1)

    def test_the_prefix_is_not_displaced_by_what_is_named(self):
        """Added rather than substituted, so a run stays comparable with one
        that used the prefix alone."""
        kept, _ = self.sample(self.flows, 3, ["u-8", "u-9"])
        self.assertEqual([f.uuid for f in kept][:3], ["u-0", "u-1", "u-2"])

    def test_naming_a_flow_already_in_the_prefix_changes_nothing(self):
        kept, extra = self.sample(self.flows, 3, ["u-1"])
        self.assertEqual(len(kept), 3)
        self.assertEqual(extra, 0)

    def test_order_is_preserved(self):
        kept, _ = self.sample(self.flows, 2, ["u-9", "u-5"])
        self.assertEqual([f.uuid for f in kept], ["u-0", "u-1", "u-5", "u-9"])

    def test_naming_a_flow_the_list_does_not_ship_raises(self):
        """A typo'd uuid that sampled silently would have the run report on the
        wrong thing, which is the defect this option exists to fix."""
        with self.assertRaises(ValueError) as caught:
            self.sample(self.flows, 3, ["u-8", "not-a-flow"])
        self.assertIn("not-a-flow", str(caught.exception))
        self.assertNotIn("u-8", str(caught.exception))

    def test_blank_names_are_ignored_rather_than_reported_missing(self):
        kept, extra = self.sample(self.flows, 2, ["", "   "])
        self.assertEqual(len(kept), 2)
        self.assertEqual(extra, 0)
