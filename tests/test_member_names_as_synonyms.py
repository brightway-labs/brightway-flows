"""A name a source list published stays a name the list answers to.

The pass is `flow_layers/synonyms.py` and the property it establishes is that a
published name names exactly one substance.  These assert both halves: the names
it carries, and the names it refuses to carry or withdraws because they would
answer for two substances at once (#113).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.flow_layers.synonyms import (
    PLACES_FILEPATH,
    carry_member_names,
    load_place_vocabulary,
    names_a_place,
    place_vocabulary,
)


def _obj(object_id: str, pref: str, alts: tuple[str, ...] = ()) -> FlowObject:
    return FlowObject(
        flow_object_id=object_id,
        prefLabel=[{"@value": pref, "@language": "en"}],
        altLabel=[{"@value": value, "@language": "en"} for value in alts],
        properties={},
        references=[],
        created_from={},
    )


class _Flow:
    """The two fields the pass reads off an elementary flow.

    A stand-in rather than the record: `ElementaryFlow` requires a resolved
    context and a unit IRI, and this pass reads neither, so building one would
    be asserting that the pass depends on things it does not.
    """

    def __init__(self, flow_object_id: str, *names: str) -> None:
        self.flow_object_id = flow_object_id
        self.source_refs = [
            {"list_name": "ecoinvent", "source_flow_name": name} for name in names
        ]


def _labels(obj: FlowObject) -> list[str]:
    return [row["@value"] for row in obj.altLabel or []]


class TheCuratedVocabularyTestCase(unittest.TestCase):
    """The file is a ruling, so a malformed one raises rather than applying."""

    def test_the_shipped_file_loads(self):
        vocab = load_place_vocabulary()
        self.assertIn("ground", vocab.places)
        self.assertIn("occupation", vocab.land_flow_prefixes)

    def test_the_cached_loader_answers_the_same(self):
        self.assertEqual(place_vocabulary(), load_place_vocabulary())

    def test_a_missing_section_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "places.json"
            path.write_bytes(orjson.dumps({"places": {"values": ["ground"]}}))
            with self.assertRaises(ValueError):
                load_place_vocabulary(path)

    def test_an_empty_section_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "places.json"
            path.write_bytes(orjson.dumps({
                "land_flow_prefixes": {"values": ["occupation"]},
                "places": {"values": []},
            }))
            with self.assertRaises(ValueError):
                load_place_vocabulary(path)

    def test_every_value_is_lower_case_in_the_file(self):
        """The comparison folds case; the file should not rely on that."""
        payload = orjson.loads(PLACES_FILEPATH.read_bytes())
        for section in ("land_flow_prefixes", "places"):
            for value in payload[section]["values"]:
                with self.subTest(value):
                    self.assertEqual(value, value.lower())

    def test_every_section_says_why(self):
        payload = orjson.loads(PLACES_FILEPATH.read_bytes())
        for section in ("land_flow_prefixes", "places"):
            with self.subTest(section):
                self.assertTrue(payload[section]["comment"].strip())


class WhichNamesDescribeAPlaceTestCase(unittest.TestCase):
    """`Hafnium, In Ground` is not another name for hafnium."""

    def test_a_trailing_place_is_a_place(self):
        self.assertTrue(names_a_place("Hafnium, In Ground"))
        self.assertTrue(names_a_place("Bromine, In Water"))

    def test_a_land_flow_prefix_is_a_place(self):
        self.assertTrue(names_a_place("Occupation, Annual Crop, Irrigated"))
        self.assertTrue(names_a_place("Transformation, From Seabed, Mining"))

    def test_a_stated_concentration_is_an_ore_grade(self):
        self.assertTrue(
            names_a_place("Aluminium, 24% In Bauxite, 11% In Crude Ore, In Ground")
        )

    def test_a_chemical_name_is_not_a_place(self):
        for name in [
            "Dichloroethylene",
            "Ethane, 1,1,2-trichloro-1,2,2-trifluoro-, CFC-113",
            "HFE-143a",
            "Quizalofop-P-tefuryl",
            "AOX, Adsorbable Organic Halides",
        ]:
            with self.subTest(name):
                self.assertFalse(names_a_place(name))

    def test_the_prefix_test_matches_a_whole_segment(self):
        """`Occupational Exposure` is not an occupation flow."""
        self.assertFalse(names_a_place("Occupational Exposure"))

    def test_the_place_test_matches_a_whole_segment(self):
        """`Ground` alone is a place; `Ground Nut Oil` is a substance."""
        self.assertFalse(names_a_place("Oil, In Ground Nut"))


class CarryingAMemberNameTestCase(unittest.TestCase):
    """The half the issue asked for."""

    def test_a_demoted_name_becomes_a_synonym(self):
        obj = _obj("fo-1", "Methyl Trifluoromethyl Ether")
        stats = carry_member_names([obj], [_Flow("fo-1", "HFE-143a")])
        self.assertEqual(_labels(obj), ["HFE-143a"])
        self.assertEqual(stats["names_carried"], 1)

    def test_a_name_the_substance_already_has_is_not_added_twice(self):
        obj = _obj("fo-1", "Methyl Trifluoromethyl Ether", ("HFE-143a",))
        carry_member_names([obj], [_Flow("fo-1", "HFE-143a")])
        self.assertEqual(_labels(obj), ["HFE-143a"])

    def test_the_substances_own_name_is_not_added_as_a_synonym(self):
        obj = _obj("fo-1", "Bromomethane")
        carry_member_names([obj], [_Flow("fo-1", "bromomethane")])
        self.assertEqual(_labels(obj), [])

    def test_a_place_name_is_not_carried(self):
        obj = _obj("fo-1", "Hafnium")
        stats = carry_member_names([obj], [_Flow("fo-1", "Hafnium, In Ground")])
        self.assertEqual(_labels(obj), [])
        self.assertEqual(stats["rejected_names_a_place"], 1)

    def test_a_name_two_substances_claim_is_carried_by_neither(self):
        """`Arsenic Ion` reaches both `Arsenic` and `Arsenic(5+)`."""
        first, second = _obj("fo-1", "Arsenic"), _obj("fo-2", "Arsenic(5+)")
        stats = carry_member_names(
            [first, second],
            [_Flow("fo-1", "Arsenic Ion"), _Flow("fo-2", "Arsenic Ion")],
        )
        self.assertEqual(_labels(first), [])
        self.assertEqual(_labels(second), [])
        self.assertEqual(stats["rejected_two_substances_claim_it"], 2)

    def test_punctuation_does_not_hide_a_claim_from_the_other_side(self):
        """`Arsenic Ion` and `Arsenic, Ion` are one name for this purpose."""
        first, second = _obj("fo-1", "Arsenic"), _obj("fo-2", "Arsenic(5+)")
        carry_member_names(
            [first, second],
            [_Flow("fo-1", "Arsenic Ion"), _Flow("fo-2", "Arsenic, Ion")],
        )
        self.assertEqual(_labels(first), [])
        self.assertEqual(_labels(second), [])

    def test_a_name_that_is_another_substances_name_is_not_carried(self):
        first, second = _obj("fo-1", "Methane"), _obj("fo-2", "Methane (fossil)")
        stats = carry_member_names([first, second], [_Flow("fo-2", "Methane")])
        self.assertEqual(_labels(second), [])
        self.assertEqual(stats["rejected_already_names_a_substance"], 1)

    def test_a_name_that_is_another_substances_synonym_is_not_carried(self):
        first = _obj("fo-1", "Trichloroethane", ("Methyl chloroform",))
        second = _obj("fo-2", "HCFC-140")
        carry_member_names([first, second], [_Flow("fo-2", "Methyl chloroform")])
        self.assertEqual(_labels(second), [])

    def test_two_substances_cannot_take_one_name_by_arriving_in_order(self):
        """The claim is staked as it is written, not only read beforehand."""
        first, second = _obj("fo-1", "Alpha"), _obj("fo-2", "Beta")
        carry_member_names(
            [first, second], [_Flow("fo-1", "Shared name"), _Flow("fo-2", "Shared name")]
        )
        self.assertEqual(_labels(first) + _labels(second), [])


class WithdrawingASharedSynonymTestCase(unittest.TestCase):
    """The half that makes the property hold for names this pass did not write."""

    def test_a_synonym_on_two_substances_is_withdrawn_from_both(self):
        first = _obj("fo-1", "(1R,4R)-Camphor", ("camphor",))
        second = _obj("fo-2", "(1S,4S)-Camphor", ("camphor",))
        stats = carry_member_names([first, second], [])
        self.assertEqual(_labels(first), [])
        self.assertEqual(_labels(second), [])
        self.assertEqual(stats["synonyms_withdrawn"], 2)

    def test_a_synonym_that_is_another_substances_name_is_withdrawn(self):
        first = _obj("fo-1", "MCPA")
        second = _obj("fo-2", "Something else", ("mcpa",))
        carry_member_names([first, second], [])
        self.assertEqual(_labels(second), [])

    def test_the_name_itself_is_never_withdrawn(self):
        """A substance has to be called something, so the synonym gives way."""
        first = _obj("fo-1", "MCPA")
        second = _obj("fo-2", "Something else", ("mcpa",))
        carry_member_names([first, second], [])
        self.assertEqual(
            [row["@value"] for row in first.prefLabel], ["MCPA"]
        )

    def test_a_synonym_unique_to_one_substance_survives(self):
        obj = _obj("fo-1", "Bromomethane", ("Methyl bromide",))
        stats = carry_member_names([obj], [])
        self.assertEqual(_labels(obj), ["Methyl bromide"])
        self.assertEqual(stats["synonyms_withdrawn"], 0)

    def test_two_substances_sharing_a_name_keep_their_names(self):
        """Only synonyms are withdrawn; a shared *name* is a different defect."""
        first, second = _obj("fo-1", "Camphor"), _obj("fo-2", "Camphor")
        carry_member_names([first, second], [])
        self.assertEqual(
            [row["@value"] for row in first.prefLabel], ["Camphor"]
        )
        self.assertEqual(
            [row["@value"] for row in second.prefLabel], ["Camphor"]
        )


class ASubstanceHasOnePreferredLabelTestCase(unittest.TestCase):
    """The rows the layering kept because two names were the same length.

    `HFE-569sf2` and `n-HFE-7200` are one substance and ten characters each, so
    the length rule chose neither and the object carried both as preferred-label
    rows.  Only the first is published as the substance's name and only the
    first is indexed, so the second was in the file and could not be found.
    """

    def _obj_two_prefs(self):
        obj = _obj("fo-1", "HFE-569sf2")
        obj.prefLabel = list(obj.prefLabel) + [
            {"@value": "n-HFE-7200", "@language": "en"}
        ]
        return obj

    def test_the_second_row_becomes_a_synonym(self):
        obj = self._obj_two_prefs()
        stats = carry_member_names([obj], [])
        self.assertEqual(_labels(obj), ["n-HFE-7200"])
        self.assertEqual(stats["preferred_labels_demoted"], 1)

    def test_the_published_name_does_not_move(self):
        """`coerce_pref_label` returns the first row, so the first row stays."""
        obj = self._obj_two_prefs()
        carry_member_names([obj], [])
        self.assertEqual([row["@value"] for row in obj.prefLabel], ["HFE-569sf2"])

    def test_a_substance_with_one_name_is_untouched(self):
        obj = _obj("fo-1", "Water")
        stats = carry_member_names([obj], [])
        self.assertEqual([row["@value"] for row in obj.prefLabel], ["Water"])
        self.assertEqual(stats["preferred_labels_demoted"], 0)

    def test_a_demoted_row_is_still_subject_to_uniqueness(self):
        """Demoting must not smuggle in a name another substance answers to."""
        first = self._obj_two_prefs()
        second = _obj("fo-2", "n-HFE-7200")
        carry_member_names([first, second], [])
        self.assertEqual(_labels(first), [])

    def test_the_substance_is_reported_as_changed(self):
        obj = self._obj_two_prefs()
        changed: set[str] = set()
        carry_member_names([obj], [], changed=changed)
        self.assertEqual(changed, {"fo-1"})


class TheInvariantTestCase(unittest.TestCase):
    """One published name, one substance -- reported off the records."""

    def test_the_pass_reports_no_name_answering_for_two_substances(self):
        first = _obj("fo-1", "Arsenic", ("arsenic ion",))
        second = _obj("fo-2", "Arsenic(5+)", ("Arsenic, Ion",))
        stats = carry_member_names(
            [first, second],
            [_Flow("fo-1", "Arsenic Ion"), _Flow("fo-2", "Hafnium, In Ground")],
        )
        self.assertEqual(stats["synonyms_naming_two_substances"], 0)

    def test_two_substances_with_one_name_are_counted_apart(self):
        """The pass cannot withdraw a name, so it must not claim to have.

        `Camphor` naming two substances is a defect, and a different one: both
        of them have to be called something, so neither label can give way.
        Counting it with the synonyms would make the invariant above impossible
        to hold and hide the two figures in one.
        """
        first, second = _obj("fo-1", "Camphor"), _obj("fo-2", "Camphor")
        stats = carry_member_names([first, second], [])
        self.assertEqual(stats["synonyms_naming_two_substances"], 0)
        self.assertEqual(stats["names_shared_by_two_substances"], 1)

    def test_a_name_held_as_a_synonym_counts_against_the_invariant(self):
        first = _obj("fo-1", "Camphor")
        second = _obj("fo-2", "Something else", ("Camphor",))
        stats = carry_member_names([first, second], [])
        self.assertEqual(stats["synonyms_naming_two_substances"], 0)
        self.assertEqual(stats["names_shared_by_two_substances"], 0)

    def test_the_substances_whose_synonyms_moved_are_named(self):
        """What the merge needs, because it writes only what it is told to."""
        first = _obj("fo-1", "Arsenic", ("camphor",))
        second = _obj("fo-2", "Arsenic(5+)", ("camphor",))
        third = _obj("fo-3", "Methyl Trifluoromethyl Ether")
        untouched = _obj("fo-4", "Water")
        changed: set[str] = set()
        carry_member_names(
            [first, second, third, untouched],
            [_Flow("fo-3", "HFE-143a")],
            changed=changed,
        )
        self.assertEqual(changed, {"fo-1", "fo-2", "fo-3"})

    def test_every_counter_is_reported_even_at_zero(self):
        """A missing measure reads as `unresolved`, not as zero.

        The invariant is claimed as `equals: 0`, so on the builds where it
        holds -- which is all of them -- a `Counter` that had dropped the key
        would report the expectation as having no subject in this build.
        """
        stats = carry_member_names([_obj("fo-1", "Water")], [])
        for key in (
            "names_carried",
            "names_shared_by_two_substances",
            "rejected_names_a_place",
            "rejected_names_another_size_window",
            "rejected_two_substances_claim_it",
            "synonyms_naming_two_substances",
            "synonyms_withdrawn",
        ):
            with self.subTest(key):
                self.assertIn(key, stats)
                self.assertEqual(stats[key], 0)

    def test_running_it_twice_changes_nothing_further(self):
        objects = [
            _obj("fo-1", "Methyl Trifluoromethyl Ether"),
            _obj("fo-2", "Arsenic", ("camphor",)),
            _obj("fo-3", "Arsenic(5+)", ("camphor",)),
        ]
        flows = [_Flow("fo-1", "HFE-143a"), _Flow("fo-2", "Arsenic Ion")]
        carry_member_names(objects, flows)
        once = [_labels(obj) for obj in objects]
        carry_member_names(objects, flows)
        self.assertEqual([_labels(obj) for obj in objects], once)

    def test_a_carried_name_says_where_it_came_from(self):
        obj = _obj("fo-1", "Methyl Trifluoromethyl Ether")
        carry_member_names([obj], [_Flow("fo-1", "HFE-143a")])
        provenance = obj.altLabel[0]["provenance"]
        self.assertEqual(provenance["prov:wasDerivedFrom"], "source_flow_name")
        self.assertEqual(provenance["prov:wasGeneratedBy"], "carry_member_names")


if __name__ == "__main__":
    unittest.main()
