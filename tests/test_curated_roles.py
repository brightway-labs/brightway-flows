"""The curated half of the role axis: the file, its checks, and what it adds to.

`test_chebi_roles.py` covers the assertions read out of ChEBI.  This module
covers the ones a curator writes for the substances ChEBI has no `has role` edge
for, and the two properties that make the two halves one axis: a curated row is
*added* to a generated one rather than replacing it, and it is materialised the
same way, so nothing downstream has to know which pass wrote a row.

The data itself gets tests too, because a curation file is only worth its
sourcing.  Every row is required to carry a link and to quote what the source
says verbatim, and the shipped file is asserted to have no substance filed as
both asserted and declined -- which is the failure a hand-edited file has.
"""

from __future__ import annotations

import collections
import unittest

import orjson

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.flow_object import FlowObject, Role
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    PROV_WAS_GENERATED_BY_CURIE,
)
from brightway_flows.flow_layers.roles import (
    CURATED_BY,
    CURATED_ROLES_DATA_PATH,
    DECISIONS_SCHEMA_VERSION,
    GENERATED_BY,
    CuratedRole,
    CuratedRoleError,
    _materialise,
    assign_curated_roles,
    load_allowed_roles,
    load_curated_roles,
    validate_curated_roles,
)

OBO = "http://purl.obolibrary.org/obo/"
PESTICIDE = f"{OBO}CHEBI_25944"
HERBICIDE = f"{OBO}CHEBI_24527"
FUNGICIDE = f"{OBO}CHEBI_24127"
INSECTICIDE = f"{OBO}CHEBI_24852"
ACARICIDE = f"{OBO}CHEBI_22153"
AGROCHEMICAL = f"{OBO}CHEBI_33286"
GROWTH_REGULATOR = f"{OBO}CHEBI_26155"


def _object(flow_object_id: str, *cas: str, roles=None) -> FlowObject:
    return FlowObject(
        flow_object_id=flow_object_id,
        prefLabel=[],
        altLabel=[],
        properties={},
        references=[],
        created_from={},
        classifications=(
            {CHEMINF_CAS_REGISTRY_NUMBER: {"@value": list(cas)}} if cas else {}
        ),
        roles=roles,
    )


def _generated(iri: str) -> dict:
    allowed = load_allowed_roles()
    return Role(
        iri=iri,
        label=allowed[iri].label,
        definition=allowed[iri].definition,
        provenance=Provenance(
            was_generated_by=GENERATED_BY,
            was_attributed_to="brightway-flows",
        ),
    ).to_dict()


def _row(**overrides) -> dict:
    row = {
        "substance": "Cyhalofop-butyl",
        "cas_number": "122008-85-9",
        "roles": [HERBICIDE],
        "source_url": "https://sitem.herts.ac.uk/aeru/ppdb/en/Reports/193.htm",
        "source_states": "Herbicide",
        "cas_agreement": "exact",
        "comment": "Aryloxyphenoxypropanoate herbicide.",
    }
    row.update(overrides)
    return row


def _payload(*rows: dict, version: int | None = DECISIONS_SCHEMA_VERSION) -> dict:
    return {"schema_version": version, "assertions": list(rows)}


class ValidationTestCase(unittest.TestCase):
    """What a malformed row does, which is fail the run that introduced it.

    Every one of these raises rather than skipping the row, which is rule 14:
    a curated decision that is silently dropped looks applied and is not.
    """

    def test_it_returns_records_rather_than_a_bag(self):
        """Rule 13.  A `dict[str, Any]` out of a loader is a curator's decision
        that nothing type-checks, and the register in `domain/rulings.py` exists
        because fifteen of twenty loaders returned one."""
        loaded = validate_curated_roles(_payload(_row()))
        self.assertIsInstance(loaded["122008-85-9"], CuratedRole)
        self.assertEqual(loaded["122008-85-9"].roles, (HERBICIDE,))

    def test_a_file_of_another_format_version_is_an_error(self):
        """`DECISIONS_SCHEMA_VERSION` is this file's own format and nothing
        else's; the bare `SCHEMA_VERSION` is the version of the list this
        project publishes (#98)."""
        with self.assertRaises(CuratedRoleError) as raised:
            validate_curated_roles(_payload(_row(), version=2))
        self.assertIn("schema version", str(raised.exception))

    def test_a_role_outside_the_allow_list_is_an_error(self):
        """Not a dropped value.  The allow-list is the decision about what this
        project publishes -- fourteen classes out of ChEBI's role tree, with the
        rejections argued in `plans/pesticide-taxonomy.md` -- and a curator
        reaching past it is making that decision by accident.  `greenhouse gas`
        is the one that would be reached for first, so it is the one used here.
        """
        with self.assertRaises(CuratedRoleError) as raised:
            validate_curated_roles(_payload(_row(roles=[f"{OBO}CHEBI_76413"])))
        self.assertIn("allow-list", str(raised.exception))

    def test_two_rows_for_one_registry_number_are_an_error(self):
        """Which one won would otherwise depend on file order."""
        with self.assertRaises(CuratedRoleError) as raised:
            validate_curated_roles(
                _payload(_row(), _row(substance="Cyhalofop", roles=[PESTICIDE]))
            )
        self.assertIn("122008-85-9", str(raised.exception))

    def test_a_row_without_a_comment_is_an_error(self):
        """For the reason `comment` is mandatory on a match override: an
        assertion nobody can check is an assertion nobody can revise."""
        with self.assertRaises(CuratedRoleError):
            validate_curated_roles(_payload(_row(comment="")))

    def test_a_row_without_a_source_is_an_error(self):
        with self.assertRaises(CuratedRoleError):
            validate_curated_roles(_payload(_row(source_url="")))

    def test_a_row_asserting_no_role_is_an_error(self):
        """An empty list reads as "checked, and it has none", which is what the
        `undecided` section is for -- and that one is not loaded at all."""
        with self.assertRaises(CuratedRoleError):
            validate_curated_roles(_payload(_row(roles=[])))

    def test_a_row_with_no_cas_is_an_error(self):
        """The file is keyed by registry number on purpose: normalising a name
        to alphanumerics deletes the stereodescriptor, so a racemate matches its
        eutomer.  A row with nothing to key on cannot be applied safely."""
        with self.assertRaises(CuratedRoleError):
            validate_curated_roles(_payload(_row(cas_number="  ")))

    def test_a_row_that_does_not_say_whether_the_numbers_agree_is_an_error(self):
        """The field a row is worth no more than.  Left optional it would be
        absent exactly where it matters -- on the rows whose source record
        carries a different registry number from the one the source list ships.
        """
        with self.assertRaises(CuratedRoleError) as raised:
            validate_curated_roles(_payload(_row(cas_agreement="probably")))
        self.assertIn("registry numbers agree", str(raised.exception))


class MaterialisationTestCase(unittest.TestCase):
    """The published set holds what it entails, on both halves of the axis."""

    def test_a_herbicide_is_published_as_a_pesticide_too(self):
        """`roles_for_cas` closes over ChEBI's role hierarchy before writing, so
        a generated `herbicide` always arrives with `pesticide` beside it.  A
        curated row has to be closed here or the same predicate would publish
        two differently shaped sets, and a consumer doing a dictionary lookup
        would find a herbicide that is not a pesticide."""
        self.assertEqual(_materialise({HERBICIDE}), {HERBICIDE, PESTICIDE})

    def test_a_role_with_no_broader_is_left_alone(self):
        self.assertEqual(_materialise({PESTICIDE}), {PESTICIDE})

    def test_growth_regulator_does_not_entail_pesticide(self):
        """Chlormequat is the case: it retards stem growth and kills nothing,
        and ChEBI files its role nowhere under `pesticide`.  If this closure
        reached one, the objection recorded against chlormequat's bucket would
        be undone by the closure that was supposed to be neutral."""
        self.assertEqual(_materialise({GROWTH_REGULATOR}), {GROWTH_REGULATOR})

    def test_several_roles_close_independently(self):
        self.assertEqual(
            _materialise({HERBICIDE, GROWTH_REGULATOR}),
            {HERBICIDE, PESTICIDE, GROWTH_REGULATOR},
        )


class AssignmentTestCase(unittest.TestCase):
    """Curated rows land on objects, beside whatever ChEBI already said."""

    def test_it_writes_the_curated_role_and_what_it_entails(self):
        obj = _object("fo-1", "122008-85-9")
        assign_curated_roles([obj])
        self.assertEqual(
            [row["@id"] for row in obj.roles], [HERBICIDE, PESTICIDE]
        )

    def test_it_adds_to_a_generated_assertion_rather_than_replacing_it(self):
        """Laminarin is the case this is written for.  ChEBI gives it
        `agrochemical` and no more; PPDB and its EU approval type it a
        fungicide.  Both are true, a role is many-valued, and the object must
        end up holding both -- an earlier ordering, curated first, would have
        made `assign_chebi_roles` skip the object and lose ChEBI's half."""
        obj = _object("fo-1", "9008-22-4", roles=[_generated(AGROCHEMICAL)])
        assign_curated_roles([obj])
        self.assertEqual(
            {row["@id"] for row in obj.roles},
            {AGROCHEMICAL, FUNGICIDE, PESTICIDE},
        )

    def test_each_half_keeps_its_own_provenance(self):
        """A generated assertion can be recomputed from a newer ChEBI release
        and a curated one cannot, so the two have to stay tellable apart in the
        published document rather than in someone's memory."""
        obj = _object("fo-1", "9008-22-4", roles=[_generated(AGROCHEMICAL)])
        assign_curated_roles([obj])
        by_iri = {
            row["@id"]: row["provenance"][PROV_WAS_GENERATED_BY_CURIE]
            for row in obj.roles
        }
        self.assertEqual(by_iri[AGROCHEMICAL], GENERATED_BY)
        self.assertEqual(by_iri[FUNGICIDE], CURATED_BY)

    def test_the_provenance_names_the_record_rather_than_the_database(self):
        """Rule 16 wants `prov:hadPrimarySource` filled whenever it can be, and
        the whole claim of a curated role is that somebody can open the page and
        read the same thing.  A source naming only "PPDB" sends them to a search
        box.  It is also the reuse the source's terms permit: citing and linking
        are free, copying the data is not."""
        obj = _object("fo-1", "1332-58-7")
        assign_curated_roles([obj])
        insecticide = next(r for r in obj.roles if r["@id"] == INSECTICIDE)
        self.assertEqual(
            insecticide["provenance"]["prov:hadPrimarySource"],
            ["https://sitem.herts.ac.uk/aeru/ppdb/en/Reports/1306.htm"],
        )
        self.assertIn(
            "Insecticide; Other substance; Veterinary substance",
            insecticide["provenance"]["prov:wasDerivedFrom"],
        )

    def test_an_entailed_role_cites_the_record_that_entailed_it(self):
        """`pesticide` is published because the source said `insecticide`, so it
        carries the same record.  Leaving the entailed row unsourced would make
        the materialisation look like an assertion nobody made."""
        obj = _object("fo-1", "1332-58-7")
        assign_curated_roles([obj])
        pesticide = next(r for r in obj.roles if r["@id"] == PESTICIDE)
        self.assertEqual(
            pesticide["provenance"]["prov:hadPrimarySource"],
            ["https://sitem.herts.ac.uk/aeru/ppdb/en/Reports/1306.htm"],
        )

    def test_a_role_chebi_already_asserted_is_not_written_twice(self):
        obj = _object("fo-1", "122008-85-9", roles=[_generated(HERBICIDE)])
        stats = assign_curated_roles([obj])
        self.assertEqual(
            [row["@id"] for row in obj.roles], [HERBICIDE, PESTICIDE]
        )
        self.assertEqual(stats["already_generated"], 1)

    def test_an_object_with_no_curated_cas_is_left_alone(self):
        obj = _object("fo-1", "7732-18-5")
        assign_curated_roles([obj])
        self.assertIsNone(obj.roles)

    def test_an_object_with_no_cas_is_left_alone(self):
        obj = _object("fo-1")
        assign_curated_roles([obj])
        self.assertIsNone(obj.roles)

    def test_roles_are_ordered_by_label_across_both_halves(self):
        """So the published order says nothing about which pass wrote a row."""
        obj = _object("fo-1", "9008-22-4", roles=[_generated(AGROCHEMICAL)])
        assign_curated_roles([obj])
        allowed = load_allowed_roles()
        labels = [allowed[row["@id"]].label for row in obj.roles]
        self.assertEqual(labels, sorted(labels))

    def test_a_row_that_reaches_no_object_is_counted_and_not_an_error(self):
        """Most of these substances have no flow object of their own yet -- that
        collapse is what #76 is about -- so the assertions are written before
        the objects they will land on.  The count is how a file that has quietly
        stopped applying to anything becomes visible."""
        stats = assign_curated_roles([_object("fo-1", "122008-85-9")])
        self.assertEqual(stats["unmatched"], len(load_curated_roles()) - 1)

    def test_it_is_idempotent(self):
        obj = _object("fo-1", "122008-85-9")
        assign_curated_roles([obj])
        first = list(obj.roles)
        assign_curated_roles([obj])
        self.assertEqual(obj.roles, first)


class ShippedFileTestCase(unittest.TestCase):
    """The curation itself, and the claims it is allowed to make."""

    @classmethod
    def setUpClass(cls):
        cls.payload = orjson.loads(CURATED_ROLES_DATA_PATH.read_bytes())

    def test_it_loads(self):
        self.assertTrue(load_curated_roles())

    def test_the_registry_numbers_agree_on_all_but_three_rows(self):
        """The count the pull request quotes, pinned where it is read (rule 29).

        27 of 30 rows cite a record carrying the same registry number the source
        list ships. The three that do not are named, because they are the rows a
        reviewer should look at hardest: copper oxychloride and potassium soap
        cite a record under a second number for the same commercial substance,
        and pydiflumetofen cites a number ecoinvent does not ship at all, which
        makes its row inert rather than wrong.

        27 rather than 26 since #46: MCPA-methyl moved out of `undecided` once
        the substance was identified, and PPDB's record for it is under the very
        number ecoinvent ships.
        """
        by_agreement = collections.Counter(
            row["cas_agreement"] for row in self.payload["assertions"]
        )
        self.assertEqual(by_agreement["exact"], 27)
        self.assertEqual(
            sorted(
                row["substance"] for row in self.payload["assertions"]
                if row["cas_agreement"] == "different_registry_entry"
            ),
            ["Copper oxychloride", "Potassium soap"],
        )
        self.assertEqual(
            [
                row["substance"] for row in self.payload["assertions"]
                if row["cas_agreement"] == "not_shipped"
            ],
            ["Pydiflumetofen"],
        )

    def test_a_substance_is_not_both_asserted_and_declined(self):
        """The failure a hand-edited file has: a row added to `assertions` while
        the objection it contradicts stays behind, so the file says two things
        and only one of them is read."""
        asserted = {row["cas_number"] for row in self.payload["assertions"]}
        for section in ("objections", "undecided"):
            for row in self.payload[section]:
                with self.subTest(section=section, substance=row["substance"]):
                    self.assertNotIn(row["cas_number"], asserted)

    def test_every_objection_names_the_role_it_declines(self):
        """An objection is a decision not to publish a specific role, so it has
        to say which one.  `Etoxazole` declines `insecticide` and keeps
        `acaricide`; without the field that reads as declining both."""
        allowed = load_allowed_roles()
        for row in self.payload["objections"]:
            with self.subTest(row["substance"]):
                self.assertIn(row["declined_role"], allowed)
                self.assertTrue(row["comment"])
                self.assertTrue(row["source_url"])

    def test_every_undecided_row_says_what_is_missing(self):
        """A gap a reviewer reads rather than a silent zero."""
        for row in self.payload["undecided"]:
            with self.subTest(row["substance"]):
                self.assertTrue(row["comment"])
                self.assertTrue(row.get("source_states"))
                self.assertTrue(row["bucket"])

    def test_the_pesticide_buckets_are_the_ones_covered(self):
        """Every asserted role names a use class, not a fate class.  The two
        environmental-fate roles in the allow-list -- `environmental
        contaminant` and `persistent organic pollutant` -- are observations
        about where a substance ends up, and a curator asserting one from a
        pesticide database would be reading a field that is not there."""
        fate = {f"{OBO}CHEBI_78298", f"{OBO}CHEBI_77853"}
        for row in self.payload["assertions"]:
            with self.subTest(row["substance"]):
                self.assertFalse(set(row["roles"]) & fate)


if __name__ == "__main__":
    unittest.main()
