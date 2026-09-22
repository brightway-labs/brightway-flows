"""Can the stored build answer for this branch, and what is copied when it can.

#101's other half.  The stamp made a stored build reusable; this is the check
that decides whether to reuse it, run at the beginning of an investigation
rather than on a timer.

The failures worth testing are the ones that put a wrong file under a commit's
name, because everything downstream reads it as that commit's answer and has no
way to notice: saying yes to a build from a modified tree, saying yes to one the
branch does not descend from, saying yes across commits that move rows, copying
a build under a commit it is not a build of, and leaving a half-written extract
where an interrupted one was.

Saying *no* wrongly costs a rebuild and nothing else, which is why every
uncertain answer here is a no.
"""

import argparse
import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


def _load(name: str):
    """`tools/` is not a package; a tool is a script, loaded here by path."""
    path = Path(__file__).resolve().parent.parent / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tool = _load("refresh_base_build")
compare = _load("compare_merge_outcomes")

COMMIT = "1111111111111111111111111111111111111111"
OTHER = "2222222222222222222222222222222222222222"

#: A build database with more in it than a comparison reads, so that the extract
#: can be shown to leave the rest behind.  `payload_json` on `elementary_flows`
#: stands for the 474 MB of that table an extract does not carry.
TABLES = (
    """
    CREATE TABLE pipeline_runs (
        run_id TEXT, timestamp TEXT,
        git_commit TEXT NOT NULL DEFAULT '', git_dirty INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE TABLE merge_run_inputs (source_key TEXT, rows_read INTEGER)",
    """
    CREATE TABLE merge_outcomes (
        list_name TEXT, list_version TEXT, source_uuid TEXT, source_name TEXT,
        source_context_json TEXT, source_unit TEXT, outcome TEXT, reason TEXT,
        flow_object_id TEXT, target_elementary_flow_id TEXT, basis TEXT,
        has_unit_mismatch INTEGER, detail_json TEXT
    )
    """,
    "CREATE TABLE flow_objects (flow_object_id TEXT, pref_label_value TEXT, synonyms_json TEXT)",
    """
    CREATE TABLE elementary_flows (
        uuid TEXT, pref_label_value TEXT, unit TEXT, context_display TEXT,
        lcia_factor_count INTEGER, is_deprecated INTEGER, payload_json TEXT
    )
    """,
    "CREATE TABLE changelog (entry TEXT)",
)


def write_build(
    path: Path,
    commit: str | None = COMMIT,
    dirty: bool = False,
    with_inputs: bool = True,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    connection = sqlite3.connect(path)
    for statement in TABLES:
        if not with_inputs and "merge_run_inputs" in statement:
            continue
        connection.execute(statement)
    if commit is None:
        connection.execute("INSERT INTO pipeline_runs (run_id) VALUES ('r0')")
    else:
        connection.execute(
            "INSERT INTO pipeline_runs (run_id, git_commit, git_dirty) VALUES ('r1', ?, ?)",
            (commit, int(dirty)),
        )
    connection.execute(
        "INSERT INTO merge_outcomes (list_name, list_version, source_uuid,"
        " outcome, detail_json)"
        " VALUES ('bafu', '2026-v1', 'u1', 'matched',"
        " '{\"scored_candidates\": []}')"
    )
    connection.execute(
        "INSERT INTO elementary_flows (uuid, pref_label_value, unit, context_display,"
        " lcia_factor_count, is_deprecated, payload_json)"
        " VALUES ('f1', 'Lake water', 'm3', 'Resource / Water / Lake', 3, 0, 'x')"
    )
    connection.execute(
        "INSERT INTO flow_objects (flow_object_id, pref_label_value, synonyms_json)"
        " VALUES ('o1', 'Water', '[]')"
    )
    connection.execute("INSERT INTO changelog (entry) VALUES ('a change')")
    connection.commit()
    connection.close()
    return path


def tables(path: Path) -> set[str]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {
            row[0]
            for row in connection.execute("select name from sqlite_master where type='table'")
        }
    finally:
        connection.close()


def columns(path: Path, table: str) -> set[str]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {row[1] for row in connection.execute(f"pragma table_info({table})")}
    finally:
        connection.close()


class TempCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.shared = Path(directory.name)


class StampTestCase(TempCase):
    """What the shared build says about the code that wrote it."""

    def test_a_clean_build_reports_its_commit(self):
        database = write_build(self.shared / "consensus-flows.sqlite3")
        self.assertEqual(tool.stamp(database), (COMMIT, False))

    def test_a_modified_tree_is_carried_through(self):
        database = write_build(self.shared / "consensus-flows.sqlite3", dirty=True)
        self.assertEqual(tool.stamp(database), (COMMIT, True))

    def test_a_build_from_before_the_stamp_says_nothing(self):
        database = write_build(self.shared / "consensus-flows.sqlite3", commit=None)
        self.assertIsNone(tool.stamp(database))

    def test_a_missing_database_says_nothing(self):
        self.assertIsNone(tool.stamp(self.shared / "absent.sqlite3"))

    def test_a_database_that_is_not_a_build_says_nothing(self):
        path = self.shared / "other.sqlite3"
        sqlite3.connect(path).close()
        self.assertIsNone(tool.stamp(path))


class ExtractTestCase(TempCase):
    """What the archive carries, and what it leaves in the build."""

    def setUp(self):
        super().setUp()
        self.database = write_build(self.shared / "consensus-flows.sqlite3")
        self.destination = tool.archived_path(self.shared, COMMIT)

    def test_it_carries_every_table_the_comparison_reads(self):
        tool.extract(self.database, self.destination)
        self.assertEqual(tables(self.destination), set(tool.EXTRACT_TABLES))

    def test_it_leaves_behind_what_the_comparison_never_asks_for(self):
        tool.extract(self.database, self.destination)
        self.assertNotIn("changelog", tables(self.destination))
        self.assertNotIn("payload_json", columns(self.destination, "elementary_flows"))
        self.assertNotIn("synonyms_json", columns(self.destination, "flow_objects"))

    def test_it_keeps_the_detail_a_defect_is_read_out_of(self):
        # `merge_outcomes` is carried whole: `detail_json` is every candidate the
        # selector scored, which is what step 2 of the skill reads.
        tool.extract(self.database, self.destination)
        self.assertIn("detail_json", columns(self.destination, "merge_outcomes"))

    def test_an_older_build_without_merge_run_inputs_still_extracts(self):
        database = write_build(self.shared / "old.sqlite3", with_inputs=False)
        destination = tool.archived_path(self.shared, OTHER)
        tool.extract(database, destination)
        self.assertNotIn("merge_run_inputs", tables(destination))
        self.assertIn("merge_outcomes", tables(destination))

    def test_a_missing_table_that_is_not_optional_is_an_error(self):
        path = self.shared / "empty.sqlite3"
        sqlite3.connect(path).close()
        with self.assertRaises(sqlite3.OperationalError):
            tool.extract(path, self.shared / "base-builds" / "nope.sqlite3")

    def test_it_leaves_no_temporary_file_behind(self):
        tool.extract(self.database, self.destination)
        self.assertEqual(
            list(self.destination.parent.glob("*.tmp")),
            [],
            "an interrupted extract must not be readable under a commit's name",
        )

    def test_the_extract_is_what_the_comparison_reads(self):
        tool.extract(self.database, self.destination)
        build = compare.Build(self.destination)
        self.assertEqual(build.revision, (COMMIT, False))
        self.assertEqual(build.flows["f1"], ("Lake water", "m3", "Resource / Water / Lake", 3, 0))
        self.assertEqual(build.substances["o1"], "Water")
        # Keyed by list version as well as list, so the extract has to carry
        # `list_version` for the comparison to read it at all (#317).
        self.assertIn(("bafu", "2026-v1", "u1"), build.outcomes)


class PruneTestCase(TempCase):
    """An archive nobody prunes is a disk that fills quietly."""

    def _archive(self, name: str, age: int) -> Path:
        path = tool.archive_dir(self.shared) / f"{name}.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        os.utime(path, (1_700_000_000 - age, 1_700_000_000 - age))
        return path

    def test_it_keeps_the_newest_and_drops_the_rest(self):
        oldest = self._archive("a", 300)
        middle = self._archive("b", 200)
        newest = self._archive("c", 100)
        removed = tool.prune(self.shared, keep=2)
        self.assertEqual(removed, [oldest])
        self.assertTrue(middle.exists() and newest.exists())

    def test_it_removes_nothing_under_the_bound(self):
        self._archive("a", 300)
        self.assertEqual(tool.prune(self.shared, keep=10), [])

    def test_an_archive_that_does_not_exist_yet_is_not_an_error(self):
        self.assertEqual(tool.prune(self.shared, keep=3), [])


class SurveyTestCase(TempCase):
    """Whether the stored build answers for a branch, and why not when it does not."""

    def setUp(self):
        super().setUp()
        self.database = self.shared / "consensus-flows.sqlite3"

    def _survey(self, wanted=COMMIT, ancestor=None, moving=()):
        original_ancestor, original_log = tool.is_ancestor, tool.deciding_commits
        tool.is_ancestor = lambda earlier, later: ancestor
        tool.deciding_commits = lambda earlier, later: list(moving)
        self.addCleanup(setattr, tool, "is_ancestor", original_ancestor)
        self.addCleanup(setattr, tool, "deciding_commits", original_log)
        return tool.survey(self.shared, wanted)

    def test_a_build_of_the_wanted_commit_answers(self):
        write_build(self.database, COMMIT)
        self.assertEqual(self._survey(COMMIT), (COMMIT, []))

    def test_an_unstamped_build_does_not(self):
        write_build(self.database, commit=None)
        usable, reasons = self._survey(COMMIT)
        self.assertIsNone(usable)
        self.assertIn("does not say which revision", reasons[0])

    def test_a_build_from_a_modified_tree_does_not(self):
        write_build(self.database, COMMIT, dirty=True)
        usable, reasons = self._survey(COMMIT)
        self.assertIsNone(usable)
        self.assertIn("modified tree", reasons[0])

    def test_an_older_build_with_nothing_row_moving_since_answers_as_itself(self):
        # Archived under the commit it *is*, never under the one asked about.
        write_build(self.database, COMMIT)
        self.assertEqual(self._survey(OTHER, ancestor=True, moving=()), (COMMIT, []))

    def test_an_older_build_with_a_row_moving_commit_since_does_not(self):
        write_build(self.database, COMMIT)
        usable, reasons = self._survey(OTHER, ancestor=True, moving=["abc1234 A rule"])
        self.assertIsNone(usable)
        self.assertIn("decide where a row goes", reasons[0])
        self.assertIn("abc1234", reasons[1])

    def test_a_build_the_branch_does_not_descend_from_does_not(self):
        write_build(self.database, COMMIT)
        usable, reasons = self._survey(OTHER, ancestor=False)
        self.assertIsNone(usable)
        self.assertIn("does not descend from", reasons[0])

    def test_a_git_that_will_not_answer_ancestry_is_a_no(self):
        write_build(self.database, COMMIT)
        usable, reasons = self._survey(OTHER, ancestor=None)
        self.assertIsNone(usable)
        self.assertIn("would not say", reasons[0])


class PublishTestCase(TempCase):
    """What a usable stored build leaves behind for the comparison to read."""

    def test_it_copies_the_extract_under_the_commit(self):
        write_build(self.shared / "consensus-flows.sqlite3", COMMIT)
        published = tool.publish(self.shared, COMMIT, keep=10)
        self.assertEqual(published, tool.archived_path(self.shared, COMMIT))
        self.assertEqual(tables(published), set(tool.EXTRACT_TABLES))

    def test_a_second_run_does_not_copy_again(self):
        write_build(self.shared / "consensus-flows.sqlite3", COMMIT)
        first = tool.publish(self.shared, COMMIT, keep=10)
        stamped = first.stat().st_mtime_ns
        self.assertEqual(tool.publish(self.shared, COMMIT, keep=10).stat().st_mtime_ns, stamped)


class ResolveBeforeTestCase(TempCase):
    """Naming the before side rather than finding it."""

    def test_an_existing_path_wins_over_any_reading_as_a_commit(self):
        path = self.shared / "base"
        path.write_bytes(b"")
        self.assertEqual(compare.resolve_before(str(path)), path)

    def test_a_commit_resolves_to_its_archived_extract(self):
        archived = tool.archived_path(self.shared, COMMIT)
        archived.parent.mkdir(parents=True, exist_ok=True)
        archived.write_bytes(b"")
        original = compare._archive_dir
        compare._archive_dir = lambda: tool.archive_dir(self.shared)
        self.addCleanup(setattr, compare, "_archive_dir", original)

        class Resolved:
            returncode = 0
            stdout = COMMIT

        original_git = compare._git
        compare._git = lambda *args: Resolved()
        self.addCleanup(setattr, compare, "_git", original_git)

        self.assertEqual(compare.resolve_before(COMMIT), archived)

    def test_a_commit_with_no_extract_says_how_to_make_one(self):
        original = compare._archive_dir
        compare._archive_dir = lambda: tool.archive_dir(self.shared)
        self.addCleanup(setattr, compare, "_archive_dir", original)

        class Resolved:
            returncode = 0
            stdout = OTHER

        original_git = compare._git
        compare._git = lambda *args: Resolved()
        self.addCleanup(setattr, compare, "_git", original_git)

        with self.assertRaises(SystemExit) as caught:
            compare.resolve_before(OTHER)
        self.assertIn("refresh_base_build.py", str(caught.exception))

    def test_something_that_is_neither_a_file_nor_a_commit_is_refused(self):
        original_git = compare._git
        compare._git = lambda *args: None
        self.addCleanup(setattr, compare, "_git", original_git)
        with self.assertRaises(SystemExit):
            compare.resolve_before("not-a-thing")


class CharacteriseTestCase(TempCase):
    """The second half of a build, and what happens when it is the half that fails."""

    def _record(self, returncode=0):
        calls = []

        class Done:
            pass

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            done = Done()
            done.returncode = returncode
            return done

        original = tool.subprocess.run
        tool.subprocess.run = fake_run
        self.addCleanup(setattr, tool.subprocess, "run", original)
        return calls

    def test_it_runs_characterise_from_the_checkout_against_the_shared_directory(self):
        calls = self._record()
        tree = self.shared / "tree"
        self.assertTrue(tool.run_characterise(tree, self.shared))
        command, kwargs = calls[0]
        self.assertEqual(command, ["brightway-flows", "characterise"])
        self.assertEqual(kwargs["cwd"], tree)
        self.assertEqual(
            kwargs["env"]["BRIGHTWAY_FLOWS_DATA_DIR"], str(self.shared)
        )
        self.assertEqual(kwargs["env"]["PYTHONPATH"], str(tree / "src"))

    def test_a_failure_is_answered_rather_than_raised(self):
        # It runs after the extract has been copied, so raising here would only
        # hide a before side that is already complete and already on disk.
        self._record(returncode=1)
        self.assertFalse(tool.run_characterise(self.shared / "tree", self.shared))

    def test_the_build_and_the_characterisation_run_against_the_same_checkout(self):
        # One environment, built once: a characterisation that read a different
        # `PYTHONPATH` than the build would publish one checkout's factors onto
        # another checkout's flows and say nothing about it.
        tree = self.shared / "tree"
        self.assertEqual(
            tool.build_environment(tree, self.shared)["PYTHONPATH"], str(tree / "src")
        )


class RefreshTestCase(TempCase):
    """What `--build` leaves behind, in the order it leaves it."""

    def _report(self, characterised=True):
        database = self.shared / "consensus-flows.sqlite3"
        built = []

        def fake_build(tree, shared, sources):
            built.append(sources)
            write_build(database, COMMIT)

        def fake_characterise(tree, shared):
            # The claim under test: by the time this runs the extract exists.
            self.assertTrue(tool.archived_path(self.shared, COMMIT).exists())
            return characterised

        for name, replacement in (
            ("wanted_commit", lambda ref, fetch: COMMIT),
            ("git", lambda *args, **kwargs: "a subject"),
            ("survey", lambda shared, wanted: (None, ["needs one"])),
            ("build_worktree", lambda commit, path: path),
            ("run_build", fake_build),
            ("run_characterise", fake_characterise),
        ):
            original = getattr(tool, name)
            setattr(tool, name, replacement)
            self.addCleanup(setattr, tool, name, original)

        args = tool.build_parser().parse_args(["--build"])
        args.shared = self.shared
        args.worktree = self.shared / "tree"
        args.source = list(tool.DEFAULT_SOURCES)
        return tool.report(args), built

    def test_it_builds_the_default_lists_and_publishes_the_extract(self):
        status, built = self._report()
        self.assertEqual(status, 0)
        self.assertEqual(built, [tool.DEFAULT_SOURCES])
        self.assertTrue(tool.archived_path(self.shared, COMMIT).exists())

    def test_a_build_with_no_factors_on_it_is_not_a_finished_refresh(self):
        # The before side survives -- characterisation writes no table the
        # extract carries -- but the shared directory is what the webapp serves
        # and what `assess` reads, and an uncharacterised build answers "no
        # factors" to every question either of them asks.
        status, _ = self._report(characterised=False)
        self.assertEqual(status, 2)
        self.assertTrue(tool.archived_path(self.shared, COMMIT).exists())


class DefaultsTestCase(unittest.TestCase):
    """The two constants a reader of a comparison depends on."""

    def test_the_extract_covers_every_table_the_comparison_queries(self):
        # Kept honest by hand rather than by import: the comparison spells its
        # queries inline, and an extract missing one of them fails only when
        # somebody runs it against an archived build.
        for table in ("merge_outcomes", "flow_objects", "elementary_flows", "pipeline_runs"):
            self.assertIn(table, tool.EXTRACT_TABLES)

    def test_the_sources_are_what_a_comparison_needs_both_sides_to_have(self):
        # Whatever a stored build merges is what a branch's own build has to
        # merge for the two to be comparable, so this is the assertion that
        # says the two recipes are the same recipe.
        self.assertEqual(
            tool.DEFAULT_SOURCES,
            (
                "ecoinvent-3.12",
                "ecoinvent-3.8",
                "bafu-2026-v1",
                "stepwise-2006-1.09",
                "agribalyse-3.2",
            ),
        )

    def test_every_simapro_lineage_list_is_merged(self):
        # `simapro_origin` unlocks the name rewriting -- de-inverting `Benzene,
        # chloro-`, splitting a geography off a name, reading a unit out of one
        # -- that no other merged list can exercise.  A before side without one
        # of these lists cannot say what a change to any of those strategies
        # did, so the baseline has to merge one.
        #
        # All of them, not one.  #164 registered Stepwise 2006 and left it out
        # here, on the argument that a list whose review queues nobody has been
        # through moves rows in every comparison for reasons unrelated to the
        # change being measured.  That is true and is the cost; what it missed
        # is that this build is also what `assess` grades, so leaving a list out
        # does not park its rows -- it makes every expectation about them
        # ungradeable, which is how #167's four chlordane claims came to fail on
        # a build that had never seen a Stepwise row.
        #
        # Counted rather than named, so that registering a sixth SimaPro-lineage
        # list is a decision somebody makes here rather than an omission.
        from brightway_flows.sources import known_source_lists

        registry = known_source_lists()
        simapro = {key for key, source in registry.items() if source.simapro_origin}
        self.assertTrue(simapro)
        self.assertEqual(
            simapro, {"bafu-2026-v1", "stepwise-2006-1.09", "agribalyse-3.2"}
        )
        for key in simapro:
            self.assertIn(key, tool.DEFAULT_SOURCES)

    def test_every_default_source_is_a_registered_list(self):
        # A key with a typo in it is a build that stops after the hours it took
        # to get to the merge, and the message names a registry the reader of
        # this constant cannot see.
        from brightway_flows.sources import known_source_lists

        registered = set(known_source_lists())
        for key in tool.DEFAULT_SOURCES:
            self.assertIn(key, registered)

    def test_it_asks_about_where_the_branch_left_main_by_default(self):
        # `--ref` unset means the merge base rather than `main` itself: that is
        # the commit the diff is supposed to attribute nothing to.
        args = tool.build_parser().parse_args([])
        self.assertIsInstance(args, argparse.Namespace)
        self.assertIsNone(args.ref)
        self.assertEqual(args.keep, tool.DEFAULT_KEEP)

    def test_a_build_is_opt_in(self):
        # Hours, not seconds: the default answers the question and stops.
        self.assertFalse(tool.build_parser().parse_args([]).build)

    def test_the_deciding_paths_are_the_four_that_place_a_row(self):
        self.assertEqual(
            tool.DECIDING_PATHS,
            (
                "src/brightway_flows/merge",
                "src/brightway_flows/transformers",
                "src/brightway_flows/flow_layers",
                "src/brightway_flows/data",
            ),
        )

    def test_every_deciding_path_is_a_directory_that_exists(self):
        # A path that has been renamed would make the check silently permissive:
        # `git log -- <gone>` is empty, which reads as "nothing moves a row".
        for relative in tool.DECIDING_PATHS:
            self.assertTrue((tool.REPO_ROOT / relative).is_dir(), relative)


if __name__ == "__main__":
    unittest.main()
