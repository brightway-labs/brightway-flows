"""`particulate-flow-classes.json`: what it says, and what it refuses to say.

Stage 3 of `plans/particulate-taxonomy.md`. The file assigns every airborne
particle flow in every registered list to a size window, and the point of it is
that the assignment is *looked up* rather than derived at run time — so what is
pinned here is mostly the ways a bad row must fail rather than the happy path:

- **A malformed row raises.** Every decisions file in this project raises, for
  the reason `AGENTS.md` gives: a row silently skipped is a curator's decision
  that looks applied and is not.
- **One flow, one window.** Two rows for one `(source, uuid)` would be two
  curated statements arbitrated by file order, which is the collapse this whole
  taxonomy exists to undo.
- **The source category is a closed vocabulary**, because an open field is where
  `(stationary)`, `Stationary` and `stationary source` become three answers.
- **Nothing in `src/` imports the readings table.** It lives in `tools/`, and an
  import of it from a build would turn every reading into a silent rule.

The counts are measured against the extraction of 25 August 2026.
"""

import ast
import json
import tempfile
import unittest
from pathlib import Path

from brightway_flows.domain.particulate_size import (
    DECISIONS_SCHEMA_VERSION,
    FLOW_CLASSES_FILEPATH,
    SOURCE_CATEGORIES,
    ParticulateSizeError,
    particulate_class_by_source_flow,
    reached_size_classes,
    size_class_for_source_flow,
    size_classes,
    source_category_for_source_flow,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "src"


class TheFileTestCase(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FLOW_CLASSES_FILEPATH.read_bytes())
        self.rows = self.payload["rows"]

    def test_it_declares_the_format_this_reader_is_written_for(self):
        self.assertEqual(self.payload["schema_version"], DECISIONS_SCHEMA_VERSION)

    def test_every_registered_list_is_covered(self):
        """A list left out is silent, exactly as it was for water and BAFU."""
        self.assertEqual(
            {row["source"] for row in self.rows},
            {
                "EF 3.1",
                "agribalyse-3.2",
                "bafu-2026-v1",
                "ecoinvent-3.8",
                "ecoinvent-3.9.1",
                "ecoinvent-3.10.1",
                "ecoinvent-3.11",
                "ecoinvent-3.12",
                "stepwise-2006-1.09",
            },
        )

    def test_the_row_counts_are_what_the_vendors_ship(self):
        """Six names over nineteen compartments is most of EF's share.
        AGRIBALYSE ships 27 particle rows and all 27 are placed since the
        owner's readings of `diesel soot` and `SPM` (#196); Stepwise's six
        are in the table since the list joined the tool's sources."""
        counts: dict[str, int] = {}
        for row in self.rows:
            counts[row["source"]] = counts.get(row["source"], 0) + 1
        self.assertEqual(
            counts,
            {
                "EF 3.1": 114,
                "agribalyse-3.2": 27,
                "bafu-2026-v1": 17,
                "ecoinvent-3.8": 15,
                "ecoinvent-3.9.1": 15,
                "ecoinvent-3.10.1": 13,
                "ecoinvent-3.11": 13,
                "ecoinvent-3.12": 13,
                "stepwise-2006-1.09": 6,
            },
        )
        self.assertEqual(len(self.rows), 233)

    def test_every_row_names_a_class_the_scheme_carries(self):
        known = set(size_classes())
        for row in self.rows:
            with self.subTest(row["source_uuid"]):
                self.assertIn(row["size_class"], known)

    def test_every_one_of_the_seven_windows_is_reached(self):
        """A class nothing lands on would be a concept minting an object for
        nobody, which is worth being able to see."""
        self.assertEqual(set(reached_size_classes()), set(size_classes()))

    def test_it_is_keyed_on_the_pair_and_not_the_uuid(self):
        """The lists are independent vocabularies that share a uuid format."""
        rows = particulate_class_by_source_flow()
        self.assertTrue(all(isinstance(key, tuple) and len(key) == 2 for key in rows))


class TheTwoAxesTestCase(unittest.TestCase):
    """The window is the identity; what emitted the particles is not."""

    def setUp(self):
        self.rows = json.loads(FLOW_CLASSES_FILEPATH.read_bytes())["rows"]

    def test_the_source_category_is_a_closed_vocabulary(self):
        for row in self.rows:
            with self.subTest(row["source_uuid"]):
                self.assertIn(row.get("source_category", ""), SOURCE_CATEGORIES)

    def test_almost_no_row_states_a_source_category(self):
        """Six today — BAFU's stationary PM10, AGRIBALYSE's mobile and
        stationary PM10 and its above-ten process fraction (#190), and
        Stepwise's mobile and stationary PM10 (#196)."""
        categorised = [row for row in self.rows if row.get("source_category")]
        self.assertEqual(
            [(row["source"], row["source_name"], row["source_category"])
             for row in categorised],
            [
                ("agribalyse-3.2", "Particulates, < 10 um (mobile)", "mobile"),
                ("agribalyse-3.2", "Particulates, < 10 um (stationary)", "stationary"),
                ("agribalyse-3.2", "Particulates, > 10 um (process)", "process"),
                ("bafu-2026-v1", "Particulates, < 10 um (stationary)", "stationary"),
                ("stepwise-2006-1.09", "Particulates, < 10 um (mobile)", "mobile"),
                ("stepwise-2006-1.09", "Particulates, < 10 um (stationary)", "stationary"),
            ],
        )

    def test_a_process_row_lands_on_the_above_ten_window(self):
        """AGRIBALYSE's third category, read the way the other two are: the
        window is the identity and the category is recorded beside it."""
        process = [
            row for row in self.rows
            if row["source_name"] == "Particulates, > 10 um (process)"
        ]
        self.assertEqual([row["size_class"] for row in process], ["above_pm10"])
        self.assertEqual(
            source_category_for_source_flow(process[0]["source"], process[0]["source_uuid"]),
            "process",
        )

    def test_agribalyses_shared_spellings_read_as_bafus_do(self):
        """AGRIBALYSE ships BAFU's particle spellings verbatim -- the same
        SimaPro export vocabulary -- and the table reads each the same way in
        both lists, so the two lists' rows meet on one window."""
        by_list = {}
        for row in self.rows:
            if row["source"] in ("agribalyse-3.2", "bafu-2026-v1"):
                by_list.setdefault(row["source"], {})[row["source_name"].lower()] = row["size_class"]
        shared = set(by_list["agribalyse-3.2"]) & set(by_list["bafu-2026-v1"])
        self.assertGreaterEqual(len(shared), 6)
        for name in sorted(shared):
            with self.subTest(name=name):
                self.assertEqual(by_list["agribalyse-3.2"][name], by_list["bafu-2026-v1"][name])

    def test_a_qualified_row_lands_on_the_unqualified_window(self):
        """Stepwise gives plain, mobile and stationary PM10 the same factor, so
        a separate identity would buy a distinction no method uses at the cost
        of every factor the row could have had."""
        qualified = [
            row for row in self.rows
            if row["source_name"] in ("Particulates, < 10 um (stationary)", "Particulates, < 10 um (mobile)")
        ]
        self.assertEqual(len(qualified), 5)
        self.assertEqual({row["size_class"] for row in qualified}, {"pm10"})

    def test_the_category_is_readable_without_the_window(self):
        stationary = next(
            row for row in self.rows if row.get("source_category") == "stationary"
        )
        self.assertEqual(
            source_category_for_source_flow(
                stationary["source"], stationary["source_uuid"]
            ),
            "stationary",
        )


class TheReadingsThisMakesTestCase(unittest.TestCase):
    """The assignments #153 turns on, named rather than counted."""

    def _uuid_for(self, source: str, name: str) -> str:
        rows = json.loads(FLOW_CLASSES_FILEPATH.read_bytes())["rows"]
        return next(
            row["source_uuid"]
            for row in rows
            if row["source"] == source and row["source_name"] == name
        )

    def test_bafus_pm10_reads_as_pm10(self):
        """The row that minted a substance of its own with no factors."""
        found = size_class_for_source_flow(
            "bafu-2026-v1", self._uuid_for("bafu-2026-v1", "Particulates, < 10 um")
        )
        assert found is not None
        self.assertEqual(found.id, "pm10")

    def test_the_coarse_band_does_not_read_as_pm10(self):
        """The other half of #153: 2.5–10 µm is not below 10 µm, in any list."""
        for source, name in (
            ("bafu-2026-v1", "Particulates, > 2.5 um, and < 10um"),
            ("ecoinvent-3.8", "Particulates, > 2.5 um, and < 10um"),
            ("ecoinvent-3.12", "Particulate Matter, > 2.5 um and < 10um"),
        ):
            with self.subTest(source):
                found = size_class_for_source_flow(
                    source, self._uuid_for(source, name)
                )
                assert found is not None
                self.assertEqual(found.id, "pm2_5_to_pm10")

    def test_the_ecoinvent_rename_does_not_move_the_window(self):
        """3.8 and 3.9.1 ship one uuid under two names. The window is unmoved."""
        rows = json.loads(FLOW_CLASSES_FILEPATH.read_bytes())["rows"]
        by_uuid: dict[str, set[str]] = {}
        for row in rows:
            if row["source"].startswith("ecoinvent-"):
                by_uuid.setdefault(row["source_uuid"], set()).add(row["size_class"])
        disagreeing = {u: c for u, c in by_uuid.items() if len(c) > 1}
        self.assertEqual(disagreeing, {})

    def test_both_size_unstated_names_read_as_one_class(self):
        """A stated `unspecified` is the absence of a statement, not a statement.

        Flagged in the plan (§6) rather than assumed: Stepwise characterises the
        two differently, and that is recorded as a factor conflict for #2
        rather than as a second identity.
        """
        for name in ("Particulates", "Particulates, unspecified"):
            with self.subTest(name):
                found = size_class_for_source_flow(
                    "bafu-2026-v1", self._uuid_for("bafu-2026-v1", name)
                )
                assert found is not None
                self.assertEqual(found.id, "unsized")

    def test_a_flow_no_row_names_has_no_window(self):
        self.assertIsNone(size_class_for_source_flow("EF 3.1", "not-a-uuid"))
        self.assertEqual(source_category_for_source_flow("EF 3.1", "not-a-uuid"), "")


class ABadRowRaisesTestCase(unittest.TestCase):
    """Pinned against the loader rather than against a copy of its validators,
    because the thing being pinned is that the file is checked *when it is
    read* — a check that only runs in a test is a check the build does not do.
    """

    def _load(self, payload):
        import brightway_flows.domain.particulate_size as module

        path = self.tmp_path / "particulate-flow-classes.json"
        path.write_text(json.dumps(payload))
        original = module.FLOW_CLASSES_FILEPATH
        module.FLOW_CLASSES_FILEPATH = path
        module.particulate_class_by_source_flow.cache_clear()
        module.reached_size_classes.cache_clear()
        try:
            return module.particulate_class_by_source_flow()
        finally:
            module.FLOW_CLASSES_FILEPATH = original
            module.particulate_class_by_source_flow.cache_clear()
            module.reached_size_classes.cache_clear()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.row = {
            "source": "EF 3.1",
            "source_uuid": "u-1",
            "source_name": "particles (PM10)",
            "source_context": ["Emissions", "Emissions to air"],
            "unit": "kg",
            "size_class": "pm10",
            "source_category": "",
            "comment": "Read off the name.",
        }

    def _payload(self, *rows):
        return {"schema_version": DECISIONS_SCHEMA_VERSION, "rows": list(rows)}

    def test_a_good_row_loads(self):
        rows = self._load(self._payload(self.row))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[("EF 3.1", "u-1")].size_class.id, "pm10")

    def test_a_missing_field_raises(self):
        for field in ("source", "source_uuid", "source_name", "size_class", "comment"):
            with self.subTest(field=field):
                bad = {**self.row}
                bad.pop(field)
                with self.assertRaises(ParticulateSizeError):
                    self._load(self._payload(bad))

    def test_a_missing_source_category_is_not_an_error(self):
        """Most rows state none, and requiring it would make "the vendor did not
        say" indistinguishable from a missing column."""
        bare = {**self.row}
        bare.pop("source_category")
        rows = self._load(self._payload(bare))
        self.assertEqual(rows[("EF 3.1", "u-1")].source_category, "")

    def test_a_class_the_scheme_does_not_carry_raises(self):
        bad = {**self.row, "size_class": "pm5"}
        with self.assertRaises(ParticulateSizeError) as caught:
            self._load(self._payload(bad))
        self.assertIn("does not carry", str(caught.exception))

    def test_a_source_category_outside_the_vocabulary_raises(self):
        bad = {**self.row, "source_category": "stationary source"}
        with self.assertRaises(ParticulateSizeError) as caught:
            self._load(self._payload(bad))
        self.assertIn("source category", str(caught.exception))

    def test_two_rows_for_one_flow_raise(self):
        other = {**self.row, "size_class": "pm2_5"}
        with self.assertRaises(ParticulateSizeError) as caught:
            self._load(self._payload(self.row, other))
        self.assertIn("One flow, one window", str(caught.exception))

    def test_two_identical_rows_for_one_flow_are_not_a_conflict(self):
        """A file that states the same thing twice states one thing."""
        rows = self._load(self._payload(self.row, dict(self.row)))
        self.assertEqual(len(rows), 1)

    def test_a_format_this_reader_does_not_know_raises(self):
        with self.assertRaises(ParticulateSizeError):
            self._load({"schema_version": 99, "rows": [self.row]})


class TheReadingsStayOutOfTheBuildTestCase(unittest.TestCase):
    """The whole discipline, as a check rather than a comment.

    `tools/build_particulate_flow_classes.py` holds a table mapping a vendor's
    name to a window. The plan says in three places that it is a build-time aid
    and must never become a run-time rule, and a sentence in a docstring has
    never once stopped an import.
    """

    def test_nothing_in_src_imports_the_builder(self):
        offenders = []
        for path in sorted(SOURCE_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                else:
                    continue
                if any("build_particulate_flow_classes" in name for name in names):
                    offenders.append(str(path.relative_to(SOURCE_ROOT)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
