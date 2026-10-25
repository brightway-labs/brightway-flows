"""The quantity vocabulary stays consistent with the three things it names.

A row of `quantities.json` says what a number measures -- a megajoule of hard
coal is net calorific value, a megajoule of uranium is fission energy -- and it
does so by pointing outward three times: at a quantity kind `units.json`
spells, at an ILCD flow property EF 3.1 ships, and at a QUDT quantity kind.
None of those is checked by the loader beyond its shape, because the loader
cannot see `units.json`'s rows or EF's `flow-properties.json`.  These tests can,
and a row pointing at a kind no unit has, or an ILCD uuid EF does not define,
is a row no statement can ever use.

The module constants are checked the same way: `NET_CALORIFIC_VALUE` is a
spelling of a slug the file has, and nothing else keeps the two together.
"""

import unittest

import orjson

from brightway_flows.domain import quantities
from brightway_flows.domain.quantities import (
    CALORIFIC_VALUE,
    FISSION_ENERGY,
    GROSS_CALORIFIC_VALUE,
    MASS,
    NET_CALORIFIC_VALUE,
    RADIOACTIVITY,
    VOLUME,
    load_quantities,
    quantity,
    quantity_for_ilcd_flow_property,
    quantity_for_unit,
)
from brightway_flows.domain.units import UNITS_FILEPATH
from brightway_flows.domain.vocabulary import QUANTITY_IRI_PREFIX
from brightway_flows.filesystem import FLOW_PROPERTIES_FILEPATH

CONSTANTS = {
    "MASS": MASS,
    "VOLUME": VOLUME,
    "NET_CALORIFIC_VALUE": NET_CALORIFIC_VALUE,
    "GROSS_CALORIFIC_VALUE": GROSS_CALORIFIC_VALUE,
    "CALORIFIC_VALUE": CALORIFIC_VALUE,
    "FISSION_ENERGY": FISSION_ENERGY,
    "RADIOACTIVITY": RADIOACTIVITY,
}

QUDT_QUANTITY_KIND_PREFIX = "http://qudt.org/vocab/quantitykind/"

#: ILCD's net calorific value flow property, the one EF 3.1 measures its 34
#: energy flows in.
ILCD_NET_CALORIFIC_VALUE = "93a60a56-a3c8-11da-a746-0800200c9a66"


class QuantityKindsTestCase(unittest.TestCase):
    """A quantity's kind is one a unit can belong to.

    A statement's `unit` is checked against its quantity's `quantity_kind_iri`
    by comparing it with the kind `units.json` gives the unit.  A quantity
    whose kind no unit has would refuse every unit, so each row's kind must be
    one the unit table actually uses, in the same spelling.
    """

    def test_every_quantity_kind_is_one_units_json_uses(self):
        used = {
            row.get("quantity_kind_iri")
            for row in orjson.loads(UNITS_FILEPATH.read_bytes())
        }
        for slug, row in load_quantities().items():
            with self.subTest(quantity=slug):
                self.assertIn(row.quantity_kind_iri, used)

    def test_quantity_kind_is_the_local_name_of_the_iri(self):
        self.assertEqual(quantity(MASS).quantity_kind, "Mass")
        self.assertEqual(quantity(NET_CALORIFIC_VALUE).quantity_kind, "Energy")
        self.assertEqual(quantity(RADIOACTIVITY).quantity_kind, "Activity")


class IlcdFlowPropertiesTestCase(unittest.TestCase):
    """An ILCD flow property uuid names a property EF 3.1 defines.

    `reference_quantities_from_ilcd` reads EF's `flow-properties.json` and asks
    which quantity each flow's reference property is, by uuid.  A uuid typed
    wrong here would make every EF energy flow fall back to the unit's generic
    quantity without a word, so each is checked against the definitions
    `extract` wrote.  The file is a build output, so the check is skipped
    rather than failed where nobody has extracted EF 3.1.
    """

    def test_every_ilcd_uuid_is_a_property_ef_defines(self):
        if not FLOW_PROPERTIES_FILEPATH.exists():
            self.skipTest(
                f"{FLOW_PROPERTIES_FILEPATH} is not there; `brightway-flows "
                f"extract` writes it, and this check needs it."
            )
        payload = orjson.loads(FLOW_PROPERTIES_FILEPATH.read_bytes())
        defined = {
            str(row.get("id")): row.get("name")
            for row in payload.get("properties", [])
            if isinstance(row, dict)
        }
        for slug, row in load_quantities().items():
            if row.ilcd_flow_property_uuid is None:
                continue
            with self.subTest(quantity=slug):
                self.assertIn(row.ilcd_flow_property_uuid, defined)

    def test_the_two_unnamed_quantities_have_no_ilcd_property(self):
        self.assertIsNone(quantity(CALORIFIC_VALUE).ilcd_flow_property_uuid)
        self.assertIsNone(quantity(FISSION_ENERGY).ilcd_flow_property_uuid)

    def test_ilcd_uuids_are_distinct(self):
        uuids = [
            row.ilcd_flow_property_uuid
            for row in load_quantities().values()
            if row.ilcd_flow_property_uuid is not None
        ]
        self.assertEqual(len(uuids), len(set(uuids)))

    def test_quantity_for_ilcd_flow_property(self):
        self.assertEqual(
            quantity_for_ilcd_flow_property(ILCD_NET_CALORIFIC_VALUE),
            NET_CALORIFIC_VALUE,
        )
        self.assertIsNone(quantity_for_ilcd_flow_property("not-a-property"))
        self.assertIsNone(quantity_for_ilcd_flow_property(""))


class ConstantsTestCase(unittest.TestCase):
    """Every slug code branches on is a row of the file."""

    def test_every_constant_is_a_slug_of_the_file(self):
        slugs = set(load_quantities())
        for name, slug in CONSTANTS.items():
            with self.subTest(constant=name):
                self.assertIn(slug, slugs)

    def test_the_constants_are_distinct(self):
        self.assertEqual(len(set(CONSTANTS.values())), len(CONSTANTS))

    def test_the_file_has_exactly_the_quantities_the_constants_name(self):
        """A row with no constant would be a quantity nothing can ask for."""
        self.assertEqual(set(load_quantities()), set(CONSTANTS.values()))


class QudtMatchTestCase(unittest.TestCase):
    """Each row relates to a published QUDT quantity kind, and says how.

    QUDT has one `HeatingValue`, undivided into net and gross, so both stated
    bases are narrower terms of it and the basis-unstated one is the same
    thing as it.  QUDT has no per-mass fission kind, so fission energy narrows
    `SpecificEnergy`.
    """

    def test_every_match_is_a_qudt_quantity_kind(self):
        for slug, row in load_quantities().items():
            with self.subTest(quantity=slug):
                self.assertTrue(
                    row.qudt_match_iri.startswith(QUDT_QUANTITY_KIND_PREFIX),
                    row.qudt_match_iri,
                )
                self.assertIn(
                    row.qudt_match_relation, {"skos:exactMatch", "skos:broader"}
                )

    def test_net_and_gross_both_narrow_heating_value(self):
        heating_value = f"{QUDT_QUANTITY_KIND_PREFIX}HeatingValue"
        for slug in (NET_CALORIFIC_VALUE, GROSS_CALORIFIC_VALUE):
            with self.subTest(quantity=slug):
                row = quantity(slug)
                self.assertEqual(row.qudt_match_relation, "skos:broader")
                self.assertEqual(row.qudt_match_iri, heating_value)

    def test_basis_unstated_calorific_value_is_heating_value_itself(self):
        row = quantity(CALORIFIC_VALUE)
        self.assertEqual(row.qudt_match_relation, "skos:exactMatch")
        self.assertEqual(row.qudt_match_iri, f"{QUDT_QUANTITY_KIND_PREFIX}HeatingValue")

    def test_fission_energy_narrows_specific_energy(self):
        row = quantity(FISSION_ENERGY)
        self.assertEqual(row.qudt_match_relation, "skos:broader")
        self.assertEqual(
            row.qudt_match_iri, f"{QUDT_QUANTITY_KIND_PREFIX}SpecificEnergy"
        )

    def test_mass_volume_and_radioactivity_are_exact(self):
        for slug, kind in ((MASS, "Mass"), (VOLUME, "Volume"), (RADIOACTIVITY, "Activity")):
            with self.subTest(quantity=slug):
                row = quantity(slug)
                self.assertEqual(row.qudt_match_relation, "skos:exactMatch")
                self.assertEqual(row.qudt_match_iri, f"{QUDT_QUANTITY_KIND_PREFIX}{kind}")


class QuantityForUnitTestCase(unittest.TestCase):
    """What a flow's unit measures when nothing states more.

    A kilogram is a mass and a cubic metre a volume.  A megajoule is a
    calorific value of *unstated* basis: EF says net for its own flows through
    `flow-properties.json`, and a flow nobody has said that for must not be
    assumed net.  A standard cubic metre is an amount of substance in
    `units.json`, which no quantity here is the generic of, so it answers
    nothing -- which is what keeps a mine-gas row from being read as a volume.
    """

    def test_generic_quantities_by_unit(self):
        cases = {
            "kg": MASS,
            "t": MASS,
            "m3": VOLUME,
            "MJ": CALORIFIC_VALUE,
            "kBq": RADIOACTIVITY,
        }
        for unit, expected in cases.items():
            with self.subTest(unit=unit):
                self.assertEqual(quantity_for_unit(unit), expected)

    def test_a_megajoule_is_not_assumed_net(self):
        self.assertNotEqual(quantity_for_unit("MJ"), NET_CALORIFIC_VALUE)

    def test_units_with_no_generic_quantity_answer_none(self):
        for unit in ("sm3", "m2", "no-such-unit", ""):
            with self.subTest(unit=unit):
                self.assertIsNone(quantity_for_unit(unit))


class LookupTestCase(unittest.TestCase):
    """Asking for a quantity the file does not have raises, naming the slug."""

    def test_unknown_slug_raises_key_error_naming_it(self):
        with self.assertRaises(KeyError) as caught:
            quantity("nothing")
        self.assertIn("'nothing'", str(caught.exception))
        self.assertIn("quantities.json", str(caught.exception))

    def test_load_quantities_is_keyed_by_slug(self):
        for slug, row in load_quantities().items():
            with self.subTest(quantity=slug):
                self.assertEqual(row.slug, slug)

    def test_every_row_has_a_label_and_a_definition(self):
        for slug, row in load_quantities().items():
            with self.subTest(quantity=slug):
                self.assertTrue(row.label.strip())
                self.assertTrue(row.definition.strip())


class AliasesTestCase(unittest.TestCase):
    """No spelling names two quantities.

    A vendor parser matches a property's label against the aliases, case
    folded, so a spelling shared by two rows would make the parser's answer
    depend on file order.  The canonical label is matched too, so it counts as
    one of the row's spellings here.
    """

    def test_aliases_are_unique_across_rows_case_insensitively(self):
        owners: dict[str, str] = {}
        for slug, row in load_quantities().items():
            for spelling in (row.label, *row.aliases):
                folded = spelling.casefold()
                with self.subTest(quantity=slug, alias=spelling):
                    self.assertNotIn(
                        folded, {k: v for k, v in owners.items() if v != slug},
                        f"{spelling!r} names both {owners.get(folded)!r} and {slug!r}",
                    )
                owners.setdefault(folded, slug)

    def test_every_row_has_at_least_one_alias(self):
        for slug, row in load_quantities().items():
            with self.subTest(quantity=slug):
                self.assertTrue(row.aliases)


class IriTestCase(unittest.TestCase):
    """A quantity's IRI is minted under the vocabulary's quantity namespace."""

    def test_iri_uses_the_quantity_namespace(self):
        for slug, row in load_quantities().items():
            with self.subTest(quantity=slug):
                self.assertEqual(row.iri, f"{QUANTITY_IRI_PREFIX}{slug}")
                self.assertTrue(row.iri.startswith("https://vocab.brightway.one/quantity/"))

    def test_the_module_reads_the_prefix_from_the_vocabulary(self):
        self.assertIs(quantities.QUANTITY_IRI_PREFIX, QUANTITY_IRI_PREFIX)


class LabelTestCase(unittest.TestCase):
    """A vendor's label for a property is matched against the file's spellings.

    This is what the adapters read SimaPro's substance block and ecoinvent's
    property list with (#407, phase B), so a label the file does not spell is
    passed over rather than guessed at.
    """

    def test_the_vendors_spellings_resolve(self):
        from brightway_flows.domain.quantities import quantity_for_label

        for label, slug in {
            "Higher heating value (HHV)": "gross-calorific-value",
            "Lower heating value (LHV)": "net-calorific-value",
            "heating value, net": "net-calorific-value",
            "heating value, gross": "gross-calorific-value",
            "Net calorific value": "net-calorific-value",
            "HHV": "gross-calorific-value",
            "  lower   heating value  ": "net-calorific-value",
        }.items():
            with self.subTest(label=label):
                self.assertEqual(quantity_for_label(label), slug)

    def test_a_measurement_qualifier_in_parentheses_is_dropped(self):
        from brightway_flows.domain.quantities import quantity_for_label

        self.assertEqual(
            quantity_for_label("Specific weight (for absolutely dry, u=0%)"), "mass"
        )

    def test_a_label_the_file_does_not_spell_is_none(self):
        from brightway_flows.domain.quantities import quantity_for_label

        for label in ("wet mass", "carbon content, fossil", "Formula", "", "Synonyms"):
            with self.subTest(label=label):
                self.assertIsNone(quantity_for_label(label))


if __name__ == "__main__":
    unittest.main()
