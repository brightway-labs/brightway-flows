"""Reading Stepwise 2006, the first list that arrives as an LCIA method.

Every other registered list publishes flows and this one does not: it publishes
nineteen impact categories, and its flows are whatever those characterise.  So
the tests here are mostly about the two places that fact can go wrong -- the
unit, which is in a different block from the compartment, and the placement,
which is nobody's compartment vocabulary but SimaPro's.

The fixture is a hand-cut export with the shape of the real one: five
categories, both `as CO2e` conventions, the hectare-year occupation row, and
the substance blocks that carry the units and comments.  Its rows are copied
from `Stepwise2006_v1.09.csv` field for field, so the identifiers it produces
are the identifiers the real file produces -- which is what lets the curated
context rows, which name UUIDs, be tested against it.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from brightway_flows.context_mapping import (
    MANUAL_MAPPING_FILEPATH,
    context_iri_by_source_context,
    normalize_context_key,
)
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.units import build_units_index, resolve_unit_notation
from brightway_flows.filesystem import stepwise_csv_path
from brightway_flows.integrations.stepwise import (
    STEPWISE_METHOD_NAME,
    _blocks,
    _method_block,
    _method_version,
    extract_elementary_flows,
    fetch,
    method_revision,
    parse_substance_comment,
)
from brightway_flows.pipeline.loading import _normalize_input_flow_record
from brightway_flows.sources import (
    SourceList,
    excluded_source_flows,
    known_source_lists,
)
from brightway_flows.transformers.default_context_mapping import (
    DefaultContextMappingTransformer,
)

import orjson

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "stepwise-mini.csv"
KEY = "stepwise-2006-1.09"
PREFIX = "https://vocab.brightway.one/flow-contexts/"

#: Every unit notation Stepwise's substance blocks use, and what the unit
#: vocabulary makes of it.  Nine, of which four had to be taught: the metric
#: tonne, the hectare-year, SimaPro's `p` for a counted thing, and the method's
#: EUR2003.
STEPWISE_UNITS = {
    "kg": "kg",
    "kBq": "kBq",
    "m3": "m3",
    "MJ": "MJ",
    "m2a": "m2.a",
    "ha a": "ha.a",
    "ton": "t",
    "p": "#",
    "EUR2003": "EUR",
}


class SubstanceCommentTestCase(unittest.TestCase):
    """SimaPro writes a substance's synonyms and its formula in one text field."""

    def test_the_synonyms_come_out_and_the_formula_stays(self):
        synonyms, remaining = parse_substance_comment(
            "Formula: C9H16Cl2N4 \n"
            "Synonyms: 1-(3-Chloro-2-propenyl)decane chloride; \n"
            "Dowicide Q; Hexamethylenetetramine chloroallyl chloride"
        )
        self.assertEqual(
            synonyms,
            [
                "1-(3-Chloro-2-propenyl)decane chloride",
                "Dowicide Q",
                "Hexamethylenetetramine chloroallyl chloride",
            ],
        )
        self.assertEqual(remaining, "Formula: C9H16Cl2N4")

    def test_a_heating_value_ends_the_synonym_run(self):
        """The run wraps over lines, so its end has to be recognised."""
        synonyms, remaining = parse_substance_comment(
            "Synonyms: Lignite; Brown coal\n"
            "\n"
            "Higher heating value (HHV): 9.90 MJ/kg\n"
            "Lower heating value (LHV): 8.75 MJ/kg"
        )
        self.assertEqual(synonyms, ["Lignite", "Brown coal"])
        self.assertEqual(
            remaining,
            "Higher heating value (HHV): 9.90 MJ/kg\n"
            "Lower heating value (LHV): 8.75 MJ/kg",
        )

    def test_a_comment_that_says_nothing_becomes_nothing(self):
        self.assertEqual(parse_substance_comment("No formula available"), ([], ""))
        self.assertEqual(parse_substance_comment(""), ([], ""))


class UnitsTestCase(unittest.TestCase):
    def test_every_unit_the_method_uses_resolves(self):
        index = build_units_index()
        for shipped, canonical in STEPWISE_UNITS.items():
            with self.subTest(unit=shipped):
                resolved = resolve_unit_notation(shipped, index)
                self.assertIsNotNone(resolved, f"unresolved unit: {shipped}")
                self.assertEqual(resolved[0], canonical)
                self.assertTrue(resolved[1], f"no unit IRI for {shipped}")


class ExtractionTestCase(unittest.TestCase):
    """What the adapter makes of the export."""

    @classmethod
    def setUpClass(cls):
        cls.rows = extract_elementary_flows(FIXTURE, source=KEY)
        cls.by_key = {(row["name"], tuple(row["context"])): row for row in cls.rows}

    def test_a_flow_is_a_name_in_a_compartment(self):
        self.assertEqual(len({row["uuid"] for row in self.rows}), len(self.rows))
        butanol = [row for row in self.rows if row["name"] == "1-Butanol"]
        self.assertEqual(len(butanol), 4)
        self.assertEqual(len({row["uuid"] for row in butanol}), 4)

    def test_the_identifiers_are_the_same_every_time(self):
        """A method file has none, so they are derived -- and a derivation that
        moved between runs would renumber the list on every fetch."""
        self.assertEqual(
            [row["uuid"] for row in extract_elementary_flows(FIXTURE, source=KEY)],
            [row["uuid"] for row in self.rows],
        )

    def test_the_unit_is_the_substance_block_s_and_not_the_factor_row_s(self):
        """The one that would be wrong silently.

        `Carbon dioxide, in air` is inventoried in kilograms and characterised
        per tonne in this fixture, as the radionuclides are inventoried in kBq
        and characterised per Bq in the real file.  Reading the factor row's
        unit would publish the flow a thousandfold out.
        """
        uptake = self.by_key[("Carbon dioxide, in air", ("Raw", "(unspecified)"))]
        self.assertEqual(uptake["unit"], "kg")

    def test_the_vendor_s_own_unit_string_is_what_is_written(self):
        """Canonicalising is the build's job, so the row keeps what it said."""
        occupation = self.by_key[
            (
                "Occupation, accelerated denaturalisation, primary forest "
                "to managed forest",
                ("Raw", "(unspecified)"),
            )
        ]
        self.assertEqual(occupation["unit"], "ha a")
        self.assertEqual(
            self.by_key[
                (
                    "Carbon dioxide in air, as CO2e (GWP aggr timing)",
                    ("Raw", "(unspecified)"),
                )
            ]["unit"],
            "ton",
        )

    def test_the_compartments_go_out_as_the_vendor_wrote_them(self):
        """`Raw` holds ores, land and an uptake from air, and the adapter
        refines none of it: where a compartment's rows belong is stated in
        `context-manual-mapping.json`, where a curator can read it."""
        raw = {
            row["name"]
            for row in self.rows
            if tuple(row["context"]) == ("Raw", "(unspecified)")
        }
        self.assertLessEqual(
            {
                "Copper",
                "Occupation, arable",
                "Carbon dioxide, in air",
                "Wood, hard, standing",
                "Carbon dioxide in air, as CO2e (GWP aggr timing)",
            },
            raw,
        )

    def test_a_registry_number_is_a_list_with_the_padding_gone(self):
        """The list form, because `simapro-lineage-manual-fixes.json` is written
        against it: a scalar would be passed over by every one of its rows."""
        zinc = self.by_key[("Zinc", ("Air", "(unspecified)"))]
        self.assertEqual(zinc["cas_numbers"], ["7440-66-6"])
        self.assertNotIn("cas_number", zinc)

    def test_the_synonyms_and_the_rest_of_the_comment_are_kept_apart(self):
        zinc = self.by_key[("Zinc", ("Air", "(unspecified)"))]
        self.assertEqual(zinc["synonyms"], ["Zinc metal", "Blue powder"])
        self.assertIn("Formula: Zn", zinc["general_comment"])

    def test_the_factors_are_read_and_not_written(self):
        """A category's rows are how its flows are found; publishing them on a
        flow record is a different mechanism from the one this project has.
        Factors reach a build through the manifest's `lcia` block."""
        for row in self.rows:
            self.assertNotIn("lcia_methods", row)
            self.assertNotIn("characterization_factor", row)

    def test_every_row_normalises_into_the_pipeline(self):
        for row in self.rows:
            with self.subTest(name=row["name"]):
                normalised = _normalize_input_flow_record(row)
                self.assertIsNotNone(normalised)
                self.assertEqual(normalised["source"], KEY)
                self.assertTrue(normalised["context"])


class PlacementTestCase(unittest.TestCase):
    """Where the curated rules put the flows the adapter refuses to place.

    The rows a *refusal* takes out are not asked about.  A refused row is in
    the fetch by design -- `excluded_rows_are_in_the_fetch` -- and is removed
    by `apply_additional_flows` before a build ever places it, so a
    compartment rule for it would be a mapping for a compartment no flow has.
    The fixture holds one: `Injuries, fatal`, in the `Social` compartment #173
    emptied.
    """

    @classmethod
    def setUpClass(cls):
        refused = {
            record.uuid
            for record in excluded_source_flows().get(KEY, ())
        }
        cls.rows = [
            row
            for row in extract_elementary_flows(FIXTURE, source=KEY)
            if row["uuid"] not in refused
        ]
        cls.refused = refused
        cls.transformer = DefaultContextMappingTransformer()
        cls.transformer.setup()

    def test_the_fixture_holds_a_refused_row(self):
        # Otherwise the filter above is inert and the class silently stops
        # testing that a refusal takes its compartment with it.
        shipped = {
            row["uuid"]
            for row in extract_elementary_flows(FIXTURE, source=KEY)
        }
        self.assertTrue(shipped & self.refused)

    def _placed(self):
        flows = [
            Flow.from_dict(_normalize_input_flow_record(row)) for row in self.rows
        ]
        by_uuid = {flow.uuid: flow for flow in flows}
        changes = self.transformer.transform(flows)
        return {
            (by_uuid[change.uuid].provided.name, change.new_value.rsplit("/", 1)[-1])
            for change in changes
            if change.field == "context_iri"
        }

    def test_every_row_is_placed(self):
        placed = {name for name, _ in self._placed()}
        self.assertEqual(placed, {row["name"] for row in self.rows})

    def test_the_pre_characterised_rows_leave_the_environment(self):
        """`Methane, as CO2e (GWP aggr timing)` is characterised at 1 where real
        `Methane` is 29.8, so its amount is already the result.  Both the `Raw`
        uptake and the two `Air` emissions are impact scores; the real methane
        beside them is not."""
        placed = self._placed()
        for name in (
            "Carbon dioxide in air, as CO2e (GWP aggr timing)",
            "Carbon dioxide, as CO2e (GWP aggr timing)",
            "Methane, as CO2e (GWP aggr timing)",
        ):
            with self.subTest(name=name):
                self.assertIn((name, "imassc"), placed)
        self.assertIn(("Methane", "envi-air-unkn"), placed)

    def test_land_occupation_leaves_the_ground(self):
        """SimaPro writes the land class in the name and files it with the ores,
        so the name rule is what tells the 41 occupation rows from the 93
        resources -- #52's failure, in another list's spelling."""
        placed = self._placed()
        self.assertIn(("Occupation, arable", "laus-occu"), placed)
        self.assertIn(
            (
                "Occupation, accelerated denaturalisation, primary forest "
                "to managed forest",
                "laus-occu",
            ),
            placed,
        )
        self.assertIn(("Copper", "reso-grou"), placed)

    def test_the_uptake_and_the_timber_are_not_in_the_ground(self):
        placed = self._placed()
        self.assertIn(("Carbon dioxide, in air", "reso-air"), placed)
        self.assertIn(("Wood, hard, standing", "reso-biot"), placed)

    def test_the_curated_rows_name_flows_this_list_ships(self):
        """A per-flow rule is keyed on a UUID, and a UUID here is derived from
        the vendor's fields -- so a row whose name or unit was mistyped states a
        decision about a flow that does not exist.  The real file's 6,064 rows
        are not in the repository; these eight are the ones the fixture holds.
        """
        payload = orjson.loads(MANUAL_MAPPING_FILEPATH.read_bytes())
        stated = {
            row["source_uuid"]: row["source_name"]
            for row in payload["flow_specific_context_mappings"]
            if row["source"] == KEY
        }
        shipped = {row["uuid"]: row["name"] for row in self.rows}
        for uuid_, name in stated.items():
            if uuid_ in shipped:
                with self.subTest(name=name):
                    self.assertEqual(shipped[uuid_], name)
        self.assertTrue(set(stated) & set(shipped))

    def test_the_compartment_rules_cover_the_list(self):
        """`resolve_source_list` refuses a list with no context rules; this is
        the stronger claim, that the rules answer every compartment the method
        actually uses."""
        rules = context_iri_by_source_context(KEY)
        for row in self.rows:
            with self.subTest(context=row["context"]):
                self.assertIn(normalize_context_key(row["context"]), rules)


class MethodIdentityTestCase(unittest.TestCase):
    """The manifest and the export have to be talking about the same method."""

    def test_the_version_is_read_as_the_file_writes_it(self):
        method = _method_block(_blocks(FIXTURE))
        self.assertEqual(method["Name"], STEPWISE_METHOD_NAME)
        self.assertEqual(_method_version(method), "1.09")

    def test_the_registered_version_is_the_method_and_the_export(self):
        """`2006-1.09` has two halves, as BAFU's `2026-v1` does: the method,
        and the export of it that this list is.  Only the second is a version
        the file itself declares, which is what `method_revision` reads."""
        registered = known_source_lists()[KEY].list_version
        self.assertEqual(registered, "2006-1.09")
        self.assertEqual(method_revision(registered), "1.09")
        self.assertEqual(
            stepwise_csv_path(registered).name, "Stepwise2006_v1.09.csv"
        )

    def test_another_release_is_refused_rather_than_read(self):
        """Stepwise is revised, and its flows are published under this version
        with its curated rules keyed to it.  A 1.10 export read under this key
        would republish 1.10's flows as 1.09's."""
        with tempfile.TemporaryDirectory() as directory:
            source = SourceList(
                list_name="stepwise",
                list_version="2006-1.10",
                flows_path=Path(directory) / "flows.json",
                flow_iri_prefix="https://vocab.brightway.one/stepwise/2006-1.10/flow/",
            )
            with mock.patch(
                "brightway_flows.filesystem.stepwise_csv_path",
                return_value=FIXTURE,
            ):
                with self.assertRaises(ValueError) as caught:
                    fetch(source)
        self.assertIn("1.09", str(caught.exception))
        self.assertFalse(source.flows_path.exists())


if __name__ == "__main__":
    unittest.main()
