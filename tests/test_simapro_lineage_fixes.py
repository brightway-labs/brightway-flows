"""The corrections a naming lineage needs, written once (#147).

SimaPro-shaped lists inherit ecoinvent 2's data habits along with its
spellings, and three of them turned up in BAFU 2026 v1 and Stepwise 2006 before
either was looked at for them: the element's registry number on `Uranium-238`'s
activity rows, a resource's energy content written into its name with the row
still in kilograms, and `Carbon dioxide, in air` unqualified.
`simapro-lineage-manual-fixes.json` corrects them for every list whose
`simapro_origin` is true, and for a lookup query sent with the flag.

Both halves of every entry, per the repo's discipline for a rule that refines
something: what it changes, on rows shaped the way the adapters shape them, and
the rows it must leave alone -- the isotope row that ships no number, the
element's own rows, the carbon dioxide row that carries no registry number.
"""

from __future__ import annotations

import unittest

import orjson

from brightway_flows.filesystem import SIMAPRO_LINEAGE_FIXES_FILEPATH
from brightway_flows.lookup.query import FlowQuery, prepare_query
from brightway_flows.manual_fixes import UNIT_CONVERSION_KEY, apply_manual_fixes
from brightway_flows.simapro_names import LINEAGE_FIX_STEP, PREPARATION_STEPS

URANIUM = "7440-61-1"
URANIUM_238 = "24678-82-8"
CARBON_DIOXIDE = "124-38-9"


def _apply(rows):
    return apply_manual_fixes(rows, SIMAPRO_LINEAGE_FIXES_FILEPATH, label="test")


def _alt_labels(row) -> list[str]:
    return [
        item.get("@value") if isinstance(item, dict) else item
        for item in row.get("altLabel") or []
    ]


class TheFileTestCase(unittest.TestCase):
    def test_every_entry_matches_by_name_and_spells_registry_numbers_as_a_list(self):
        """A lineage has no uuids, and the file is written against the shape
        the project's own adapters emit."""
        fixes = orjson.loads(SIMAPRO_LINEAGE_FIXES_FILEPATH.read_bytes())["fixes"]
        self.assertTrue(fixes)
        for fix in fixes:
            with self.subTest(fix=fix.get("match")):
                self.assertIn("name", fix["match"])
                self.assertNotIn("uuid", fix)
                self.assertNotIn("cas_number", fix["match"])
                self.assertNotEqual(fix.get("field"), "cas_number")
                self.assertTrue(str(fix.get("comment") or "").strip())

    def test_the_lookup_reports_the_step_in_the_vocabulary_a_row_reports_in(self):
        self.assertIn(LINEAGE_FIX_STEP, PREPARATION_STEPS)


class TheIsotopeTakesItsOwnNumberTestCase(unittest.TestCase):
    """BAFU's shape: `cas_numbers` as a list, activity in Bq or kBq."""

    def _rows(self):
        return [
            {"uuid": "a", "name": "Uranium-238", "cas_numbers": [URANIUM], "unit": "Bq"},
            {"uuid": "b", "name": "Uranium-238", "cas_numbers": [URANIUM], "unit": "kBq"},
            {"uuid": "c", "name": "Uranium-238", "unit": "kBq"},
            {"uuid": "d", "name": "Uranium", "cas_numbers": [URANIUM], "unit": "kg"},
            {"uuid": "e", "name": "Uranium-235", "cas_numbers": ["15117-96-1"], "unit": "kBq"},
        ]

    def test_rows_carrying_the_element_s_number_take_the_isotope_s(self):
        rows = _apply(self._rows())
        by_uuid = {row["uuid"]: row.get("cas_numbers") for row in rows}
        self.assertEqual(by_uuid["a"], [URANIUM_238])
        self.assertEqual(by_uuid["b"], [URANIUM_238])

    def test_the_row_shipped_without_a_number_is_left_without_one(self):
        """BAFU's fifteenth row already reaches the isotope on its name; giving
        it a number it did not ship is not a correction."""
        rows = _apply(self._rows())
        self.assertNotIn("cas_numbers", {row["uuid"]: row for row in rows}["c"])

    def test_the_element_and_the_other_isotope_keep_their_numbers(self):
        rows = _apply(self._rows())
        by_uuid = {row["uuid"]: row.get("cas_numbers") for row in rows}
        self.assertEqual(by_uuid["d"], [URANIUM])
        self.assertEqual(by_uuid["e"], ["15117-96-1"])


class UraniumAsEnergyTestCase(unittest.TestCase):
    """Stepwise's shape, once its adapter emits `cas_numbers`."""

    CASES = (("451", 451000), ("560", 560000), ("2291", 2291000))

    def _row(self, gj: str):
        return {
            "uuid": gj, "name": f"Uranium, {gj} GJ per kg",
            "cas_numbers": [URANIUM], "unit": "kg",
        }

    def test_the_row_is_rebased_onto_megajoules_by_the_number_in_its_name(self):
        for gj, factor in self.CASES:
            with self.subTest(gj=gj):
                (row,) = _apply([self._row(gj)])
                self.assertEqual(row["unit"], "MJ")
                self.assertEqual(row[UNIT_CONVERSION_KEY]["factor"], float(factor))
                self.assertEqual(row[UNIT_CONVERSION_KEY]["source_unit"], "kg")
                self.assertEqual(row[UNIT_CONVERSION_KEY]["target_unit"], "MJ")

    def test_the_row_is_named_for_the_substance_and_keeps_its_spelling(self):
        for gj, _factor in self.CASES:
            with self.subTest(gj=gj):
                (row,) = _apply([self._row(gj)])
                self.assertEqual(row["name"], "Uranium")
                self.assertIn(f"Uranium, {gj} GJ per kg", _alt_labels(row))
                self.assertEqual(row["cas_numbers"], [URANIUM])

    def test_the_element_s_plain_row_is_not_rebased(self):
        """The other half: `Uranium` in kilograms is a mass row the list already
        converts by its own rule, and a fix keyed on the energy names must not
        reach it."""
        (row,) = _apply([{"uuid": "u", "name": "Uranium", "cas_numbers": [URANIUM], "unit": "kg"}])
        self.assertEqual(row["unit"], "kg")
        self.assertNotIn(UNIT_CONVERSION_KEY, row)


class CarbonDioxideInAirTestCase(unittest.TestCase):
    def test_a_row_with_the_registry_number_is_read_as_biogenic(self):
        (row,) = _apply([{"uuid": "c", "name": "Carbon dioxide, in air", "cas_numbers": [CARBON_DIOXIDE], "unit": "kg"}])
        self.assertEqual(row["name"], "Carbon dioxide, biogenic, in air")
        self.assertIn("Carbon dioxide, in air", _alt_labels(row))

    def test_a_row_without_one_is_left_to_its_own_list_s_override(self):
        """BAFU ships the row with no number, and the qualifier is only ever
        read beside one; its override places the row, and a rename here would
        change the spelling the build records for it for nothing."""
        (row,) = _apply([{"uuid": "c", "name": "Carbon dioxide, in air", "unit": "kg"}])
        self.assertEqual(row["name"], "Carbon dioxide, in air")


class AppliedTwiceTestCase(unittest.TestCase):
    """The base list applies its fixes at extract and again as the transform
    reads the rows back; a lineage file may one day be applied the same way."""

    def test_a_second_pass_changes_nothing(self):
        rows = [
            {"uuid": "a", "name": "Uranium-238", "cas_numbers": [URANIUM], "unit": "Bq"},
            {"uuid": "b", "name": "Uranium, 451 GJ per kg", "cas_numbers": [URANIUM], "unit": "kg"},
            {"uuid": "c", "name": "Carbon dioxide, in air", "cas_numbers": [CARBON_DIOXIDE], "unit": "kg"},
        ]
        _apply(rows)
        once = [dict(row) for row in rows]
        _apply(rows)
        self.assertEqual(rows, once)


class TheLookupAppliesTheSameFileTestCase(unittest.TestCase):
    """A query answers the way a merged row would, or the lookup is not
    reproducing the build it claims to."""

    def test_uranium_as_energy_is_prepared_as_uranium_in_megajoules(self):
        prepared = prepare_query(FlowQuery(
            name="Uranium, 451 GJ per kg", context=["Raw", "in ground"],
            cas=URANIUM, unit="kg", simapro_origin=True,
        ))
        self.assertEqual(prepared.query.name, "Uranium")
        self.assertEqual(prepared.query.unit, "MJ")
        self.assertIn("Uranium, 451 GJ per kg", prepared.query.synonyms)
        self.assertEqual(prepared.preparation.steps, (LINEAGE_FIX_STEP,))
        self.assertEqual(prepared.preparation.shipped_name, "Uranium, 451 GJ per kg")
        self.assertEqual(prepared.unit_conversion["factor"], 451000.0)
        self.assertEqual(prepared.unit_conversion["target_unit"], "MJ")

    def test_the_isotope_query_takes_the_isotope_s_number(self):
        prepared = prepare_query(FlowQuery(
            name="Uranium-238", context=["Air", "(unspecified)"],
            cas=URANIUM, unit="kBq", simapro_origin=True,
        ))
        self.assertEqual(prepared.query.cas, URANIUM_238)
        self.assertEqual(prepared.query.name, "Uranium-238")
        self.assertEqual(prepared.preparation.steps, (LINEAGE_FIX_STEP,))
        self.assertIsNone(prepared.unit_conversion)

    def test_a_query_nothing_names_is_untouched(self):
        query = FlowQuery(name="Benzene", cas="71-43-2", unit="kg", simapro_origin=True)
        prepared = prepare_query(query)
        self.assertIs(prepared.query, query)
        self.assertEqual(prepared.preparation.steps, ())

    def test_without_the_flag_the_row_belongs_to_whoever_wrote_it(self):
        query = FlowQuery(name="Uranium-238", cas=URANIUM, unit="kBq", simapro_origin=False)
        prepared = prepare_query(query)
        self.assertEqual(prepared.query.cas, URANIUM)
        self.assertEqual(prepared.preparation.steps, ())

    def test_a_split_and_a_fix_on_one_row_are_both_reported(self):
        prepared = prepare_query(FlowQuery(
            name="Uranium, 451 GJ per kg/kg", cas=URANIUM, unit="kg", simapro_origin=True,
        ))
        self.assertEqual(prepared.query.name, "Uranium")
        self.assertEqual(prepared.preparation.steps, ("unit-suffix", LINEAGE_FIX_STEP))
        self.assertEqual(prepared.preparation.shipped_name, "Uranium, 451 GJ per kg/kg")
        self.assertIn("Uranium, 451 GJ per kg", prepared.query.synonyms)


class TetramethylAmmoniumHydroxideTestCase(unittest.TestCase):
    """The fourth habit, and the first to earn its place by recurrence rather
    than by being found in two lists at once: BAFU shipped `Tetramethyl
    ammonium hydroxide` with no registry number and was given 75-59-2 in its
    own file (#103); AGRIBALYSE then shipped the same spelling, bare of the
    same number, and minted the same duplicate (#190). One entry here now
    corrects both."""

    TMAH = "75-59-2"

    def test_a_row_shipped_without_a_number_is_given_the_substance_s(self):
        for unit, context in (("kg", ["emissions to air", "high. pop."]), ("kg", ["Emissions to air", "high. pop."])):
            with self.subTest(context=context):
                (row,) = _apply([{"uuid": "t", "name": "Tetramethyl ammonium hydroxide", "context": context, "unit": unit}])
                self.assertEqual(row["cas_numbers"], [self.TMAH])
                self.assertEqual(row["name"], "Tetramethyl ammonium hydroxide")

    def test_the_one_word_spelling_is_not_this_fix_s_business(self):
        """A row already spelled the way the list publishes it reaches the
        substance on its name; the fix is keyed on the two-word spelling and
        must not write a number onto a row that did not ship one under it."""
        (row,) = _apply([{"uuid": "t", "name": "Tetramethylammonium hydroxide", "unit": "kg"}])
        self.assertNotIn("cas_numbers", row)

    def test_bafu_s_own_file_no_longer_carries_the_entry(self):
        """Moved, not copied: two files writing one number onto one row would
        be two decisions to keep in step."""
        from brightway_flows.sources import known_source_lists

        fixes = orjson.loads(
            known_source_lists()["bafu-2026-v1"].manual_fixes_path.read_bytes()
        )["fixes"]
        self.assertFalse(
            [fix for fix in fixes if fix["match"].get("name") == "Tetramethyl ammonium hydroxide"]
        )


if __name__ == "__main__":
    unittest.main()
