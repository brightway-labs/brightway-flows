"""The renames nobody ruled on have to be readable back off the run.

`cc_chebi_agreement` is in `DEFAULT_APPROVED_RULES`, so its renames are applied
rather than queued: no review row is written, and the change log is the only
record that they happened (#224).  `curation.applied_renames` reads them back and
`tools/build_scope_narrowing_shortlist.py` audits them.

Two things are pinned here.  The rule's own output has to be recognisable as its
output -- the identification is on the provenance of the label written, so a
change to how the rule records what it derived the name from must fail here
rather than silently empty the shortlist.  And the shortlist has to contain the
whole population: it orders the rows a chemist reads first, and a shortlist that
dropped the rest would read as coverage of a question nobody asked.
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brightway_flows.curation.applied_renames import (
    applied_cc_chebi_renames,
    cas_of,
    fold_applied_pairs,
    is_cc_chebi_rename,
)
from brightway_flows.domain.flow import Flow
from brightway_flows.pipeline.review_records import (
    ChangeEvent,
    PipelineRun,
)
from brightway_flows.pipeline.review_tables import (
    REVIEW_SCHEMA_VERSION,
    number_change_events,
    write_review_tables,
)
from brightway_flows.transformers.consensus_match.grouping import (
    GroupEvidence,
    ObjectUnit,
)
from brightway_flows.transformers.consensus_match.rename_gate import RenameGate
from brightway_flows.transformers.consensus_match.rules import (
    Proposals,
    rename_from_cc_chebi_agreement,
)
from brightway_flows.transformers.consensus_match.transformer import (
    ConsensusMatchTransformer,
)


def _load_tool():
    """`tools/` is not a package; the shortlist builder is a script, loaded by path."""
    path = (
        Path(__file__).resolve().parent.parent
        / "tools" / "build_scope_narrowing_shortlist.py"
    )
    spec = importlib.util.spec_from_file_location("build_scope_narrowing_shortlist", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_scope_narrowing_shortlist"] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def _renamed(current, replacement, *, cas="1330-20-7", uuid="u1"):
    """One change event, produced by the rule and logged as the engine logs it.

    The rule writes the change and `apply_transformers` turns it into a
    `ChangeEvent` with the flow's previous value; both halves are done here the
    way the pipeline does them, so that a fixture cannot describe a shape the
    run does not produce.
    """
    flow = Flow(uuid=uuid, prefLabel=[{"@value": current, "@language": "en"}])
    unit = ObjectUnit(
        row=flow,
        members=[flow],
        member_uuids=[uuid],
        object_uuid="fo-1",
        flow_name=current,
        cas_numbers=[cas],
        skip_name_updates=False,
        group=GroupEvidence(group_key="k", group_member_count=1),
    )
    out = Proposals()
    rename_from_cc_chebi_agreement(unit, cas, replacement, gate=RenameGate(), out=out)
    return [
        ChangeEvent(
            uuid=change.uuid,
            flow_name=current,
            field_name=change.field,
            old_value=flow.prefLabel,
            new_value=change.new_value,
            transformer=ConsensusMatchTransformer.name,
            comment=change.comment,
        )
        for change in out.changes
        if change.field == "prefLabel"
    ]


class AppliedRenameTestCase(unittest.TestCase):
    def test_the_rule_s_own_output_is_recognised_as_its_output(self):
        """The identification is the provenance the rule writes on the label.

        If that string moves and this reader is not moved with it, the shortlist
        comes back empty and reads as "nothing to review".
        """
        change = _renamed("Xylene (all isomers)", "Xylene")[0]
        self.assertTrue(is_cc_chebi_rename(change))
        self.assertEqual(cas_of(change), "1330-20-7")

    def test_a_label_from_another_writer_is_not_a_cc_chebi_rename(self):
        change = ChangeEvent(
            uuid="u1",
            field_name="prefLabel",
            old_value=[{"@value": "Xylene (all isomers)", "@language": "en"}],
            new_value=[{
                "@value": "Xylene",
                "@language": "en",
                "source": {"prov:wasDerivedFrom": "legacy name field"},
            }],
            transformer=ConsensusMatchTransformer.name,
        )
        self.assertFalse(is_cc_chebi_rename(change))
        self.assertEqual(cas_of(change), "")

    def test_pairs_fold_across_spellings_of_the_same_ruling(self):
        """A ruling is keyed on the canonicalised pair, so the row is too."""
        changes = [
            *_renamed("Hcfc-140", "1,1,1-Trichloroethane", uuid="u1"),
            *_renamed("HCFC-140", "1,1,1-trichloroethane", uuid="u2"),
        ]
        pairs = fold_applied_pairs(changes)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].flow_count, 2)

    def test_one_flow_renamed_twice_counts_once(self):
        """The merge runs the chain once per source list, so a flow can carry
        the same rename twice; counting events would overstate the reach."""
        changes = [
            *_renamed("Xylene (all isomers)", "Xylene", uuid="u1"),
            *_renamed("Xylene (all isomers)", "Xylene", uuid="u1"),
        ]
        self.assertEqual(fold_applied_pairs(changes)[0].flow_count, 1)

    def test_several_cas_on_one_pair_are_all_kept(self):
        changes = [
            *_renamed("Xylene (all isomers)", "Xylene", cas="1330-20-7", uuid="u1"),
            *_renamed("Xylene (all isomers)", "Xylene", cas="95-47-6", uuid="u2"),
        ]
        self.assertEqual(fold_applied_pairs(changes)[0].cas_numbers, ["1330-20-7", "95-47-6"])


class StubSources:
    """`xylene` is a name for the CAS; `xylene (all isomers)` is not."""

    def evidence(self, cas):
        from brightway_flows.domain.labels import canonical_label_value
        return {
            "common_chemistry_name": "Xylene",
            "common_chemistry_synonyms": [],
            "chebi_labels": [],
            "_known": {canonical_label_value(n) for n in ("Xylene", "Tetraconazole")},
        }


class BuildTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _build(self, changes):
        """Build the shortlist from a fixture database.

        Written by the pipeline's own writer, as the worklist tests are, so a
        fixture that disagrees with the schema cannot make these pass.
        """
        path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        write_review_tables(
            path,
            run=PipelineRun(
                run_id="fixture",
                timestamp="2026-08-06T12:54:00+00:00",
                schema_version=REVIEW_SCHEMA_VERSION,
            ),
            stats=[],
            changes=number_change_events(changes, flow_object_id_by_uuid={}),
            queue_items=[],
            formula_mismatches=[],
            element_coverage=[],
            context_mappings=[],
        )
        with patch.object(tool, "SourceNames", StubSources):
            return tool.build(path)

    def test_it_reads_the_applied_renames_back_off_the_run(self):
        payload = self._build(_renamed("Xylene (all isomers)", "Xylene"))
        self.assertEqual(payload["summary"]["pairs"], 1)
        row = payload["decisions"][0]
        self.assertEqual(row["current"], "Xylene (all isomers)")
        self.assertEqual(row["replacement"], "Xylene")

    def test_rows_are_shaped_like_a_decisions_entry(self):
        payload = self._build(_renamed("Xylene (all isomers)", "Xylene"))
        row = payload["decisions"][0]
        self.assertEqual(
            [k for k in row if k != "audit"], ["current", "replacement", "decision", "notes"]
        )
        self.assertEqual(row["decision"], "undecided")

    def test_the_archetype_is_shortlisted_and_the_identity_audit_still_passes_it(self):
        """The whole of #224 in one row: supported identity, dropped scope."""
        payload = self._build(_renamed("Xylene (all isomers)", "Xylene"))
        audit = payload["decisions"][0]["audit"]
        self.assertEqual(audit["verdict"], "systematic_to_common")
        self.assertTrue(audit["supported"])
        self.assertTrue(audit["shortlisted"])
        self.assertEqual(
            audit["qualifier_loss"][0], {"detector": "scope", "tokens": ["all isomers"]}
        )

    def test_a_pair_that_drops_nothing_is_reported_and_not_shortlisted(self):
        """Every applied pair is in the output. A shortlist that filtered the
        population would report a rate over a denominator it had chosen."""
        payload = self._build([
            *_renamed("Xylene (all isomers)", "Xylene", uuid="u1"),
            *_renamed("(+/-) 2-(2,4-dichlorophenyl)propyl ether", "Tetraconazole", uuid="u2"),
        ])
        self.assertEqual(payload["summary"]["pairs"], 2)
        self.assertEqual(payload["summary"]["shortlisted_pairs"], 1)
        self.assertFalse(payload["decisions"][1]["audit"]["shortlisted"])

    def test_shortlisted_rows_sort_first(self):
        payload = self._build([
            *_renamed("(+/-) 2-(2,4-dichlorophenyl)propyl ether", "Tetraconazole", uuid="u1"),
            *_renamed("Xylene (all isomers)", "Xylene", uuid="u2"),
        ])
        self.assertEqual(
            [row["audit"]["shortlisted"] for row in payload["decisions"]], [True, False]
        )

    def test_the_summary_counts_what_the_rows_say(self):
        payload = self._build([
            *_renamed("Xylene (all isomers)", "Xylene", uuid="u1"),
            *_renamed("Xylene (all isomers)", "Xylene", uuid="u2"),
            *_renamed("(+/-) 2-(2,4-dichlorophenyl)propyl ether", "Tetraconazole", uuid="u3"),
        ])
        summary = payload["summary"]
        self.assertEqual(summary["pairs"], 2)
        self.assertEqual(summary["flows"], 3)
        self.assertEqual(summary["shortlisted_pairs"], 1)
        self.assertEqual(summary["shortlisted_flows"], 2)
        self.assertEqual(summary["verdicts"]["systematic_to_common"], 2)
        self.assertEqual(summary["detectors"]["scope"], 1)

    def test_a_run_that_renamed_nothing_is_a_valid_shortlist(self):
        payload = self._build([])
        self.assertEqual(payload["decisions"], [])
        self.assertEqual(payload["summary"]["pairs"], 0)
        self.assertEqual(payload["summary"]["shortlisted_pairs"], 0)


class DatabaseReaderTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_only_this_rule_s_renames_are_read(self):
        """Other writers change `prefLabel` too -- `bootstrap_labels` writes
        94k of them -- and none of those were applied without a ruling."""
        path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        other = ChangeEvent(
            uuid="u9",
            field_name="prefLabel",
            old_value=[],
            new_value=[{"@value": "Xylene", "@language": "en"}],
            transformer="bootstrap_labels",
        )
        write_review_tables(
            path,
            run=PipelineRun(run_id="r", timestamp="t", schema_version=REVIEW_SCHEMA_VERSION),
            stats=[],
            changes=number_change_events(
                [*_renamed("Xylene (all isomers)", "Xylene"), other],
                flow_object_id_by_uuid={},
            ),
            queue_items=[],
            formula_mismatches=[],
            element_coverage=[],
            context_mappings=[],
        )
        pairs = applied_cc_chebi_renames(path)
        self.assertEqual([(p.current, p.replacement) for p in pairs],
                         [("Xylene (all isomers)", "Xylene")])


if __name__ == "__main__":
    unittest.main()
