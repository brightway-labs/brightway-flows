"""The curation worklist must say what it can and cannot see.

`tools/build_label_worklist.py` answers one question per queued rename -- is the
replacement a name this substance actually has, per Common Chemistry and ChEBI?
A curator rules on the answer, so a verdict that overstates its reach is worse
than no verdict: the flagged rows get read and the unflagged ones do not.

What is pinned here is both directions -- the four verdicts, and the fact that
the method is blind to scope narrowing.
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brightway_flows.pipeline.review_records import (
    PipelineRun,
    ReviewQueue,
    ReviewQueueItem,
)
from brightway_flows.pipeline.review_tables import (
    REVIEW_SCHEMA_VERSION,
    write_review_tables,
)


def _load_tool():
    """`tools/` is not a package; the worklist builder is a script, loaded by path."""
    path = Path(__file__).resolve().parent.parent / "tools" / "build_label_worklist.py"
    spec = importlib.util.spec_from_file_location("build_label_worklist", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_label_worklist"] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def _known(*names):
    from brightway_flows.domain.labels import canonical_label_value
    return {canonical_label_value(n) for n in names}


class VerdictTestCase(unittest.TestCase):
    def test_both_names_known_is_a_synonym_swap(self):
        self.assertEqual(
            tool.verdict_for("Systhane", "Myclobutanil", _known("Systhane", "Myclobutanil")),
            "synonym_swap",
        )

    def test_only_the_replacement_known_is_systematic_to_common(self):
        self.assertEqual(
            tool.verdict_for("(+/-) 2-(2,4-dichlorophenyl)…", "Tetraconazole",
                             _known("Tetraconazole")),
            "systematic_to_common",
        )

    def test_replacement_unknown_is_flagged(self):
        """`'Sodium Chloride' -> 'sea water'`, the case the rule proposed anyway."""
        self.assertEqual(
            tool.verdict_for("Sodium Chloride", "sea water", _known("Sodium chloride", "Salt")),
            "replacement_not_a_name_for_this_cas",
        )

    def test_neither_name_known_is_flagged(self):
        self.assertEqual(
            tool.verdict_for("Calcium Ethynediide", "piperidin-2-one", _known("calcium carbide")),
            "neither_name_known_for_this_cas",
        )

    def test_a_cas_the_sources_do_not_hold_is_flagged(self):
        self.assertEqual(tool.verdict_for("A", "B", set()), "cas_unknown_to_sources")

    def test_the_verdict_cannot_see_scope_narrowing(self):
        """The known limitation, pinned so it is not mistaken for coverage.

        `xylene` is a name CAS 1330-20-7 holds and `xylene (all isomers)` is
        not, so the archetypal specificity loss -- the one that motivated the
        curation gate -- scores as a benign improvement.  Reading the unflagged
        rows is not optional.
        """
        self.assertEqual(
            tool.verdict_for("Xylene (all isomers)", "Xylene", _known("xylene")),
            "systematic_to_common",
        )


class StubSources:
    """Two CAS: one supporting the replacement, one not."""

    def evidence(self, cas):
        known = _known("Butene", "1-butene") if cas == "106-98-9" else _known("Butene")
        return {
            "common_chemistry_name": "stub",
            "common_chemistry_synonyms": [],
            "chebi_labels": [],
            "_known": known,
        }


class BuildTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _build(self, queued):
        """Build the worklist from a fixture database.

        Written by the pipeline's own writer, not by hand: a fixture that
        disagrees with the schema would make these tests pass over a shape the
        pipeline never produces.
        """
        path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        write_review_tables(
            path,
            run=PipelineRun(
                run_id="fixture",
                timestamp="2026-08-05T21:48:44+00:00",
                schema_version=REVIEW_SCHEMA_VERSION,
            ),
            stats=[],
            changes=[],
            queue_items=[
                ReviewQueueItem(
                    queue_name=ReviewQueue.UNDECIDED_LABEL_REPLACEMENT,
                    item_key=f"pair-{index}",
                    item_index=index,
                    payload=payload,
                )
                for index, payload in enumerate(queued)
            ],
            formula_mismatches=[],
            element_coverage=[],
            context_mappings=[],
        )
        with patch.object(tool, "SourceNames", StubSources):
            return tool.build(path)

    def _row(self, current, replacement, cas_numbers, flow_count=1):
        return {
            "rule": "multi_source_consensus", "current": current, "replacement": replacement,
            "cas_numbers": cas_numbers, "flow_count": flow_count,
            "example_uuid": "u1", "decision": "undecided", "hint": "",
        }

    def test_rows_are_shaped_like_a_decisions_entry(self):
        payload = self._build([self._row("Butene", "1-butene", ["106-98-9"])])
        row = payload["decisions"][0]
        self.assertEqual(
            [k for k in row if k != "audit"], ["current", "replacement", "decision", "notes"]
        )
        self.assertEqual(row["decision"], "undecided")

    def test_a_row_is_flagged_when_any_of_its_cas_fails(self):
        """A ruling is keyed on the pair, so it binds every CAS that produced
        it.  One unsupported CAS is enough to want a reader."""
        payload = self._build([self._row("Butene", "1-butene", ["106-98-9", "25167-67-3"])])
        row = payload["decisions"][0]
        self.assertTrue(row["audit"]["suspicious"])
        self.assertEqual(row["audit"]["verdict"], "replacement_not_a_name_for_this_cas")
        self.assertEqual(len(row["audit"]["sources"]), 2)

    def test_a_row_whose_cas_all_support_it_is_not_flagged(self):
        payload = self._build([self._row("Butene", "1-butene", ["106-98-9"])])
        self.assertFalse(payload["decisions"][0]["audit"]["suspicious"])

    def test_flagged_rows_sort_first_then_by_flow_count(self):
        payload = self._build([
            self._row("Butene", "1-butene", ["106-98-9"], flow_count=99),
            self._row("Butene", "1-butene", ["25167-67-3"], flow_count=1),
        ])
        verdicts = [r["audit"]["suspicious"] for r in payload["decisions"]]
        self.assertEqual(verdicts, [True, False])

    def test_the_summary_counts_what_the_rows_say(self):
        payload = self._build([
            self._row("Butene", "1-butene", ["25167-67-3"], flow_count=5),
            self._row("Butene", "1-butene", ["106-98-9"], flow_count=3),
        ])
        self.assertEqual(payload["summary"]["pairs"], 2)
        self.assertEqual(payload["summary"]["flows"], 8)
        self.assertEqual(payload["summary"]["suspicious_pairs"], 1)
        self.assertEqual(payload["summary"]["suspicious_flows"], 5)

    def test_an_empty_queue_is_a_valid_worklist(self):
        payload = self._build([])
        self.assertEqual(payload["decisions"], [])
        self.assertEqual(payload["summary"]["pairs"], 0)


if __name__ == "__main__":
    unittest.main()
