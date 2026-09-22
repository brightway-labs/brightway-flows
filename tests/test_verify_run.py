"""The verification harness must report real changes and only real changes.

The harness is what every subsequent refactor is checked with, so its own
failure modes matter more than usual.  A snapshot that misses a change lets a
broken refactor through; a snapshot that reports a change which is only a
timestamp, an absolute path, or a rowid makes the harness useless in practice
and it stops being run.  Both directions are tested here.
"""

import gzip
import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import orjson


def _load_harness():
    """`tools/` is not a package; the harness is a script, loaded here by path."""
    path = Path(__file__).resolve().parent.parent / "tools" / "verify_run.py"
    spec = importlib.util.spec_from_file_location("verify_run", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load the verification harness from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_run"] = module
    spec.loader.exec_module(module)
    return module


verify_run = _load_harness()


def build_database(
    path: Path,
    rows,
    *,
    start_id: int = 1,
    extra_table: bool = False,
    duplicate_source: bool = False,
):
    """A database shaped like `consensus.db`: a table, an FTS index, a rowid table."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE flows (uuid TEXT PRIMARY KEY, name TEXT, unit TEXT)")
    conn.execute("CREATE VIRTUAL TABLE flows_fts USING fts5(uuid, name)")
    conn.execute(
        "CREATE TABLE sources (id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT, list TEXT)"
    )
    conn.execute("CREATE TABLE runs (run_id TEXT, generated_at TEXT, note TEXT)")
    for uuid, name, unit in rows:
        conn.execute("INSERT INTO flows VALUES (?, ?, ?)", (uuid, name, unit))
        conn.execute("INSERT INTO flows_fts VALUES (?, ?)", (uuid, name))
        conn.execute(
            "INSERT INTO sources (id, uuid, list) VALUES (?, ?, ?)",
            (start_id, uuid, "ecoinvent"),
        )
        start_id += 1
    if duplicate_source:
        conn.execute(
            "INSERT INTO sources (id, uuid, list) VALUES (?, ?, ?)",
            (start_id, rows[0][0], "ecoinvent"),
        )
    conn.execute(
        "INSERT INTO runs VALUES (?, ?, ?)", ("run-abc", "2026-01-01T00:00:00Z", "ok")
    )
    if extra_table:
        conn.execute("CREATE TABLE conflicts (target TEXT, kind TEXT)")
    conn.commit()
    conn.close()


ROWS = [
    ("u-1", "Carbon dioxide", "kg"),
    ("u-2", "Methane", "kg"),
    ("u-3", "Water", "m3"),
]


class HarnessTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def build_data_dir(self, name, *, rows=ROWS, db_rows=None, **kwargs) -> Path:
        """A data directory.  `db_rows` varies the database alone, so that a
        test about SQLite ordering is not also a test about JSON ordering."""
        data_dir = self.root / name
        data_dir.mkdir()
        build_database(
            data_dir / "consensus-flows.sqlite3",
            rows if db_rows is None else db_rows,
            **kwargs,
        )
        content = {
            "schema_version": 1,
            "generated_at": f"generated-in-{name}",
            "input_paths": {"flows": f"{data_dir}/ef-31-flows.json"},
            "flows": [{"uuid": uuid, "name": flow_name} for uuid, flow_name, _ in rows],
        }
        (data_dir / "elementary-flows.json").write_bytes(orjson.dumps(content))
        (data_dir / "harmonised-flows-simple.json.gz").write_bytes(
            gzip.compress(orjson.dumps([{"identifier": uuid} for uuid, _, _ in rows]))
        )
        return data_dir

    def snapshot(self, data_dir: Path) -> Path:
        out = self.root / f"snap-{data_dir.name}"
        verify_run.snapshot(data_dir, out)
        return out

    def assertIdentical(self, left: Path, right: Path):
        self.assertEqual(verify_run.compare(left, right), 0)

    def assertDiffers(self, left: Path, right: Path):
        self.assertEqual(verify_run.compare(left, right), 1)


class SnapshotShapeTestCase(HarnessTestCase):
    def test_covers_json_gzip_and_every_sqlite_table(self):
        manifest = verify_run.snapshot(
            self.build_data_dir("a"), self.root / "out"
        )
        self.assertIn("elementary-flows.json.canonical", manifest)
        self.assertIn("harmonised-flows-simple.json.gz.canonical", manifest)
        for table in ("flows", "sources", "runs", "flows_fts"):
            self.assertIn(f"consensus-flows.sqlite3/{table}.tsv", manifest)

    def test_fts_shadow_tables_are_excluded(self):
        """fts5 internals are not stable across builds and say nothing."""
        manifest = verify_run.snapshot(
            self.build_data_dir("a"), self.root / "out"
        )
        shadows = [name for name in manifest if "flows_fts_" in name]
        self.assertEqual(shadows, [])

    def test_sqlite_sidecars_are_not_snapshotted(self):
        """`-wal` and `-shm` exist depending on how the last connection closed.

        They were the only difference between two otherwise identical runs, and
        reporting them makes every comparison look like a failure.
        """
        data_dir = self.build_data_dir("a")
        for suffix in ("-wal", "-shm"):
            (data_dir / f"consensus-flows.sqlite3{suffix}").write_bytes(b"")
        manifest = verify_run.snapshot(data_dir, self.root / "out")
        self.assertEqual(
            [name for name in manifest if "-wal" in name or "-shm" in name], []
        )
        self.assertIn("consensus-flows.sqlite3/flows.tsv", manifest)

    def test_an_unreadable_database_is_reported_not_fatal(self):
        """A database left mid-transaction needs recovery, which needs a write.

        Snapshotting must not modify what it is measuring, so the database is
        opened read-only and the failure becomes a finding.
        """
        data_dir = self.build_data_dir("a")
        (data_dir / "consensus-flows.sqlite3-journal").write_bytes(b"hot journal")
        manifest = verify_run.snapshot(data_dir, self.root / "out")
        self.assertIn("consensus-flows.sqlite3.unreadable", manifest)
        self.assertIn("elementary-flows.json.canonical", manifest)

    def test_a_run_leaving_sidecars_matches_one_that_does_not(self):
        left_dir = self.build_data_dir("a")
        right_dir = self.build_data_dir("b")
        (right_dir / "consensus-flows.sqlite3-wal").write_bytes(b"transient")
        self.assertIdentical(self.snapshot(left_dir), self.snapshot(right_dir))

    def test_seeded_inputs_are_not_snapshotted(self):
        """Only what the run produced is evidence; its inputs are not."""
        data_dir = self.build_data_dir("a")
        (data_dir / "pubchem-data.json").write_bytes(b"[]")
        (data_dir / "ecoinvent-biosphere-flows-3.12.json").write_bytes(b"[]")
        manifest = verify_run.snapshot(data_dir, self.root / "out")
        self.assertNotIn("pubchem-data.json.canonical", manifest)
        self.assertNotIn("ecoinvent-biosphere-flows-3.12.json.canonical", manifest)

    def test_the_extracted_base_file_is_snapshotted(self):
        """It is derived, so it is evidence, so it is compared (#237).

        The other half of not seeding it.  Seeding put it on the input side of
        the line, where the snapshot ignored it -- so two revisions extracting
        differently produced the same snapshot, and a change to extraction code
        or to `ef-3.1-manual-fixes.json` was invisible by construction.
        """
        data_dir = self.build_data_dir("a")
        (data_dir / "ef-31-flows.json").write_bytes(b"[]")
        manifest = verify_run.snapshot(data_dir, self.root / "out")
        self.assertIn("ef-31-flows.json.canonical", manifest)

    def test_row_count_is_stated_in_the_dump(self):
        verify_run.snapshot(self.build_data_dir("a"), self.root / "out")
        text = (self.root / "out" / "consensus-flows.sqlite3" / "flows.tsv").read_text()
        self.assertEqual(text.splitlines()[0], "# rows: 3")


class NoiseIsIgnoredTestCase(HarnessTestCase):
    """Differences that are properties of the run, not of the code."""

    def test_two_equivalent_runs_are_identical(self):
        left = self.snapshot(self.build_data_dir("a"))
        right = self.snapshot(self.build_data_dir("b"))
        self.assertIdentical(left, right)

    def test_absolute_data_directory_paths_are_normalised(self):
        """`input_paths` names the data dir, which differs by construction."""
        left = self.snapshot(self.build_data_dir("a"))
        right = self.snapshot(self.build_data_dir("b"))
        canonical = (left / "elementary-flows.json.canonical").read_text()
        self.assertIn("<DATA_DIR>", canonical)
        self.assertNotIn(str(self.root / "a"), canonical)
        self.assertIdentical(left, right)

    def test_volatile_json_fields_are_masked(self):
        left = self.snapshot(self.build_data_dir("a"))
        canonical = (left / "elementary-flows.json.canonical").read_text()
        self.assertIn("<volatile>", canonical)
        self.assertNotIn("generated-in-a", canonical)

    def test_volatile_sqlite_columns_are_masked(self):
        left = self.snapshot(self.build_data_dir("a"))
        text = (left / "consensus-flows.sqlite3" / "runs.tsv").read_text()
        self.assertIn("<volatile>", text)
        self.assertNotIn("run-abc", text)

    def test_row_insertion_order_does_not_matter(self):
        """Same rows, written in a different order: the same database."""
        left = self.snapshot(self.build_data_dir("a", db_rows=ROWS))
        right = self.snapshot(self.build_data_dir("b", db_rows=list(reversed(ROWS))))
        self.assertIdentical(left, right)

    def test_autoincrement_rowids_do_not_matter(self):
        """`sources.id` reflects insertion order, which the merge may reorder."""
        left = self.snapshot(self.build_data_dir("a", start_id=1))
        right = self.snapshot(self.build_data_dir("b", start_id=500))
        self.assertIdentical(left, right)


class RealChangesAreCaughtTestCase(HarnessTestCase):
    """The direction that matters: a change to the data must be reported."""

    def test_changed_cell_is_caught(self):
        altered = [("u-1", "Carbon dioxide", "g"), *ROWS[1:]]
        left = self.snapshot(self.build_data_dir("a"))
        right = self.snapshot(self.build_data_dir("b", rows=altered))
        self.assertDiffers(left, right)

    def test_dropped_row_is_caught(self):
        left = self.snapshot(self.build_data_dir("a"))
        right = self.snapshot(self.build_data_dir("b", rows=ROWS[:2]))
        self.assertDiffers(left, right)

    def test_duplicated_row_is_caught(self):
        """Sorting must not collapse duplicates into one.

        Duplicated source references are a real failure mode of the merge: a
        flow matched twice gains the same `elementary_flow_sources` row twice.
        """
        left = self.snapshot(self.build_data_dir("a"))
        right = self.snapshot(self.build_data_dir("b", duplicate_source=True))
        self.assertDiffers(left, right)

    def test_new_table_is_caught(self):
        left = self.snapshot(self.build_data_dir("a"))
        right = self.snapshot(self.build_data_dir("b", extra_table=True))
        self.assertDiffers(left, right)

    def test_changed_gzip_artifact_is_caught(self):
        """The one published file; a silent change to it is the worst case."""
        left_dir = self.build_data_dir("a")
        right_dir = self.build_data_dir("b")
        (right_dir / "harmonised-flows-simple.json.gz").write_bytes(
            gzip.compress(orjson.dumps([{"identifier": "different"}]))
        )
        self.assertDiffers(self.snapshot(left_dir), self.snapshot(right_dir))

    def test_json_key_order_change_is_caught(self):
        """Converting a dict to a dataclass record reorders keys.

        `to_dict()` follows declaration order, so a record conversion that is
        meant to be behaviour-preserving can still move every key in the
        artifact.  Sorting keys here would hide precisely that.
        """
        left_dir = self.build_data_dir("a")
        right_dir = self.build_data_dir("b")
        payload = orjson.loads((right_dir / "elementary-flows.json").read_bytes())
        (right_dir / "elementary-flows.json").write_bytes(
            orjson.dumps(dict(reversed(list(payload.items()))))
        )
        self.assertDiffers(self.snapshot(left_dir), self.snapshot(right_dir))

    def test_log_timestamps_are_masked_but_content_is_not(self):
        """Every line of `rdkit-log.txt` is stamped with the wall-clock time.

        Two runs of the same revision differ on all 1,182 lines without this,
        while a genuinely new warning must still be reported.
        """
        left_dir = self.build_data_dir("a")
        right_dir = self.build_data_dir("b")
        (left_dir / "rdkit-log.txt").write_text(
            "2026-08-04T08:45:33Z\tu-1\tWARNING: Omitted undefined stereo\n"
        )
        (right_dir / "rdkit-log.txt").write_text(
            "2026-08-04T09:12:07Z\tu-1\tWARNING: Omitted undefined stereo\n"
        )
        self.assertIdentical(self.snapshot(left_dir), self.snapshot(right_dir))

        (right_dir / "rdkit-log.txt").write_text(
            "2026-08-04T09:12:07Z\tu-1\tWARNING: something else entirely\n"
        )
        self.assertDiffers(self.snapshot(left_dir), self.snapshot(right_dir))

    def test_log_line_order_is_preserved(self):
        """Unlike table rows, the order a log was written in is part of it."""
        left_dir = self.build_data_dir("a")
        right_dir = self.build_data_dir("b")
        (left_dir / "opsin-log.txt").write_text("2026-01-01T00:00:00Z\tfirst\n"
                                                "2026-01-01T00:00:01Z\tsecond\n")
        (right_dir / "opsin-log.txt").write_text("2026-01-01T00:00:00Z\tsecond\n"
                                                 "2026-01-01T00:00:01Z\tfirst\n")
        self.assertDiffers(self.snapshot(left_dir), self.snapshot(right_dir))

    def test_unreadable_artifact_is_reported_rather_than_skipped(self):
        data_dir = self.build_data_dir("a")
        (data_dir / "broken.json").write_bytes(b"{not json")
        manifest = verify_run.snapshot(data_dir, self.root / "out")
        self.assertIn("broken.json.unreadable", manifest)


class SeedingTestCase(HarnessTestCase):
    GLAD_LEGACY = "additional-flow-input-glad-ilcd-ef31-to-simapro-10.2.json"

    def test_seeds_named_inputs_and_globs_by_hard_link(self):
        source = self.root / "real"
        source.mkdir()
        for name in ("EF-v3.1.zip", "chebi.json.gz",
                     "ecoinvent-biosphere-flows-3.12.json",
                     self.GLAD_LEGACY):
            (source / name).write_bytes(b"x")
        (source / "elementary-flows.json").write_bytes(b"derived")

        work = self.root / "work" / "data"
        linked = verify_run.seed_data_dir(work, source)

        self.assertIn("EF-v3.1.zip", linked)
        self.assertIn("ecoinvent-biosphere-flows-3.12.json", linked)
        self.assertIn(self.GLAD_LEGACY, linked)
        self.assertFalse(
            (work / "elementary-flows.json").exists(),
            "a derived artifact must not be seeded, or the run proves nothing",
        )

    def test_the_base_flow_file_is_derived_rather_than_seeded(self):
        """`ef-31-flows.json` comes out of `EF-v3.1.zip`, which is seeded.

        It was seeded too until #237, and the derived copy won -- `build` reads
        it and never regenerates it -- so the harness pinned one extraction on
        both sides of every comparison.  The zip was already there and read by
        nothing; the run extracts from it now.
        """
        source = self.root / "real"
        source.mkdir()
        (source / "EF-v3.1.zip").write_bytes(b"x")
        (source / "ef-31-flows.json").write_bytes(b"derived")

        work = self.root / "work" / "data"
        linked = verify_run.seed_data_dir(work, source)

        self.assertIn("EF-v3.1.zip", linked)
        self.assertNotIn("ef-31-flows.json", linked)
        self.assertFalse((work / "ef-31-flows.json").exists())

    def test_only_the_glad_table_is_seeded_from_the_old_input_names(self):
        """`additional-flow-input-*.json` was a glob while the transform had an
        input path. It does not any more (#210), and the only file left under
        that prefix that anything reads is the GLAD correspondence table under
        the name it had back then."""
        source = self.root / "real"
        source.mkdir()
        for name in (self.GLAD_LEGACY,
                     "additional-flow-input-stepwise-2006.json",
                     "additional-flow-input-ecoinvent-3.12-no-match.json"):
            (source / name).write_bytes(b"x")

        linked = verify_run.seed_data_dir(self.root / "work" / "data", source)

        self.assertEqual(
            [n for n in linked if n.startswith("additional-flow-input-")],
            [self.GLAD_LEGACY],
        )

    def test_missing_source_directory_is_an_error(self):
        with self.assertRaises(SystemExit):
            verify_run.seed_data_dir(self.root / "work", self.root / "nope")


if __name__ == "__main__":
    unittest.main()
