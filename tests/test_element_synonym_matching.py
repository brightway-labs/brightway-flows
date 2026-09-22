"""An element is matched to its published substance, and never to a nuclide of it.

#327. The element enrichment matches PubChem's element list against the base
list's published names, on the element's name and on its symbol.  PubChem calls
element 13 `Aluminum`; this list publishes IUPAC's `Aluminium`; `Al` is nobody's
published name.  So aluminium matched nothing and was never typed
`ChemicalElement`.

The fallback added for it looks the element up among the *synonyms* of the base
list's objects, where `aluminum` already sits.  These tests are about the half
that bounds it, because the first build that ran it took `Neptunium-237` --
which carries `neptunium` among its synonyms -- and gave the isotope the
element's atomic number, symbol and isotope list, and stopped minting the
element object the nuclides point at.  `Neptunium` simply disappeared from the
published list, and nothing else moved; only a build could have caught it.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.nuclides import parse_nuclide_label
from brightway_flows.domain.vocabulary import CHEMROF_MOLECULAR_FORMULA
from brightway_flows.flow_layers.elements import _could_be_the_element


def _object(label, formula=None):
    properties = {}
    if formula:
        properties[CHEMROF_MOLECULAR_FORMULA] = {"@value": [formula]}
    return FlowObject(
        flow_object_id="fo-x",
        prefLabel=[{"@value": label, "@language": "en"}],
        altLabel=[],
        properties=properties,
        references=[],
        created_from={},
    )


class ANuclideIsNotItsElement(unittest.TestCase):
    """The discriminator the fallback uses, asked directly.

    The rule is `parse_nuclide_label(...) is None`, which is the same test the
    isotope machinery uses to decide what a nuclide label is -- so the fallback
    and the isotope pass cannot drift into disagreeing about it.
    """

    def test_an_isotope_label_is_recognised(self):
        for label in (
            "Neptunium-237", "Americium-241", "Silver-110m", "Carbon-14",
            "Uranium-235",
        ):
            with self.subTest(label=label):
                self.assertIsNotNone(parse_nuclide_label(label))

    def test_an_element_label_is_not(self):
        for label in ("Aluminium", "Aluminum", "Neptunium", "Astatine", "Tin"):
            with self.subTest(label=label):
                self.assertIsNone(parse_nuclide_label(label))

    def test_the_pair_that_made_this_necessary(self):
        # `Neptunium-237` carries `neptunium` as a synonym, so a lookup by
        # element name finds it.  The element and its isotope are different
        # substances, and the isotope is the more specific of the two -- which
        # is the direction that must never win.
        self.assertIsNotNone(parse_nuclide_label("Neptunium-237"))
        self.assertIsNone(parse_nuclide_label("Neptunium"))


class TheFallbackIsBounded(unittest.TestCase):
    """What the rule refuses, stated as the conditions it is written under."""

    def test_it_is_a_fallback_and_not_a_second_opinion(self):
        # Read off the source rather than asserted about behaviour: the synonym
        # lookup is reached only where the published name and the symbol have
        # both found nothing, so an element that matches a published name can
        # never be pulled onto some other substance by a synonym.
        from pathlib import Path

        source = Path(
            "src/brightway_flows/flow_layers/elements.py"
        ).read_text()
        pref_match = source.index("matched_ef_obj_ids.update(ef_by_canon_pref")
        alt_match = source.index("ef_by_canon_alt.get(_canonical_name(name)")
        self.assertLess(
            pref_match, alt_match,
            "the synonym lookup must come after the published-name lookup",
        )

    def test_it_never_looks_up_the_symbol_among_synonyms(self):
        # `Al`, `As` and `In` are ordinary words and two-letter fragments, and a
        # symbol matched against hundreds of synonyms of one substance finds
        # something for reasons having nothing to do with chemistry.
        from pathlib import Path

        source = Path(
            "src/brightway_flows/flow_layers/elements.py"
        ).read_text()
        # The claim is about what the synonym index is *queried with*, so it is
        # asserted on the lookup itself rather than on the lines around it: the
        # symbol appears nearby as the value `_could_be_the_element` compares a
        # formula against, which is a different use and a correct one.
        self.assertIn("ef_by_canon_alt.get(_canonical_name(name)", source)
        self.assertNotIn("ef_by_canon_alt.get(_canonical_name(symbol)", source)


class NeitherIsAnAllotrope(unittest.TestCase):
    """The second thing the fallback found wearing an element's name.

    `Dinitrogen` carries `nitrogen` among its synonyms, and EF 3.1 ships no flow
    called `Nitrogen`, so the fallback matched it and typed N2 as
    `ChemicalElement` -- where the build before it had `Allotrope`, which is what
    two atoms of nitrogen are.

    The nuclide test does not catch this one: `Dinitrogen` is not a nuclide
    label.  The formula does, and says what a chemist would say -- the element is
    the substance whose formula is the bare symbol.
    """

    def test_the_element_is_the_bare_symbol(self):
        self.assertTrue(
            _could_be_the_element(_object("Aluminium", formula="Al"), symbol="Al")
        )

    def test_an_allotrope_is_not(self):
        self.assertFalse(
            _could_be_the_element(_object("Dinitrogen", formula="N2"), symbol="N")
        )

    def test_a_nuclide_is_refused_before_the_formula_is_asked(self):
        # `Neptunium-237` states the bare symbol `Np`, so the formula alone would
        # admit it.  The nuclide test runs first for exactly that reason.
        self.assertFalse(
            _could_be_the_element(
                _object("Neptunium-237", formula="Np"), symbol="Np"
            )
        )

    def test_an_object_stating_no_formula_is_allowed(self):
        # Many base list objects state none, and refusing them would switch this
        # fallback off for the spelling case it exists for.  What keeps it from
        # being a hole is the caller's other condition: exactly one object may
        # answer for an element.
        self.assertTrue(_could_be_the_element(_object("Astatine"), symbol="At"))

    def test_a_compound_of_the_element_is_not_the_element(self):
        self.assertFalse(
            _could_be_the_element(_object("Alumina", formula="Al2O3"), symbol="Al")
        )

    def test_nothing_is_not_the_element(self):
        self.assertFalse(_could_be_the_element(None, symbol="Al"))


if __name__ == "__main__":
    unittest.main()
