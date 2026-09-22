"""A nuclide is an element, a nucleon count and a nuclear state.

Three defects were filed separately and turned out to be one thing. A nuclide
row was found by looking its *name* up in a dictionary built from every spelling
that row might go by, and:

* an isomer and its ground state generate the same spellings, so one overwrote
  the other and PubChem's row order decided which -- 37 of 79 published nuclides
  carried an isomer's half-life, decay mode and specific activity under a ground
  state's label (#18);
* where the element symbol ended in ``238Um`` was guessed from the trailing
  letters, which reads ``147Pm`` as phosphorus (#18);
* the merge key was the CAS registry number, and both source lists ship the
  *element's* number on some nuclide rows, so uranium ore in kg resolved to an
  object typed ``Isotope`` and elemental uranium had no object at all (#17);
* and a name naming a nuclide that cannot exist was recorded as unmatched and
  never read again (#20).

None of it needed data this project did not already have on disk. What it needed
was a type for the identity, which is :class:`~brightway_flows.domain.nuclides.Nuclide`,
and these are the cases that pin it.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from brightway_flows.domain.flow import Flow
from brightway_flows.filesystem import PUBCHEM_ELEMENTS_CACHE_FILEPATH
from brightway_flows.domain.nuclides import (
    ELEMENTS,
    Nuclide,
    element_symbol,
    half_life_years,
    parse_nuclide,
    parse_nuclide_label,
)
from brightway_flows.domain.vocabulary import CHEMROF_CHEMICAL_ELEMENT
from brightway_flows.flow_layers import resolve_flow_layers
from brightway_flows.flow_layers.elements import _nuclide_record_checks
from brightway_flows.sources import base_source_list

BASE = base_source_list()


def _flow(uuid: str, name: str, cas: str | None, *, unit: str = "kBq") -> dict[str, Any]:
    # The base list's own label: element enrichment is seeded from the base list
    # only (#14), so a fixture that says anything else silently skips the
    # matching this is about and every element looks unmatched.
    return {
        "uuid": uuid,
        "prefLabel": [{"@value": name, "@language": "en"}],
        "source": BASE.source_label,
        "unit": unit,
        "context": {"dimension": "Environmental", "media": "Air", "strata": "Unknown"},
        "cas_numbers": [cas] if cas else [],
        "ec_numbers": [],
    }


def _layer(rows: list[dict[str, Any]]):
    return resolve_flow_layers([Flow.from_dict(r) for r in rows], source_list=BASE)


class NuclideParsingTestCase(unittest.TestCase):
    def test_the_symbol_is_given_and_the_rest_is_the_state(self):
        """The letters that end a symbol and the letters that name a state
        overlap, so nothing in the string settles where one stops. The caller
        knows the element; guessing produced `chemrof:symbol` values of `P` for
        promethium, `M` for manganese, `R` for radon and `Sbp` for antimony."""
        cases = {
            ("238U", "U"): Nuclide("U", 238),
            ("238Um", "U"): Nuclide("U", 238, "m"),
            ("147Pm", "Pm"): Nuclide("Pm", 147),
            ("54Mn", "Mn"): Nuclide("Mn", 54),
            ("222Rn", "Rn"): Nuclide("Rn", 222),
            ("122Sbp", "Sb"): Nuclide("Sb", 122, "p"),
            ("99Tcm", "Tc"): Nuclide("Tc", 99, "m"),
            ("242Cm", "Cm"): Nuclide("Cm", 242),
            ("242Cmm", "Cm"): Nuclide("Cm", 242, "m"),
        }
        for (text, symbol), expected in cases.items():
            with self.subTest(nuclide=text):
                self.assertEqual(parse_nuclide(text, symbol=symbol), expected)

    def test_a_row_filed_under_the_wrong_element_is_refused(self):
        self.assertIsNone(parse_nuclide("238U", symbol="Pu"))

    def test_a_state_letter_outside_the_set_is_refused_not_guessed(self):
        self.assertIsNone(parse_nuclide("238Uz", symbol="U"))

    def test_the_ground_state_is_a_distinct_key_from_its_isomer(self):
        """The whole of #18 in one line: these two used to collide."""
        self.assertNotEqual(Nuclide("U", 238), Nuclide("U", 238, "m"))
        self.assertNotEqual(Nuclide("Tc", 99), Nuclide("Tc", 99, "m"))
        index = {}
        index[Nuclide("U", 238)] = "ground"
        index[Nuclide("U", 238, "m")] = "isomer"
        self.assertEqual(index[Nuclide("U", 238)], "ground")

    def test_a_flow_label_parses_to_the_same_triple(self):
        cases = {
            "Uranium-238": Nuclide("U", 238),
            "Uranium 238": Nuclide("U", 238),
            "Technetium-99m": Nuclide("Tc", 99, "m"),
            "Potassium-40": Nuclide("K", 40),
            "Cesium-137": Nuclide("Cs", 137),
            "Caesium-137": Nuclide("Cs", 137),
            "Praseodymium-147": Nuclide("Pr", 147),
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(parse_nuclide_label(label), expected)

    def test_a_name_that_merely_looks_like_one_is_not_a_nuclide(self):
        """`HCFC-123a` has the shape and is a molecule, which is why the
        semantic typing keys on the isotope record rather than on the label.
        The element name being a closed set is what makes the check free."""
        for label in (
            "HCFC-123a",
            "Halon-1211",
            "PCB-118",
            "Lead 2,4,6-trinitro-m-phenylene dioxide",
            "Sodium 2-ethylhexanoate",
            "Thorium",
            "Radioactive Species, Alpha Emitters",
            "Praseodym-147",
        ):
            with self.subTest(label=label):
                self.assertIsNone(parse_nuclide_label(label))

    def test_the_periodic_table_agrees_with_the_pubchem_cache(self):
        """`ELEMENTS` is a literal so the parsing is a pure function. That is
        only safe while it says what the cached table says."""
        path = PUBCHEM_ELEMENTS_CACHE_FILEPATH
        if not path.exists():
            self.skipTest("PubChem element cache not present in this data directory")
        cached = json.loads(path.read_text())["elements"]
        self.assertEqual(
            sorted((e["atomic_number"], e["symbol"], e["name"]) for e in cached),
            sorted(ELEMENTS),
        )

    def test_every_cached_nuclide_row_parses(self):
        """A row this cannot read gets no record, so a silent drift in the
        cache's notation would quietly shrink the published list."""
        path = PUBCHEM_ELEMENTS_CACHE_FILEPATH
        if not path.exists():
            self.skipTest("PubChem element cache not present in this data directory")
        unparsed = [
            (element["symbol"], row.get("nuclide"))
            for element in json.loads(path.read_text())["elements"]
            for row in element.get("isotope_decay", []) + element.get("stable_isotopes", [])
            if row.get("nuclide")
            and parse_nuclide(row["nuclide"], symbol=element["symbol"]) is None
        ]
        self.assertEqual(unparsed, [])

    def test_only_genuine_spelling_variants_are_accepted(self):
        """A truncated element name is a defect in the label and is corrected
        in the manual fixes. Absorbing it here would hide the next one."""
        self.assertEqual(element_symbol("Aluminium"), "Al")
        self.assertEqual(element_symbol("Sulphur"), "S")
        self.assertIsNone(element_symbol("Praseodym"))
        self.assertIsNone(element_symbol("Uran"))


class HalfLifeUnitsTestCase(unittest.TestCase):
    """The units the long-lived nuclides are actually written in.

    These are the flows an inventory is most likely to carry, and every one of
    them published without a `chemrof:half_life` while the isomer records that
    had displaced them -- nanoseconds and microseconds -- parsed perfectly.
    """

    def test_si_prefixed_years(self):
        cases = {
            "4.463 Gy ± 0.003": 4.463e9,    # uranium-238
            "1.248 Gy ± 0.003": 1.248e9,    # potassium-40
            "704 My ± 1": 7.04e8,           # uranium-235
            "211.1 ky ± 1.2": 2.111e5,      # technetium-99
            "5.70 ky ± 0.03": 5.70e3,       # carbon-14
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertAlmostEqual(half_life_years(text) / expected, 1.0, places=6)

    def test_the_exponent_chemlin_writes_as_markup(self):
        """`7.04(1) &times; 10<sup>8</sup> a`, folded before it gets here. The
        scrape used to stop at the first tag and keep only the mantissa."""
        self.assertAlmostEqual(half_life_years("4.468(6)e9 years"), 4.468e9, places=3)
        self.assertAlmostEqual(half_life_years("7.04(1)e8 a"), 7.04e8, places=3)


class RecordChecksTestCase(unittest.TestCase):
    def test_a_ground_state_may_not_decay_by_isomeric_transition(self):
        """Isomeric transition is the fall from an excited state, so a ground
        state has nothing to fall from. 31 objects published it."""
        checks = _nuclide_record_checks(
            nuclide=Nuclide("K", 40),
            record={"decay_modes": "IT=100%", "half_life_and_uncertainty": "336 ns ± 12"},
        )
        failed = [c["check"] for c in checks if not c["passed"]]
        self.assertEqual(
            failed, ["ground_state_does_not_decay_by_isomeric_transition"]
        )

    def test_an_isomer_may(self):
        checks = _nuclide_record_checks(
            nuclide=Nuclide("K", 40, "m"),
            record={"decay_modes": "IT=100%", "half_life_and_uncertainty": "336 ns ± 12"},
        )
        self.assertTrue(all(c["passed"] for c in checks))

    def test_the_two_sources_have_to_agree(self):
        checks = _nuclide_record_checks(
            nuclide=Nuclide("Pb", 210),
            record={
                "decay_modes": "β-=100%",
                "half_life_and_uncertainty": "201 ns ± 17",   # the isomer's
                "half_life_chemlin": "22.20 a",               # the ground state's
            },
        )
        failed = [c["check"] for c in checks if not c["passed"]]
        self.assertEqual(failed, ["half_life_sources_agree"])

    def test_two_sources_that_both_say_stable_have_not_disagreed(self):
        """Infinity over infinity is a NaN, and a NaN fails every comparison
        it is put through, so Argon-40 and Xenon-131 -- stable, and agreed to
        be stable by both sources -- were withheld for disagreeing."""
        checks = _nuclide_record_checks(
            nuclide=Nuclide("Ar", 40),
            record={
                "decay_modes": "IS=99.6035±25%",
                "half_life_and_uncertainty": "Stable",
                "half_life_chemlin": "stable",
            },
        )
        self.assertTrue(all(c["passed"] for c in checks))
        self.assertNotIn(
            "half_life_sources_agree", [c["check"] for c in checks]
        )


class NuclideFlowObjectTestCase(unittest.TestCase):
    """#17, at the layer that decides what a flow object is."""

    def test_a_nuclide_does_not_merge_with_the_element_it_shares_a_cas_with(self):
        rows = [
            _flow("u238-ef", "uranium-238", "7440-61-1"),
            _flow("u-kg", "Uranium", "7440-61-1", unit="kg"),
            _flow("u-mj", "uranium", "7440-61-1", unit="MJ"),
        ]
        _objects, elementary, _stats = _layer(rows)
        by_uuid = {row.elementary_flow_id: row.flow_object_id for row in elementary}
        self.assertNotEqual(by_uuid["u238-ef"], by_uuid["u-kg"])
        self.assertEqual(by_uuid["u-kg"], by_uuid["u-mj"])

    def test_the_element_keeps_the_identifier_it_was_published_under(self):
        """`fo-93d10c394b58394e` is `sha1("cas:7440-61-1")`, and 7440-61-1 is
        the element's number. The object that keeps it is the element."""
        rows = [
            _flow("u238-ef", "uranium-238", "7440-61-1"),
            _flow("u-kg", "Uranium", "7440-61-1", unit="kg"),
        ]
        objects, _elementary, _stats = _layer(rows)
        by_label = {o.prefLabel[0]["@value"].lower(): o for o in objects}
        self.assertEqual(
            by_label["uranium"].flow_object_id, "fo-93d10c394b58394e"
        )

    def test_the_two_lists_still_meet_on_one_nuclide_object(self):
        """Grouping is what the CAS was doing, and it still has to happen --
        on the nuclide instead. EF writes `uranium-238`, ecoinvent `Uranium-238`."""
        rows = [
            _flow("u238-ef", "uranium-238", "7440-61-1"),
            _flow("u238-ei", "Uranium-238", "7440-61-1"),
        ]
        objects, elementary, _stats = _layer(rows)
        by_uuid = {row.elementary_flow_id: row.flow_object_id for row in elementary}
        self.assertEqual(by_uuid["u238-ef"], by_uuid["u238-ei"])
        self.assertEqual(len(objects), 1)

    def test_a_nuclide_and_its_isomer_are_separate_objects(self):
        """They have distinct CAS numbers today and separate for that reason.
        The separation must not depend on the vendors having assigned one."""
        rows = [
            _flow("pa234", "Protactinium-234", None),
            _flow("pa234m", "Protactinium-234m", None),
        ]
        _objects, elementary, _stats = _layer(rows)
        by_uuid = {row.elementary_flow_id: row.flow_object_id for row in elementary}
        self.assertNotEqual(by_uuid["pa234"], by_uuid["pa234m"])

    def test_an_element_is_not_keyed_as_a_nuclide(self):
        """`Thorium` and `Plutonium` keep their CAS key. Keying them by
        nuclide is what would merge an element with its own isotopes."""
        rows = [
            _flow("th232", "thorium-232", "7440-29-1"),
            _flow("th-kg", "Thorium", "7440-29-1", unit="kg"),
            _flow("th-kg2", "thorium", "7440-29-1", unit="kg"),
        ]
        objects, elementary, _stats = _layer(rows)
        by_uuid = {row.elementary_flow_id: row.flow_object_id for row in elementary}
        self.assertNotEqual(by_uuid["th232"], by_uuid["th-kg"])
        self.assertEqual(by_uuid["th-kg"], by_uuid["th-kg2"])
        self.assertEqual(len(objects), 2)


class MintedElementTestCase(unittest.TestCase):
    """An element with isotopes in the list, and no flow of its own.

    `chemrof:has_element` has range `ChemicalElement`, so the target has to
    exist as an object for the triple to say anything. Americium, Neptunium,
    Promethium and Technetium appear in both source lists only as nuclides.
    """

    def _layer_with_enrichment(self, rows: list[dict[str, Any]]):
        return resolve_flow_layers(
            [Flow.from_dict(r) for r in rows],
            source_list=BASE,
            include_pubchem_isotopes=True,
        )

    def test_an_element_with_isotopes_and_no_flow_gets_an_object(self):
        objects, _elementary, stats = self._layer_with_enrichment(
            [_flow("am241", "Americium-241", "14596-10-2")]
        )
        by_label = {o.prefLabel[0]["@value"].lower(): o for o in objects}
        self.assertIn("americium", by_label)
        self.assertEqual(stats["element_flow_object_count_added"], 1)
        self.assertEqual(stats["element_flow_object_names_added"], ["Americium"])

    def test_it_is_typed_as_the_element_and_carries_the_periodic_table_row(self):
        """It goes through the same enrichment every other element does, so
        `has_element`'s declared range holds against it."""
        objects, _elementary, _stats = self._layer_with_enrichment(
            [_flow("am241", "Americium-241", "14596-10-2")]
        )
        americium = next(
            o for o in objects if o.prefLabel[0]["@value"] == "Americium"
        )
        self.assertIn(CHEMROF_CHEMICAL_ELEMENT, americium.types or [])
        self.assertEqual(americium.properties["element"]["atomic_number"], 95)
        self.assertEqual(americium.properties["element"]["symbol"], "Am")

    def test_the_isotope_links_to_it(self):
        objects, _elementary, stats = self._layer_with_enrichment(
            [_flow("am241", "Americium-241", "14596-10-2")]
        )
        by_label = {o.prefLabel[0]["@value"].lower(): o for o in objects}
        self.assertEqual(
            by_label["americium-241"].properties["relationships"][
                "parent_element_flow_object_id"
            ],
            by_label["americium"].flow_object_id,
        )
        self.assertEqual(stats["isotope_unlinked_element_count"], 0)

    def test_nothing_is_minted_when_the_list_carries_the_element(self):
        """The guard against a duplicate is that the match runs first."""
        objects, _elementary, stats = self._layer_with_enrichment(
            [
                _flow("am241", "Americium-241", "14596-10-2"),
                _flow("am", "Americium", "7440-35-9", unit="kg"),
            ]
        )
        self.assertEqual(stats["element_flow_object_count_added"], 0)
        self.assertEqual(
            [o.prefLabel[0]["@value"] for o in objects].count("Americium"), 1
        )

    def test_an_element_with_no_isotopes_in_the_list_is_not_minted(self):
        """This completes a substance the list is already publishing. It does
        not pour the periodic table into the list."""
        _objects, _elementary, stats = self._layer_with_enrichment(
            [_flow("co2", "Carbon dioxide", "124-38-9", unit="kg")]
        )
        self.assertEqual(stats["element_flow_object_count_added"], 0)

    def test_the_identifier_is_a_function_of_the_element(self):
        first, _e, _s = self._layer_with_enrichment(
            [_flow("am241", "Americium-241", "14596-10-2")]
        )
        second, _e, _s = self._layer_with_enrichment(
            [_flow("am241-other-uuid", "Americium-241", "14596-10-2")]
        )
        self.assertEqual(
            next(o for o in first if o.prefLabel[0]["@value"] == "Americium").flow_object_id,
            next(o for o in second if o.prefLabel[0]["@value"] == "Americium").flow_object_id,
        )


if __name__ == "__main__":
    unittest.main()
