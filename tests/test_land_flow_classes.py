"""`land-flow-classes.json`: what it says, and what it refuses to say.

Stage 4 of `plans/land-class-taxonomy.md`.  The file assigns every land flow in
every registered list to a `LandUse`, and the point of it is that the assignment
is *looked up* rather than derived at run time -- so what is pinned here is
mostly the ways a bad row must fail rather than the happy path:

- **A malformed row raises.**  Every decisions file in this project raises, for
  the reason `AGENTS.md` gives: a row silently skipped is a curator's decision
  that looks applied and is not.
- **`key` and `land_use` must agree.**  `key` is redundant and is carried anyway
  so the file can be grepped by class.  Redundancy that nothing checks is how
  one class gets published under another's name.
- **One flow, one land class.**  Two rows for one `(source, uuid)` would be two
  curated statements arbitrated by file order, which is the collapse this whole
  taxonomy exists to undo.
- **Nothing in `src/` parses a name.**  The decomposition tables are in
  `tools/`, and an import of them from a build is the failure this file was
  written to make impossible.

The counts are measured against the extraction of 19 August 2026.
"""

import ast
import json
import unittest
from pathlib import Path

from brightway_flows.domain.land_flow_classes import (
    DECISIONS_SCHEMA_VERSION,
    LAND_FLOW_CLASSES_FILEPATH,
    LandFlowClass,
    LandFlowClassError,
    land_class_by_source_flow,
    land_class_for_source_flow,
    published_land_classes,
)
from brightway_flows.domain.land_use import Direction, LandCover, LandUse

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "src"


class TheFileTestCase(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(LAND_FLOW_CLASSES_FILEPATH.read_bytes())
        self.rows = self.payload["rows"]

    def test_it_declares_the_format_this_reader_is_written_for(self):
        self.assertEqual(self.payload["schema_version"], DECISIONS_SCHEMA_VERSION)

    def test_every_registered_list_is_covered(self):
        """A list left out is silent, exactly as it was for water and BAFU.

        Stepwise 2006 was left out for a year of commits, and #174 is what that
        cost: 35 of its 41 land rows minted a second flow for a class this list
        already published, named the way Stepwise spells it rather than the way
        this list does.  AGRIBALYSE 3.2 repeated it at ten times the traffic
        before #351: 132 of its 201 land rows minted 120 duplicates on the
        first build that merged it.
        """
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

    def test_every_row_states_a_legal_land_class(self):
        """The validators of `domain/land_use.py`, over the whole file.

        A row stating `forest, primary, short rotation` would construct only if
        the validators had stopped working: a primary forest is on no rotation.
        """
        for row in self.rows:
            with self.subTest(uuid=row["source_uuid"]):
                self.assertEqual(LandUse.from_dict(row["land_use"]).key, row["key"])

    def test_the_reached_space_is_far_smaller_than_the_legal_one(self):
        """339 classes reached by 1,316 source flows, on the 29 August extraction.

        §3.6 predicted 333, and the reading that produced it folded EF's
        `grassland/pasture/meadow` onto plain grassland. It is a class of its
        own -- grassland is not meadow -- so the three flows EF ships for it
        stand apart and the count is three higher. What the number is for is
        the claim underneath it: 339 shared structured classes replace 381
        strings, one list's each, with BAFU's 123 duplicating EF's work.

        It was 336 and 1,288 until #174 curated Stepwise 2006's land rows.
        Twenty-eight of its 41 are here, and 25 of those reach a class another
        list already ships -- which is the point of the file, and the reason
        Stepwise's rows had been minting duplicates. The three new classes are
        `occupation/cropland/intensity=integrated`,
        `occupation/traffic/infrastructure=rail-embankment` and
        `occupation/pasture/intensity=organic`; the first two brought an axis
        value with them and the third did not. The remaining 13 name the state
        the land was in before, which no axis has, and are recorded in
        `tests/data/observed-land-classes.json`'s `unparsed`.

        It was 339 and 1,316 until #351 curated AGRIBALYSE 3.2's land rows.
        All 201 are here -- the names are ecoinvent 3's vocabulary, so 195
        reach classes other lists already ship, and the six new classes are
        the vineyard pair (`crop_type=vine`, an axis value the vendor stated
        and the axes lacked), the unqualified fruit pair, `occupation/sea`,
        and the rail embankment's transformation beside Stepwise's occupation
        of it. Eight of the 201 carry a country the way BAFU's rail rows do,
        split off per #65 and recorded as the row's location.
        """
        self.assertEqual(len(self.rows), 1517)
        self.assertEqual(len({row["key"] for row in self.rows}), 345)

    def test_the_three_directions_are_all_present(self):
        """The repair the plan is really about.

        Direction lived only in a name, so a balanced `from`/`to` pair was held
        apart by two spellings and nothing else. Every land flow now states it.
        """
        directions = {row["land_use"]["direction"] for row in self.rows}
        self.assertEqual(directions, {d.name for d in Direction})

    def test_the_volume_occupations_are_left_out(self):
        """Four EF flows measuring the inside of a mountain, filed under land.

        No surface classification has a word for a volume, and folding them in
        would make the taxonomy's root claim false. They are #72's (§6.3).
        """
        names = {row["source_name"].lower() for row in self.rows}
        self.assertFalse([name for name in names if name.startswith("volume occupied")])


class FiveListsAgreeAboutABuildingSiteTestCase(unittest.TestCase):
    """#174, at the smallest thing that can answer it.

    Five lists ship a row for land occupied by a building site and all five
    spell it `Occupation, construction site`.  Three of them reached the flow
    this list publishes for it; Stepwise's made a second one, because no row of
    Stepwise's was in this file, and AGRIBALYSE's pair did the same until #351.
    What the fix has to produce is one land class from five vendor identifiers
    -- which is checkable here, in milliseconds, without a build.
    """

    #: The building site, as each list identifies it.  ecoinvent's uuid is one
    #: flow in every release, which is why the five releases contribute one
    #: entry and not five.
    THE_SAME_BUILDING_SITE = {
        "ecoinvent-3.12": "4b6b9b76-3199-4bd0-b11d-f8f2efbeac4e",
        "ecoinvent-3.8": "4b6b9b76-3199-4bd0-b11d-f8f2efbeac4e",
        "bafu-2026-v1": "2b353c3f-d447-53cb-8624-71f3a38bd054",
        "stepwise-2006-1.09": "95f8ed6d-0c05-56d4-92ad-c5704605838a",
        # AGRIBALYSE ships it twice, under `Resources / land` and the bare
        # heading; the land-compartment row stands for the pair here (#351).
        "agribalyse-3.2": "ce3f1152-232f-5496-a027-77b5d090bdb0",
    }

    def test_all_five_lists_resolve_to_one_land_class(self):
        classes = {
            source: land_class_for_source_flow(source, uuid_)
            for source, uuid_ in self.THE_SAME_BUILDING_SITE.items()
        }
        for source, land_use in classes.items():
            with self.subTest(source=source):
                self.assertIsNotNone(land_use, f"{source} has no curated class")
        self.assertEqual(
            {land_use.key for land_use in classes.values()},
            {"occupation/construction-site"},
        )

    def test_the_thirteen_stepwise_leaves_behind_have_no_class(self):
        """And say so by having none, rather than by having a guessed one.

        These name the state the land was in before -- a paved square metre
        that was grassland, a forest planted where a field was -- and no axis
        in `domain/land_use.py` describes the land as it was.  `None` is the
        honest answer, and it is what sends the row down the ordinary matching
        path to a flow of its own.
        """
        for uuid_ in (
            "7281725c-8f54-58d4-92a8-c81d624b6327",  # sealed, on grassland
            "f1812655-5bdf-5f6b-be83-099915aa716d",  # forest, on arable land
            "49d53442-c736-5871-928c-5e12c6312ee0",  # grassland to pasture
        ):
            with self.subTest(uuid=uuid_):
                self.assertIsNone(
                    land_class_for_source_flow("stepwise-2006-1.09", uuid_)
                )


class TheLoaderTestCase(unittest.TestCase):
    def test_it_is_keyed_on_the_pair_and_not_the_uuid(self):
        """Two lists are independent vocabularies sharing a uuid format."""
        rows = land_class_by_source_flow()
        self.assertTrue(all(isinstance(key, tuple) and len(key) == 2 for key in rows))
        self.assertTrue(all(isinstance(row, LandFlowClass) for row in rows.values()))

    def test_a_flow_no_row_names_has_no_land_class(self):
        """Which is the answer for almost every flow in the list."""
        self.assertIsNone(land_class_for_source_flow("EF 3.1", "not-a-uuid"))

    def test_a_known_flow_resolves_to_the_class_the_file_states(self):
        rows = land_class_by_source_flow()
        (key, row) = next(
            (key, row)
            for key, row in rows.items()
            if row.land_use.cover is LandCover.CROPLAND
        )
        self.assertEqual(land_class_for_source_flow(*key), row.land_use)

    def test_the_reached_classes_are_the_ones_a_source_flow_lands_on(self):
        reached = published_land_classes()
        self.assertEqual(len(reached), 345)
        self.assertTrue(all(isinstance(value, LandUse) for value in reached.values()))
        self.assertTrue(all(key == value.key for key, value in reached.items()))


class ABadRowTestCase(unittest.TestCase):
    """Every way a row can be wrong, and the error it raises.

    The loader is exercised through a rewritten payload rather than by calling
    the validators, because the thing being pinned is that the file is checked
    *when it is read* -- a check that only runs in a test is a check the build
    does not do.
    """

    def _load(self, payload, tmp_path):
        import brightway_flows.domain.land_flow_classes as module

        path = tmp_path / "land-flow-classes.json"
        path.write_text(json.dumps(payload))
        original = module.LAND_FLOW_CLASSES_FILEPATH
        module.LAND_FLOW_CLASSES_FILEPATH = path
        module.land_class_by_source_flow.cache_clear()
        try:
            return module.land_class_by_source_flow()
        finally:
            module.LAND_FLOW_CLASSES_FILEPATH = original
            module.land_class_by_source_flow.cache_clear()

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.row = {
            "source": "EF 3.1",
            "source_uuid": "u-1",
            "source_name": "arable, irrigated, intensive",
            "source_context": ["Land use", "Land occupation"],
            "unit": "m2*a",
            "key": "occupation/cropland/irrigation=irrigated/intensity=intensive",
            "land_use": {
                "direction": "OCCUPATION",
                "cover": "CROPLAND",
                "irrigation": "IRRIGATED",
                "intensity": "INTENSIVE",
            },
            "comment": "Read off the name.",
        }

    def _payload(self, *rows):
        return {"schema_version": DECISIONS_SCHEMA_VERSION, "rows": list(rows)}

    def test_a_good_row_loads(self):
        rows = self._load(self._payload(self.row), self.tmp_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[("EF 3.1", "u-1")].land_use.cover, LandCover.CROPLAND
        )

    def test_a_missing_field_raises(self):
        for field in ("source", "source_uuid", "key", "land_use", "comment"):
            with self.subTest(field=field):
                bad = {**self.row}
                bad.pop(field)
                with self.assertRaises(LandFlowClassError):
                    self._load(self._payload(bad), self.tmp_path)

    def test_a_key_that_does_not_match_its_fields_raises(self):
        """The redundancy is checked, or it is a second answer waiting to rot."""
        bad = {**self.row, "key": "occupation/forest"}
        with self.assertRaises(LandFlowClassError) as caught:
            self._load(self._payload(bad), self.tmp_path)
        self.assertIn("decompose", str(caught.exception))

    def test_a_combination_the_axes_rule_out_raises(self):
        """A tillage regime is stated instead of an intensity, never as well."""
        bad = {
            **self.row,
            "key": "occupation/cropland/intensity=intensive/tillage=reduced",
            "land_use": {
                "direction": "OCCUPATION",
                "cover": "CROPLAND",
                "intensity": "INTENSIVE",
                "tillage": "REDUCED",
            },
        }
        with self.assertRaises(LandFlowClassError):
            self._load(self._payload(bad), self.tmp_path)

    def test_an_axis_no_cover_admits_raises(self):
        """`landfill` is a question about a dump site and never about a forest."""
        bad = {
            **self.row,
            "key": "occupation/forest/landfill=sanitary",
            "land_use": {
                "direction": "OCCUPATION",
                "cover": "FOREST",
                "landfill": "SANITARY",
            },
        }
        with self.assertRaises(LandFlowClassError):
            self._load(self._payload(bad), self.tmp_path)

    def test_two_rows_for_one_flow_raise(self):
        other = {
            **self.row,
            "key": "occupation/forest",
            "land_use": {"direction": "OCCUPATION", "cover": "FOREST"},
        }
        with self.assertRaises(LandFlowClassError) as caught:
            self._load(self._payload(self.row, other), self.tmp_path)
        self.assertIn("One flow, one land class", str(caught.exception))

    def test_two_identical_rows_for_one_flow_are_not_a_conflict(self):
        """A file that states the same thing twice states one thing."""
        rows = self._load(self._payload(self.row, dict(self.row)), self.tmp_path)
        self.assertEqual(len(rows), 1)

    def test_a_format_this_reader_does_not_know_raises(self):
        bad = {"schema_version": 99, "rows": [self.row]}
        with self.assertRaises(LandFlowClassError):
            self._load(bad, self.tmp_path)


class TheParserStaysOutOfTheBuildTestCase(unittest.TestCase):
    """The whole discipline, as a check rather than a comment.

    `tools/land_class_parser.py` reads a vendor's name and decides what it
    means. The plan says in three places that it is a build-time aid and must
    never become a run-time rule, and a sentence in a docstring has never once
    stopped an import.
    """

    def test_nothing_in_src_imports_the_parser(self):
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
                if any("land_class_parser" in name for name in names):
                    offenders.append(str(path.relative_to(SOURCE_ROOT)))
        self.assertEqual(
            offenders,
            [],
            "the land-class parser is a build-time aid: it gets a curator to "
            "152 of 153 strings and does not get to decide the 153rd "
            "unsupervised. Assign the flow in land-flow-classes.json instead.",
        )


class AgribalyseLandRowsTestCase(unittest.TestCase):
    """#351: AGRIBALYSE's 201 land rows, curated where the merge reads them.

    The rows are ecoinvent 3's vocabulary under SimaPro's compartment habits --
    duplicated between the bare `Resources` heading and `Resources / land`,
    eight of them misfiled among the ground, water and biotic resources, eight
    carrying a country the way BAFU's rail rows do, and two stating a crop the
    axes had no word for.  Each habit gets the test that pins how it is read.
    """

    def test_the_busiest_row_is_the_cropland_transformation(self):
        """`Transformation, from annual crop`, 4,390 of 20,440 processes -- the
        single busiest unmatched row in the list before this file knew it."""
        land_use = land_class_for_source_flow(
            "agribalyse-3.2", "f09dd74c-3f3a-5692-9435-cf1d9509bf24"
        )
        self.assertIsNotNone(land_use)
        self.assertEqual(land_use.key, "transformation-from/cropland")

    def test_a_misfiled_compartment_does_not_move_the_class(self):
        """The `Occupation, annual crop` filed under biotic resources is the
        same class as its land-compartment siblings: the table is keyed to the
        row's identifier, not to where the export filed it, which is how
        BAFU's 29 land rows outside `resources / land` already work."""
        land_use = land_class_for_source_flow(
            "agribalyse-3.2", "b8a66e15-d200-5ed4-a07a-593f42cf25a1"
        )
        self.assertIsNotNone(land_use)
        self.assertEqual(land_use.key, "occupation/cropland")

    def test_a_country_row_records_its_place_and_shares_the_class(self):
        """`Occupation, annual crop, CN`: the place is split off per #65 and
        recorded as the row's location, and the class is the sibling's --
        where the crop grew is not a land class."""
        row = land_class_by_source_flow()[
            ("agribalyse-3.2", "7eae2373-1d74-547e-845b-e0c2a8a3ac0d")
        ]
        self.assertEqual(row.location, "CN")
        self.assertEqual(row.source_name, "Occupation, annual crop")
        self.assertEqual(row.land_use.key, "occupation/cropland")

    def test_the_vineyard_states_its_crop_rather_than_losing_it(self):
        """`Occupation, permanent crop, vine` is a crop type, like `fruit`,
        and the axes gained the word rather than coarsening what the vendor
        said."""
        land_use = land_class_for_source_flow(
            "agribalyse-3.2", "bf3cbaa0-9844-5f8a-8ea0-33a7e0983dcf"
        )
        self.assertIsNotNone(land_use)
        self.assertEqual(
            land_use.key, "occupation/permanent-cropland/crop_type=vine"
        )
        self.assertEqual(land_use.label, "Permanent cropland, vine")

    def test_every_agribalyse_land_row_has_a_class(self):
        """201 rows, none left to name matching.  Stepwise keeps 13 rows no
        axis can read; AGRIBALYSE's vocabulary is ecoinvent's, so the honest
        count here is zero."""
        rows = [
            row
            for (source, _uuid), row in land_class_by_source_flow().items()
            if source == "agribalyse-3.2"
        ]
        self.assertEqual(len(rows), 201)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
