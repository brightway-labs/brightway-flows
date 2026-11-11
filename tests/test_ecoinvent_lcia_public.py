"""EF 3.1 as the ecoinvent Centre implements it, read from the file ecoinvent
publishes at github.com/ecoinvent/lcia, and what is checked at ingest.

The 3.12 implementation used to be read from `LCIA Implementation 3.12.xlsx`,
which sits behind ecoinvent's login and may not be redistributed.  The mapped
file ecoinvent publishes states the same EF v3.1 factors -- 27,415 of 27,415, at
the same numbers to the last digit the CSV prints -- under CC BY-NC 4.0, so the
manifest reads that instead and the implementation says so on every category
row.  Every number below is measured against `EF v3.1_mapped_3.12.csv` at
commit `1aed01c5` and the 9,850 ecoinvent 3.12 biosphere flows this project
extracted, and each is asserted in the adapter because each is a fact about a
release:

* the file names a flow by ecoinvent's UUID, and every UUID that carries a
  number is an extracted flow under the same name, compartment and
  subcompartment -- 7,960 of 7,960;
* 3,212 cells are written as `0.0` where the workbook has no row, and they are
  dropped and counted rather than published as a factor of zero;
* the 25 category columns are exactly the 25 the crosswalk pairs with EF 3.1's.

The file is 3 MB and public, but no test downloads it: the cases that need one
build a small stand-in, and the ones at the end read what a real fetch wrote
and skip where nothing has.
"""

from __future__ import annotations

import csv
import math
import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.lcia.crosswalk import ef_method
from brightway_flows.integrations.ecoinvent_lcia import (
    FACTORS_SCHEMA_VERSION,
    FlowKey,
    load_factors,
)
from brightway_flows.integrations.ecoinvent_lcia_public import (
    LEADING_COLUMNS,
    LICENCE_NAME,
    LICENCE_URL,
    PUBLISHED_METHOD_FILES,
    REPOSITORY,
    EcoinventPublicLciaError,
    factors_payload,
    flows_by_uuid,
    method_payload,
    published_file_for,
    read_mapped_file,
    resolve,
)
from brightway_flows.lcia.categories import impact_categories_for
from brightway_flows.sources import known_source_lists

ECOINVENT_PREVIOUS = "ecoinvent-centre"
ECOINVENT_CURRENT = "ecoinvent-centre-3-13"
METHOD = "EF v3.1"

ACIDIFICATION = "acidification|accumulated exceedance (AE)"
CLIMATE = "climate change|global warming potential (GWP100)"
HEADER = (*LEADING_COLUMNS, ACIDIFICATION, CLIMATE)


def _row(uuid, name, compartment, subcompartment, *amounts):
    """One row in the file's shape: the triple in its columns, the rest blank."""
    leading = [""] * len(LEADING_COLUMNS)
    leading[0] = uuid
    leading[1] = name
    leading[5] = compartment
    leading[6] = subcompartment
    return [*leading, *amounts]


ROWS = (
    _row("flow-1", "Ammonia", "air", "unspecified", "3.02", ""),
    _row("flow-2", "Carbon dioxide, fossil", "air", "unspecified", "", "1.0"),
    _row("flow-3", "Water", "water", "unspecified", "0.0", "0.0"),
)
FLOWS = [
    {"uuid": "flow-1", "name": "Ammonia", "context": ["air", "unspecified"]},
    {"uuid": "flow-2", "name": "Carbon dioxide, fossil", "context": ["air", "unspecified"]},
    {"uuid": "flow-3", "name": "Water", "context": ["water", "unspecified"]},
]


class _FileTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())

    def write(self, rows=ROWS, header=HEADER, name="EF v3.1_mapped_3.12.csv"):
        path = self.directory / name
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        return path

    def read(self, **kwargs):
        return read_mapped_file(self.write(**kwargs), method=METHOD)


class ReadingTheFileTestCase(_FileTestCase):
    def test_the_categories_come_from_the_headings(self):
        file = self.read()
        self.assertEqual(
            [(c.name, c.impact_indicator) for c in file.categories],
            [
                ("acidification", "accumulated exceedance (AE)"),
                ("climate change", "global warming potential (GWP100)"),
            ],
        )
        self.assertEqual({c.methodology for c in file.categories}, {METHOD})

    def test_a_category_states_no_unit_and_no_uuid(self):
        """The file has the flow's unit and the method flow's, neither of which
        is the category's; `None` is that absence, as it is in the workbook."""
        file = self.read()
        self.assertEqual({c.reference_unit for c in file.categories}, {None})
        self.assertEqual({c.uuid for c in file.categories}, {None})

    def test_the_numbers_of_each_row(self):
        file = self.read()
        self.assertEqual(
            [(row.flow_uuid, row.amounts) for row in file.rows],
            [
                ("flow-1", {"acidification": 3.02}),
                ("flow-2", {"climate change": 1.0}),
                ("flow-3", {}),
            ],
        )
        self.assertEqual(file.rows[0].key, FlowKey("Ammonia", "air", "unspecified"))
        self.assertEqual(file.factor_count, 2)

    def test_a_zero_cell_is_dropped_and_counted(self):
        """The workbook states no row where the file writes `0.0`; a zero kept
        would be a factor the ecoinvent Centre never stated."""
        file = self.read()
        self.assertEqual(file.zero_cells, 2)
        self.assertEqual(file.rows[2].amounts, {})

    def test_columns_that_have_moved_are_refused(self):
        header = (HEADER[1], HEADER[0], *HEADER[2:])
        with self.assertRaises(EcoinventPublicLciaError) as caught:
            self.read(header=header)
        self.assertIn("elementary_flow_id", str(caught.exception))

    def test_a_heading_without_the_separator_is_refused(self):
        with self.assertRaises(EcoinventPublicLciaError) as caught:
            self.read(header=(*LEADING_COLUMNS, "acidification"), rows=[_row("f", "A", "air", "x", "1")])
        self.assertIn("category|indicator", str(caught.exception))

    def test_a_category_stated_twice_is_refused(self):
        header = (*LEADING_COLUMNS, ACIDIFICATION, "acidification|another indicator")
        with self.assertRaises(EcoinventPublicLciaError):
            self.read(header=header)

    def test_a_file_with_no_category_columns_is_refused(self):
        with self.assertRaises(EcoinventPublicLciaError):
            self.read(header=LEADING_COLUMNS, rows=[_row("f", "A", "air", "x")])

    def test_a_flow_with_two_rows_is_refused(self):
        rows = (*ROWS, _row("flow-1", "Ammonia", "air", "unspecified", "", "2.0"))
        with self.assertRaises(EcoinventPublicLciaError) as caught:
            self.read(rows=rows)
        self.assertIn("flow-1", str(caught.exception))

    def test_a_row_with_no_identifier_is_refused(self):
        with self.assertRaises(EcoinventPublicLciaError):
            self.read(rows=(_row("", "Ammonia", "air", "unspecified", "1", ""),))

    def test_a_cell_that_is_not_a_number_is_refused(self):
        with self.assertRaises(EcoinventPublicLciaError) as caught:
            self.read(rows=(_row("f", "A", "air", "x", "n/a", ""),))
        self.assertIn("'n/a'", str(caught.exception))

    def test_a_cell_that_is_not_finite_is_refused(self):
        with self.assertRaises(EcoinventPublicLciaError):
            self.read(rows=(_row("f", "A", "air", "x", "inf", ""),))

    def test_a_row_of_the_wrong_width_is_refused(self):
        with self.assertRaises(EcoinventPublicLciaError) as caught:
            self.read(rows=(_row("f", "A", "air", "x", "1"),))
        self.assertIn("line 2", str(caught.exception))

    def test_an_empty_file_is_refused(self):
        path = self.directory / "empty.csv"
        path.write_text("", encoding="utf-8")
        with self.assertRaises(EcoinventPublicLciaError):
            read_mapped_file(path, method=METHOD)

    def test_a_header_with_no_rows_is_refused(self):
        with self.assertRaises(EcoinventPublicLciaError):
            self.read(rows=())


class ResolvingAgainstTheExtractedFlowsTestCase(_FileTestCase):
    def test_each_row_reaches_the_flow_it_names(self):
        factors, counts = resolve(file=self.read(), flows=flows_by_uuid(FLOWS))
        self.assertEqual(
            [(f.flow_uuid, f.category.name, f.amount) for f in factors],
            [("flow-1", "acidification", 3.02), ("flow-2", "climate change", 1.0)],
        )
        self.assertEqual(counts, {"acidification": 1, "climate change": 1})

    def test_a_flow_the_list_does_not_have_is_refused(self):
        with self.assertRaises(EcoinventPublicLciaError) as caught:
            resolve(file=self.read(), flows=flows_by_uuid(FLOWS[1:]))
        self.assertIn("flow-1", str(caught.exception))

    def test_a_flow_named_differently_is_refused(self):
        """The UUID is the join; the triple beside it is checked, because a
        release that renamed or moved the flow is one to look at."""
        renamed = [dict(FLOWS[0], context=["air", "urban air close to ground"]), *FLOWS[1:]]
        with self.assertRaises(EcoinventPublicLciaError) as caught:
            resolve(file=self.read(), flows=flows_by_uuid(renamed))
        self.assertIn("urban air close to ground", str(caught.exception))

    def test_a_row_with_no_number_is_not_looked_at(self):
        """The file lists every flow of the release, characterised or not, and
        an uncharacterised flow the extracted list has retired reaches nothing
        that matters."""
        factors, _counts = resolve(file=self.read(), flows=flows_by_uuid(FLOWS[:2]))
        self.assertEqual(len(factors), 2)

    def test_a_flow_without_a_two_part_context_is_refused(self):
        with self.assertRaises(EcoinventPublicLciaError):
            flows_by_uuid([{"uuid": "f", "name": "A", "context": ["air"]}])


class TheWrittenFileTestCase(_FileTestCase):
    """The workbook adapter's file format, so `lcia.sources` reads both with
    one reader, plus the provenance that says which this is."""

    def payload(self):
        source = known_source_lists()["ecoinvent-3.12"]
        file = self.read()
        factors, counts = resolve(file=file, flows=flows_by_uuid(FLOWS))
        published = published_file_for(source, METHOD)
        block = method_payload(
            file=file,
            published=published,
            digest=published.sha256,
            factors=factors,
            counts=counts,
        )
        return factors_payload(source=source, methods=[block])

    def test_the_file_states_where_it_came_from(self):
        payload = self.payload()
        self.assertEqual(payload["schema_version"], FACTORS_SCHEMA_VERSION)
        self.assertEqual(payload["repository"], REPOSITORY)
        self.assertEqual(payload["licence"], {"name": LICENCE_NAME, "url": LICENCE_URL})
        block = payload["methods"][0]
        published = PUBLISHED_METHOD_FILES[("3.12", METHOD)]
        self.assertEqual(block["file"], published.path)
        self.assertEqual(block["commit"], published.commit)
        self.assertEqual(block["file_sha256"], published.sha256)
        self.assertIn(published.commit, block["permalink"])
        self.assertIsNone(block["long_term_check"])
        self.assertEqual(
            (block["rows"], block["zero_cells_dropped"], block["factor_count"], block["flow_count"]),
            (3, 2, 2, 2),
        )

    def test_a_file_that_is_not_the_pinned_one_claims_no_commit(self):
        source = known_source_lists()["ecoinvent-3.12"]
        file = self.read()
        factors, counts = resolve(file=file, flows=flows_by_uuid(FLOWS))
        block = method_payload(
            file=file,
            published=published_file_for(source, METHOD),
            digest="0" * 64,
            factors=factors,
            counts=counts,
        )
        self.assertIsNone(block["commit"])
        self.assertEqual(block["file_sha256"], "0" * 64)

    def test_the_workbook_adapters_reader_reads_it(self):
        path = self.directory / "factors.json"
        path.write_bytes(orjson.dumps(self.payload()))
        factors = load_factors(path)[METHOD]
        self.assertEqual(
            [(f.flow_uuid, f.category.name, f.amount) for f in factors],
            [("flow-1", "acidification", 3.02), ("flow-2", "climate change", 1.0)],
        )
        self.assertEqual(factors[0].category.methodology, METHOD)
        self.assertIsNone(factors[0].category.reference_unit)


class ThePinTestCase(unittest.TestCase):
    def test_the_3_12_ef_file_is_pinned_to_a_commit(self):
        published = PUBLISHED_METHOD_FILES[("3.12", METHOD)]
        self.assertRegex(published.commit, r"^[0-9a-f]{40}$")
        self.assertRegex(published.sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(published.path, "3.12/methods_mapped/EF v3.1_mapped_3.12.csv")
        self.assertEqual(
            published.url,
            "https://raw.githubusercontent.com/ecoinvent/lcia/"
            f"{published.commit}/3.12/methods_mapped/EF%20v3.1_mapped_3.12.csv",
        )
        self.assertTrue(published.permalink.startswith(f"{REPOSITORY}/blob/{published.commit}/"))
        self.assertEqual(published.pinned.urls, (published.url,))
        self.assertEqual(published.pinned.sha256, published.sha256)

    def test_a_release_with_no_pin_is_refused(self):
        """3.13 has no public file yet, and the branch tip is not read in its
        place; the error names the workbook adapter that has it."""
        with self.assertRaises(EcoinventPublicLciaError) as caught:
            published_file_for(known_source_lists()["ecoinvent-3.13"], METHOD)
        self.assertIn("ecoinvent_lcia:fetch", str(caught.exception))
        self.assertIn("3.13", str(caught.exception))

    def test_every_pin_names_a_method_of_the_release_folder(self):
        for (version, method), published in PUBLISHED_METHOD_FILES.items():
            with self.subTest(version=version, method=method):
                self.assertTrue(published.path.startswith(f"{version}/"))
                self.assertIn(method, published.path)


class TheManifestDeclaresItTestCase(unittest.TestCase):
    def test_3_12_reads_the_public_file(self):
        source = known_source_lists()["ecoinvent-3.12"]
        self.assertEqual(
            source.lcia.adapter, "brightway_flows.integrations.ecoinvent_lcia_public:fetch"
        )
        self.assertEqual(source.lcia.factors_path.name, "ecoinvent-3.12-lcia-factors-public.json")
        self.assertEqual([m.name for m in source.lcia.methods], [METHOD])
        self.assertIsNone(
            source.lcia.methods[0].no_long_term,
            "the repository publishes no `no LT` file, and the adapter refuses "
            "a manifest that asks for one",
        )
        self.assertEqual(source.lcia.implemented_by, "ecoinvent Centre (3.12)")

    def test_3_13_still_reads_the_workbook(self):
        source = known_source_lists()["ecoinvent-3.13"]
        self.assertEqual(source.lcia.adapter, "brightway_flows.integrations.ecoinvent_lcia:fetch")
        self.assertEqual(source.lcia.methods[0].no_long_term, "EF v3.1 no LT")

    def test_the_reader_registry_knows_the_adapter(self):
        from brightway_flows.lcia.sources import _READERS, ecoinvent_factors

        source = known_source_lists()["ecoinvent-3.12"]
        self.assertIs(_READERS[source.lcia.adapter], ecoinvent_factors)

    def test_the_adapter_it_names_is_importable(self):
        from brightway_flows.sources import load_adapter

        source = known_source_lists()["ecoinvent-3.12"]
        self.assertTrue(callable(load_adapter(source, dotted_path=source.lcia.adapter)))

    def test_the_adapter_refuses_a_manifest_that_asks_for_the_long_term_check(self):
        from dataclasses import replace

        from brightway_flows.integrations.ecoinvent_lcia_public import fetch
        from brightway_flows.sources import LciaMethodSpec

        source = known_source_lists()["ecoinvent-3.12"]
        asked = replace(
            source,
            lcia=replace(
                source.lcia,
                methods=(LciaMethodSpec(name=METHOD, no_long_term="EF v3.1 no LT"),),
            ),
        )
        with self.assertRaises(EcoinventPublicLciaError) as caught:
            fetch(asked)
        self.assertIn("no_long_term", str(caught.exception))


class TheImplementationRowTestCase(unittest.TestCase):
    def test_the_row_states_the_licence_and_the_file(self):
        previous = ef_method().implementation(ECOINVENT_PREVIOUS)
        self.assertEqual(previous.licence, LICENCE_NAME)
        self.assertIn("github.com/ecoinvent/lcia", previous.source)
        self.assertIn(PUBLISHED_METHOD_FILES[("3.12", METHOD)].commit[:8], previous.source)

    def test_the_workbook_row_states_no_licence(self):
        """Not a statement that the workbook is free of terms: nothing this
        list has recorded, and `meta` carries the key only where it has."""
        self.assertEqual(ef_method().implementation(ECOINVENT_CURRENT).licence, "")

    def test_every_category_of_the_3_12_implementation_carries_the_licence(self):
        categories = impact_categories_for("ef", ECOINVENT_PREVIOUS)
        self.assertEqual(len(categories), 25)
        self.assertEqual({c.meta.get("licence") for c in categories}, {LICENCE_NAME})
        self.assertEqual(
            {c.meta.get("licence") for c in impact_categories_for("ef", ECOINVENT_CURRENT)},
            {None},
        )


class WhatAFetchWroteTestCase(unittest.TestCase):
    """The measured numbers, against a file a real fetch produced.

    Skipped where nothing has fetched: the file is public, and no test may
    download it either.
    """

    FACTORS = 27_415
    FLOWS = 7_960
    ROWS = 9_830
    ZERO_CELLS = 3_212

    def setUp(self):
        self.source = known_source_lists()["ecoinvent-3.12"]
        self.path = self.source.lcia.factors_path
        if not self.path.exists():
            self.skipTest(f"{self.path} has not been fetched here")
        self.payload = orjson.loads(self.path.read_bytes())
        self.method = self.payload["methods"][0]

    def test_the_counts(self):
        self.assertEqual(self.method["method"], METHOD)
        self.assertEqual(len(self.method["categories"]), 25)
        self.assertEqual(self.method["factor_count"], self.FACTORS)
        self.assertEqual(self.method["flow_count"], self.FLOWS)
        self.assertEqual(self.method["rows"], self.ROWS)
        self.assertEqual(self.method["zero_cells_dropped"], self.ZERO_CELLS)
        self.assertIsNone(self.method["long_term_check"])

    def test_the_provenance(self):
        published = PUBLISHED_METHOD_FILES[("3.12", METHOD)]
        self.assertEqual(self.payload["repository"], REPOSITORY)
        self.assertEqual(self.payload["licence"]["name"], LICENCE_NAME)
        self.assertEqual(self.method["file"], published.path)
        self.assertEqual(self.method["file_sha256"], published.sha256)
        self.assertEqual(self.method["commit"], published.commit)

    def test_the_categories_are_the_crosswalks(self):
        self.assertEqual(
            {row["category"] for row in self.method["categories"]},
            set(ef_method().by_stated_name(ECOINVENT_PREVIOUS)),
        )

    def test_every_factor_reaches_a_flow_and_a_category(self):
        factors = load_factors(self.path)[METHOD]
        self.assertEqual(len(factors), self.FACTORS)
        self.assertTrue(all(factor.flow_uuid for factor in factors))
        self.assertEqual(
            {factor.category.name for factor in factors},
            set(ef_method().by_stated_name(ECOINVENT_PREVIOUS)),
        )

    def test_it_states_what_the_workbook_stated(self):
        """Where a workbook fetch of 3.12 is also present, the two files state
        the same factors for the same flows.  To the last binary digit on all
        but two: the CSV prints `2.4343e-08` for Buprofezin to forestry soil
        where the workbook holds the double one unit in the last place above
        it, and both are the number 2.4343e-08 as a person reads it."""
        workbook = self.path.with_name("ecoinvent-3.12-lcia-factors.json")
        if not workbook.exists():
            self.skipTest(f"{workbook} has not been fetched here")
        theirs = {
            (f.flow_uuid, f.category.name): f.amount
            for f in load_factors(workbook)[METHOD]
        }
        ours = {
            (f.flow_uuid, f.category.name): f.amount
            for f in load_factors(self.path)[METHOD]
        }
        self.assertEqual(set(ours), set(theirs))
        self.assertTrue(
            all(math.isclose(ours[key], theirs[key], rel_tol=1e-15) for key in ours)
        )
        exact = sum(ours[key] == theirs[key] for key in ours)
        self.assertGreaterEqual(exact, len(ours) - 2)


if __name__ == "__main__":
    unittest.main()
