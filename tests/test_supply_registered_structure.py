"""The registry's structure fills a hole, where the registry knows the name (#71).

`supply_registered_composition` publishes what CAS says a substance is made of.
It refuses a multi-component formula, because `C15H24O6.C4H11N` is CAS stating
two substances in one string -- right for a UVCB, and wrong for a salt.  So
`Disodium Phosphonate` published a label and a number and nothing else, while
CAS held `InChIKey=NOMFAOXRBCOULH-UHFFFAOYSA-N` for 13708-85-5 throughout.

The half worth testing hardest is again the corroboration, and it is a
*different* gate from the composition step's: `corroborates_name` asks the name
to state a count, and none of the 35 substances in this population have a name
it accepts.  What they can meet is that CAS registers the substance under the
name this list gives it -- see `TheRegistryMustKnowTheName`, whose four cases
are the ones #129's docstring warns about, and `AndThatIsNotSufficient`, whose
three are the groups that pass it and must still be refused.

The payloads are the real cache records, trimmed to the fields the index reads.
"""

from __future__ import annotations

import unittest
from unittest import mock

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.vocabulary import (
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_INCHI2D_STRING,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_SMILES_STRING,
)
from brightway_flows.integrations.commonchemistry import (
    build_commonchemistry_index,
)
from brightway_flows.transformers.supply_registered_structure import (
    SupplyRegisteredStructureTransformer,
)

#: Real `detail_by_cas` records, trimmed.  Every value here is what Common
#: Chemistry actually publishes for the number.
DETAILS = {
    # A salt: definite, and written in two pieces because that is what a salt
    # looks like.  The case this step was added for.
    "13708-85-5": {
        "rn": "13708-85-5",
        "name": "Disodium hydrogen phosphite",
        "synonyms": ["Phosphonic acid, disodium salt", "Disodium phosphonate"],
        "molecularFormula": "H<sub>3</sub>O<sub>3</sub>P.2Na",
        "inchi": "InChI=1S/2Na.H3O3P/c;;1-4(2)3/h;;4H,(H2,1,2,3)",
        "inchiKey": "InChIKey=NOMFAOXRBCOULH-UHFFFAOYSA-N",
    },
    # A single molecule that already publishes the same composition.
    "946578-00-3": {
        "rn": "946578-00-3",
        "name": "Sulfoxaflor",
        "synonyms": [],
        "molecularFormula": "C<sub>10</sub>H<sub>10</sub>F<sub>3</sub>N<sub>3</sub>OS",
        "inchi": "InChI=1S/C10H10F3N3OS",
        "inchiKey": "InChIKey=ZVQOOHYFBIDMTQ-UHFFFAOYSA-N",
    },
    # The element's own number, which `Rhenium(2+)` carries.
    "7440-15-5": {
        "rn": "7440-15-5",
        "name": "Rhenium",
        "synonyms": ["Rhenium metal"],
        "molecularFormula": "Re",
        "inchi": "InChI=1S/Re",
        "inchiKey": "InChIKey=WUAPFZMCVAUBPE-UHFFFAOYSA-N",
    },
    # Carbon dioxide, which the delayed-emission correction flows carry.
    "124-38-9": {
        "rn": "124-38-9",
        "name": "Carbon dioxide",
        "synonyms": ["Carbonic anhydride"],
        "molecularFormula": "CO<sub>2</sub>",
        "inchi": "InChI=1S/CO2/c2-1-3",
        "inchiKey": "InChIKey=CURLTUGMZLYLDI-UHFFFAOYSA-N",
    },
    # Uranium.  This is the number `Uranium-238` carries, and CAS gives it the
    # *elemental* structure -- the #35 collision this step must not create.
    "24678-82-8": {
        "rn": "24678-82-8",
        "name": "Uranium",
        "synonyms": ["Uranium-238", "U-238"],
        "molecularFormula": "U",
        "inchi": "InChI=1S/U",
        "inchiKey": "InChIKey=JFALSRSLKYAFGM-UHFFFAOYSA-N",
    },
    # A UVCB CAS names as one: the InChI is the recipe the name lists.
    "101357-15-7": {
        "rn": "101357-15-7",
        "name": "Benzenamine, reaction products with aniline hydrochloride and nitrobenzene",
        "synonyms": [],
        "molecularFormula": "C<sub>6</sub>H<sub>7</sub>N.C<sub>6</sub>H<sub>7</sub>N.C<sub>6</sub>H<sub>5</sub>NO<sub>2</sub>.ClH",
        "inchi": "InChI=1S/C6H5NO2.2C6H7N.ClH",
        "inchiKey": "InChIKey=ICLILCPZDYQICM-UHFFFAOYSA-N",
    },
    # A mineral whose formula is a ratio: three-quarters of a magnesium against
    # an InChI holding one.
    "14807-96-6": {
        "rn": "14807-96-6",
        "name": "Talc (Mg<sub>3</sub>H<sub>2</sub>(SiO<sub>3</sub>)<sub>4</sub>)",
        "synonyms": ["Talc"],
        "molecularFormula": "H<sub>2</sub>O<sub>3</sub>Si.<sup>3</sup>/<sub>4</sub>Mg",
        "inchi": "InChI=1S/Mg.H2O3Si/c;1-4(2)3/h;1-2H",
        "inchiKey": "InChIKey=YOSWCTAKRWUBQU-UHFFFAOYSA-N",
    },
    # Hematite, where the registry's answer is vaguer than the pipeline's.
    "1317-60-8": {
        "rn": "1317-60-8",
        "name": "Hematite (Fe<sub>2</sub>O<sub>3</sub>)",
        "synonyms": ["Hematite"],
        "molecularFormula": "Fe.O",
        "inchi": "InChI=1S/Fe.O",
        "inchiKey": "InChIKey=UQSXHKLRYXJYBZ-UHFFFAOYSA-N",
    },
    # Tetracycline hydrochloride: the same salt this list writes the other way
    # round, which a string comparison would call a disagreement.
    "64-75-5": {
        "rn": "64-75-5",
        "name": "Tetracycline hydrochloride",
        "synonyms": [],
        "molecularFormula": "C<sub>22</sub>H<sub>24</sub>N<sub>2</sub>O<sub>8</sub>.ClH",
        "inchi": "InChI=1S/C22H24N2O8.ClH",
        "inchiKey": "InChIKey=IWVCMVBTMGNXQD-PXOLEDIWSA-N",
    },
}


def _flow(uuid, pref, *cas, properties=None):
    return Flow.from_dict({
        "uuid": uuid,
        "identifier": uuid,
        "source": "test",
        "unit": "kg",
        "prefLabel": [{"@value": pref, "@language": "en"}],
        "cas_numbers": list(cas),
        "properties": properties or {},
    })


def _formula(value):
    """A `properties` block publishing *value* as the molecular formula."""
    return {
        CHEMROF_MOLECULAR_FORMULA: {
            "@id": CHEMROF_MOLECULAR_FORMULA,
            "@value": [value],
        }
    }


class _Runs:
    def run_transformer(self, flows, details=None):
        transformer = SupplyRegisteredStructureTransformer()
        index = build_commonchemistry_index(
            {"detail_by_cas": DETAILS if details is None else details}
        )
        with mock.patch(
            "brightway_flows.transformers.supply_registered_structure"
            ".load_commonchemistry_index",
            return_value=index,
        ):
            transformer.setup()
            return transformer.transform(flows)

    def written(self, changes, uuid):
        for change in changes:
            if change.uuid == uuid and change.field == "properties":
                return change.new_value
        return None

    def value(self, changes, uuid, iri):
        properties = self.written(changes, uuid)
        if properties is None:
            return None
        entry = properties.get(iri)
        if entry is None:
            return None
        raw = entry["@value"]
        return raw[0] if isinstance(raw, list) else raw

    def assertRefused(self, changes, uuid):
        self.assertIsNone(self.written(changes, uuid))


class TheHoleIsFilled(_Runs, unittest.TestCase):
    """The case this step was added for."""

    def test_the_salt_gets_its_structure(self):
        flow = _flow("u-1", "Disodium Phosphonate", "13708-85-5")
        changes = self.run_transformer([flow])
        self.assertEqual(
            self.value(changes, "u-1", CHEMROF_INCHI2D_KEY_STRING),
            "NOMFAOXRBCOULH-UHFFFAOYSA-N",
        )
        self.assertEqual(
            self.value(changes, "u-1", CHEMROF_INCHI2D_STRING),
            "InChI=1S/2Na.H3O3P/c;;1-4(2)3/h;;4H,(H2,1,2,3)",
        )

    def test_the_key_is_published_without_its_display_prefix(self):
        """`InChIKey=` is a display convention, not part of the join key."""
        flow = _flow("u-2", "Disodium Phosphonate", "13708-85-5")
        key = self.value(self.run_transformer([flow]), "u-2", CHEMROF_INCHI2D_KEY_STRING)
        self.assertFalse(key.startswith("InChIKey="))

    def test_the_multi_component_composition_is_published_too(self):
        """The shape `registered_formula_for` refuses, which a salt has.

        Safe here and not there: everything reaching this point has been shown
        to be one substance -- CAS holds a single structure for the number and
        names the substance the way this list does.
        """
        flow = _flow("u-3", "Disodium Phosphonate", "13708-85-5")
        self.assertEqual(
            self.value(self.run_transformer([flow]), "u-3", CHEMROF_MOLECULAR_FORMULA),
            "H3O3P.2Na",
        )

    def test_no_mass_or_smiles_is_invented(self):
        """Both would have to be computed, and this step publishes only what CAS states."""
        flow = _flow("u-4", "Disodium Phosphonate", "13708-85-5")
        properties = self.written(self.run_transformer([flow]), "u-4")
        self.assertNotIn(CHEMROF_SMILES_STRING, properties)

    def test_it_is_attributed_to_the_registry(self):
        flow = _flow("u-5", "Disodium Phosphonate", "13708-85-5")
        entry = self.written(self.run_transformer([flow]), "u-5")[CHEMROF_INCHI2D_STRING]
        blob = str(entry.get("provenance"))
        self.assertIn("13708-85-5", blob)
        self.assertIn("CAS Common Chemistry", blob)

    def test_a_substance_with_only_a_formula_gains_an_identity(self):
        """The other half of the population, and the one that also fixes a type.

        `Sulfoxaflor` publishes `C10H10F3N3OS` and no structure, so it is typed
        as a mixture when it is a single molecule.
        """
        flow = _flow(
            "u-6", "Sulfoxaflor", "946578-00-3", properties=_formula("C10H10F3N3OS")
        )
        self.assertEqual(
            self.value(self.run_transformer([flow]), "u-6", CHEMROF_INCHI2D_KEY_STRING),
            "ZVQOOHYFBIDMTQ-UHFFFAOYSA-N",
        )

    def test_an_agreeing_formula_is_left_where_it_was_derived(self):
        """Its own value and its own attribution stand; only the hole is filled."""
        flow = _flow(
            "u-7", "Sulfoxaflor", "946578-00-3", properties=_formula("C10H10F3N3OS")
        )
        properties = self.written(self.run_transformer([flow]), "u-7")
        entry = properties[CHEMROF_MOLECULAR_FORMULA]
        self.assertNotIn("provenance", entry)


class ItOnlyEverFillsAHole(_Runs, unittest.TestCase):
    def test_a_flow_that_already_has_a_structure_is_left_alone(self):
        flow = _flow(
            "u-8",
            "Disodium Phosphonate",
            "13708-85-5",
            properties={
                CHEMROF_INCHI2D_KEY_STRING: {
                    "@id": CHEMROF_INCHI2D_KEY_STRING,
                    "@value": ["SOMEKEY-UHFFFAOYSA-N"],
                }
            },
        )
        self.assertRefused(self.run_transformer([flow]), "u-8")

    def test_a_number_the_registry_was_never_asked_about_writes_nothing(self):
        flow = _flow("u-9", "Disodium Phosphonate", "99999-99-9")
        self.assertRefused(self.run_transformer([flow]), "u-9")


class TheRegistryMustKnowTheName(_Runs, unittest.TestCase):
    """The gate, and the cases #129's docstring warns about.

    Each carries a number CAS holds a real structure for.  What stops the
    structure being published is that CAS does not know the substance by the
    name this list publishes it under.
    """

    def test_an_ion_does_not_take_its_element_s_structure(self):
        flow = _flow("u-10", "Rhenium(2+)", "7440-15-5")
        self.assertRefused(self.run_transformer([flow]), "u-10")

    def test_an_accounting_construct_does_not_take_carbon_dioxide_s(self):
        flow = _flow(
            "u-11",
            "Correction Flow For Delayed Emission Of Fossil Carbon Dioxide "
            "(within First 100 Years)",
            "124-38-9",
        )
        self.assertRefused(self.run_transformer([flow]), "u-11")

    def test_the_registry_s_own_name_is_accepted(self):
        flow = _flow("u-12", "Carbon Dioxide", "124-38-9")
        self.assertIsNotNone(self.written(self.run_transformer([flow]), "u-12"))

    def test_a_synonym_is_accepted_and_spelling_does_not_matter(self):
        """`Disodium Phosphonate` is CAS's synonym under a different casing."""
        flow = _flow("u-13", "disodium  phosphonate", "13708-85-5")
        self.assertIsNotNone(self.written(self.run_transformer([flow]), "u-13"))

    def test_two_numbers_reaching_two_structures_settle_nothing(self):
        flow = _flow("u-14", "Carbon Dioxide", "124-38-9", "7440-15-5")
        self.assertRefused(self.run_transformer([flow]), "u-14")


class AndThatIsNotSufficient(_Runs, unittest.TestCase):
    """Three groups pass the name gate and must still be refused.

    Each was found by running the rule over a full build.
    """

    def test_a_nuclide_does_not_take_its_element_s_structure(self):
        """CAS registers 24678-82-8 as `Uranium`, with the elemental key.

        Publishing it would make `Uranium-238` and uranium metal one substance
        to anyone joining on structure, which is #35.  `Uranium-238` is among
        CAS's own synonyms for the number, so the name gate lets it through.
        """
        flow = _flow("u-15", "Uranium-238", "24678-82-8")
        self.assertRefused(self.run_transformer([flow]), "u-15")

    def test_a_uvcb_the_registry_names_as_one_is_refused(self):
        flow = _flow(
            "u-16",
            "Benzenamine, Reaction Products With Aniline Hydrochloride And Nitrobenzene",
            "101357-15-7",
        )
        self.assertRefused(self.run_transformer([flow]), "u-16")

    def test_an_indefinite_stoichiometry_is_refused(self):
        """Talc's formula holds three-quarters of a magnesium; its InChI holds one."""
        flow = _flow("u-17", "Talc", "14807-96-6")
        self.assertRefused(self.run_transformer([flow]), "u-17")


class TheFlowSOwnCompositionIsRespected(_Runs, unittest.TestCase):
    def test_a_vaguer_registry_answer_does_not_replace_a_derived_one(self):
        """`Hematite` publishes `Fe2O3`; CAS registers `Fe.O`."""
        flow = _flow("u-18", "Hematite", "1317-60-8", properties=_formula("Fe2O3"))
        self.assertRefused(self.run_transformer([flow]), "u-18")

    def test_the_same_salt_written_the_other_way_round_is_not_a_disagreement(self):
        """`C22H24N2O8.HCl` and CAS's `C22H24N2O8.ClH` are one substance.

        Compared as compositions rather than as strings, which is the whole
        reason `registered_composition` is used here.
        """
        flow = _flow(
            "u-19",
            "Tetracycline Hydrochloride",
            "64-75-5",
            properties=_formula("C22H24N2O8.HCl"),
        )
        self.assertEqual(
            self.value(self.run_transformer([flow]), "u-19", CHEMROF_INCHI2D_KEY_STRING),
            "IWVCMVBTMGNXQD-PXOLEDIWSA-N",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
