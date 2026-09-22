"""A particle size band does not answer to another band's name.

The rule #153 needed and nothing could express before the window was a field.

`Particles (PM10)` published two alternative labels on the build of 25 August
2026 (run `20260825T0605411116990000`, revision `b03c940b`) — `Particulate
Matter, > 2.5 um and < 10um` and `Particulates, > 2.5 um, and < 10um` — and both
name the **coarse fraction**, which is 2.5 to 10 µm and is not PM10.

They arrived honestly. #37 deliberately maps ecoinvent's coarse rows onto PM10
to reproduce the scores existing tools report, so those rows are members of
PM10's merge group, and `carry_member_names` keeps a member's name so that a
vendor's own spelling stays searchable (#113). Two correct rules, one wrong
outcome.

The cost was not the label. BAFU spells its coarse fraction the ecoinvent way,
so four of its rows then matched `Particles (PM10)` **on that label**, with
`basis_value` reading `Particulates, > 2.5 Um, And < 10um` — a second vendor
taking a curated trade nobody chose for it. The size-class branch in the merge
stops that happening again; this stops the claim being published in the first
place.
"""

import unittest

from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.particulate_size import size_classes
from brightway_flows.flow_layers.synonyms import (
    carry_member_names,
    names_another_size_window,
    promise_size_class_labels,
)


def _obj(object_id: str, pref: str) -> FlowObject:
    return FlowObject(
        flow_object_id=object_id,
        prefLabel=[{"@value": pref, "@language": "en"}],
        altLabel=[],
        properties={},
        references=[],
        created_from={},
    )


class _Flow:
    """The two fields the pass reads off an elementary flow."""

    def __init__(self, flow_object_id: str, *names: str) -> None:
        self.flow_object_id = flow_object_id
        self.source_refs = [
            {"list_name": "ecoinvent", "source_flow_name": name} for name in names
        ]


class TheCoarseFractionDoesNotNamePm10TestCase(unittest.TestCase):
    PM10 = "fo-4619792929f057e6"
    COARSE = "fo-ae1315a262379c68"
    PM2_5 = "fo-68bfa13f441778cb"

    def test_the_two_names_that_were_published_are_refused(self):
        """Both spellings, because ecoinvent renamed its own row at 3.9.1."""
        for name in (
            "Particulates, > 2.5 um, and < 10um",
            "Particulate Matter, > 2.5 um and < 10um",
        ):
            with self.subTest(name):
                self.assertTrue(names_another_size_window(name, self.PM10))

    def test_the_coarse_fraction_still_answers_to_its_own_names(self):
        """The rule is about a band naming a *different* band, not about
        withholding a vendor's spelling from the flow it belongs to."""
        for name in (
            "Particulates, > 2.5 um, and < 10um",
            "Particulate Matter, > 2.5 um and < 10um",
        ):
            with self.subTest(name):
                self.assertFalse(names_another_size_window(name, self.COARSE))

    def test_pm10s_own_spellings_are_not_refused(self):
        """`Particulates, < 10 um` is PM10 in three lists and must stay a name
        PM10 answers to — that is half of what #153 asked for."""
        for name in ("Particulates, < 10 um", "Particulates, < 10 um (stationary)"):
            with self.subTest(name):
                self.assertFalse(names_another_size_window(name, self.PM10))

    def test_a_source_category_does_not_make_it_another_window(self):
        """`(stationary)` says what emitted the particles, not how large they
        were, and its curated row reads `pm10` like the unqualified one."""
        self.assertFalse(
            names_another_size_window(
                "Particulates, < 10 um (stationary)", self.PM10
            )
        )

    def test_the_fine_fractions_name_does_not_name_pm10_either(self):
        """Not a case that has bitten, and the rule is not written for one
        pair."""
        self.assertTrue(
            names_another_size_window("Particulates, < 2.5 um", self.PM10)
        )
        self.assertFalse(
            names_another_size_window("Particulates, < 2.5 um", self.PM2_5)
        )

    def test_a_name_no_curated_row_uses_is_not_asked_about(self):
        """The rule reads the curated table and nothing else. A substance's
        ordinary synonyms are not its business."""
        self.assertFalse(names_another_size_window("Benzene", self.PM10))
        self.assertFalse(names_another_size_window("", self.PM10))

    def test_a_substance_that_is_not_a_size_window_is_not_asked_about(self):
        """Benzene's object may carry any name it likes."""
        self.assertFalse(
            names_another_size_window(
                "Particulates, > 2.5 um, and < 10um", "fo-not-a-size-class"
            )
        )

    def test_every_size_class_object_is_covered_by_the_rule(self):
        """Stated so that adding a window without a flow object — or renaming
        one — cannot quietly take it out of the rule's reach."""
        for identifier, size in size_classes().items():
            with self.subTest(identifier):
                other = next(
                    value for value in size_classes().values()
                    if value.id != identifier
                )
                self.assertFalse(
                    names_another_size_window("", size.flow_object_id),
                    "an empty name is never a band",
                )
                self.assertNotEqual(size.flow_object_id, other.flow_object_id)


class TheRejectionHappensBeforeClaimantsAreCountedTestCase(unittest.TestCase):
    """Where the test runs decides who keeps the name, not just who loses it.

    `names_a_place` and `names_a_class` disqualify a name for every substance
    alike, so where they run cannot change who else may have it. This one is
    about the *pair* — `Particulates, > 2.5 um, and < 10um` is wrong for PM10
    and right for the coarse flow — and in this build both want it: #37 maps
    ecoinvent's coarse rows onto PM10 while BAFU's reach the coarse flow.

    Run inside the carrying loop, the rejection leaves PM10 counted as a
    claimant, and the two-claimant rule then takes the name off the coarse flow
    as well. The flow whose name it actually is would be the one that lost it.
    So it runs in the proposal filter instead, and this is the case that says so.
    """

    PM10 = "fo-4619792929f057e6"
    COARSE = "fo-ae1315a262379c68"
    NAME = "Particulates, > 2.5 um, and < 10um"

    def test_the_coarse_flow_keeps_the_name_pm10_is_refused(self):
        objects = [
            _obj(self.PM10, "Particles (PM10)"),
            _obj(self.COARSE, "Particles (PM2.5 - PM10)"),
        ]
        stats = carry_member_names(
            objects,
            [
                _Flow(self.PM10, self.NAME, "Particulate Matter, > 2.5 um and < 10um"),
                _Flow(self.COARSE, self.NAME),
            ],
        )
        pm10, coarse = objects
        # PM10 carries nothing from its members; the one name on it is the
        # spelling the scheme promises every window (#196).
        self.assertEqual(
            [a.get("@value") for a in pm10.altLabel or []], ["Particulates, < 10 um"]
        )
        self.assertEqual(
            [a.get("@value") for a in coarse.altLabel or []], [self.NAME]
        )
        self.assertEqual(stats["rejected_names_another_size_window"], 2)
        self.assertEqual(
            stats["rejected_two_substances_claim_it"], 0,
            "PM10 must not count as a claimant of a name it cannot have",
        )

    def test_pm10_alone_is_still_refused(self):
        """With no rival, only this rule can stop the name being carried."""
        objects = [_obj(self.PM10, "Particles (PM10)")]
        stats = carry_member_names(objects, [_Flow(self.PM10, self.NAME)])
        self.assertEqual(
            [a.get("@value") for a in objects[0].altLabel or []], ["Particulates, < 10 um"]
        )
        self.assertEqual(stats["rejected_names_another_size_window"], 1)


class EveryWindowIsPromisedItsSpellingTestCase(unittest.TestCase):
    """`promise_size_class_labels` keeps the scheme's promise by identifier.

    The merge rebuilds an object when it mints a flow on it, and the rebuilt
    object knows no window; on the first build of stage 1 (#196) that left PM10
    and the above-ten fraction with none of their promised spellings while the
    other five windows had theirs. Keyed on the object id, the pass cannot lose
    them that way."""

    PM10 = "fo-4619792929f057e6"
    ABOVE = "fo-a30bea921eacba3f"

    def test_a_window_with_no_labels_is_given_its_spellings(self):
        objects = [_obj(self.PM10, "Particles (PM10)"), _obj(self.ABOVE, "Particles (> PM10)")]
        written = promise_size_class_labels(objects)
        self.assertEqual(written, 2)
        self.assertEqual([a.get("@value") for a in objects[0].altLabel], ["Particulates, < 10 um"])
        self.assertEqual([a.get("@value") for a in objects[1].altLabel], ["Particulates, > 10 um"])
        provenance = objects[0].altLabel[0]["provenance"]
        self.assertEqual(provenance["prov:wasGeneratedBy"], "particulate_size_class")

    def test_a_spelling_already_published_is_left_alone(self):
        obj = _obj(self.PM10, "Particles (PM10)")
        obj.altLabel = [{"@value": "particulates, < 10 UM", "@language": "en"}]
        self.assertEqual(promise_size_class_labels([obj]), 0)
        self.assertEqual(len(obj.altLabel), 1)

    def test_a_spelling_another_substance_publishes_is_not_written(self):
        obj = _obj(self.PM10, "Particles (PM10)")
        rival = _obj("fo-somebody-else", "Particulates, < 10 um")
        self.assertEqual(promise_size_class_labels([obj, rival]), 0)
        self.assertEqual(obj.altLabel, [])

    def test_two_windows_whose_spellings_differ_only_in_punctuation_both_keep_theirs(self):
        """`< 10 um` and `> 10 um` fold to one claim key; the promise and the
        withdrawal both read the exact text instead."""
        objects = [_obj(self.PM10, "Particles (PM10)"), _obj(self.ABOVE, "Particles (> PM10)")]
        carry_member_names(objects, [])
        carry_member_names(objects, [])  # a second pass, as the merge runs it per list
        self.assertEqual([a.get("@value") for a in objects[0].altLabel], ["Particulates, < 10 um"])
        self.assertEqual([a.get("@value") for a in objects[1].altLabel], ["Particulates, > 10 um"])

    def test_a_substance_that_is_not_a_window_is_untouched(self):
        obj = _obj("fo-ammonium", "Ammonium")
        self.assertEqual(promise_size_class_labels([obj]), 0)
        self.assertEqual(obj.altLabel, [])

    def test_the_member_name_pass_runs_it(self):
        objects = [_obj(self.ABOVE, "Particles (> PM10)")]
        stats = carry_member_names(objects, [])
        self.assertEqual(stats["size_class_labels_promised"], 1)
        self.assertEqual([a.get("@value") for a in objects[0].altLabel], ["Particulates, > 10 um"])


if __name__ == "__main__":
    unittest.main()
