"""A build says which revision it came from, so two of them can be compared.

Verifying a change that moves rows means diffing a build of the branch against a
build of `main`.  The second is ten minutes of code that has not changed, and
somebody has almost certainly built that revision already -- but reusing a stored
build is only safe if it can say what it is a build *of*.

Without the stamp the failure is silent: a diff against a build of an older
`main` reports that `main`'s own commits as though they were the branch's.  It
happened while #297 was being written, and was caught only because the rows were
visibly unrelated to the change under review (#101).
"""

from __future__ import annotations

import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from brightway_flows import filesystem
from brightway_flows.pipeline.review_records import PipelineRun
from brightway_flows.pipeline.review_tables import (
    _RUN_COLUMNS,
    _run_row,
    read_pipeline_run,
    write_review_tables,
)


class GitRevisionTestCase(unittest.TestCase):
    """What `git_revision` reports, and what it does when it cannot."""

    def test_it_reports_this_repositorys_head(self):
        commit, _dirty = filesystem.git_revision()
        expected = subprocess.run(
            ["git", "-C", str(filesystem.REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False,
        )
        if expected.returncode:  # pragma: no cover -- not a git checkout
            self.skipTest("not a git working tree")
        self.assertEqual(commit, expected.stdout.strip())

    def test_a_working_tree_is_reported_as_dirty(self):
        with mock.patch("subprocess.run") as run:
            run.side_effect = [
                mock.Mock(returncode=0, stdout="abc123\n"),
                mock.Mock(returncode=0, stdout=" M src/thing.py\n"),
            ]
            self.assertEqual(filesystem.git_revision(), ("abc123", True))

    def test_a_clean_tree_is_not(self):
        with mock.patch("subprocess.run") as run:
            run.side_effect = [
                mock.Mock(returncode=0, stdout="abc123\n"),
                mock.Mock(returncode=0, stdout="\n"),
            ]
            self.assertEqual(filesystem.git_revision(), ("abc123", False))

    def test_no_repository_is_no_revision_rather_than_an_error(self):
        """An installed copy still builds.  A stamp is worth having and is not
        worth failing a ten-minute run over."""
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=128, stdout="")
            self.assertEqual(filesystem.git_revision(), ("", False))

    def test_a_git_that_will_not_run_is_the_same(self):
        with mock.patch("subprocess.run", side_effect=OSError("no git")):
            self.assertEqual(filesystem.git_revision(), ("", False))


class ItReachesTheDatabaseTestCase(unittest.TestCase):
    """The stamp is only worth anything if it survives to the file."""

    RUN = PipelineRun(
        run_id="r1",
        timestamp="2026-08-15T00:00:00+00:00",
        schema_version=1,
        git_commit="0123456789abcdef",
        git_dirty=True,
    )

    def test_the_row_carries_both_fields(self):
        row = dict(zip(_RUN_COLUMNS, _run_row(self.RUN), strict=True))
        self.assertEqual(row["git_commit"], "0123456789abcdef")
        self.assertEqual(row["git_dirty"], 1)

    def test_it_round_trips_through_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "consensus-flows.sqlite3"
            write_review_tables(
                path,
                run=self.RUN,
                stats=[],
                changes=[],
                queue_items=[],
                formula_mismatches=[],
                element_coverage=[],
                context_mappings=[],
            )
            stored = read_pipeline_run(path)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.git_commit, "0123456789abcdef")
        self.assertTrue(stored.git_dirty)

    def test_a_database_without_the_columns_still_reads(self):
        """`assess` and the review app open whatever is in the data directory,
        which is not always a build of the code reading it."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE pipeline_runs (run_id TEXT, timestamp TEXT,"
                " schema_version INTEGER, dry_run INTEGER, max_flows INTEGER,"
                " input_files_json TEXT, transformer_names_json TEXT,"
                " flow_count INTEGER, change_count INTEGER)"
            )
            connection.execute(
                "INSERT INTO pipeline_runs VALUES"
                " ('r0', 't', 1, 0, NULL, '[]', '[]', 0, 0)"
            )
            connection.commit()
            connection.close()
            stored = read_pipeline_run(path)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.git_commit, "")
        self.assertFalse(stored.git_dirty)


if __name__ == "__main__":
    unittest.main()
