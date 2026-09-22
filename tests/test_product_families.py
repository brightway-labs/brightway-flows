"""Which repeated leading tokens are supplier catalogues rather than vocabulary.

`Silicon Dioxide` published 4,003 alternative labels, 173 of them beginning
`Snowtex` and 126 `Aerosil` (#27).  The per-label shapes in
`strip_catalogue_altlabels` cannot see these -- `Snowtex 30` resembles no
anchored registry prefix and is shorter than the trade-name pattern requires --
so the signal has to be repetition within one object.

Repetition is a blunt instrument, so most of what follows is about what must
survive it: the object's own name, published designation conventions, Colour
Index generic names, corroborated dye names, and every object small enough that
a repeated token has an innocent reading.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import coerce_alt_labels
from brightway_flows.transformers.strip_product_families import (
    COLOUR_INDEX_NAMES_FILEPATH,
    StripProductFamiliesTransformer,
    family_token,
    is_product_designation,
    load_colour_index_names,
)


def _flow(alt_labels, *, pref="Silicon Dioxide"):
    return Flow.from_dict({
        "uuid": "flow-1",
        "prefLabel": [{"@value": pref, "@language": "en"}],
        "altLabel": [{"@value": v, "@language": "en"} for v in alt_labels],
    })


def _apply(flow, *, min_object_labels=2, min_family_size=3, use_chebi=False, **kwargs):
    transformer = StripProductFamiliesTransformer(
        min_object_labels=min_object_labels,
        min_family_size=min_family_size,
        use_chebi=use_chebi,
        **kwargs,
    )
    transformer.setup()
    changes = transformer.transform([flow])
    if not changes:
        return [x.value for x in coerce_alt_labels(flow.altLabel)]
    return [x["@value"] for x in changes[0].new_value]


def _json_file(payload):
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(payload, handle)
    handle.close()
    return Path(handle.name)


class TestDesignationShape(unittest.TestCase):
    """What counts as a free-standing designation hanging off a token."""

    def test_product_codes_are_designations(self):
        for value in (
            "Snowtex 30",
            "Aerosil R 300",
            "Nissan Nonion NS 202",
            "Admafine SC 1500SMJ",
            "Cataloid S 1-50",
            "Grace Davison SP 18-8749.01",
            "Nipgel AY 8A2",
        ):
            self.assertTrue(is_product_designation(value), value)

    def test_locants_mean_the_digits_are_chemistry(self):
        # The distinguishing feature is not that a number is present but that it
        # is bound into the name by hyphens and commas.
        for value in (
            "Sodium 2-mercaptopyridine 1-oxide",
            "Disodium 1-hydroxyethane-1-diphosphonate",
            "Sodium pyridine-1-oxide-2-thiolate",
            "disodium (1-hydroxyethylidene)diphosphonate",
        ):
            self.assertFalse(is_product_designation(value), value)

    def test_a_bare_designation_is_not_this_rules_business(self):
        # One token has no family token to hang off; `strip_catalogue_altlabels`
        # owns these, and claiming them here would double-count the removal.
        for value in ("S 100", "165MPJ", "03CAL"):
            self.assertFalse(is_product_designation(value.split()[0]), value)

    def test_a_hyphen_between_digits_is_a_range_not_a_locant(self):
        # `1-50` and `18-8749.01` are how catalogues number things; only a
        # hyphen against lower-case chemistry is a locant.
        for value in ("Cataloid S 1-50", "Ludox HS-40", "Snowtex 1PA-ST"):
            self.assertTrue(is_product_designation(value), value)

    def test_a_tail_without_digits_is_not_a_designation(self):
        for value in ("Silica gel", "Colloidal silicon dioxide", "Snowtex AS"):
            self.assertFalse(is_product_designation(value), value)

    def test_family_token_folds_case_and_punctuation(self):
        self.assertEqual(family_token("Snowtex 30"), "snowtex")
        self.assertEqual(family_token("Cab-O-Sil M 5"), "cab-o-sil")
        self.assertEqual(family_token("SNOWTEX, 40"), "snowtex")


class TestFamilyRemoval(unittest.TestCase):
    """The rule proper: repetition, and the size gate that bounds it."""

    def test_a_repeated_brand_family_is_removed(self):
        labels = ["Snowtex 30", "Snowtex 40", "Snowtex 50", "Colloidal silica"]
        self.assertEqual(_apply(_flow(labels)), ["Colloidal silica"])

    def test_a_family_below_the_threshold_survives(self):
        # Two `Snowtex` labels is not evidence of a catalogue.
        labels = ["Snowtex 30", "Snowtex 40", "Colloidal silica"]
        self.assertEqual(sorted(_apply(_flow(labels))), sorted(labels))

    def test_the_size_gate_confines_the_rule_to_the_head(self):
        # The same four labels, on an object too small to qualify.  `Tween 80`
        # and `Vitamin B12` are why this gate exists.
        labels = ["Snowtex 30", "Snowtex 40", "Snowtex 50", "Colloidal silica"]
        kept = _apply(_flow(labels), min_object_labels=100)
        self.assertEqual(sorted(kept), sorted(labels))

    def test_the_objects_own_name_is_not_a_brand(self):
        labels = ["Silicon 100", "Silicon 200", "Silicon 300", "Silica"]
        self.assertEqual(sorted(_apply(_flow(labels))), sorted(labels))

    def test_two_families_are_both_taken_and_both_named(self):
        labels = [
            "Snowtex 30", "Snowtex 40", "Snowtex 50",
            "Aerosil 130", "Aerosil 200", "Aerosil 300",
            "Colloidal silica",
        ]
        transformer = StripProductFamiliesTransformer(
            min_object_labels=2, min_family_size=3
        )
        transformer.setup()
        change = transformer.transform([_flow(labels)])[0]
        self.assertIn("'aerosil' (3", change.comment)
        self.assertIn("'snowtex' (3", change.comment)
        self.assertEqual([x["@value"] for x in change.new_value], ["Colloidal silica"])


class TestWhatMustSurvive(unittest.TestCase):
    """Conventions and curated strings the repetition signal must not reach."""

    def test_colour_index_generic_names_survive(self):
        # `Red 27` is a free-standing designation by shape, and a Colour Index
        # generic name identifies the colorant rather than a seller's product.
        labels = ["Acid Red 18", "Acid Red 27", "Acid Red 97", "Amaranth"]
        self.assertEqual(sorted(_apply(_flow(labels, pref="Amaranth"))), sorted(labels))

    def test_refrigerant_and_congener_numbering_survive(self):
        labels = ["Halon 1211", "Halon 1301", "Halon 2402", "Bromochlorodifluoromethane"]
        self.assertEqual(sorted(_apply(_flow(labels, pref="Halon"))), sorted(labels))

    def test_a_registered_colorant_name_survives(self):
        # `Ponceau 4R` and `Ponceau 3R` are the same shape; only the register
        # says the first is a name.  This is the case shape cannot decide.
        path = _json_file({"schema_version": 1, "names": ["Ponceau 4R"]})
        labels = ["Ponceau 4R", "Ponceau 3R", "Ponceau 6R", "Ponceau 2G"]
        kept = _apply(_flow(labels, pref="Acid Red 18"), colour_index_path=path)
        self.assertEqual(kept, ["Ponceau 4R"])

    def test_the_shipped_register_rescues_the_known_names(self):
        # Regression guard for the six the survey found the rule taking from the
        # real build.  ChEBI is off here; these must be covered by the file.
        names = load_colour_index_names()
        self.assertIn("ponceau 4r", {n.lower() for n in names})

    def test_the_keep_list_overrules_the_family(self):
        path = _json_file({
            "schema_version": 1,
            "keep": [{"value": "Snowtex 30", "comment": "curator ruled this a name"}],
        })
        labels = ["Snowtex 30", "Snowtex 40", "Snowtex 50", "Snowtex 60"]
        kept = _apply(_flow(labels), keep_list_path=path)
        self.assertEqual(kept, ["Snowtex 30"])

    def test_the_shipped_register_loads_and_records_its_provenance(self):
        payload = json.loads(COLOUR_INDEX_NAMES_FILEPATH.read_text())
        self.assertTrue(payload["names"])
        # Provenance is the whole point of this file: no shape test can judge
        # these strings, so the record of who vouched for them, and by what
        # query, is what makes it re-derivable and arguable later.
        source = payload["source"]
        for field in ("name", "property", "query", "endpoint", "retrieved"):
            self.assertTrue(source.get(field), field)
        self.assertEqual(
            len(load_colour_index_names()),
            len({n.strip().lower() for n in payload["names"]}),
        )


if __name__ == "__main__":
    unittest.main()
