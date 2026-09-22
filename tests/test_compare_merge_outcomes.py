"""A comparison says which code built each side, and refuses a pair that cannot
answer.

Diffing two builds answers "what did this change do" only if the other side was
built from the commit the branch started at.  It was not, once: a branch was
compared against a stored build of an older `main`, and eight halocarbon rows --
five `Dichloromethane`, four `Methane, Bromo-, Halon 1001` and the rest -- were
reported as the branch's doing when they were #90's and #95's.  Nothing in
either database said so.  It was caught because the rows were visibly unrelated
to water; a change whose subject *was* halocarbons would have absorbed them
(#101).

So the pair is checked before the diff is printed, and the failure modes of that
check are what this file is about.  A check that refuses a good pair gets turned
off; a check that passes a bad one is worse than none, because the reader has
stopped watching for the thing it was meant to catch.
"""

import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _load_tool():
    """`tools/` is not a package; the tool is a script, loaded here by path."""
    path = (
        Path(__file__).resolve().parent.parent / "tools" / "compare_merge_outcomes.py"
    )
    spec = importlib.util.spec_from_file_location("compare_merge_outcomes", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load the comparison tool from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["compare_merge_outcomes"] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()

#: Enough of a build database for the tool to open and read end to end.  Every
#: table it queries, and no rows in any of them: the pair is checked before a
#: single outcome is read, so what the rows say is not what these cases are
#: about.
TABLES = (
    """
    CREATE TABLE pipeline_runs (
        run_id TEXT, timestamp TEXT, schema_version INTEGER, dry_run INTEGER,
        max_flows INTEGER, input_files_json TEXT, transformer_names_json TEXT,
        flow_count INTEGER, change_count INTEGER,
        git_commit TEXT NOT NULL DEFAULT '', git_dirty INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE merge_run_inputs (
        source_key TEXT, rows_read INTEGER, rows_available INTEGER
    )
    """,
    """
    CREATE TABLE merge_outcomes (
        list_name TEXT, list_version TEXT, source_uuid TEXT, source_name TEXT,
        source_context_json TEXT, source_unit TEXT, outcome TEXT, reason TEXT,
        flow_object_id TEXT, target_elementary_flow_id TEXT, basis TEXT,
        has_unit_mismatch INTEGER
    )
    """,
    "CREATE TABLE flow_objects (flow_object_id TEXT, pref_label_value TEXT)",
    """
    CREATE TABLE elementary_flows (
        uuid TEXT, pref_label_value TEXT, unit TEXT, context_display TEXT,
        lcia_factor_count INTEGER, is_deprecated INTEGER
    )
    """,
)

EARLIER = "1111111111111111111111111111111111111111"
LATER = "2222222222222222222222222222222222222222"


def write_build(path: Path, commit: str | None, dirty: bool = False) -> Path:
    """A database stamped with *commit*, or -- for None -- one from before #101."""
    path.unlink(missing_ok=True)  # a case that writes the same pair twice
    connection = sqlite3.connect(path)
    for statement in TABLES:
        connection.execute(statement)
    if commit is None:
        connection.execute("INSERT INTO pipeline_runs (run_id) VALUES ('r0')")
    else:
        connection.execute(
            "INSERT INTO pipeline_runs (run_id, git_commit, git_dirty)"
            " VALUES ('r1', ?, ?)",
            (commit, int(dirty)),
        )
    connection.commit()
    connection.close()
    return path


class RevisionTestCase(unittest.TestCase):
    """What a database says about the code that wrote it."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_a_stamped_build_reports_its_commit(self):
        build = tool.Build(write_build(self.root / "a.sqlite3", EARLIER))
        self.assertEqual(build.revision, (EARLIER, False))

    def test_a_modified_tree_is_carried_through(self):
        build = tool.Build(write_build(self.root / "b.sqlite3", LATER, dirty=True))
        self.assertEqual(build.revision, (LATER, True))

    def test_a_build_from_before_the_stamp_says_nothing(self):
        build = tool.Build(write_build(self.root / "c.sqlite3", None))
        self.assertIsNone(build.revision)

    def test_a_build_made_outside_a_repository_says_nothing_either(self):
        """`git_revision()` stamps `""` where there is no repository, which has
        to read as the same answer as never having stamped at all -- otherwise
        an unplaceable build would compare as though it were placed."""
        build = tool.Build(write_build(self.root / "d.sqlite3", ""))
        self.assertIsNone(build.revision)


class ComparabilityTestCase(unittest.TestCase):
    """Which pairs are refused, and which are not."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def pair(self, before, after):
        """Two builds, each `(commit, dirty)`, or None for one that never said."""
        builds = []
        for name, described in (("before", before), ("after", after)):
            commit, dirty = described if described else (None, False)
            builds.append(
                tool.Build(write_build(self.root / f"{name}.sqlite3", commit, dirty))
            )
        return builds

    def reasons(self, before, after, *, known=True, ancestor=True):
        with (
            mock.patch.object(tool, "_known", return_value=known),
            mock.patch.object(tool, "_is_ancestor", return_value=ancestor),
        ):
            return tool._comparability(*self.pair(before, after))

    def test_a_descendant_of_the_before_side_is_comparable(self):
        self.assertEqual(self.reasons((EARLIER, False), (LATER, False)), [])

    def test_an_unstamped_side_is_refused(self):
        reasons = self.reasons(None, (LATER, False))
        self.assertEqual(len(reasons), 1)
        self.assertIn("before build does not say which revision", reasons[0])

    def test_a_modified_tree_is_refused_on_either_side(self):
        for before, after, side in (
            ((EARLIER, True), (LATER, False), "before"),
            ((EARLIER, False), (LATER, True), "after"),
        ):
            with self.subTest(side=side):
                reasons = self.reasons(before, after)
                self.assertEqual(len(reasons), 1)
                self.assertIn(f"the {side} build came from a modified", reasons[0])

    def test_the_same_commit_on_both_sides_is_refused(self):
        reasons = self.reasons((LATER, False), (LATER, False))
        self.assertEqual(len(reasons), 1)
        self.assertIn("nothing between them is a change to the code", reasons[0])

    def test_a_before_side_that_is_not_an_ancestor_is_refused(self):
        """The case that cost eight halocarbon rows: what the after side has
        never had would be reported as what the after side did."""
        reasons = self.reasons((EARLIER, False), (LATER, False), ancestor=False)
        self.assertEqual(len(reasons), 1)
        self.assertIn("is not an ancestor of", reasons[0])

    def test_a_commit_this_repository_has_never_seen_is_refused(self):
        reasons = self.reasons((EARLIER, False), (LATER, False), known=False)
        self.assertEqual(len(reasons), 1)
        self.assertIn("this repository has no", reasons[0])

    def test_git_declining_to_answer_is_not_read_as_yes(self):
        reasons = self.reasons((EARLIER, False), (LATER, False), ancestor=None)
        self.assertEqual(len(reasons), 1)
        self.assertIn("git would not say whether", reasons[0])

    def test_both_sides_are_reported_not_only_the_first(self):
        self.assertEqual(len(self.reasons((EARLIER, True), (LATER, True))), 2)


class GitAnswersTestCase(unittest.TestCase):
    """The questions put to git, and what a non-answer means."""

    def test_is_ancestor_reads_the_exit_status(self):
        for code, expected in ((0, True), (1, False), (128, None)):
            with self.subTest(code=code):
                with mock.patch.object(
                    tool, "_git", return_value=mock.Mock(returncode=code, stdout="")
                ):
                    self.assertIs(tool._is_ancestor(EARLIER, LATER), expected)

    def test_a_git_that_will_not_run_is_a_non_answer(self):
        with mock.patch.object(tool, "_git", return_value=None):
            self.assertIsNone(tool._is_ancestor(EARLIER, LATER))
            self.assertFalse(tool._known(EARLIER))
            self.assertEqual(tool._subject(EARLIER), "")

    def test_this_repositorys_own_head_is_known_and_is_its_own_ancestor(self):
        head = tool._git("rev-parse", "HEAD")
        if head is None or head.returncode:  # pragma: no cover -- not a checkout
            self.skipTest("not a git working tree")
        commit = head.stdout.strip()
        self.assertTrue(tool._known(commit))
        self.assertTrue(tool._is_ancestor(commit, commit))
        self.assertNotEqual(tool._subject(commit), "")


class RefusalTestCase(unittest.TestCase):
    """What the tool does with a pair it will not compare."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.before = write_build(root / "before.sqlite3", EARLIER)
        self.after = write_build(root / "after.sqlite3", LATER)

    def run_tool(self, *extra):
        argv = ["compare_merge_outcomes.py", str(self.before), str(self.after), *extra]
        printed: list[str] = []

        def record(*values, **_keywords):
            printed.append(" ".join(str(value) for value in values))

        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(tool, "_known", return_value=True),
            mock.patch.object(tool, "_is_ancestor", return_value=False),
            mock.patch.object(tool, "_subject", return_value="a commit"),
            mock.patch("builtins.print", record),
        ):
            code = tool.main()
        return code, "\n".join(printed)

    def test_it_stops_rather_than_printing_a_diff_that_reads_as_an_answer(self):
        code, output = self.run_tool()
        self.assertEqual(code, 2)
        self.assertIn("THIS PAIR CANNOT ANSWER WHAT THE CHANGE DID", output)
        self.assertIn("is not an ancestor of", output)
        self.assertNotIn("ROWS DECIDED DIFFERENTLY", output)

    def test_anyway_compares_them_and_still_says_why_it_should_not(self):
        code, output = self.run_tool("--anyway")
        self.assertEqual(code, 0)
        self.assertIn("is not an ancestor of", output)
        self.assertIn("ROWS DECIDED DIFFERENTLY", output)

    def test_both_revisions_are_printed_whatever_the_verdict(self):
        _code, output = self.run_tool()
        self.assertIn("WHICH CODE BUILT THEM", output)
        self.assertIn(EARLIER[:12], output)
        self.assertIn(LATER[:12], output)


def _outcome(connection, version, uuid, target, name="Trifloxystrobin"):
    """One decision, in the two columns this case turns on plus enough to read."""
    connection.execute(
        "INSERT INTO merge_outcomes (list_name, list_version, source_uuid,"
        " source_name, outcome, reason, flow_object_id,"
        " target_elementary_flow_id) VALUES ('ecoinvent', ?, ?, ?, 'prepared',"
        " '', 'fo-1', ?)",
        (version, uuid, name, target),
    )


class OneUuidInTwoVersionsTestCase(unittest.TestCase):
    """A build merging two ecoinvent versions decides one uuid twice (#317).

    ecoinvent keeps a flow's uuid stable across releases, so 3.12 and 3.8 both
    ship `52a00fec`, and `merge_outcomes` holds a row for each.  Keyed on
    `(list_name, source_uuid)` -- `list_name` being `ecoinvent` for both -- the
    second row overwrote the first, and a quarter of the build was compared
    against nothing at all.

    The case is built so that the *older* version is the one that moves, which
    is what the old key hid: whichever row SQLite returned last was the one
    kept, so a change confined to 3.8 could report nothing moved.
    """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.before = write_build(root / "before.sqlite3", EARLIER)
        self.after = write_build(root / "after.sqlite3", LATER)

    def _fill(self, path, target_38):
        connection = sqlite3.connect(path)
        _outcome(connection, "3.12", "52a00fec", "flow-trifloxystrobin")
        _outcome(connection, "3.8", "52a00fec", target_38)
        connection.commit()
        connection.close()

    def test_both_versions_of_one_uuid_are_compared(self):
        self._fill(self.before, "flow-fungicides")
        self._fill(self.after, "flow-fungicides")
        before, after = tool.Build(self.before), tool.Build(self.after)
        self.assertEqual(len(before.outcomes), 2)
        self.assertEqual(set(before.outcomes) & set(after.outcomes), set(after.outcomes))

    def test_a_row_that_moves_only_in_the_older_version_is_seen(self):
        self._fill(self.before, "flow-fungicides")
        self._fill(self.after, "flow-trifloxystrobin")
        before, after = tool.Build(self.before), tool.Build(self.after)
        moved = [
            key for key in set(before.outcomes) & set(after.outcomes)
            if tool._decision(before.outcomes[key]) != tool._decision(after.outcomes[key])
        ]
        self.assertEqual(moved, [("ecoinvent", "3.8", "52a00fec")])

    def test_the_list_is_still_the_first_part_of_the_key(self):
        """`--list` and the per-list counters read `key[0]`, so the version had
        to be appended rather than inserted anywhere else."""
        self._fill(self.before, "flow-fungicides")
        self.assertEqual(
            {key[0] for key in tool.Build(self.before).outcomes}, {"ecoinvent"}
        )


if __name__ == "__main__":
    unittest.main()
