"""EF 3.1 as the ecoinvent Centre implements it, and what is checked at ingest.

The second implementation of a method this list holds, and the first that is not
the method's own publisher's. Every number below is measured against
`LCIA Implementation 3.12.xlsx` and the 9,850 ecoinvent 3.12 biosphere flows this
project has already extracted, and the point of asserting them in the adapter
rather than recording them once is that each is a fact about a release:

* the flow triple is the workbook's only name for a flow, and it resolves
  exactly -- 7,960 of 7,960, with no ecoinvent flow sharing a triple with
  another;
* `EF v3.1 no LT` states no row and no number `EF v3.1` does not, and the 225
  rows it drops are all in `air / low population density, long-term` (201) and
  `water / ground-, long-term` (24). That is what makes it a subtraction rather
  than a second implementation, and why it is read and not published;
* the 25 categories it declares are exactly the 25 the crosswalk pairs with EF
  3.1's. A release that renames one would leave a crosswalk row pairing a name
  nobody publishes.

The workbook itself is not in the repository and a fresh worktree has not fetched
it, so the cases that need one build a small stand-in. The two at the end read
what a real fetch wrote, and skip where nothing has.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.lcia.crosswalk import ef_method
from brightway_flows.integrations.ecoinvent_lcia import (
    FACTOR_COLUMNS,
    FACTORS_SCHEMA_VERSION,
    INDICATOR_COLUMNS,
    EcoinventLciaError,
    FlowKey,
    check_against_crosswalk,
    check_long_term,
    flow_index,
    load_factors,
    read_categories,
    read_factors,
    resolve,
)
from brightway_flows.sources import LciaMethodSpec, known_source_lists

METHOD = LciaMethodSpec(name="M", no_long_term="M no LT")

#: What ecoinvent's workbook calls the method this list ingests, read from the
#: method file rather than spelled here: it is the implementation's own
#: statement of which workbook method its factors are.
ECOINVENT_METHOD = ef_method().implementation("ecoinvent-centre").factors.stated_method


class _Sheet:
    def __init__(self, rows):
        self._rows = rows

    def iter_rows(self, values_only=False):  # noqa: ARG002 - openpyxl's signature
        return iter(self._rows)


class _Workbook:
    """As much of an `openpyxl` workbook as the reader touches."""

    def __init__(self, **sheets):
        self._sheets = sheets

    @property
    def sheetnames(self):
        return list(self._sheets)

    def __getitem__(self, name):
        return _Sheet(self._sheets[name])


def _workbook(indicators=(), factors=()):
    return _Workbook(
        **{
            "Indicators": [INDICATOR_COLUMNS, *indicators],
            "CFs": [FACTOR_COLUMNS, *factors],
        }
    )


#: One category and two flows, in both methods, with a long-term row only in the
#: full one -- the shape of the real workbook in miniature.
INDICATORS = (
    ("M", "acidification", "accumulated exceedance (AE)", "mol H+-Eq"),
    ("M no LT", "acidification no LT", "accumulated exceedance (AE) no LT", "mol H+-Eq"),
)
FACTORS = (
    ("M", "acidification", "AE", "Ammonia", "air", "unspecified", 3.02),
    ("M", "acidification", "AE", "Ammonia", "air", "low population density, long-term", 1.5),
    ("M no LT", "acidification no LT", "AE no LT", "Ammonia", "air", "unspecified", 3.02),
)
FLOWS = [
    {"uuid": "flow-1", "name": "Ammonia", "context": ["air", "unspecified"]},
    {
        "uuid": "flow-2",
        "name": "Ammonia",
        "context": ["air", "low population density, long-term"],
    },
]


class ReadingTheSheetsTestCase(unittest.TestCase):
    def test_a_missing_sheet_is_named(self):
        with self.assertRaises(EcoinventLciaError) as caught:
            read_categories(_Workbook(CFs=[FACTOR_COLUMNS]), "M")
        self.assertIn("Indicators", str(caught.exception))

    def test_columns_that_have_moved_are_refused(self):
        moved = _Workbook(Indicators=[("Method", "Indicator", "Category", "Unit")])
        with self.assertRaises(EcoinventLciaError):
            read_categories(moved, "M")

    def test_the_categories_of_one_method(self):
        categories = read_categories(_workbook(INDICATORS, FACTORS), "M")
        self.assertEqual([c.name for c in categories], ["acidification"])
        self.assertEqual(categories[0].methodology, "M")
        self.assertEqual(categories[0].impact_indicator, "accumulated exceedance (AE)")
        self.assertEqual(categories[0].reference_unit, "mol H+-Eq")

    def test_a_category_with_no_uuid_says_so(self):
        """The workbook states no identifier for a category, and `None` is that
        absence rather than a value."""
        categories = read_categories(_workbook(INDICATORS, FACTORS), "M")
        self.assertIsNone(categories[0].uuid)

    def test_a_method_the_workbook_does_not_declare_raises(self):
        with self.assertRaises(EcoinventLciaError):
            read_categories(_workbook(INDICATORS, FACTORS), "ReCiPe")

    def test_a_category_declared_twice_raises(self):
        twice = (*INDICATORS, ("M", "acidification", "AE again", "mol H+-Eq"))
        with self.assertRaises(EcoinventLciaError):
            read_categories(_workbook(twice, FACTORS), "M")

    def test_the_factors_of_both_methods_in_one_pass(self):
        rows = read_factors(_workbook(INDICATORS, FACTORS), ["M", "M no LT"])
        self.assertEqual(len(rows["M"]), 2)
        self.assertEqual(len(rows["M no LT"]), 1)
        key = (FlowKey("Ammonia", "air", "unspecified"), "acidification")
        self.assertEqual(rows["M"][key], 3.02)

    def test_two_numbers_for_one_flow_and_category_raises(self):
        """One factor per flow and category; a workbook that breaks that is not
        something to reconcile here."""
        doubled = (*FACTORS, FACTORS[0][:-1] + (9.9,))
        with self.assertRaises(EcoinventLciaError):
            read_factors(_workbook(INDICATORS, doubled), ["M"])

    def test_a_factor_that_is_not_a_number_raises(self):
        text = (FACTORS[0][:-1] + ("n/a",),)
        with self.assertRaises(EcoinventLciaError):
            read_factors(_workbook(INDICATORS, text), ["M"])

    def test_a_method_with_no_factors_raises(self):
        with self.assertRaises(EcoinventLciaError):
            read_factors(_workbook(INDICATORS, FACTORS), ["ReCiPe"])


class TheFlowKeyIsTheJoinTestCase(unittest.TestCase):
    def test_the_triple_names_one_flow(self):
        index = flow_index(FLOWS)
        self.assertEqual(index[FlowKey("Ammonia", "air", "unspecified")], "flow-1")

    def test_two_flows_sharing_a_triple_raises(self):
        """The workbook has no other way to name a flow, so a shared triple is a
        factor that could belong to either."""
        shared = [*FLOWS, {**FLOWS[0], "uuid": "flow-3"}]
        with self.assertRaises(EcoinventLciaError):
            flow_index(shared)

    def test_a_flow_with_no_subcompartment_raises(self):
        with self.assertRaises(EcoinventLciaError):
            flow_index([{"uuid": "f", "name": "Ammonia", "context": ["air"]}])

    def test_every_row_becomes_a_record(self):
        rows = read_factors(_workbook(INDICATORS, FACTORS), ["M"])["M"]
        categories = {
            c.name: c for c in read_categories(_workbook(INDICATORS, FACTORS), "M")
        }
        factors, counts = resolve(
            rows=rows, categories=categories, index=flow_index(FLOWS)
        )
        self.assertEqual(counts, {"acidification": 2})
        self.assertEqual({f.flow_uuid for f in factors}, {"flow-1", "flow-2"})
        self.assertEqual(sorted(f.amount for f in factors), [1.5, 3.02])
        self.assertTrue(all(f.category is categories["acidification"] for f in factors))

    def test_a_row_naming_no_extracted_flow_raises(self):
        rows = read_factors(_workbook(INDICATORS, FACTORS), ["M"])["M"]
        categories = {
            c.name: c for c in read_categories(_workbook(INDICATORS, FACTORS), "M")
        }
        with self.assertRaises(EcoinventLciaError):
            resolve(rows=rows, categories=categories, index=flow_index(FLOWS[:1]))

    def test_a_row_naming_an_undeclared_category_raises(self):
        rows = read_factors(_workbook(INDICATORS, FACTORS), ["M"])["M"]
        with self.assertRaises(EcoinventLciaError):
            resolve(rows=rows, categories={}, index=flow_index(FLOWS))


class TheNoLongTermSiblingIsASubtractionTestCase(unittest.TestCase):
    """Four ways it could be more than one, each of them a failed fetch."""

    def _rows(self, factors=FACTORS):
        return read_factors(_workbook(INDICATORS, factors), ["M", "M no LT"])

    def test_what_it_drops_is_reported_by_compartment(self):
        rows = self._rows()
        check = check_long_term(
            method=METHOD, rows=rows["M"], sibling_rows=rows["M no LT"]
        )
        self.assertEqual(check.rows, 2)
        self.assertEqual(check.rows_in_sibling, 1)
        self.assertEqual(check.dropped, 1)
        self.assertEqual(
            check.dropped_by_compartment,
            (("air", "low population density, long-term", 1),),
        )

    def test_a_row_only_the_sibling_states_raises(self):
        extra = (
            *FACTORS,
            ("M no LT", "acidification no LT", "AE no LT", "Ozone", "air",
             "unspecified", 1.0),
        )
        rows = self._rows(extra)
        with self.assertRaises(EcoinventLciaError) as caught:
            check_long_term(method=METHOD, rows=rows["M"], sibling_rows=rows["M no LT"])
        self.assertIn("minus its long-term rows", str(caught.exception))

    def test_a_number_that_differs_raises(self):
        """This is the one that would make it a second implementation."""
        moved = list(FACTORS)
        moved[2] = moved[2][:-1] + (3.5,)
        rows = self._rows(tuple(moved))
        with self.assertRaises(EcoinventLciaError) as caught:
            check_long_term(method=METHOD, rows=rows["M"], sibling_rows=rows["M no LT"])
        self.assertIn("subtraction", str(caught.exception))

    def test_a_dropped_row_outside_a_long_term_compartment_raises(self):
        dropped = (
            *FACTORS,
            ("M", "acidification", "AE", "Ozone", "air", "unspecified", 1.0),
        )
        rows = self._rows(dropped)
        with self.assertRaises(EcoinventLciaError) as caught:
            check_long_term(method=METHOD, rows=rows["M"], sibling_rows=rows["M no LT"])
        self.assertIn("long-term", str(caught.exception))

    def test_a_sibling_category_without_the_suffix_raises(self):
        """The suffix is the only thing pairing a row here with a row there."""
        unsuffixed = (
            FACTORS[0],
            ("M no LT", "acidification", "AE", "Ammonia", "air", "unspecified", 3.02),
        )
        rows = self._rows(unsuffixed)
        with self.assertRaises(EcoinventLciaError) as caught:
            check_long_term(method=METHOD, rows=rows["M"], sibling_rows=rows["M no LT"])
        self.assertIn("no LT", str(caught.exception))


class TheCrosswalkAndTheWorkbookAgreeTestCase(unittest.TestCase):
    """The half of the crosswalk that needed a reader for the workbook."""

    def _categories(self, names):
        return tuple(
            read_categories(
                _workbook(
                    tuple((ECOINVENT_METHOD, name, "i", "u") for name in names), ()
                ),
                ECOINVENT_METHOD,
            )
        )

    def test_the_crosswalks_own_names_pass(self):
        check_against_crosswalk(
            self._categories(sorted(ef_method().by_stated_name("ecoinvent-centre"))), method=ECOINVENT_METHOD
        )

    def test_a_renamed_category_raises(self):
        names = sorted(ef_method().by_stated_name("ecoinvent-centre"))
        names[0] = names[0] + " (renamed)"
        with self.assertRaises(EcoinventLciaError) as caught:
            check_against_crosswalk(self._categories(names), method=ECOINVENT_METHOD)
        self.assertIn("A method file is what pairs them", str(caught.exception))

    def test_another_method_is_not_checked_against_it(self):
        """The crosswalk covers one method; ReCiPe's categories are not its
        business, and the tables hold them without a row here."""
        check_against_crosswalk(self._categories(["climate change"]), method="ReCiPe")


class TheFileRoundTripsTestCase(unittest.TestCase):
    def test_what_was_written_comes_back_as_records(self):
        payload = {
            "schema_version": FACTORS_SCHEMA_VERSION,
            "methods": [
                {
                    "method": "M",
                    "categories": [
                        {"category": "acidification", "indicator": "AE", "unit": "u"}
                    ],
                    "factors": [
                        {
                            "flow_uuid": "flow-1",
                            "category": "acidification",
                            "amount": 3.02,
                        }
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "factors.json"
            path.write_bytes(orjson.dumps(payload))
            factors = load_factors(path)
        self.assertEqual(len(factors["M"]), 1)
        self.assertEqual(factors["M"][0].amount, 3.02)
        self.assertEqual(factors["M"][0].category.name, "acidification")
        self.assertEqual(factors["M"][0].category.methodology, "M")

    def test_a_file_of_another_version_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "factors.json"
            path.write_bytes(orjson.dumps({"schema_version": 99, "methods": []}))
            with self.assertRaises(EcoinventLciaError):
                load_factors(path)


class TheManifestDeclaresItTestCase(unittest.TestCase):
    def test_ecoinvent_3_12_declares_an_lcia_block(self):
        source = known_source_lists()["ecoinvent-3.12"]
        self.assertIsNotNone(source.lcia)
        self.assertEqual(
            [method.name for method in source.lcia.methods], [ECOINVENT_METHOD]
        )
        self.assertEqual(source.lcia.methods[0].no_long_term, "EF v3.1 no LT")
        self.assertEqual(
            source.lcia.factors_path.name, "ecoinvent-3.12-lcia-factors.json"
        )

    def test_which_lists_declare_one(self):
        """EF 3.1's factors are in its own flow records, and no ecoinvent
        release but 3.12 publishes an implementation.  BAFU's manifest declares
        one because its openLCA distribution ships GreenDelta's package -- the
        artifact is BAFU's, the implementation is not, which is what
        `implemented_by` is there to keep apart.

        Stepwise 2006 declares its own publisher's, and is the one entry here
        that is not an implementation of EF 3.1: the export is the method, so
        the list that carries the flows carries the factors too (#346)."""
        declared = {
            key: source.lcia.implemented_by
            for key, source in known_source_lists().items()
            if source.lcia is not None
        }
        self.assertEqual(
            declared,
            {
                "ecoinvent-3.12": "ecoinvent Centre",
                "bafu-2026-v1": "GreenDelta",
                "stepwise-2006-1.09": "2.-0 LCA consultants",
            },
        )

    def test_the_adapter_it_names_is_importable(self):
        from brightway_flows.sources import load_adapter

        source = known_source_lists()["ecoinvent-3.12"]
        self.assertTrue(callable(load_adapter(source, dotted_path=source.lcia.adapter)))


class WhatAFetchWroteTestCase(unittest.TestCase):
    """The measured numbers, against a file a real fetch produced.

    Skipped where nothing has fetched: the workbook is 40 MB behind ecoinvent's
    login and no test may download it.
    """

    def setUp(self):
        source = known_source_lists()["ecoinvent-3.12"]
        self.path = source.lcia.factors_path
        if not self.path.exists():
            self.skipTest(f"{self.path} has not been fetched here")
        self.payload = orjson.loads(self.path.read_bytes())
        self.method = self.payload["methods"][0]

    def test_the_counts(self):
        self.assertEqual(self.method["method"], ECOINVENT_METHOD)
        self.assertEqual(len(self.method["categories"]), 25)
        self.assertEqual(self.method["factor_count"], 27_415)
        self.assertEqual(self.method["flow_count"], 7_960)

    def test_the_long_term_check(self):
        check = self.method["long_term_check"]
        self.assertEqual(check["checked_against"], "EF v3.1 no LT")
        self.assertEqual(check["rows_in_sibling"], 27_190)
        self.assertEqual(check["rows_dropped"], 225)
        self.assertEqual(
            [(row["compartment"], row["subcompartment"], row["rows"])
             for row in check["dropped_by_compartment"]],
            [
                ("air", "low population density, long-term", 201),
                ("water", "ground-, long-term", 24),
            ],
        )

    def test_the_categories_are_the_crosswalks(self):
        self.assertEqual(
            {row["category"] for row in self.method["categories"]},
            set(ef_method().by_stated_name("ecoinvent-centre")),
        )

    def test_every_factor_reaches_a_flow_and_a_category(self):
        factors = load_factors(self.path)[ECOINVENT_METHOD]
        self.assertEqual(len(factors), 27_415)
        self.assertTrue(all(factor.flow_uuid for factor in factors))
        self.assertEqual(
            {factor.category.name for factor in factors}, set(ef_method().by_stated_name("ecoinvent-centre"))
        )

    def test_no_no_lt_category_is_published(self):
        self.assertEqual(
            [row["category"] for row in self.method["categories"] if "no LT" in row["category"]],
            [],
        )


if __name__ == "__main__":
    unittest.main()
