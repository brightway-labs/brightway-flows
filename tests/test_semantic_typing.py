"""Substances whose classification is not in doubt, pinned.

The typing this replaced came from a regex over the preferred label, and its
failures were invisible: `Chloride` and `Sodium ion` are monoatomic ions by any
reading and went untyped, while five objects carrying no charge at all were
typed `MonoatomicIon`.  Nothing failed, so nothing said so.

These are that guard.  Each case is a substance a chemist would classify the
same way every time, so a rule change that breaks one is a regression rather
than a matter of taste.  The dirty cases -- the ones the rules genuinely cannot
place -- are pinned too, as *untyped with a named reason*, because "we do not
know" is a different answer from "we forgot to look".
"""

import gzip
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

import orjson
from pyld import jsonld

from brightway_flows.domain.context_registry import context_from_dict
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMINF_EC_NUMBER,
    CHEMROF_CHEMICAL_ELEMENT,
    CHEMROF_DECAY_MODE,
    CHEMROF_ELEMENTAL_CHARGE,
    CHEMROF_HALF_LIFE,
    CHEMROF_HAS_ELEMENT,
    CHEMROF_ISOMERIC_SMILES_STRING,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_NUCLEON_NUMBER,
    CHEMROF_SMILES_STRING,
    CHEMROF_SYMBOL,
    CLASS_TERMS,
    QUDT_HAS_UNIT,
    CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX,
    IRIS,
    SKOS_CONCEPT_IRI,
    Term,
    flow_object_iri,
)
from brightway_flows.pipeline.exporting import write_simple_export
from brightway_flows.pipeline.semantic_typing import (
    assign_semantic_types,
    classify,
    isomeric_values_in_graph_slot,
)

RDF_TYPE = "@type"

#: ChEBI's SMILES for L-tryptophan (CHEBI:16828), as the dump publishes it: it
#: carries `[C@@H]` and writes the indole nitrogen without its hydrogen, so
#: RDKit will not kekulise it.  The pair of properties #51 is about.
CHEBI_TRYPTOPHAN = "N[C@@H](Cc1cnc2ccccc12)C(=O)O"


def _prop(values: list[Any]) -> dict[str, Any]:
    return {"@value": values}


def make_object(
    *,
    label: str = "x",
    formula: str = "",
    smiles: str = "",
    charge: int | None = None,
    isotope: dict[str, Any] | None = None,
    cas: str = "",
    ec: str = "",
    types: list[str] | None = None,
    relationships: dict[str, Any] | None = None,
) -> FlowObject:
    properties: dict[str, Any] = {}
    if formula:
        properties[CHEMROF_MOLECULAR_FORMULA] = _prop([formula])
    if smiles:
        properties[CHEMROF_SMILES_STRING] = _prop([smiles])
    if charge is not None:
        properties[CHEMROF_ELEMENTAL_CHARGE] = _prop([charge])
    if isotope is not None:
        properties["isotope"] = isotope
    if relationships is not None:
        properties["relationships"] = relationships
    classifications: dict[str, Any] = {}
    if cas:
        classifications[CHEMINF_CAS_REGISTRY_NUMBER] = {"@value": [cas]}
    if ec:
        classifications[CHEMINF_EC_NUMBER] = {"@value": [ec]}
    return FlowObject(
        flow_object_id="fo-" + label.lower().replace(" ", "-")[:24],
        prefLabel=[{"@value": label, "@language": "en"}],
        altLabel=[],
        properties=properties,
        references=[],
        created_from={},
        classifications=classifications,
        types=types,
    )


class KnownSubstanceTestCase(unittest.TestCase):
    """One substance, one right answer."""

    def assertTypes(self, obj, expected, *, label="", slots=frozenset()):
        result = classify(obj, label=label or "x", context_slots=slots)
        self.assertEqual(
            list(result.types), list(expected),
            f"rule={result.rule!r} reason={result.reason!r}",
        )
        return result

    def test_carbon_dioxide_is_a_neutral_molecule(self):
        self.assertTypes(
            make_object(label="Carbon dioxide", formula="CO2", smiles="O=C=O", charge=0),
            [IRIS[Term.NEUTRAL_MOLECULE]],
        )

    def test_sodium_ion_is_an_atom_cation(self):
        """The label regex this replaced did not match "Sodium ion"."""
        self.assertTypes(
            make_object(label="Sodium ion", formula="Na", smiles="[Na+]", charge=1),
            [IRIS[Term.ATOM_CATION]],
        )

    def test_chloride_is_an_atom_anion(self):
        """Nor "Chloride" -- no charge in the name at all."""
        self.assertTypes(
            make_object(label="Chloride", formula="Cl", smiles="[Cl-]", charge=-1),
            [IRIS[Term.ATOM_ANION]],
        )

    def test_a_neutral_element_stays_an_element(self):
        self.assertTypes(
            make_object(
                label="Nickel", formula="Ni", charge=0,
                types=[CHEMROF_CHEMICAL_ELEMENT],
            ),
            [CHEMROF_CHEMICAL_ELEMENT],
        )

    def test_a_charged_element_is_only_an_ion(self):
        """`ChemicalElement` leaves charge unspecified, so it and a charge state
        are mutually exclusive.  This used to emit both, which was possible only
        because `FullySpecifiedAtom` claims a charge *is* stated -- and it never
        was, for these objects.
        """
        self.assertTypes(
            make_object(
                label="Nickel(2+)", formula="Ni", charge=2,
                types=[CHEMROF_CHEMICAL_ELEMENT],
            ),
            [IRIS[Term.ATOM_CATION]],
        )

    def test_ammonium_is_a_molecular_cation(self):
        self.assertTypes(
            make_object(label="Ammonium", formula="H4N", smiles="[NH4+]", charge=1),
            [IRIS[Term.MOLECULAR_CATION]],
        )

    def test_carbonate_is_a_molecular_anion(self):
        self.assertTypes(
            make_object(label="Carbonate ion", formula="CO3", smiles="[O-]C([O-])=O", charge=-2),
            [IRIS[Term.MOLECULAR_ANION]],
        )

    def test_sodium_chloride_is_a_salt(self):
        self.assertTypes(
            make_object(label="Sodium chloride", formula="ClNa", smiles="[Na+].[Cl-]", charge=0),
            [IRIS[Term.CHEMICAL_SALT]],
        )

    def test_a_neutral_two_component_structure_is_a_complex(self):
        self.assertTypes(
            make_object(
                label="Ethanol hydrate", formula="C2H8O2", smiles="CCO.O", charge=0,
            ),
            [IRIS[Term.MOLECULAR_COMPLEX]],
        )

    def test_ozone_is_an_allotrope_not_a_zwitterion(self):
        """Ozone's canonical SMILES separates formal charges that net to zero.

        The zwitterion test matches it, and "a zwitterion of oxygen" is not a
        thing -- so the single-element check has to come first.
        """
        self.assertTypes(
            make_object(label="Ozone", formula="O3", smiles="[O-][O+]=O", charge=0),
            [IRIS[Term.ALLOTROPE]],
        )

    def test_lead_2_plus_is_monoatomic_despite_the_charge_in_its_formula(self):
        """PubChem writes the charge into the formula: `Pb+2`, not `Pb`.

        A plain single-symbol test says that is not one atom, which sent lead
        and silver down the polyatomic branch in a 400-flow run.
        """
        self.assertTypes(
            make_object(label="Lead(2+)", formula="Pb+2", smiles="[Pb+2]", charge=2),
            [IRIS[Term.ATOM_CATION]],
        )

    def test_silver_1_plus_is_monoatomic(self):
        self.assertTypes(
            make_object(label="Silver(1+)", formula="Ag+", smiles="[Ag+]", charge=1),
            [IRIS[Term.ATOM_CATION]],
        )

    def test_a_nitro_compound_is_not_a_zwitterion(self):
        """`[N+](=O)[O-]` is a charge-separated resonance form, not a zwitterion.

        Nitroaromatics are everywhere in these lists, and a plain "contains both
        signs" test called ten of them zwitterions in a 400-flow run.
        """
        self.assertTypes(
            make_object(
                label="2-nitrophenol", formula="C6H5NO3",
                smiles="O=[N+]([O-])c1ccccc1O", charge=0,
            ),
            [IRIS[Term.NEUTRAL_MOLECULE]],
        )

    def test_a_di_nitro_compound_is_not_a_zwitterion_either(self):
        """Two nitro groups defeat a plain "the charges are not bonded" test.

        The nitrogen of one group is not bonded to the oxygen of the other, so
        adjacency alone still called 2,5-dinitrotoluene a zwitterion.  What
        matters is whether a charge stands *alone*: here every one is paired off
        against the one next to it.
        """
        self.assertTypes(
            make_object(
                label="2,5-dinitrotoluene", formula="C7H6N2O4",
                smiles="CC1=C(C=CC(=C1)[N+](=O)[O-])[N+](=O)[O-]", charge=0,
            ),
            [IRIS[Term.NEUTRAL_MOLECULE]],
        )

    def test_betaine_is_a_zwitterion(self):
        """The counter-case: charges several bonds apart, on different groups."""
        self.assertTypes(
            make_object(
                label="Betaine", formula="C5H11NO2",
                smiles="C[N+](C)(C)CC(=O)[O-]", charge=0,
            ),
            [IRIS[Term.ZWITTERION]],
        )

    def test_an_unparseable_structure_claims_nothing(self):
        """Better a plain molecule than a class read off a structure we cannot parse."""
        self.assertTypes(
            make_object(
                label="broken", formula="C2H5NO2", smiles="[NH3+]not-a-smiles[O-]",
                charge=0,
            ),
            [IRIS[Term.NEUTRAL_MOLECULE]],
        )

    def test_glycine_is_a_zwitterion(self):
        self.assertTypes(
            make_object(
                label="Glycine", formula="C2H5NO2",
                smiles="C(C(=O)[O-])[NH3+]", charge=0,
            ),
            [IRIS[Term.ZWITTERION]],
        )

    def test_a_decaying_nuclide_is_an_isotope_and_a_radionuclide(self):
        self.assertTypes(
            make_object(
                label="Americium-241",
                isotope={"mass_number": "241", "symbol": "Am",
                         "decay_modes": ["A"], "half_life_and_uncertainty": "432.6 a"},
            ),
            [IRIS[Term.ISOTOPE], IRIS[Term.RADIONUCLIDE]],
        )

    def test_a_stable_nuclide_is_an_isotope_only(self):
        self.assertTypes(
            make_object(label="Argon-40", isotope={"mass_number": "40", "symbol": "Ar"}),
            [IRIS[Term.ISOTOPE]],
        )

    def test_a_refrigerant_code_is_not_mistaken_for_a_nuclide(self):
        """"HCFC-123a" has the shape of "Americium-241" and is a molecule.

        This is why the isotope record decides, and never the label.
        """
        self.assertTypes(
            make_object(label="HCFC-123a", formula="C2HCl2F3", smiles="FC(F)(Cl)C(F)Cl", charge=0),
            [IRIS[Term.NEUTRAL_MOLECULE]],
        )

    def test_a_registered_substance_with_no_structure_is_a_uvcb(self):
        """Variable composition, unknown stoichiometry: the UVCB definition."""
        self.assertTypes(
            make_object(label="Alcohols, C12-15, ethoxylated", ec="500-195-7"),
            [IRIS[Term.IMPRECISE_CHEMICAL_MIXTURE]],
            label="Alcohols, C12-15, ethoxylated",
        )

    def test_a_structureless_resource_is_a_material(self):
        self.assertTypes(
            make_object(label="Basalt", cas="1302-74-5"),
            [IRIS[Term.MATERIAL]],
            label="Basalt",
            slots=frozenset({("Resource", "Ground")}),
        )

    def test_a_substance_class_is_a_grouping_class(self):
        self.assertTypes(
            make_object(label="Aldehydes, unspecified"),
            [IRIS[Term.MOLECULE_GROUPING_CLASS]],
            label="Aldehydes, unspecified",
        )

    def test_a_class_of_elements_groups_atoms_not_molecules(self):
        self.assertTypes(
            make_object(label="Actinides, radioactive, unspecified"),
            [IRIS[Term.ATOM_GROUPING_CLASS]],
            label="Actinides, radioactive, unspecified",
        )

    def test_parenthesised_unspecified_is_the_same_statement(self):
        """`Hydrocarbons (unspecified)` says what `Aldehydes, Unspecified` says."""
        self.assertTypes(
            make_object(label="Hydrocarbons (unspecified)"),
            [IRIS[Term.MOLECULE_GROUPING_CLASS]],
            label="Hydrocarbons (unspecified)",
        )

    def test_a_qualified_parenthesis_still_counts(self):
        """`(unspecified, ...)` is the parenthesised form of the `, Unspecified`
        suffix, and the trailing qualification does not stop it matching.

        The example was `Nitrogenous Matter (unspecified, As N)` until #68,
        which is now a curated aggregate measurement: `(as N)` says the number
        is a mass of nitrogen counted across an unstated set of molecules, and a
        class over molecules is the near miss.  The regex is unchanged, so it
        needs a case that still reaches it.
        """
        self.assertTypes(
            make_object(label="Hydrocarbons (unspecified)"),
            [IRIS[Term.MOLECULE_GROUPING_CLASS]],
            label="Hydrocarbons (unspecified)",
        )

    def test_the_singular_compound_is_a_class_too(self):
        """`Volatile Organic Compound` -- the plural was the only form matched."""
        self.assertTypes(
            make_object(label="Volatile Organic Compound"),
            [IRIS[Term.MOLECULE_GROUPING_CLASS]],
            label="Volatile Organic Compound",
        )

    def test_radioactive_species_group_nuclides_not_molecules(self):
        """The same answer #238 gives the alpha-emitter aggregates."""
        self.assertTypes(
            make_object(label="Radioactive Species, Alpha Emitters"),
            [IRIS[Term.ATOM_GROUPING_CLASS]],
            label="Radioactive Species, Alpha Emitters",
        )

    def test_a_family_noun_alone_is_a_class_when_nothing_else_identifies_it(self):
        self.assertTypes(
            make_object(label="Hydrocarbons, Aromatic"),
            [IRIS[Term.MOLECULE_GROUPING_CLASS]],
            label="Hydrocarbons, Aromatic",
        )

    def test_a_registered_uvcb_keeps_its_class_despite_the_family_noun(self):
        """The guard that makes the wider net safe.

        `Fatty Acids, Tallow, Zinc Salts` and `Hydrocarbons, C4` are registered
        substances of variable composition, not categories.  Matching `salts`
        and `hydrocarbons` unconditionally takes 39 of these away from
        `ImpreciseChemicalMixture` -- measured against the full build, not
        guessed -- so the weak patterns only apply where rule 10 finds nothing.
        """
        for label in ("Fatty Acids, Tallow, Zinc Salts", "Hydrocarbons, C4"):
            with self.subTest(label=label):
                self.assertTypes(
                    make_object(label=label, ec="268-098-9"),
                    [IRIS[Term.IMPRECISE_CHEMICAL_MIXTURE]],
                    label=label,
                )

    def test_an_explicit_class_label_outranks_a_registry_identifier(self):
        """`Tributyltin Compounds` has an EC number for the *class*.

        Only the weak patterns defer to a registry identifier.  A label that
        says "compounds" or "unspecified" is settling the question itself, and
        an authority registering the category does not unsettle it.
        """
        self.assertTypes(
            make_object(label="Tributyltin Compounds", ec="268-098-9"),
            [IRIS[Term.MOLECULE_GROUPING_CLASS]],
            label="Tributyltin Compounds",
        )


class GroupingClassIsStillAFlowObjectTestCase(unittest.TestCase):
    """A grouping class is a class *and* a flow object with elementary flows.

    `Aldehydes, unspecified` names a category of substance rather than a
    substance, and `MoleculeGroupingClass` says so.  That is a statement about
    what it is, not a licence to model it differently: the source lists emit
    against it, LCIA methods characterise it, and the harmonised list has to
    carry those rows.  Typing it must not become a reason to drop them.

    Pinned because the tempting next step -- "a class is not a thing, so it
    should not have a flow object" -- would silently delete real inventory.
    """

    def setUp(self):
        self.obj = make_object(label="Aldehydes, unspecified", cas="75-07-0")
        assign_semantic_types([self.obj], [])

    def test_it_is_typed_as_a_grouping_class(self):
        self.assertEqual(self.obj.types, [IRIS[Term.MOLECULE_GROUPING_CLASS]])

    def test_it_keeps_its_flow_object_identity(self):
        self.assertTrue(self.obj.flow_object_id)

    def test_it_keeps_its_registry_identifiers(self):
        """Typing it a class does not make its CAS number stop being real."""
        self.assertIn(CHEMINF_CAS_REGISTRY_NUMBER, self.obj.classifications)

    def test_the_export_publishes_it_as_a_concept_like_any_other(self):
        """`skos:Concept` first, then the grouping class -- the same shape every
        other flow gets, so a consumer needs no special case to read it."""
        from brightway_flows.domain.vocabulary import SKOS_CONCEPT_IRI

        published = [SKOS_CONCEPT_IRI, *self.obj.types]
        self.assertEqual(
            published, [SKOS_CONCEPT_IRI, IRIS[Term.MOLECULE_GROUPING_CLASS]]
        )


class DeliberatelyUntypedTestCase(unittest.TestCase):
    """"We do not know" is an answer, and it has to be a named one."""

    def test_a_land_use_class_is_not_a_chemical_entity(self):
        result = classify(
            make_object(label="Arable, irrigated"),
            label="Arable, irrigated",
            context_slots=frozenset({("Land Use", "")}),
        )
        self.assertEqual(result.types, ())
        self.assertEqual(result.reason, "land_use_not_a_chemical_entity")

    def test_a_flow_with_neither_structure_nor_identifier_says_so(self):
        result = classify(make_object(label="From unspecified"), label="From unspecified")
        self.assertEqual(result.types, ())
        self.assertEqual(result.reason, "no_structure_and_no_registry_identifier")

    def test_every_non_chemical_dimension_names_itself(self):
        """`Labour Cost` is not a substance whose identity is too thin to read.

        Land use was the only dimension named, so `Economic` and
        `Inventory Indicator` fell through to
        `no_structure_and_no_registry_identifier` -- "we could not tell what
        this is", which is untrue of rent and exported heat.  We can tell
        exactly what they are; they are not chemistry.
        """
        cases = [
            ("Labour Cost", "Economic", "economic_not_a_chemical_entity"),
            (
                "Exported Energy - Heat",
                "Inventory Indicator",
                "inventory_indicator_not_a_chemical_entity",
            ),
            ("Arable, irrigated", "Land Use", "land_use_not_a_chemical_entity"),
        ]
        for label, dimension, expected in cases:
            with self.subTest(dimension=dimension):
                result = classify(
                    make_object(label=label),
                    label=label,
                    context_slots=frozenset({(dimension, "")}),
                )
                self.assertEqual(result.types, ())
                self.assertEqual(result.reason, expected)

    def test_two_non_chemical_dimensions_blame_neither(self):
        result = classify(
            make_object(label="Recovered Energy"),
            label="Recovered Energy",
            context_slots=frozenset({("Economic", ""), ("Inventory Indicator", "")}),
        )
        self.assertEqual(result.reason, "not_a_chemical_entity")

    def test_traffic_noise_is_not_a_thin_identity_either(self):
        """#70: six BAFU rows said "we could not tell what this is".

        `Noise, Road, Lorry, Average` has no formula, no mass and no registry
        number because it is not matter -- not because its identity is too thin
        to read.  BAFU files all six under a compartment it calls `non material
        emissions`, which maps to `Environmental / Other`.
        """
        for label in (
            "Noise, Aircraft, Freight",
            "Noise, Rail, Passenger Train, Average",
            "Noise, Road, Lorry, Average",
        ):
            with self.subTest(label=label):
                result = classify(
                    make_object(label=label),
                    label=label,
                    context_slots=frozenset({("Environmental", "Other")}),
                )
                self.assertEqual(result.types, ())
                self.assertEqual(
                    result.reason,
                    "non_material_intervention_not_a_chemical_entity",
                )

    def test_only_the_other_medium_of_environmental_leaves_chemistry(self):
        """The carve-out is a `(dimension, media)` slot, not the dimension.

        Everything else on `Environmental` is a substance released into a
        medium, and a rule that read the dimension alone would untype the whole
        list.
        """
        for media in ("Air", "Water", "Ground", "Biotic", "Product"):
            with self.subTest(media=media):
                result = classify(
                    make_object(label="Carbon dioxide", formula="CO2", smiles="O=C=O"),
                    label="Carbon dioxide",
                    context_slots=frozenset({("Environmental", media)}),
                )
                self.assertEqual(list(result.types), [IRIS[Term.NEUTRAL_MOLECULE]])

    def test_a_substance_also_emitted_to_a_medium_keeps_its_chemistry(self):
        """One non-material context does not make the substance non-material."""
        result = classify(
            make_object(label="Carbon dioxide", formula="CO2", smiles="O=C=O"),
            label="Carbon dioxide",
            context_slots=frozenset({
                ("Environmental", "Other"), ("Environmental", "Air"),
            }),
        )
        self.assertEqual(list(result.types), [IRIS[Term.NEUTRAL_MOLECULE]])

    def test_a_non_material_flow_and_a_land_use_flow_blame_neither(self):
        result = classify(
            make_object(label="Noise, Road, Lorry, Average"),
            label="Noise, Road, Lorry, Average",
            context_slots=frozenset({("Environmental", "Other"), ("Land Use", "")}),
        )
        self.assertEqual(result.types, ())
        self.assertEqual(result.reason, "not_a_chemical_entity")

    def test_an_environmental_flow_is_never_swept_up_by_the_dimension_rule(self):
        """The rule needs *every* context to count something other than a substance."""
        result = classify(
            make_object(label="Carbon dioxide", formula="CO2", smiles="O=C=O"),
            label="Carbon dioxide",
            context_slots=frozenset({("Environmental", "Air"), ("Land Use", "")}),
        )
        self.assertEqual(list(result.types), [IRIS[Term.NEUTRAL_MOLECULE]])

    def test_an_aggregate_measurement_is_not_a_thin_identity(self):
        """A quantity defined by the method that measures it, not a substance.

        No ChemROF class fits `Chemical Oxygen Demand` or `Particles (PM2.5)`
        -- the nearest, `ImpreciseChemicalMixture`, is a portion of matter --
        so these carry the one class this project mints.  A class rather than a
        recorded reason because a reason is not published: an untyped row says
        nothing a consumer can exclude from a query for substances, and being
        excluded from one is what these need saying about them (#68).
        """
        for label in (
            "Chemical Oxygen Demand",
            "Total Organic Carbon",
            "Particles (PM2.5)",
            "Phosphorus, Total",
            "Dissolved Solids",
            "Nitrogen, Organic Bound",
            "Benzene (as BTEX)",
            "AOX, Adsorbable Organic Halogen as Cl",
            "Acidity, Unspecified",
            "Acid (as H+)",
        ):
            with self.subTest(label=label):
                result = classify(make_object(label=label), label=label)
                self.assertEqual(
                    list(result.types), [IRIS[Term.AGGREGATE_MEASUREMENT]]
                )
                self.assertEqual(result.rule, "aggregate_measurement")

    def test_the_curated_name_is_matched_however_the_source_spelled_it(self):
        """BAFU writes `as Cl`; the preferred label reads `As Cl`.

        Case and whitespace are normalised, so a curator writes the name as the
        source has it and the harmonised spelling still matches.  Nothing
        weaker: a containment test would make `Benzene` match `Benzene (as
        BTEX)` and merge the row this exists to keep apart.
        """
        for label in (
            "AOX, Adsorbable Organic Halogen As Cl",
            "aox,  adsorbable organic halogen as cl",
        ):
            with self.subTest(label=label):
                result = classify(make_object(label=label), label=label)
                self.assertEqual(result.rule, "aggregate_measurement")

        benzene = classify(
            make_object(label="Benzene", formula="C6H6", smiles="c1ccccc1", charge=0),
            label="Benzene",
        )
        self.assertEqual(list(benzene.types), [IRIS[Term.NEUTRAL_MOLECULE]])

    def test_organic_bound_nitrogen_is_a_quantity_and_not_nitrogen_gas(self):
        """#57, and the reason the CAS had to come off at source.

        The nitrogen held inside a discharge's organic matter is a nutrient
        load summed over proteins, urea and amino acids -- not a compound, and
        so not something a registry number can name.  EF 3.1 gave its rows
        7727-37-9, which is dinitrogen's, and every rule that reads chemistry
        then read them as the inert gas: with the number and the structure it
        pulls in, the object is a molecule three rules earlier and this one
        never runs.
        """
        as_shipped = make_object(
            label="Nitrogen, Organic Bound",
            cas="7727-37-9", formula="N2", smiles="N#N", charge=0,
        )
        self.assertEqual(
            list(classify(as_shipped, label="Nitrogen, Organic Bound").types),
            [IRIS[Term.AGGREGATE_MEASUREMENT]],
        )

        corrected = classify(
            make_object(label="Nitrogen, Organic Bound"),
            label="Nitrogen, Organic Bound",
        )
        self.assertEqual(
            list(corrected.types), [IRIS[Term.AGGREGATE_MEASUREMENT]]
        )

    def test_the_curated_decision_outranks_the_chemistry_it_arrived_with(self):
        """The whole reason the rule is third rather than last (#68).

        The label rule this replaced ran after everything, so it only ever saw
        rows nothing else had claimed -- and the rows that most needed it were
        exactly the ones a registry number had already claimed.  `Acid (as H+)`
        was published as a `NeutralMolecule` carrying the hydron's structure and
        `COD, Chemical Oxygen Demand` as an `ImpreciseChemicalMixture`, both off
        a number that names no compound.  A curated decision has to beat a
        structure, or it does not reach the objects it is for.
        """
        acid = classify(
            make_object(
                label="Acid (as H+)", cas="12408-02-5", formula="H", smiles="[H+]",
            ),
            label="Acid (as H+)",
        )
        self.assertEqual(list(acid.types), [IRIS[Term.AGGREGATE_MEASUREMENT]])

        cod = classify(
            make_object(label="COD, Chemical Oxygen Demand", cas="17612-50-9"),
            label="COD, Chemical Oxygen Demand",
        )
        self.assertEqual(list(cod.types), [IRIS[Term.AGGREGATE_MEASUREMENT]])

    def test_a_name_that_merely_looks_like_a_measurement_is_left_to_chemistry(self):
        """Curation is the point: an unlisted name gets no special treatment.

        `Particles, Total` would have matched the `, total` branch of the regex
        this replaced.  It is not in the file, so the chemistry places it --
        which is the behaviour a pattern cannot offer, because a pattern cannot
        be told about `Alkoxylation Reaction Product of Glycerin as Starter`.
        """
        result = classify(
            make_object(label="Particles, Total", formula="CO2", smiles="O=C=O"),
            label="Particles, Total",
        )
        self.assertEqual(list(result.types), [IRIS[Term.NEUTRAL_MOLECULE]])

    def test_a_land_use_flow_is_not_swept_into_uvcb_by_a_stray_cas(self):
        """Rule order matters: land use is checked before "registered"."""
        result = classify(
            make_object(label="Agriculture", cas="7732-18-5"),
            label="Agriculture",
            context_slots=frozenset({("Land Use", "")}),
        )
        self.assertEqual(result.types, ())


class NuclidePropertiesTestCase(unittest.TestCase):
    """Isotope data has sat in an untyped bag; ChemROF has slots for most of it."""

    def setUp(self):
        self.obj = make_object(
            label="Americium-241",
            isotope={
                "mass_number": "241", "symbol": "Am", "decay_modes": ["A", "SF"],
                "half_life_and_uncertainty": "432.6 a",
                "specific_activity_bq_per_g": "1.27e11",
            },
            relationships={"parent_element_flow_object_id": "fo-americium"},
        )
        assign_semantic_types([self.obj], [])

    def test_mass_number_becomes_nucleon_number(self):
        self.assertEqual(self.obj.properties[CHEMROF_NUCLEON_NUMBER]["@value"], [241])

    def test_symbol_and_decay_mode_move_onto_their_slots(self):
        self.assertEqual(self.obj.properties[CHEMROF_SYMBOL]["@value"], ["Am"])
        self.assertEqual(self.obj.properties[CHEMROF_DECAY_MODE]["@value"], ["A", "SF"])

    def test_the_element_link_uses_the_chemrof_predicate(self):
        """It was `relationships.parent_element_flow_object_id`, a home-grown key."""
        self.assertEqual(
            self.obj.properties[CHEMROF_HAS_ELEMENT]["@value"],
            [{"@id": flow_object_iri("fo-americium")}],
        )

    def test_the_element_link_is_a_node_and_not_a_string(self):
        """A bare `flow_object_id` expands to a literal, so the link went nowhere.

        `has_element` ranges over `ChemicalElement`, a class -- so the value has
        to be something a consumer can follow.  The export flattens the entry to
        its `@value`, which made the published triple
        `<flow> chemrof:has_element "fo-americium"`.
        """
        [value] = self.obj.properties[CHEMROF_HAS_ELEMENT]["@value"]
        self.assertIsInstance(value, dict)
        self.assertTrue(value["@id"].startswith("https://"))

    def test_the_original_bag_is_left_alone(self):
        """It still holds specific activity and the half-life, which have no slot."""
        self.assertEqual(
            self.obj.properties["isotope"]["specific_activity_bq_per_g"], "1.27e11"
        )

    def test_half_life_is_published_as_a_float(self):
        """`NumberOfYears` is `xsd:int`, and 432.6 years is not an integer.

        A wrong number, no number, or a float the declared range does not
        permit.  The float is the only one that tells the truth.
        """
        value = self.obj.properties[CHEMROF_HALF_LIFE]["@value"]
        self.assertEqual(len(value), 1)
        self.assertAlmostEqual(value[0], 432.6, places=1)
        self.assertIsInstance(value[0], float)

    def test_the_half_life_carries_the_unit_that_says_years(self):
        entry = self.obj.properties[CHEMROF_HALF_LIFE]
        self.assertEqual(
            entry[QUDT_HAS_UNIT], "https://vocab.brightway.one/units/unit/YR"
        )

    def test_the_exact_string_is_still_in_the_bag(self):
        """The float is derived; the uncertainty it drops is not recoverable."""
        self.assertEqual(
            self.obj.properties["isotope"]["half_life_and_uncertainty"], "432.6 a"
        )

    def test_every_written_property_carries_provenance(self):
        for key in (CHEMROF_NUCLEON_NUMBER, CHEMROF_SYMBOL, CHEMROF_DECAY_MODE,
                    CHEMROF_HAS_ELEMENT):
            with self.subTest(property=key):
                provenance = self.obj.properties[key]["provenance"]
                self.assertIn("prov:wasGeneratedBy", provenance)
                self.assertIn("prov:wasDerivedFrom", provenance)


class IsomericSmilesTestCase(unittest.TestCase):
    """ChemROF says `smiles_string` carries no chirality.  We put chirality in it.

    "A string encoding of a molecular graph, no chiral or isotopic
    information" -- and 2,204 flow objects stored `C[C@H]1CO[C@H]2...` there.
    `isomeric_smiles_string`, declared `is_a: smiles_string`, is the slot for
    those, so this is a move rather than a new claim.
    """

    def _split(self, smiles: str) -> FlowObject:
        obj = make_object(label="x", smiles=smiles)
        assign_semantic_types([obj], [])
        return obj

    def test_a_chiral_smiles_moves_to_the_isomeric_slot(self):
        obj = self._split("C[C@H]1CO[C@H]2CCCC2O1")
        self.assertEqual(
            obj.properties[CHEMROF_ISOMERIC_SMILES_STRING]["@value"],
            ["C[C@H]1CO[C@H]2CCCC2O1"],
        )

    def test_the_graph_slot_keeps_the_same_structure_without_the_stereochemistry(self):
        """Computed by RDKit, not by deleting characters from the string."""
        obj = self._split("C[C@H]1CO[C@H]2CCCC2O1")
        self.assertEqual(
            obj.properties[CHEMROF_SMILES_STRING]["@value"], ["CC1COC2CCCC2O1"]
        )

    def test_double_bond_configuration_counts_as_isomeric(self):
        obj = self._split("F/C=C/F")
        self.assertEqual(obj.properties[CHEMROF_SMILES_STRING]["@value"], ["FC=CF"])
        self.assertEqual(
            obj.properties[CHEMROF_ISOMERIC_SMILES_STRING]["@value"], ["F/C=C/F"]
        )

    def test_an_isotopic_label_counts_as_isomeric(self):
        """ChemROF names this case outright: "E.g. [13C] for carbon-13"."""
        obj = self._split("[13CH4]")
        self.assertEqual(
            obj.properties[CHEMROF_ISOMERIC_SMILES_STRING]["@value"], ["[13CH4]"]
        )

    def test_a_plain_smiles_is_left_alone(self):
        obj = self._split("O=C=O")
        self.assertEqual(obj.properties[CHEMROF_SMILES_STRING]["@value"], ["O=C=O"])
        self.assertNotIn(CHEMROF_ISOMERIC_SMILES_STRING, obj.properties)

    def test_charge_is_not_stereochemistry(self):
        """Ozone's `[O-][O+]=O` is its graph, not a claim about its chirality."""
        obj = self._split("[O-][O+]=O")
        self.assertNotIn(CHEMROF_ISOMERIC_SMILES_STRING, obj.properties)

    def test_no_graph_is_invented_for_a_structure_rdkit_cannot_read(self):
        """There is no graph-only form of a string that is not a molecule.

        Claiming nothing beats claiming a structure we could not read -- the
        same fallback `_is_zwitterion` takes.
        """
        obj = self._split(CHEBI_TRYPTOPHAN)
        self.assertNotIn(CHEMROF_SMILES_STRING, obj.properties)

    def test_an_unreadable_structure_still_leaves_the_slot_that_denies_its_shape(self):
        """ChEBI's L-tryptophan: `[C@@H]`, and an indole N that will not kekulise.

        Being unable to compute the graph is a reason to publish no graph. It
        was being read as a reason to publish the stereochemistry as one (#51).
        """
        obj = self._split(CHEBI_TRYPTOPHAN)
        self.assertEqual(
            obj.properties[CHEMROF_ISOMERIC_SMILES_STRING]["@value"],
            [CHEBI_TRYPTOPHAN],
        )

    def test_a_readable_graph_beside_it_is_what_the_slot_keeps(self):
        """The build's actual shape: PubChem's flat form and ChEBI's unreadable
        stereo string in one slot.  The first is the graph, the second is not."""
        obj = make_object(label="x")
        obj.properties = {
            CHEMROF_SMILES_STRING: _prop(
                ["NC(Cc1c[nH]c2ccccc12)C(=O)O", CHEBI_TRYPTOPHAN]
            )
        }
        assign_semantic_types([obj], [])
        self.assertEqual(
            obj.properties[CHEMROF_SMILES_STRING]["@value"],
            ["NC(Cc1c[nH]c2ccccc12)C(=O)O"],
        )
        self.assertEqual(
            obj.properties[CHEMROF_ISOMERIC_SMILES_STRING]["@value"],
            [CHEBI_TRYPTOPHAN],
        )

    def test_a_string_that_is_not_a_structure_at_all_is_still_not_a_graph(self):
        obj = self._split("not/a/smiles[")
        self.assertNotIn(CHEMROF_SMILES_STRING, obj.properties)
        self.assertEqual(
            obj.properties[CHEMROF_ISOMERIC_SMILES_STRING]["@value"],
            ["not/a/smiles["],
        )

    def test_the_graph_slot_claims_only_what_it_derived(self):
        """A value RDKit could not read is not a source this run derived from."""
        obj = make_object(label="x")
        obj.properties = {
            CHEMROF_SMILES_STRING: _prop(["C[C@H]1CO[C@H]2CCCC2O1", CHEBI_TRYPTOPHAN])
        }
        assign_semantic_types([obj], [])
        provenance = obj.properties[CHEMROF_SMILES_STRING]["provenance"]
        records = provenance if isinstance(provenance, list) else [provenance]
        derived = [
            r for r in records
            if r.get("prov:wasDerivedFrom") == "smiles_string.stereochemistry_removed"
        ]
        self.assertEqual(
            [r["prov:hadPrimarySource"] for r in derived], [["C[C@H]1CO[C@H]2CCCC2O1"]]
        )

    def test_the_isomeric_slot_keeps_what_it_already_held(self):
        """The merge re-runs this over records already split, and a stereo value
        arriving then must not replace the ones the slot was holding."""
        obj = make_object(label="x")
        obj.properties = {
            CHEMROF_SMILES_STRING: _prop(["C[C@H]1CO[C@H]2CCCC2O1"]),
            CHEMROF_ISOMERIC_SMILES_STRING: _prop(["F/C=C/F"]),
        }
        assign_semantic_types([obj], [])
        self.assertEqual(
            obj.properties[CHEMROF_ISOMERIC_SMILES_STRING]["@value"],
            ["F/C=C/F", "C[C@H]1CO[C@H]2CCCC2O1"],
        )

    def test_the_measure_reads_the_published_record(self):
        """What a run reports as `objects_with_stereochemistry_in_smiles`."""
        obj = self._split(CHEBI_TRYPTOPHAN)
        self.assertEqual(isomeric_values_in_graph_slot(obj.properties), 0)
        self.assertEqual(
            isomeric_values_in_graph_slot(
                {CHEMROF_SMILES_STRING: _prop(["CCO", CHEBI_TRYPTOPHAN])}
            ),
            1,
        )

    def test_two_stereoisomers_do_not_leave_a_duplicate_graph(self):
        obj = make_object(label="x")
        obj.properties = {
            CHEMROF_SMILES_STRING: _prop(["C[C@@H](N)C(=O)O", "C[C@H](N)C(=O)O"])
        }
        assign_semantic_types([obj], [])
        self.assertEqual(
            obj.properties[CHEMROF_SMILES_STRING]["@value"], ["CC(N)C(=O)O"]
        )
        self.assertEqual(
            obj.properties[CHEMROF_ISOMERIC_SMILES_STRING]["@value"],
            ["C[C@@H](N)C(=O)O", "C[C@H](N)C(=O)O"],
        )

    def test_both_slots_carry_provenance_for_the_move(self):
        obj = self._split("C[C@H]1CO[C@H]2CCCC2O1")
        for key in (CHEMROF_SMILES_STRING, CHEMROF_ISOMERIC_SMILES_STRING):
            with self.subTest(property=key):
                provenance = obj.properties[key]["provenance"]
                records = provenance if isinstance(provenance, list) else [provenance]
                self.assertTrue(
                    any("smiles_string" in r.get("prov:wasDerivedFrom", "")
                        for r in records)
                )

    def test_running_it_twice_changes_nothing(self):
        """The merge writes flows by a path that runs the export's normalisation
        again, so every one of these has to be idempotent."""
        obj = self._split("C[C@H]1CO[C@H]2CCCC2O1")
        before = orjson.dumps(obj.properties, option=orjson.OPT_SORT_KEYS)
        assign_semantic_types([obj], [])
        self.assertEqual(
            orjson.dumps(obj.properties, option=orjson.OPT_SORT_KEYS), before
        )

    def test_classification_is_unchanged_by_the_move(self):
        """A stereo SMILES and its flat form classify the same, so re-running the
        typing over already-split data cannot change what anything is."""
        chiral = make_object(label="x", formula="C6H12O6", smiles="OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O")
        flat = make_object(label="x", formula="C6H12O6", smiles="OCC1OC(O)C(O)C(O)C1O")
        self.assertEqual(
            list(classify(chiral, label="x").types),
            list(classify(flat, label="x").types),
        )


class ElementChargeTestCase(unittest.TestCase):
    """`ChemicalElement` leaves the charge unspecified, and so does the data."""

    def test_the_charge_statement_is_withdrawn(self):
        """Saying the charge is zero would make it an `UnchargedAtom` instead,
        which is a claim this project has no grounds for."""
        obj = make_object(
            label="Hafnium", formula="Hf", charge=0,
            types=[CHEMROF_CHEMICAL_ELEMENT],
        )
        assign_semantic_types([obj], [])
        self.assertEqual(obj.types, [CHEMROF_CHEMICAL_ELEMENT])
        self.assertNotIn(CHEMROF_ELEMENTAL_CHARGE, obj.properties)

    def test_a_charged_ion_keeps_its_charge(self):
        """Only the element rule withdraws it.  An ion's charge is the point."""
        obj = make_object(
            label="Nickel(2+)", formula="Ni", charge=2,
            types=[CHEMROF_CHEMICAL_ELEMENT],
        )
        assign_semantic_types([obj], [])
        self.assertEqual(obj.types, [IRIS[Term.ATOM_CATION]])
        self.assertIn(CHEMROF_ELEMENTAL_CHARGE, obj.properties)

    def test_a_molecule_keeps_its_charge(self):
        obj = make_object(
            label="Carbon dioxide", formula="CO2", smiles="O=C=O", charge=0
        )
        assign_semantic_types([obj], [])
        self.assertEqual(obj.types, [IRIS[Term.NEUTRAL_MOLECULE]])
        self.assertIn(CHEMROF_ELEMENTAL_CHARGE, obj.properties)


class ProvenanceTestCase(unittest.TestCase):
    def test_the_rule_that_fired_is_recorded_on_the_object(self):
        obj = make_object(label="Carbon dioxide", formula="CO2", smiles="O=C=O", charge=0)
        assign_semantic_types([obj], [])
        recorded = obj.created_from["semantic_typing"]
        self.assertEqual(recorded["rule"], "neutral_molecule")
        self.assertEqual(recorded["types"], [IRIS[Term.NEUTRAL_MOLECULE]])
        self.assertIn("prov:wasGeneratedBy", recorded["provenance"])

    def test_an_untyped_object_records_why(self):
        obj = make_object(label="From unspecified")
        assign_semantic_types([obj], [])
        recorded = obj.created_from["semantic_typing"]
        self.assertEqual(recorded["types"], [])
        self.assertEqual(recorded["reason"], "no_structure_and_no_registry_identifier")


class ContextDimensionsTestCase(unittest.TestCase):
    """Dimensions come from the occurrence, not the substance."""

    #: A dimension alone is not a context -- `Resource` and `Environmental` both
    #: require a medium -- so each row names the ground context of its dimension.
    #: The rule reads dimension and media, and the media are the same on both, so
    #: what varies between these rows is what the test says varies.
    EXTRACTED = context_from_dict({"dimension": "Resource", "media": "Ground"})
    EMITTED = context_from_dict(
        {"dimension": "Environmental", "media": "Ground", "geography": "Unknown"}
    )

    class _Row:
        def __init__(self, flow_object_id, context):
            self.flow_object_id = flow_object_id
            self.context = context

    def test_dimensions_are_read_from_the_elementary_flows(self):
        obj = make_object(label="Basalt", cas="1302-74-5")
        assign_semantic_types([obj], [self._Row(obj.flow_object_id, self.EXTRACTED)])
        self.assertEqual(obj.types, [IRIS[Term.MATERIAL]])

    def test_a_substance_seen_in_several_dimensions_is_not_a_material(self):
        """`Resource`-only is the rule; anything else means it is emitted too."""
        obj = make_object(label="Bentonite", cas="1302-78-9")
        assign_semantic_types(
            [obj],
            [
                self._Row(obj.flow_object_id, self.EXTRACTED),
                self._Row(obj.flow_object_id, self.EMITTED),
            ],
        )
        self.assertEqual(obj.types, [IRIS[Term.IMPRECISE_CHEMICAL_MIXTURE]])


class PublishedTypesTestCase(unittest.TestCase):
    """`@type` has to reach the export, and expand to `rdf:type`."""

    FLOW = {
        "uuid": "aaaaaaaa-0000-4000-8000-000000000001",
        "identifier": "aaaaaaaa-0000-4000-8000-000000000001",
        "source": "EF 3.1",
        "cas_numbers": ["124-38-9"],
        "ec_numbers": [],
        "context_iri": "https://vocab.brightway.one/flow-contexts/envi-air",
        "unit": "kg",
        "unit_iri": "https://vocab.brightway.one/units/unit/KiloGM",
        "prefLabel": [{"@value": "Carbon dioxide", "@language": "en"}],
        "altLabel": [],
        "properties": {},
        "references": [],
        "concept_associations": [],
        "@type": [IRIS[Term.NEUTRAL_MOLECULE]],
    }

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        db = root / "consensus-flows.sqlite3"
        connection = sqlite3.connect(db)
        connection.execute(
            "CREATE TABLE elementary_flows (uuid TEXT PRIMARY KEY, "
            "flow_object_id TEXT, flow_json TEXT)"
        )
        connection.execute(
            "INSERT INTO elementary_flows VALUES (?, ?, ?)",
            ("r-0", "fo", orjson.dumps(self.FLOW).decode()),
        )
        connection.commit()
        connection.close()
        output = root / "out.json.gz"
        write_simple_export(db, output)
        self.document = orjson.loads(gzip.decompress(output.read_bytes()))
        # `flatten`: the node arrays are `@included`, so `expand` returns the
        # wrapper and leaves the real nodes inside it.
        self.expanded = jsonld.flatten(self.document)

    def test_the_export_states_the_class(self):
        """`skos:Concept` first, then the substance class."""
        self.assertEqual(
            self.document["flows"][0][RDF_TYPE],
            [SKOS_CONCEPT_IRI, IRIS[Term.NEUTRAL_MOLECULE]],
        )

    def test_it_expands_to_an_rdf_type(self):
        node = next(
            n for n in self.expanded
            if n.get("@id")
            == f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{self.FLOW['identifier']}"
        )
        self.assertEqual(
            node["@type"], [SKOS_CONCEPT_IRI, IRIS[Term.NEUTRAL_MOLECULE]]
        )


class PublishedElementLinkTestCase(unittest.TestCase):
    """`has_element` has to reach the export as a link, not as a name.

    The export flattens a property entry to its `@value`, so a bare
    `flow_object_id` was published as the literal `"fo-sodium"` -- against a
    slot whose declared range is `ChemicalElement`, a class.  Nothing could
    follow it and no reasoner could use it.
    """

    FLOW: dict[str, Any] = {
        "uuid": "aaaaaaaa-0000-4000-8000-000000000002",
        "identifier": "aaaaaaaa-0000-4000-8000-000000000002",
        "source": "EF 3.1",
        "cas_numbers": [],
        "ec_numbers": [],
        "context_iri": "https://vocab.brightway.one/flow-contexts/envi-air",
        "unit": "kg",
        "unit_iri": "https://vocab.brightway.one/units/unit/KiloGM",
        "prefLabel": [{"@value": "Sodium ion", "@language": "en"}],
        "altLabel": [],
        "properties": {
            CHEMROF_HAS_ELEMENT: {"@value": [{"@id": flow_object_iri("fo-sodium")}]},
        },
        "references": [],
        "concept_associations": [],
        "@type": [IRIS[Term.ATOM_CATION]],
    }

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        db = root / "consensus-flows.sqlite3"
        connection = sqlite3.connect(db)
        connection.execute(
            "CREATE TABLE elementary_flows (uuid TEXT PRIMARY KEY, "
            "flow_object_id TEXT, flow_json TEXT)"
        )
        connection.execute(
            "INSERT INTO elementary_flows VALUES (?, ?, ?)",
            ("r-0", "fo", orjson.dumps(self.FLOW).decode()),
        )
        connection.commit()
        connection.close()
        output = root / "out.json.gz"
        write_simple_export(db, output)
        self.document = orjson.loads(gzip.decompress(output.read_bytes()))
        self.expanded = jsonld.flatten(self.document)

    def test_the_export_carries_a_node_reference(self):
        self.assertEqual(
            self.document["flows"][0]["properties"][CHEMROF_HAS_ELEMENT],
            {"@id": flow_object_iri("fo-sodium")},
        )

    def test_it_expands_to_a_link_and_not_a_literal(self):
        node = next(
            n for n in self.expanded
            if n.get("@id")
            == f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{self.FLOW['identifier']}"
        )
        self.assertEqual(
            node[CHEMROF_HAS_ELEMENT], [{"@id": flow_object_iri("fo-sodium")}]
        )


class RegistryTestCase(unittest.TestCase):
    def test_every_class_the_rules_can_emit_is_in_the_registry(self):
        """A class emitted but undeclared would not resolve in the context."""
        declared = {IRIS[term] for term in CLASS_TERMS}
        declared.add(CHEMROF_CHEMICAL_ELEMENT)
        cases = [
            make_object(label="a", formula="CO2", smiles="O=C=O", charge=0),
            make_object(label="b", formula="Na", smiles="[Na+]", charge=1),
            make_object(label="c", formula="Cl", smiles="[Cl-]", charge=-1),
            make_object(label="d", formula="H4N", smiles="[NH4+]", charge=1),
            make_object(label="e", formula="CO3", smiles="[O-]C([O-])=O", charge=-2),
            make_object(label="f", formula="ClNa", smiles="[Na+].[Cl-]", charge=0),
            make_object(label="g", formula="C2H8O2", smiles="CCO.O", charge=0),
            make_object(label="h", formula="O3", smiles="[O-][O+]=O", charge=0),
            make_object(label="i", formula="C2H5NO2", smiles="C(C(=O)[O-])[NH3+]", charge=0),
            make_object(label="j", isotope={"mass_number": "241", "decay_modes": ["A"]}),
            make_object(label="k", ec="500-195-7"),
        ]
        for obj in cases:
            for class_iri in classify(obj, label="Aldehydes, unspecified").types:
                with self.subTest(cls=class_iri):
                    self.assertIn(class_iri, declared)


if __name__ == "__main__":
    unittest.main()
