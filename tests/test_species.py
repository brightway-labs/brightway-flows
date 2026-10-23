"""The element/ion rule parses names, not chemistry, and stays inert on a leash.

Three properties carry the design (`plans/retire-prepared-correspondence.md`
§3a), and each has a test that would fail if it slipped:

* **Bare stays bare.**  EF 3.1 ships bare elements in every compartment, so a
  bare name is an identity, never an omission -- nothing here may reread
  `Zinc` as an ion.
* **A polyatomic ion is not the family.**  `Thiocyanate, Ion` beside
  `Thiocyanate` is #130's twin shape, and a whitelist keyed on "same root, one
  side marked" would excuse it; the element table is what refuses.
* **The rule is inert while a prepared table decides the same rows.**  Its
  introduction has to be hash-identical on a full build, and `rule_governs` is
  the single gate that makes that true by construction.
"""

import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.merge.species import (
    CANONICAL_IDENTITIES_FILEPATH,
    CANONICAL_IDENTITIES_SCHEMA_VERSION,
    CanonicalIdentity,
    CanonicalIdentityError,
    ELEMENTS,
    ELEMENT_CAS,
    _canonical_element,
    canonicalized_for_matching,
    element_number_set_aside,
    ground_resource_is_the_element,
    load_canonical_identities,
    number_is_the_bare_elements,
    parse_species,
    redefines,
    rule_governs,
    species_object_label,
)
from brightway_flows.merge.state import SourceRow
from brightway_flows.sources import resolve_source_list


def _row(**fields) -> SourceRow:
    base = dict(
        uuid="s-1",
        name="Nickel II",
        synonyms=[],
        labels=["Nickel II"],
        context=["water", "surface water"],
        context_iri="",
        context_normalized=[],
        unit="kg",
        unit_iri="",
        cas="14701-22-5",
        ec="",
        conversion=None,
    )
    base.update(fields)
    return SourceRow(**base)


class ParseTestCase(unittest.TestCase):
    def test_roman_numeric_and_parenthesised_spellings_are_one_identity(self):
        for name in ("Nickel II", "nickel (ii)", "Nickel(2+)"):
            with self.subTest(name=name):
                species = parse_species(name)
                self.assertEqual((species.element, species.kind, species.charge),
                                 ("Nickel", "charge", 2))
                self.assertEqual(species_object_label(species), "Nickel(2+)")

    def test_the_platinum_group_metals_the_lists_ship_charged_are_the_family(self):
        """ecoinvent 3.12's `Rhodium III` and `Palladium II` were outside the
        table, so neither was ever looked up as its ion and both fell to the
        vendor's bare synonym (#198)."""
        for name, expected in (("Rhodium III", "Rhodium(3+)"), ("Palladium (II)", "Palladium(2+)")):
            with self.subTest(name=name):
                species = parse_species(name)
                self.assertEqual(species.kind, "charge")
                self.assertEqual(species_object_label(species), expected)

    def test_the_generic_ion_marker_is_its_own_identity(self):
        for name in ("Copper ion", "Copper, Ion", "copper ions"):
            with self.subTest(name=name):
                species = parse_species(name)
                self.assertEqual((species.kind, species.charge), ("ion", None))
                self.assertEqual(species_object_label(species), "Copper, ion")

    def test_an_ion_is_looked_up_in_iupac_spelling(self):
        """The published ion is `Caesium(1+)` (`domain.ion_names`), so that is
        the name a tie is broken on, whichever spelling the row used; the
        element itself keeps the spelling this list's element labels use."""
        self.assertEqual(species_object_label(parse_species("Cesium I")), "Caesium(1+)")
        self.assertEqual(species_object_label(parse_species("Caesium ion")), "Caesium, ion")
        self.assertEqual(species_object_label(parse_species("Caesium")), "Cesium")

    def test_bare_stays_bare(self):
        species = parse_species("Zinc")
        self.assertEqual(species.kind, "bare")
        self.assertEqual(species_object_label(species), "Zinc")

    def test_spellings_fold_to_the_lists_own(self):
        self.assertEqual(parse_species("Caesium I").element, "Cesium")
        self.assertEqual(parse_species("aluminum iii").element, "Aluminium")

    def test_a_polyatomic_ion_is_not_the_family(self):
        self.assertIsNone(parse_species("Thiocyanate, Ion"))
        self.assertIsNone(parse_species("Thiocyanate"))

    def test_ordinary_substances_are_not_the_family(self):
        for name in ("Fungicides, unspecified", "Silver-110m", "", "Granite"):
            with self.subTest(name=name):
                self.assertIsNone(parse_species(name))


class LoaderTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _file(self, payload) -> Path:
        path = self.dir / "identities.json"
        path.write_bytes(orjson.dumps(payload))
        return path

    def _payload(self, **entry):
        row = {
            "uuid": "u-1",
            "name": "Zinc II",
            "cas_number": "23713-49-7",
            "decided_by": "3.12",
            "replaces": [{"version": "3.8", "name": "Zinc, ion", "cas_number": "23713-49-7"}],
        }
        row.update(entry)
        return {
            "schema_version": CANONICAL_IDENTITIES_SCHEMA_VERSION,
            "identities": [row],
        }

    def test_a_wrong_schema_version_is_refused(self):
        with self.assertRaises(CanonicalIdentityError):
            load_canonical_identities(self._file({"schema_version": 99, "identities": []}))

    def test_an_entry_outside_the_family_is_refused(self):
        with self.assertRaises(CanonicalIdentityError):
            load_canonical_identities(self._file(self._payload(name="Granite")))

    def test_an_entry_that_replaces_nothing_is_refused(self):
        with self.assertRaises(CanonicalIdentityError):
            load_canonical_identities(self._file(self._payload(replaces=[])))

    def test_an_entry_that_turns_the_element_into_the_ion_is_refused(self):
        """#398: 3.8's `Zinc` under 7440-66-6 is the metal, and an entry
        sending it to `Zinc II` is a substitution the ruling forbids."""
        with self.assertRaises(CanonicalIdentityError):
            load_canonical_identities(self._file(self._payload(
                replaces=[{"version": "3.8", "name": "Zinc", "cas_number": "7440-66-6"}]
            )))

    def test_a_missing_file_is_an_empty_index(self):
        self.assertEqual(load_canonical_identities(self.dir / "absent.json"), {})

    def test_the_derived_file_loads_and_every_entry_is_the_family(self):
        index = load_canonical_identities(CANONICAL_IDENTITIES_FILEPATH)
        self.assertGreater(len(index), 100)
        zinc = [i for i in index.values() if i.name == "Zinc II"]
        self.assertTrue(zinc)
        self.assertTrue(all(i.replaces for i in index.values()))


class MatchingEvidenceTestCase(unittest.TestCase):
    IDENTITIES = {
        "s-zinc": CanonicalIdentity(
            uuid="s-zinc", name="Zinc II", cas_number="23713-49-7",
            decided_by="3.12",
            replaces=(("3.8", "Zinc, ion", "23713-49-7"),),
        ),
        "s-copper": CanonicalIdentity(
            uuid="s-copper", name="Copper ion", cas_number="",
            decided_by="3.12",
            replaces=(("3.8", "Copper, ion", "17493-86-6"),),
        ),
        # The shape #398 leaves behind: 3.8 and 3.9.1 name the uuid `Calcium`
        # under the element's number and are not listed, and the entry exists
        # only for 3.10.1, which stated the ion under the element's number.
        "s-calcium": CanonicalIdentity(
            uuid="s-calcium", name="Calcium II", cas_number="14127-61-8",
            decided_by="3.12",
            replaces=(("3.10.1", "Calcium II", "7440-70-2"),),
        ),
    }

    def test_a_stale_identity_is_replaced_and_its_labels_dropped(self):
        row = _row(uuid="s-zinc", name="Zinc, ion", cas="23713-49-7", labels=["Zinc, ion"])
        out = canonicalized_for_matching(row, self.IDENTITIES)
        self.assertEqual((out.name, out.cas), ("Zinc II", "23713-49-7"))
        self.assertEqual(out.labels, ["Zinc(2+)", "Zinc II"])
        self.assertNotIn("Zinc, ion", out.labels)

    def test_a_deleted_number_is_deleted(self):
        row = _row(uuid="s-copper", name="Copper, ion", cas="17493-86-6",
                   labels=["Copper, ion"])
        out = canonicalized_for_matching(row, self.IDENTITIES)
        self.assertEqual((out.name, out.cas), ("Copper ion", ""))
        self.assertEqual(out.labels, ["Copper, ion", "Copper ion"])

    def test_the_stale_ec_number_goes_with_the_stale_labels(self):
        """3.8's `Arsenic ion` rows carry the element's EC beside the stale
        registration; a substitution that cleared the CAS and kept the EC sent
        nine of them to elemental arsenic while their 3.12 siblings minted the
        ion -- one uuid, two substances."""
        row = _row(uuid="s-copper", name="Copper, ion", cas="17493-86-6",
                   labels=["Copper, ion"], ec="231-159-6")
        out = canonicalized_for_matching(row, self.IDENTITIES)
        self.assertEqual(out.ec, "")
        # ... and a row with no substitution keeps its EC: the rule only takes
        # evidence away where the vendor's newest statement replaces it.
        untouched = _row(uuid="s-else", name="Copper", cas="7440-50-8",
                         labels=["Copper"], ec="231-159-6")
        self.assertEqual(
            canonicalized_for_matching(untouched, self.IDENTITIES).ec, "231-159-6"
        )

    def test_a_bare_element_on_a_uuid_now_naming_the_ion_is_untouched(self):
        """#398: 3.8's `Zinc`, 7440-66-6, on a uuid 3.12 calls `Zinc II`, is
        the metal it says it is -- name, number, labels and EC all stay."""
        row = _row(uuid="s-zinc", name="Zinc", cas="7440-66-6", labels=["Zinc"],
                   ec="231-175-3")
        self.assertEqual(canonicalized_for_matching(row, self.IDENTITIES), row)

    def test_a_bare_element_whose_number_was_deleted_is_untouched(self):
        """`Copper` (7440-50-8) on a uuid 3.12 calls `Copper ion` with no
        number: the number moved to none, which is still the element leaving."""
        row = _row(uuid="s-copper", name="Copper", cas="7440-50-8", labels=["Copper"])
        self.assertEqual(canonicalized_for_matching(row, self.IDENTITIES), row)

    def test_an_entry_kept_for_a_later_release_does_not_reach_the_bare_one(self):
        bare = _row(uuid="s-calcium", name="Calcium", cas="7440-70-2", labels=["Calcium"])
        self.assertEqual(canonicalized_for_matching(bare, self.IDENTITIES), bare)
        # ... while the release that stated the ion is still corrected.
        stated = _row(uuid="s-calcium", name="Calcium II", cas="7440-70-2",
                      labels=["Calcium II"])
        out = canonicalized_for_matching(stated, self.IDENTITIES)
        self.assertEqual((out.name, out.cas), ("Calcium II", "14127-61-8"))

    def test_a_row_already_canonical_only_gains_the_normalised_label(self):
        row = _row()
        out = canonicalized_for_matching(row, self.IDENTITIES)
        self.assertEqual((out.name, out.cas), ("Nickel II", "14701-22-5"))
        self.assertEqual(out.labels, ["Nickel(2+)", "Nickel II"])

    def test_a_bare_row_with_no_entry_is_untouched(self):
        row = _row(uuid="s-else", name="Zinc", cas="7440-66-6", labels=["Zinc"])
        self.assertEqual(canonicalized_for_matching(row, self.IDENTITIES), row)

    def test_a_row_outside_the_family_is_untouched(self):
        row = _row(uuid="s-else", name="Metaldehyde", cas="108-62-3",
                   labels=["Metaldehyde"])
        self.assertEqual(canonicalized_for_matching(row, self.IDENTITIES), row)


class ElementNumberSetAsideTestCase(unittest.TestCase):
    """A name that states an ion beside the bare element's own number is the
    ion, and the number is set aside (#380).  openLCA 2.8.2 writes 7440-43-9
    on `Cadmium II` and 7439-92-1 on `Lead II` -- 339 rows under 32 names on
    the six-list build of 21 October 2026 -- and the number route, which runs
    first, placed every one of them on the metal."""

    def test_the_elements_number_on_an_ion_name_is_set_aside(self):
        out = element_number_set_aside(_row(name="Cadmium II", cas="7440-43-9",
                                            labels=["Cadmium II"], ec="231-152-8"))
        self.assertEqual((out.cas, out.ec, out.number_set_aside), ("", "", "7440-43-9"))
        self.assertEqual(out.labels, ["Cadmium(2+)", "Cadmium II"])
        self.assertEqual(out.name, "Cadmium II")

    def test_the_generic_marker_counts_as_an_ion_name(self):
        out = element_number_set_aside(_row(name="Copper Ion", cas="7440-50-8",
                                            labels=["Copper Ion"]))
        self.assertEqual(out.number_set_aside, "7440-50-8")
        self.assertEqual(out.labels, ["Copper, ion", "Copper Ion"])

    def test_the_ions_own_number_is_left_alone(self):
        row = _row(name="Cadmium II", cas="22537-48-0", labels=["Cadmium II"])
        self.assertIs(element_number_set_aside(row), row)

    def test_a_bare_element_under_its_own_number_is_the_element(self):
        """The #398 ruling: `Lead` under 7439-92-1 is the metal."""
        row = _row(name="Lead", cas="7439-92-1", labels=["Lead"])
        self.assertIs(element_number_set_aside(row), row)

    def test_another_substances_number_on_an_ion_name_is_read_by_the_number(self):
        """`Vanadium V` under vanadium pentoxide's number is a disagreement the
        label rule judges (#412), not this rule's pair."""
        row = _row(name="Vanadium V", cas="1314-62-1", labels=["Vanadium V"])
        self.assertIs(element_number_set_aside(row), row)

    def test_a_name_outside_the_family_is_not_touched(self):
        row = _row(name="Pyrethrin II", cas="121-29-9", labels=["Pyrethrin II"])
        self.assertIs(element_number_set_aside(row), row)
        self.assertFalse(number_is_the_bare_elements("Pyrethrin II", "121-29-9"))

    def test_a_numberless_ion_name_is_not_touched(self):
        row = _row(name="Vanadium V", cas="", labels=["Vanadium V"])
        self.assertIs(element_number_set_aside(row), row)

    def test_every_element_the_family_knows_has_a_number(self):
        for element in sorted(ELEMENTS):
            with self.subTest(element=element):
                self.assertIn(_canonical_element(element), ELEMENT_CAS)


GROUND = ("Resource", "Ground")


class GroundResourceIsTheElementTestCase(unittest.TestCase):
    """A metal taken from the ground is the element, whatever its name or
    number says about charge (#380, ruled 23 October 2026).  openLCA 2.8.2
    ships `Potassium I` and `Manganese II` as resources in the ground, and
    GreenDelta scores each exactly as the JRC scores the element; EF 3.1 has
    no ion among its ground resources.  The #380 rule had read them as the
    ion, minting 26 ion flows in the ground that only openLCA fed."""

    def test_an_ion_name_under_the_elements_number_is_the_element(self):
        out = ground_resource_is_the_element(_row(
            name="Potassium I", cas="7440-09-7", ec="231-119-8",
            labels=["Potassium I", "Potassium(1+)"], context_normalized=GROUND))
        self.assertEqual((out.name, out.cas, out.ec, out.number_set_aside),
                         ("Potassium", "7440-09-7", "231-119-8", ""))
        self.assertEqual(out.labels, ["Potassium"])
        self.assertTrue(out.read_as_element)
        self.assertEqual(out.shipped_name, "Potassium I")

    def test_the_ions_own_number_is_set_aside(self):
        out = ground_resource_is_the_element(_row(
            name="Cadmium II", cas="22537-48-0", ec="245-073-1",
            labels=["Cadmium II"], context_normalized=GROUND))
        self.assertEqual((out.name, out.cas, out.ec, out.number_set_aside),
                         ("Cadmium", "", "", "22537-48-0"))

    def test_a_numberless_ion_name_is_the_element(self):
        out = ground_resource_is_the_element(_row(
            name="Vanadium V", cas="", labels=["Vanadium V"], context_normalized=GROUND))
        self.assertEqual((out.name, out.cas, out.labels), ("Vanadium", "", ["Vanadium"]))

    def test_the_generic_marker_is_the_element(self):
        out = ground_resource_is_the_element(_row(
            name="Copper Ion", cas="7440-50-8", labels=["Copper Ion"], context_normalized=GROUND))
        self.assertEqual((out.name, out.labels), ("Copper", ["Copper"]))

    def test_a_bare_name_under_an_ions_number_is_the_element(self):
        """openLCA's `Sodium` ships 17341-25-2, the sodium ion's number."""
        out = ground_resource_is_the_element(_row(
            name="Sodium", cas="17341-25-2", labels=["Sodium"], context_normalized=GROUND))
        self.assertEqual((out.name, out.cas, out.number_set_aside), ("Sodium", "", "17341-25-2"))
        self.assertTrue(out.read_as_element)

    def test_a_bare_name_under_its_own_number_is_left_alone(self):
        row = _row(name="Sodium", cas="7440-23-5", labels=["Sodium"], context_normalized=GROUND)
        self.assertIs(ground_resource_is_the_element(row), row)

    def test_a_name_outside_the_family_is_left_alone(self):
        row = _row(name="Granite", cas="", labels=["Granite"], context_normalized=GROUND)
        self.assertIs(ground_resource_is_the_element(row), row)

    def test_an_emission_keeps_its_ion(self):
        """The other half: only resources in the ground are read as the element."""
        row = _row(name="Cadmium II", cas="22537-48-0", labels=["Cadmium II"],
                   context_normalized=("Environmental", "Ground", "Agricultural"))
        self.assertIs(ground_resource_is_the_element(row), row)

    def test_a_dissolved_ion_taken_from_water_keeps_its_ion(self):
        """ecoinvent's `Potassium I` taken from water ships the ion's own
        number and means the dissolved ion; the rule is for the ground only."""
        row = _row(name="Potassium I", cas="24203-36-9", labels=["Potassium I"],
                   context_normalized=("Resource", "Water"))
        self.assertIs(ground_resource_is_the_element(row), row)

    def test_the_ion_rule_then_leaves_the_element_alone(self):
        """The two rules run in turn; once the ground rule has read the row as
        the element, the #380 rule finds a bare name and does nothing."""
        out = element_number_set_aside(ground_resource_is_the_element(_row(
            name="Lead II", cas="7439-92-1", labels=["Lead II"], context_normalized=GROUND)))
        self.assertEqual((out.name, out.cas, out.number_set_aside), ("Lead", "7439-92-1", ""))


class RedefinitionTestCase(unittest.TestCase):
    """The #398 predicate, on the vendor statements it was written from."""

    def test_the_element_becoming_the_ion_is_a_redefinition(self):
        for earlier, newest in (
            (("Lead", "7439-92-1"), ("Lead II", "14280-50-3")),
            (("Copper", "7440-50-8"), ("Copper ion", "")),
            (("Cesium", "7440-46-2"), ("Caesium I", "18459-37-5")),
        ):
            with self.subTest(earlier=earlier):
                self.assertTrue(redefines(*earlier, *newest))

    def test_one_substance_spelled_twice_is_not(self):
        for earlier, newest in (
            # 3.8 already called it the ion.
            (("Cadmium, ion", "22537-48-0"), ("Cadmium II", "22537-48-0")),
            (("Arsenic, ion", "17428-41-0"), ("Arsenic ion", "")),
            # The element, respelled.
            (("Aluminium, in ground", "7429-90-5"), ("Aluminium", "7429-90-5")),
            (("Manganese-55", "7439-96-5"), ("Manganese", "7439-96-5")),
            # A charge on the name with the number unmoved is not the element
            # leaving: the number is what the ruling reads.
            (("Strontium", "7440-24-6"), ("Strontium II", "7440-24-6")),
            # Outside the family altogether.
            (("Thiocyanate, ion", "71048-69-6"), ("Thiocyanate", "302-04-5")),
        ):
            with self.subTest(earlier=earlier):
                self.assertFalse(redefines(*earlier, *newest))

    def test_a_bare_name_beside_another_number_never_stated_the_element(self):
        """The ruling reads the element's own number off the earlier row.  A
        bare name under an ion's number, or under none, is the newest name
        respelled, and matching it by that number onto whichever ion it names
        would be neither the element the ruling promises nor the vendor's
        current statement."""
        for earlier, newest in (
            (("Vanadium", "22541-77-1"), ("Vanadium V", "22537-31-1")),
            (("Lead", "14280-50-3"), ("Lead II", "14280-50-3")),
            (("Copper", ""), ("Copper II", "20427-59-2")),
            (("Copper", ""), ("Copper ion", "")),
        ):
            with self.subTest(earlier=earlier):
                self.assertFalse(redefines(*earlier, *newest))

    def test_every_element_the_rule_knows_has_its_number(self):
        """`redefines` looks the element up by the name it parsed, so a name in
        `ELEMENTS` without a number would raise on the first row it met."""
        for name in sorted(ELEMENTS):
            with self.subTest(name):
                self.assertIn(parse_species(name).element, ELEMENT_CAS)


class LeashTestCase(unittest.TestCase):
    def test_every_registered_ecoinvent_version_is_inside_the_rule(self):
        """The prepared correspondence tables are retired (#141), so the
        element/ion rule now governs every ecoinvent version.  This test said
        the exact opposite while the tables stood -- that inversion is the
        retirement's switch being thrown, not a regression."""
        for key in ("ecoinvent-3.8", "ecoinvent-3.9.1", "ecoinvent-3.10.1",
                    "ecoinvent-3.11", "ecoinvent-3.12"):
            with self.subTest(key=key):
                self.assertTrue(rule_governs(resolve_source_list(key)))

    def test_the_rule_never_governs_another_vendor(self):
        """The identities are derived from ecoinvent's releases and say nothing
        about anybody else's uuids, however BAFU's tables come and go."""
        bafu = resolve_source_list("bafu-2026-v1")
        self.assertFalse(rule_governs(bafu))
        from dataclasses import replace
        self.assertFalse(rule_governs(replace(bafu, prepared_match_table=None)))


if __name__ == "__main__":
    unittest.main()
