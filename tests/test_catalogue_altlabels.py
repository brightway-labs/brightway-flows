"""Which alternative labels are catalogue entries rather than names.

Common Chemistry files supplier grades and brand names against a CAS number
alongside the chemistry, and the enrichment cannot tell them apart from the
payload: `S 100` and `octadecanoic acid` arrive in the same list. 18.3% of
published alternative labels are one of these shapes.

They are not harmless. `test_label_matching` records a merge that resolved
Propylene Carbonate to **Talc** because both carried a `K 3` alternative label
-- a product grade shared by two unrelated substances is exactly the kind of
evidence a label index cannot weigh.

The risk of a shape test is that it deletes chemistry, so most of what follows
is about what must survive it, and about the keep list that overrules it when
it is nonetheless wrong.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import coerce_alt_labels
from brightway_flows.transformers.strip_catalogue_altlabels import (
    KEEP_LIST_FILEPATH,
    StripCatalogueAltLabelsTransformer,
    catalogue_code_kind,
    load_keep_list,
)


def _flow(alt_labels, *, pref="Stearic Acid"):
    return Flow.from_dict({
        "uuid": "flow-1",
        "prefLabel": [{"@value": pref, "@language": "en"}],
        "altLabel": [{"@value": v, "@language": "en"} for v in alt_labels],
    })


def _apply(flow, *, keep_list_path=None):
    transformer = StripCatalogueAltLabelsTransformer(keep_list_path=keep_list_path)
    transformer.setup()
    changes = transformer.transform([flow])
    if not changes:
        return [x.value for x in coerce_alt_labels(flow.altLabel)]
    return [x["@value"] for x in changes[0].new_value]


def _keep_file(entries):
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump({"schema_version": 1, "description": "test", "keep": entries}, handle)
    handle.close()
    return Path(handle.name)


class TestCatalogueShapes(unittest.TestCase):

    def test_grade_codes_are_catalogue_entries(self):
        for value in ("S 100", "D 50", "A 1", "F 1000", "SA 1", "P-30"):
            self.assertEqual(catalogue_code_kind(value), "grade code", value)

    def test_registry_accessions_are_catalogue_entries(self):
        for value in ("NSC 147337", "AKOS000118800", "C.I. 77120", "CHEMBL25",
                      "MFCD00012345", "UN 3077", "Epitope ID:2151205"):
            self.assertEqual(catalogue_code_kind(value), "registry code", value)

    def test_trade_names_are_catalogue_entries(self):
        for value in ("Garlon 480", "Prifrac 2981", "Dow Corning 777",
                      "Polytal 4641", "Penta 811K"):
            self.assertEqual(catalogue_code_kind(value), "trade name", value)

    def test_a_class_qualifier_does_not_rescue_a_grade_code(self):
        # Common Chemistry appends the substance class to disambiguate a grade
        # several substances share.  That courtesy hid the code from the shape
        # tests entirely: 2,519 published labels are one of these wearing a
        # parenthetical, `oxide` and `silica` being the commonest.
        for value in ("S 10 (silica)", "R 203 (pigment)", "A 1 (talc)",
                      "A 100 (dispersion)", "S 1250 (oxide)"):
            self.assertEqual(catalogue_code_kind(value), "grade code", value)


class TestWhatMustSurvive(unittest.TestCase):
    """Every case here is a string the shape test could plausibly eat."""

    def test_chemical_names_are_not_catalogue_entries(self):
        for value in ("Octadecanoic acid", "oxidane", "trans-2,4-hexadienal",
                      "2,4-Hexadienal, (E,E)-", "Stearic Acid"):
            self.assertIsNone(catalogue_code_kind(value), value)

    def test_formula_shaped_labels_survive(self):
        # `H2O` is letters-then-digits with no separator, which is why the
        # grade pattern requires one.
        for value in ("H2O", "CO2", "SO3", "C2H4", "H(2)O"):
            self.assertIsNone(catalogue_code_kind(value), value)

    def test_element_symbols_and_short_names_survive(self):
        for value in ("W", "As", "Zn(II)", "Trp", "TCA", "CP"):
            self.assertIsNone(catalogue_code_kind(value), value)

    def test_refrigerant_designations_survive(self):
        # EF 3.1 identifies 55 flows by designation alone (#19); these are
        # identifiers, and they are shaped exactly like grade codes.
        for value in ("HFC-134a", "HCFC-123", "CFC-11", "HFO-1234yf", "R-600a",
                      "Halon 1211", "Freon 113", "Genetron 1132a",
                      "Fluorocarbon 113", "Perfluorocarbon 116"):
            self.assertIsNone(catalogue_code_kind(value), value)

    def test_a_grade_code_that_merely_starts_like_a_refrigerant_is_removed(self):
        # `R 300` with a space is a grade of stearic acid, not refrigerant 300.
        self.assertEqual(catalogue_code_kind("R 300"), "grade code")

    def test_congener_numbering_survives(self):
        for value in ("PCB 118", "BDE-47", "PBDE 99"):
            self.assertIsNone(catalogue_code_kind(value), value)

    def test_colour_index_generic_names_survive(self):
        # A Colour Index generic name identifies the colorant; it is a published
        # convention like refrigerant numbering, not a seller's product code.
        for value in ("Acid Red 27", "Pigment Blue 15:3", "Basic Violet 3",
                      "C.I. Acid Green 5", "Solvent Yellow 14", "Vat Blue 4"):
            self.assertIsNone(catalogue_code_kind(value), value)

    def test_a_name_ending_in_a_parenthetical_is_judged_whole_first(self):
        # The qualifier strip must not let a name be judged on its stem.
        for value in ("Methyl Violet 6B (biological stain)", "Silica gel (amorphous)"):
            self.assertIsNone(catalogue_code_kind(value), value)

    def test_two_digit_product_numbers_are_left_alone(self):
        # Below the trade-name threshold on purpose: `Tween 80` is a product
        # name but `Pigment Yellow 74` and `Vitamin B12` are not, and the shape
        # cannot separate them.
        for value in ("Tween 80", "Pigment Yellow 74", "Sudan 4"):
            self.assertIsNone(catalogue_code_kind(value), value)


class TestKeepList(unittest.TestCase):
    """The curator's override, for the strings the shape rules get wrong."""

    def test_a_listed_label_is_kept_though_it_reads_as_a_code(self):
        path = _keep_file([{"value": "S 100", "comment": "a real name, somehow"}])
        self.assertEqual(_apply(_flow(["S 100", "NSC 147337"]), keep_list_path=path),
                         ["S 100"])

    def test_matching_ignores_case_and_whitespace(self):
        path = _keep_file([{"value": "s  100", "comment": "spelled loosely"}])
        self.assertEqual(_apply(_flow(["S 100"]), keep_list_path=path), ["S 100"])

    def test_an_entry_without_a_comment_is_ignored(self):
        # The file says the comment is mandatory. An exemption nobody explained
        # would otherwise sit in the data forever.
        path = _keep_file([{"value": "S 100"}])
        self.assertEqual(load_keep_list(path), set())
        self.assertEqual(_apply(_flow(["S 100"]), keep_list_path=path), [])

    def test_a_missing_file_is_an_empty_list_and_not_an_error(self):
        self.assertEqual(load_keep_list(Path("/nonexistent/keep.json")), set())

    def test_the_shipped_file_parses_and_every_entry_is_explained(self):
        payload = json.loads(KEEP_LIST_FILEPATH.read_text())
        self.assertIn("description", payload)
        for entry in payload["keep"]:
            self.assertTrue(entry.get("value", "").strip(), entry)
            self.assertTrue(entry.get("comment", "").strip(), entry)
        # Whatever is listed must be a string the filter would otherwise take;
        # an entry for a label nothing removes is a dead exemption.
        for entry in payload["keep"]:
            self.assertIsNotNone(catalogue_code_kind(entry["value"]), entry)


class TestTransformer(unittest.TestCase):

    def test_catalogue_entries_are_removed_and_chemistry_kept(self):
        flow = _flow([
            "Octadecanoic acid", "S 100", "NSC 147337", "Prifrac 2981",
            "Stearophanic acid", "HFC-134a",
        ])
        self.assertEqual(
            _apply(flow),
            ["Octadecanoic acid", "Stearophanic acid", "HFC-134a"],
        )

    def test_a_flow_with_nothing_to_remove_proposes_no_change(self):
        transformer = StripCatalogueAltLabelsTransformer()
        transformer.setup()
        self.assertEqual(transformer.transform([_flow(["Octadecanoic acid"])]), [])

    def test_the_change_comment_names_what_it_removed(self):
        transformer = StripCatalogueAltLabelsTransformer()
        transformer.setup()
        changes = transformer.transform([_flow(["Octadecanoic acid", "S 100"])])
        self.assertIn("'S 100' (grade code)", changes[0].comment)

    def test_the_step_is_in_the_default_chain_after_every_label_writer(self):
        from brightway_flows.transformers import (
            DEFAULT_TRANSFORMERS,
            ChebiAltLabelsTransformer,
            ConsensusMatchTransformer,
            DedupeAltLabelsTransformer,
        )
        order = {t: i for i, t in enumerate(DEFAULT_TRANSFORMERS)}
        self.assertIn(StripCatalogueAltLabelsTransformer, order)
        self.assertGreater(order[StripCatalogueAltLabelsTransformer],
                           order[ChebiAltLabelsTransformer])
        self.assertGreater(order[StripCatalogueAltLabelsTransformer],
                           order[ConsensusMatchTransformer])
        self.assertLess(order[StripCatalogueAltLabelsTransformer],
                        order[DedupeAltLabelsTransformer])


if __name__ == "__main__":
    unittest.main()
