"""The role axis: the allow-list, the resolver, and what must not be published.

Four things are worth a test here and one of them is unusual.

The allow-list is *data generated from ChEBI*, so the ordinary risk -- a typo in
a hand-written definition -- is handled by re-running the generator and
comparing. What that cannot catch is the judgement: which fourteen classes are
on the list. So the rejected roles are asserted absent by IRI, each with the
reason in the test name, because a later contributor adding `greenhouse gas`
because it looks obviously useful should have to delete an assertion that says
why it is not.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.flow_object import FlowObject, Role
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    IRIS,
    RDFS_LABEL_CURIE,
    RO_HAS_ROLE_IRI,
    Term,
    curie,
)
from brightway_flows.filesystem import CHEBI_JSON_GZ_FILEPATH
from brightway_flows.flow_layers.roles import (
    ROLES_DATA_PATH,
    assign_chebi_roles,
    load_allowed_roles,
    roles_for_cas,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
OBO = "http://purl.obolibrary.org/obo/"

#: Everything below the allow-list itself needs the real 49 MB ChEBI download,
#: which nothing else in the suite required before this module.  Skipped rather
#: than failed on a clean checkout, so `pytest` on a fresh clone reports what is
#: missing instead of erroring in collection.
needs_chebi = unittest.skipUnless(
    CHEBI_JSON_GZ_FILEPATH.exists(),
    f"needs {CHEBI_JSON_GZ_FILEPATH.name}; run 'brightway-flows chebi'",
)


def _chebi(accession: str) -> str:
    return f"{OBO}CHEBI_{accession}"


def _object(flow_object_id: str, *cas: str, roles=None) -> FlowObject:
    classifications = (
        {CHEMINF_CAS_REGISTRY_NUMBER: {"@value": list(cas)}} if cas else {}
    )
    return FlowObject(
        flow_object_id=flow_object_id,
        prefLabel=[],
        altLabel=[],
        properties={},
        references=[],
        created_from={},
        classifications=classifications,
        roles=roles,
    )


class PredicateTestCase(unittest.TestCase):
    """`RO:0000087`, borrowed and not minted."""

    def test_the_predicate_is_ros_has_role(self):
        """Validated against OLS4 before use, per `AGENTS.md`: "a relation
        between an independent continuant (the bearer) and a role, in which the
        role specifically depends on the bearer for its existence".

        Pinned by value because the whole argument for this design is that we
        publish the same relation ChEBI reads; an IRI drifting by a digit would
        leave a document that still validates and no longer means that.
        """
        self.assertEqual(RO_HAS_ROLE_IRI, f"{OBO}RO_0000087")
        self.assertEqual(IRIS[Term.HAS_ROLE], f"{OBO}RO_0000087")
        # `obo:` and not `ro:`: the registered `ro` prefix is `.../obo/RO_`, so
        # `ro: .../obo/` would make `ro:RO_0000087` re-expand to
        # `.../obo/RO_RO_0000087` against a registry-conformant context.
        self.assertEqual(curie(Term.HAS_ROLE), "obo:RO_0000087")

    def test_the_predicate_expands_in_the_published_context(self):
        """A key that does not expand contributes no triples, which is the
        defect `Namespace.BRIGHTWAY`'s docstring records for `context_iri`."""
        from brightway_flows.domain.vocabulary import JSONLD_CONTEXT

        self.assertEqual(JSONLD_CONTEXT["hasRole"], f"{OBO}RO_0000087")
        self.assertEqual(JSONLD_CONTEXT["obo"], OBO)
        self.assertNotIn("ro", JSONLD_CONTEXT)


@needs_chebi
class AllowListTestCase(unittest.TestCase):

    @needs_chebi
    def test_the_shipped_file_matches_a_fresh_build(self):
        """`--check` re-reads ChEBI and rebuilds every label and definition.

        The file is generated rather than typed so a ChEBI release is absorbed
        by re-running; this is what stops it being absorbed by nobody.
        """
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "generate_chebi_roles.py"), "--check"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_it_holds_exactly_the_fourteen_decided_roles(self):
        allowed = load_allowed_roles()
        self.assertEqual(len(allowed), 14)
        self.assertEqual(
            {row.label for row in allowed.values()},
            {
                "pesticide", "agrochemical", "herbicide", "fungicide", "insecticide",
                "acaricide", "plant growth regulator", "nematicide", "fertilizer",
                "rodenticide", "molluscicide", "antifeedant",
                "environmental contaminant", "persistent organic pollutant",
            },
        )

    def test_every_role_resolves_in_the_shipped_chebi(self):
        """A label or definition of `None` means the accession is not in this
        ChEBI release -- the generator raises on a missing node, so this is the
        weaker case of a node present but empty."""
        for iri, row in load_allowed_roles().items():
            with self.subTest(role=row.label):
                self.assertTrue(row.label, iri)
                self.assertTrue(iri.startswith(f"{OBO}CHEBI_"))

    def test_broader_stays_inside_the_allow_list(self):
        """`broader` is the tree *within what we publish*, so a reader can roll
        `herbicide` up to `pesticide` without a second lookup. A parent outside
        the list would be a dangling edge."""
        allowed = load_allowed_roles()
        for iri, row in allowed.items():
            for parent in row.broader:
                with self.subTest(role=row.label):
                    self.assertIn(parent, allowed)

    def test_the_pesticide_branch_is_complete(self):
        """Every ChEBI child of `pesticide` this list can reach is present, or
        a reader who finds `acaricide` and no `rodenticide` concludes there are
        no rodenticides. The three eight-bearer nodes are on the list for this
        reason and not for their counts."""
        allowed = load_allowed_roles()
        pesticide = _chebi("25944")
        children = {
            row.label for row in allowed.values() if pesticide in row.broader
        }
        self.assertEqual(
            children,
            {"herbicide", "fungicide", "insecticide", "acaricide", "nematicide",
             "rodenticide", "molluscicide", "antifeedant"},
        )

    def test_greenhouse_gas_is_rejected_because_it_omits_every_hfc(self):
        """ChEBI gives `greenhouse gas` to carbon dioxide, methane, sulfur
        hexafluoride and ozone, and to no HFC or PFC in this list -- HFC-134a,
        HFC-125, HFC-23, FC-14, perfluorobutane and nitrogen trifluoride are
        each either absent from ChEBI or present without it.

        A grouping that looks authoritative and silently omits the fluorinated
        basket is worse than no grouping, so this is a decision and not an
        oversight. Deleting this assertion is the way to reverse it.
        """
        self.assertNotIn(_chebi("76413"), load_allowed_roles())

    def test_antifungal_agrochemical_is_rejected_as_a_strict_subset(self):
        """Measured over the published list: 158 bearers, all 158 of them also
        `fungicide`, none unique. A second name for a set we already have."""
        self.assertNotIn(_chebi("86328"), load_allowed_roles())

    def test_xenobiotic_is_rejected_as_duplicating_environmental_contaminant(self):
        """171 of its 200 bearers are already `environmental contaminant`; the
        29 that are not are caffeine, aspartame and similar."""
        self.assertNotIn(_chebi("35703"), load_allowed_roles())

    def test_poison_is_rejected_as_incoherent_for_grouping(self):
        """Its bearers include ethanol, hexane, toluene, butylene glycol and
        3-octanone beside potassium cyanide and mercury."""
        self.assertNotIn(_chebi("64909"), load_allowed_roles())

    def test_the_biomedical_branch_is_absent_entirely(self):
        """The roles a naive copy of ChEBI would be dominated by."""
        allowed = load_allowed_roles()
        for accession, label in [
            ("25212", "metabolite"), ("35222", "inhibitor"), ("23888", "drug"),
            ("52217", "pharmaceutical"), ("75771", "mouse metabolite"),
            ("38462", "acetylcholinesterase inhibitor"),
        ]:
            with self.subTest(role=label):
                self.assertNotIn(_chebi(accession), allowed)


@needs_chebi
class ResolverTestCase(unittest.TestCase):

    def test_it_inherits_roles_down_the_chemical_hierarchy(self):
        """The defect review of #269 found, and the reason these expectations
        are written out by hand.

        ChEBI asserts roles on chemical *classes*, and `SubClassOf (has_role R)`
        on a class holds for every subclass.  None of the four substances below
        carries the listed role on its own node:

        - `2,3,7,8-TCDD` has **no** `has_role` edge at all; its parent class
          `polychlorinated dibenzodioxine` bears `persistent organic pollutant`.
        - `Acetamiprid` likewise has none of its own.
        - `Abamectin` has `antibiotic nematicide` only.
        - `Acephate` has `acaricide` and `agrochemical` only.

        The first version of this resolver read an entity's own edges and closed
        only upward over the role tree.  It cost **155 flow objects at least one
        entailed role, 73 of them every role they should have had** -- every
        dioxin, most PCBs and the brominated flame retardants published bare.

        These are asserted as literals because the check that missed it
        recomputed expectations with the resolver under test.  A resolver cannot
        be its own oracle, and this test only means something while the values
        below come from somewhere else.
        """
        allowed = load_allowed_roles()

        def labels(cas):
            return {allowed[iri].label for iri in roles_for_cas([cas])}

        self.assertEqual(
            labels("1746-01-6"),  # 2,3,7,8-TCDD
            {"environmental contaminant", "persistent organic pollutant"},
        )
        self.assertEqual(
            labels("135410-20-7"),  # acetamiprid
            {"environmental contaminant", "insecticide", "pesticide"},
        )
        self.assertEqual(
            labels("71751-41-2"),  # abamectin
            {"acaricide", "insecticide", "nematicide", "pesticide"},
        )
        self.assertEqual(
            labels("30560-19-1"),  # acephate
            {"acaricide", "agrochemical", "insecticide", "pesticide"},
        )

    def test_a_substance_with_no_role_anywhere_above_it_gets_none(self):
        """The other side of inheriting down the chemical tree: it must not
        become a way to reach a role through an ancestor so general that
        everything shares it.  Arsenic and water are both deep in ChEBI's
        chemical hierarchy and neither bears an allow-listed role."""
        self.assertEqual(roles_for_cas(["7440-38-2"]), set())  # arsenic
        self.assertEqual(roles_for_cas(["7732-18-5"]), set())  # water

    def test_it_closes_over_the_role_hierarchy(self):
        """ChEBI asserts `neonicotinoid insectide` on dinotefuran and *not*
        `insecticide`, because an ontology does not restate what it entails.
        Reading only direct assertions would find no insecticides at all.
        """
        found = roles_for_cas(["165252-70-0"])  # dinotefuran
        labels = {load_allowed_roles()[iri].label for iri in found}
        self.assertIn("insecticide", labels)
        self.assertIn("pesticide", labels)

    def test_a_role_outside_the_allow_list_is_dropped_not_generalised(self):
        """Dinotefuran's `neonicotinoid insectide` contributes `insecticide`,
        but the narrow class itself must not be published: it is a
        mechanism-of-action class as much as a use class -- ChEBI also files it
        under *neurotoxin* -- and that axis is not scoped here."""
        self.assertNotIn(_chebi("25540"), roles_for_cas(["165252-70-0"]))

    def test_a_substance_can_bear_more_than_one_role(self):
        """The property that rules out `parent_flow_object_id`, which is
        single-valued. Sulfluramid is an insecticide and an acaricide."""
        labels = {
            load_allowed_roles()[iri].label for iri in roles_for_cas(["4151-50-2"])
        }
        self.assertLessEqual({"insecticide", "acaricide"}, labels)

    def test_an_unknown_cas_yields_nothing(self):
        self.assertEqual(roles_for_cas(["999999-99-9"]), set())
        self.assertEqual(roles_for_cas([]), set())

    def test_chlormequat_is_a_growth_regulator_and_not_a_pesticide(self):
        """ecoinvent routes it to `Pesticides, unspecified`; ChEBI gives it
        `plant growth retardant`, which is nowhere under `pesticide`. The
        allow-list holds `plant growth regulator` precisely so this substance
        has somewhere correct to go."""
        labels = {
            load_allowed_roles()[iri].label for iri in roles_for_cas(["7003-89-6"])
        }
        self.assertIn("plant growth regulator", labels)
        self.assertNotIn("pesticide", labels)


@needs_chebi
class AssignmentTestCase(unittest.TestCase):

    def test_it_writes_roles_onto_an_object_with_a_known_cas(self):
        obj = _object("fo-1", "113614-08-7")  # beflubutamid
        stats = assign_chebi_roles([obj])
        self.assertEqual(stats["assigned"], 1)
        labels = {row[RDFS_LABEL_CURIE] for row in obj.roles}
        self.assertEqual(labels, {"agrochemical", "herbicide", "pesticide"})

    def test_every_assertion_carries_structured_provenance(self):
        """`AGENTS.md`: code that writes a value into a flow object adds
        structured provenance for it in the same change."""
        obj = _object("fo-1", "113614-08-7")
        assign_chebi_roles([obj])
        for row in obj.roles:
            provenance = row["provenance"]
            self.assertEqual(provenance["prov:wasGeneratedBy"], "chebi_roles")
            self.assertEqual(provenance["prov:hadPrimarySource"], ["ChEBI"])

    def test_an_object_with_no_role_keeps_the_key_absent(self):
        """Not an empty list: `[]` reads as "checked, and it bears none", which
        is a stronger claim than "ChEBI has nothing to say"."""
        obj = _object("fo-1", "7440-38-2")  # arsenic
        assign_chebi_roles([obj])
        self.assertIsNone(obj.roles)
        self.assertNotIn(RO_HAS_ROLE_IRI, obj.to_dict())

    def test_an_object_with_no_cas_is_left_alone(self):
        obj = _object("fo-1")
        stats = assign_chebi_roles([obj])
        self.assertIsNone(obj.roles)
        self.assertEqual(stats["no_cas"], 1)

    def test_a_curated_assertion_is_not_overwritten(self):
        """The 24 substances ChEBI has without a pesticide role, and the 9 it
        cannot resolve, get a curated role with reasoning. Recomputing over the
        top of one would erase a decision and leave no trace that it had been
        made."""
        curated = Role(
            iri=_chebi("22153"), label="acaricide",
            provenance=Provenance(
                was_generated_by="curated_roles", was_attributed_to="brightway-flows",
            ),
        ).to_dict()
        obj = _object("fo-1", "113614-08-7", roles=[curated])
        stats = assign_chebi_roles([obj])
        self.assertEqual(obj.roles, [curated])
        self.assertEqual(stats["curated_present"], 1)

    def test_its_own_earlier_output_is_replaced(self):
        """The other half of the rule above: a generated assertion *must* be
        recomputable, or a ChEBI release could never correct one."""
        obj = _object("fo-1", "113614-08-7")
        assign_chebi_roles([obj])
        obj.roles = [obj.roles[0]]
        assign_chebi_roles([obj])
        self.assertEqual(len(obj.roles), 3)

    def test_roles_are_ordered_by_label(self):
        """A set iterates in hash order, and an unstable key order is what #264
        reports as spurious diffs across runs."""
        obj = _object("fo-1", "50-29-3")  # DDT
        assign_chebi_roles([obj])
        labels = [row[RDFS_LABEL_CURIE] for row in obj.roles]
        self.assertEqual(labels, sorted(labels))


@needs_chebi
class SerialisationTestCase(unittest.TestCase):

    def test_roles_serialise_under_the_ro_iri_and_round_trip(self):
        obj = _object("fo-1", "113614-08-7")
        assign_chebi_roles([obj])
        payload = obj.to_dict()
        self.assertIn(RO_HAS_ROLE_IRI, payload)
        self.assertEqual(FlowObject.from_dict(payload).roles, obj.roles)

    def test_the_role_row_names_the_class_by_iri(self):
        """`@id` rather than a bare string, so the value is a node reference in
        the expanded graph rather than a literal."""
        obj = _object("fo-1", "113614-08-7")
        assign_chebi_roles([obj])
        for row in obj.roles:
            self.assertTrue(row["@id"].startswith(f"{OBO}CHEBI_"))

    def test_the_shipped_allow_list_is_valid_json_with_the_declared_predicate(self):
        payload = orjson.loads(ROLES_DATA_PATH.read_bytes())
        self.assertEqual(payload["predicate"], RO_HAS_ROLE_IRI)


if __name__ == "__main__":
    unittest.main()
