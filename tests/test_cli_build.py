"""`build` is the one command that produces the Brightway flows list.

It was two, `transform` and `merge-ecoinvent`, ordered by convention. Running
them out of order, or only one of them, left the database describing a state
that never existed. Collapsing them makes that unrepresentable and gives the
whole invocation one run id, rather than one that identified only the merge.

Everything that prepares potential input data stays a separate command, because
those feed a later build rather than being part of one.
"""

import unittest
from unittest import mock

import typer.main
from structlog.testing import capture_logs

from brightway_flows.application.cli import app, build


def command_names() -> set[str]:
    return set(typer.main.get_command(app).commands)


class CommandSurfaceTestCase(unittest.TestCase):
    def test_build_exists(self):
        self.assertIn("build", command_names())

    def test_the_two_build_commands_are_gone(self):
        """An alias that silently does more than its name says is worse than a
        clear error, so these are removed rather than kept pointing at `build`."""
        self.assertNotIn("transform", command_names())
        self.assertNotIn("merge-ecoinvent", command_names())

    def test_input_preparation_stays_separate(self):
        """These produce or refresh inputs; each feeds a later build."""
        for name in (
            "download",
            "extract",
            "download-ecoinvent-flows",
            "ingest-glad-mapping",
            "pubchem",
            "chebi",
        ):
            with self.subTest(name):
                self.assertIn(name, command_names())

    def test_the_merge_feedback_command_is_gone(self):
        """`generate-ecoinvent-additional-inputs` wrote a merge's unmatched
        flows back out as an input file, so a second build could put them
        through the transformers.  Enrichment is moving into the merge (#210),
        so there is no second pass to feed -- and the file it wrote gave a
        consensus flow its *source list's* uuid, which makes one uuid name two
        different things as soon as both are handled together."""
        self.assertNotIn("generate-ecoinvent-additional-inputs", command_names())

    def test_the_obsolete_layering_migration_is_gone(self):
        """`migrate-layered` rebuilt the layered JSON files from
        `harmonised-flows.json`. Both sides of that are now database tables."""
        self.assertNotIn("migrate-layered", command_names())

    def test_build_accepts_repeated_source_options(self):
        params = {
            p.name: p
            for p in typer.main.get_command(app).commands["build"].params
        }
        self.assertIn("source", params)
        self.assertTrue(params["source"].multiple)

    def test_build_keeps_the_transform_options(self):
        """The stage did not go away, so neither did the way it is driven.

        What is driven is smaller than it was: `--input`, `--sources-config`
        and `--no-discover-additional-inputs` selected *which flows* the
        transform loaded, and that is a `--source` decision now (#210). See
        `test_transform_input.py`.
        """
        params = {
            p.name for p in typer.main.get_command(app).commands["build"].params
        }
        for name in ("max_flows", "dry_run"):
            with self.subTest(name):
                self.assertIn(name, params)

    def test_the_review_artifact_flags_are_gone(self):
        """The change log, the PROV trail and the consensus review queue are
        tables written by every run, so there is nothing left to opt into.
        Behind a flag they were absent by default, and the pages reading them
        showed an empty state that was indistinguishable from no findings."""
        params = {
            p.name for p in typer.main.get_command(app).commands["build"].params
        }
        for name in ("write_transform_log", "write_provenance",
                     "export_consensus_review"):
            with self.subTest(name):
                self.assertNotIn(name, params)


class DryRunTestCase(unittest.TestCase):
    """#235: `--dry-run` guarded the transform and not the merge.

    `run_pipeline` honours it -- no database deleted, none rewritten, no export
    -- and then `build` ran the merge anyway, which wrote the four `merge_*`
    tables and rewrote `harmonised-flows-simple.json.gz`. The export is the one
    artifact with a downstream consumer, so a bounded smoke run replaced real
    data with a 20-flow version of it.

    Every write the merge makes goes through one of the four functions patched
    here, so "did not write" is checkable without a data directory: assert that
    none of them was called.
    """

    def _build(self, **kwargs):
        """Run `build` with the transform and every merge write stubbed out."""
        patches = {
            "merge": mock.patch(
                "brightway_flows.merge.pipeline.merge_source_list"
            ),
            "start_run": mock.patch("brightway_flows.merge.store.start_run"),
            "finish_run": mock.patch("brightway_flows.merge.store.finish_run"),
            "detect_conflicts": mock.patch(
                "brightway_flows.merge.store.detect_conflicts", return_value=[]
            ),
            "transform": mock.patch(
                "brightway_flows.application.cli._run_transform", return_value=[]
            ),
            "stats": mock.patch("brightway_flows.application.cli._log_merge_run_stats"),
            # Both write to, or read, the real data directory. Unpatched, this
            # test rebuilds the filter facets of whatever database is sitting
            # there -- which is how it was first noticed.
            "recompute_facets": mock.patch(
                "brightway_flows.pipeline.sqlite.recompute_filter_option_counts"
            ),
            "check_facets": mock.patch(
                "brightway_flows.pipeline.sqlite.check_filter_option_counts"
            ),
            "check_context_iris": mock.patch(
                "brightway_flows.pipeline.sqlite.check_context_iris_are_written"
            ),
        }
        started = {name: self.enterContext(patch) for name, patch in patches.items()}
        source = kwargs.pop("source", ["ecoinvent-3.12"])
        build(source=source, max_flows=20, **kwargs)
        return started

    def test_dry_run_does_not_merge(self):
        mocks = self._build(dry_run=True)
        for name in ("merge", "start_run", "finish_run", "detect_conflicts"):
            with self.subTest(name):
                mocks[name].assert_not_called()

    def test_dry_run_still_runs_the_transform(self):
        """It is a smoke run, not a no-op: the transformers still all run."""
        mocks = self._build(dry_run=True)
        mocks["transform"].assert_called_once()
        self.assertIs(mocks["transform"].call_args.kwargs["dry_run"], True)

    def test_a_real_run_still_merges(self):
        """The guard is on the flag, not on the merge."""
        mocks = self._build(dry_run=False)
        mocks["merge"].assert_called_once()
        mocks["start_run"].assert_called_once()
        mocks["finish_run"].assert_called_once()
        mocks["detect_conflicts"].assert_called_once()

    def test_a_real_run_recomputes_the_filter_facets_and_checks_them(self):
        """The merge adds flows; the facets the transform wrote predate them.

        Left as they were, the source filter totalled 93,993 of 94,429 flows and
        the two ecoinvent labels were offered nowhere (#248). The check runs
        last, after everything else `build` does, so it guards the ordering
        rather than this one call.
        """
        mocks = self._build(dry_run=False)
        mocks["recompute_facets"].assert_called_once()
        mocks["check_facets"].assert_called_once()

    def test_a_real_run_checks_that_every_flow_kept_its_context_address(self):
        """The merge adds flows, and wrote 1,200 of them with a printed context
        and no address (#295).

        Checked last, beside the facets, because both guard what the stages
        after the transform left behind rather than any one call.
        """
        mocks = self._build(dry_run=False)
        mocks["check_context_iris"].assert_called_once()

    def test_dry_run_leaves_the_filter_facets_alone(self):
        """It wrote no database, so there is nothing of this run to describe."""
        mocks = self._build(dry_run=True)
        mocks["recompute_facets"].assert_not_called()
        mocks["check_facets"].assert_not_called()
        mocks["check_context_iris"].assert_not_called()

    def test_the_skipped_merge_is_logged(self):
        """The transform says what it skipped; so should this.

        A reader who passed `--dry-run --source ecoinvent-3.12` has asked for
        that list to be merged and is owed the news that it was not.
        """
        with capture_logs() as captured:
            self._build(dry_run=True)
        events = {entry["event"] for entry in captured}
        self.assertIn("dry_run_skipped_merge", events)
        [skipped] = [e for e in captured if e["event"] == "dry_run_skipped_merge"]
        self.assertEqual(skipped["sources"], ["ecoinvent-3.12"])


class NoSourceListsTestCase(DryRunTestCase):
    """A build merges nothing unless asked (#99).

    `--source` defaulted to `ecoinvent-3.12`, so the ordinary invocation of the
    ordinary command was a build that needed a licence. The base list is
    deliberately not a valid `--source` -- it is the thing being merged *into*
    -- so there was no spelling of "just build the consensus list", and every
    list that *was* valid needed either an ecoinvent licence or an archive
    obtained from BAFU by hand.

    Inherits the harness rather than the assertions: `DryRunTestCase`'s cases
    all pass an explicit `source`, so they keep asking what they asked.
    """

    def test_the_default_is_no_source_lists(self):
        command = typer.main.get_command(app).commands["build"]
        [option] = [p for p in command.params if p.name == "source"]
        self.assertEqual(option.default, [])

    def test_a_build_with_no_source_merges_nothing(self):
        mocks = self._build(dry_run=False, source=[])
        mocks["merge"].assert_not_called()

    def test_it_still_runs_the_transform(self):
        """The point of it. This is a build, not a no-op."""
        mocks = self._build(dry_run=False, source=[])
        mocks["transform"].assert_called_once()
        self.assertIs(mocks["transform"].call_args.kwargs["dry_run"], False)

    def test_it_still_opens_and_closes_a_run(self):
        """So the merge tables describe this build -- as one that merged nothing
        -- rather than saying nothing at all."""
        mocks = self._build(dry_run=False, source=[])
        mocks["start_run"].assert_called_once()
        mocks["finish_run"].assert_called_once()
        mocks["detect_conflicts"].assert_called_once()

    def test_it_still_checks_what_the_run_left_behind(self):
        """Those guards are over the whole database, not over the merge."""
        mocks = self._build(dry_run=False, source=[])
        mocks["recompute_facets"].assert_called_once()
        mocks["check_facets"].assert_called_once()
        mocks["check_context_iris"].assert_called_once()

    def test_it_says_that_it_merged_nothing(self):
        """A reader who typed `build` and expected ecoinvent -- because that is
        what it used to do -- is owed the news."""
        with capture_logs() as captured:
            self._build(dry_run=False, source=[])
        self.assertIn(
            "no_source_lists_to_merge", {entry["event"] for entry in captured}
        )

    def test_naming_a_list_still_merges_it(self):
        """The opt-in half. Nothing is being taken away."""
        mocks = self._build(dry_run=False, source=["ecoinvent-3.12"])
        mocks["merge"].assert_called_once()


class OnlyBuildMergesTestCase(unittest.TestCase):
    def test_no_other_command_merges(self):
        """#235 asked whether a `merge-ecoinvent`-style entry point has the same
        hole. There is no other one to fix: `build` is the only command that
        merges. The library function `merge_ecoinvent()` outlived that question
        and was deleted in #243."""
        import inspect

        commands = typer.main.get_command(app).commands
        merging = {
            name
            for name, command in commands.items()
            if "merge_source_list" in inspect.getsource(command.callback)
        }
        self.assertEqual(merging, {"build"})


class MergeRunIdentityTestCase(unittest.TestCase):
    def test_merge_accepts_a_run_id_and_sequence(self):
        """`build` supplies both, so that the transform and every source list
        merged after it belong to one run, in a recorded order."""
        import inspect

        from brightway_flows.merge.pipeline import merge_source_list

        params = inspect.signature(merge_source_list).parameters
        self.assertIn("run_id", params)
        self.assertIn("sequence", params)
        self.assertEqual(params["sequence"].default, 0)
        self.assertIsNone(params["run_id"].default)


if __name__ == "__main__":
    unittest.main()
