"""A curator's answer to a collision, and what applying it may not lose.

`pipeline/collisions.py` reports two live flows of one substance in one context
and says the pipeline cannot decide whether they are one flow.  These are the
decisions, and the properties that make them safe to apply: the survivor is the
one the ruling names rather than the one a sort would reach, the factors of the
flow being collapsed arrive on the survivor rather than going the way #31's
did, and a ruling written about a group that has since changed is not obeyed.
"""

import json
import unittest
from pathlib import Path

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.lcia.records import StatedFactor, stated_category
from brightway_flows.pipeline.collision_decisions import (
    DECISIONS_FILEPATH,
    DECISIONS_SCHEMA_VERSION,
    CollisionRuling,
    CollisionRulingError,
    apply_collision_rulings,
    load_collision_rulings,
)
from brightway_flows.pipeline.collisions import find_collisions


class _Row:
    """An elementary flow, in the fields a ruling reads and writes."""

    def __init__(
        self,
        elementary_flow_id,
        flow_object_id="fo-1",
        context_iri="ctx-1",
        unit="kg",
        factors=(),
        source_refs=None,
        deprecated=False,
    ):
        self.elementary_flow_id = elementary_flow_id
        self.flow_object_id = flow_object_id
        self.context_iri = context_iri
        self.unit = unit
        self.lcia_methods = _factors(elementary_flow_id, factors)
        self.source_refs = source_refs
        self.owl_deprecated = True if deprecated else None
        self.dcterms_is_replaced_by = None
        self.is_replaced_by_uuid = None


def _factors(flow_uuid, factors):
    """The characterisation rows a fixture flow carries, as records."""
    return [
        StatedFactor(
            category=stated_category(uuid=name, name=name),
            flow_uuid=flow_uuid,
            amount=value,
        )
        for name, value in factors
    ]


def _flow(uuid):
    return Flow(uuid=uuid, name=uuid, source="EF 3.1")


def _ruling(survivor="rich", merged=("poor",)):
    return {
        ("fo-1", "ctx-1", "kg"): CollisionRuling(
            flow_object_id="fo-1",
            context_iri="ctx-1",
            unit="kg",
            survivor=survivor,
            merged=tuple(merged),
            names=("designation", "chemical name"),
            comment="one substance published twice",
        )
    }


class ApplyingARulingTestCase(unittest.TestCase):
    def setUp(self):
        self.rich = _Row("rich", factors=(("gwp", 9220.0),))
        self.poor = _Row("poor")
        self.flows = [_flow("rich"), _flow("poor")]

    def _apply(self, rulings=None):
        return apply_collision_rulings(
            flows=self.flows,
            elementary_flows=[self.rich, self.poor],
            rulings=rulings or _ruling(),
        )

    def test_the_ruled_flow_is_deprecated_onto_the_ruled_survivor(self):
        counts = self._apply()
        self.assertEqual(counts["collision_rulings_applied"], 1)
        self.assertTrue(self.poor.owl_deprecated)
        self.assertEqual(self.poor.is_replaced_by_uuid, "rich")
        self.assertEqual(self.poor.dcterms_is_replaced_by, "urn:uuid:rich")
        self.assertIsNone(self.rich.owl_deprecated)

    def test_the_harmonised_flow_is_deprecated_with_its_elementary_row(self):
        """Both records are published, so a deprecation on one of them only
        would put the export in two minds about the same flow."""
        self._apply()
        deprecated = [f for f in self.flows if f.owl_deprecated]
        self.assertEqual([f.uuid for f in deprecated], ["poor"])
        self.assertEqual(deprecated[0].is_replaced_by_uuid, "rich")

    def test_the_survivor_is_the_ruling_s_and_not_the_richer_row(self):
        """The point of a ruling: deduplication keeps whichever row holds more
        factors, and a curator may have reason to keep the other -- the one a
        source list maps onto, say."""
        counts = self._apply(_ruling(survivor="poor", merged=("rich",)))
        self.assertEqual(counts["collision_rulings_applied"], 1)
        self.assertTrue(self.rich.owl_deprecated)
        self.assertIsNone(self.poor.owl_deprecated)

    def test_the_collapsed_row_s_factors_reach_the_survivor(self):
        """#31 in one line: the flow that is deprecated takes its
        characterisation with it unless something carries it across."""
        self.poor.lcia_methods = _factors(
            "poor", [("odp", 0.57)]
        )
        counts = self._apply()
        self.assertEqual(counts["collision_ruling_factors_added"], 1)
        carried = [m for m in self.rich.lcia_methods if m.category.uuid == "odp"]
        self.assertEqual(len(carried), 1)
        self.assertEqual(carried[0].amount, 0.57)

    def test_a_factor_the_survivor_already_holds_is_not_duplicated(self):
        self.poor.lcia_methods = _factors("poor", [("gwp", 9220.0)])
        counts = self._apply()
        self.assertEqual(counts["collision_ruling_factors_added"], 0)
        self.assertEqual(len(self.rich.lcia_methods), 1)

    def test_two_rows_publishing_one_number_leave_no_trace_of_a_choice(self):
        """Agreement is the usual case, and there is nothing to record about
        it: no number was declined."""
        self.poor.lcia_methods = _factors("poor", [("gwp", 9220.0)])
        counts = self._apply()
        self.assertEqual(counts["collision_ruling_factor_values_differ"], 0)
        self.assertEqual(self.rich.lcia_methods[0].superseded_values, [])

    def test_a_carried_factor_says_where_it_came_from(self):
        self.poor.lcia_methods = _factors(
            "poor", [("odp", 0.57)]
        )
        self._apply()
        carried = next(m for m in self.rich.lcia_methods if m.category.uuid == "odp")
        self.assertEqual(
            carried.provenance.was_generated_by, "pipeline.collision_decisions"
        )
        self.assertEqual(carried.provenance.had_primary_source, ["urn:uuid:poor"])

    def test_the_collapsed_row_s_source_references_reach_the_survivor(self):
        """A source list that resolved onto the collapsed flow resolved onto
        this substance in this context, and that is what the survivor now is."""
        self.poor.source_refs = [{"list_name": "ecoinvent", "list_version": "3.8"}]
        counts = self._apply()
        self.assertEqual(counts["collision_ruling_source_refs_carried"], 1)
        self.assertEqual(
            [ref["list_name"] for ref in self.rich.source_refs], ["ecoinvent"]
        )

    def test_a_source_reference_the_survivor_already_holds_is_not_repeated(self):
        ref = {"list_name": "ecoinvent", "list_version": "3.8"}
        self.poor.source_refs = [dict(ref)]
        self.rich.source_refs = [dict(ref)]
        counts = self._apply()
        self.assertEqual(counts["collision_ruling_source_refs_carried"], 0)
        self.assertEqual(len(self.rich.source_refs), 1)

    def test_the_collision_is_gone_afterwards(self):
        """What the whole exercise is for: the guard reported a question, and
        after the answer there is no question left to report."""
        self.assertEqual(len(find_collisions([self.rich, self.poor])), 1)
        self._apply()
        self.assertEqual(find_collisions([self.rich, self.poor]), [])


class ChoosingBetweenTwoPublishedNumbersTestCase(unittest.TestCase):
    """Both rows publish the factor and say different things about it (#63).

    Before this, the survivor's number stood whatever it was and the other
    disappeared without a trace -- and which row was the survivor came down to
    an identifier sort, so on the 2026-08-12 build the more precise of the two
    numbers was kept 72 times out of 152 and thrown away 70.
    """

    def _apply(self, kept, other, *, ruling=None):
        self.rich = _Row("rich", factors=(("ecotox", kept),))
        self.poor = _Row("poor", factors=(("ecotox", other),))
        return apply_collision_rulings(
            flows=[_flow("rich"), _flow("poor")],
            elementary_flows=[self.rich, self.poor],
            rulings=ruling or _ruling(),
        )

    @property
    def _factor(self):
        return next(m for m in self.rich.lcia_methods if m.category.uuid == "ecotox")

    def test_the_precise_number_replaces_the_rounded_one(self):
        """EF publishes one refrigerant twice, under a designation and a
        chemical name, and `0.000118` is `0.00011755` rounded."""
        counts = self._apply(0.000118, 0.00011755)
        self.assertEqual(counts["collision_ruling_factors_made_precise"], 1)
        self.assertEqual(self._factor.amount, 0.00011755)

    def test_the_rounded_number_does_not_replace_the_precise_one(self):
        counts = self._apply(0.00011755, 0.000118)
        self.assertEqual(counts["collision_ruling_factors_made_precise"], 0)
        self.assertEqual(self._factor.amount, 0.00011755)

    def test_the_number_not_kept_is_recorded_on_the_factor_it_lost_to(self):
        """Whichever wins, a reader can tell a number was chosen rather than
        simply published, and what the other one was."""
        self._apply(0.000118, 0.00011755)
        superseded = self._factor.superseded_values
        self.assertEqual([row.amount for row in superseded],
                         [0.000118])
        self.assertAlmostEqual(superseded[0].relative_difference,
                               0.000118 / 0.00011755 - 1)

    def test_the_declined_number_says_which_flow_published_it(self):
        self._apply(0.000118, 0.00011755)
        declined = self._factor.superseded_values[0].provenance
        self.assertEqual(declined.had_primary_source, ["urn:uuid:rich"])
        self.assertEqual(declined.was_generated_by, "pipeline.collision_decisions")

    def test_a_replaced_number_says_where_it_came_from(self):
        """The row's own value is now the other flow's, so the row's own
        provenance has to say so."""
        self._apply(0.000118, 0.00011755)
        self.assertEqual(self._factor.provenance.had_primary_source,
                         ["urn:uuid:poor"])

    def test_two_numbers_neither_of_which_is_the_other_rounded_keep_the_survivor_s(self):
        """Nothing here adjudicates between two numbers.  Where they are two
        numbers, the ruling's survivor is what the ruling decided, and the
        other is recorded rather than preferred."""
        counts = self._apply(1.23e-05, 1.24e-05)
        self.assertEqual(counts["collision_ruling_factors_made_precise"], 0)
        self.assertEqual(counts["collision_ruling_factor_values_differ"], 1)
        self.assertEqual(self._factor.amount, 1.23e-05)
        self.assertEqual(
            [row.amount for row in self._factor.superseded_values],
            [1.24e-05],
        )

    def test_a_gap_too_wide_to_be_rounding_is_reported(self):
        """#281's turpentine pairs disagree by up to 245 times.  Discarding a
        number that far from the one kept is a decision about which source to
        believe, and it should not pass in silence."""
        counts = self._apply(0.0038, 0.932)
        self.assertEqual(counts["collision_ruling_factor_values_conflict"], 1)

    def test_a_rounding_difference_is_not_reported_as_a_conflict(self):
        counts = self._apply(0.000118, 0.00011755)
        self.assertEqual(counts["collision_ruling_factor_values_conflict"], 0)

    def test_a_stated_zero_against_a_number_is_a_conflict(self):
        """A relative difference is not defined across zero, and a row saying
        `0` against a row saying `0.5` is not a rounding of anything."""
        counts = self._apply(0.0, 0.5)
        self.assertEqual(counts["collision_ruling_factor_values_conflict"], 1)
        self.assertEqual(self._factor.amount, 0.0)
        self.assertIsNone(self._factor.superseded_values[0].relative_difference)

    def test_the_ruling_is_still_applied_when_the_numbers_conflict(self):
        """Refusing to obey a curator's ruling here would leave the collision
        standing while looking answered.  The warning is how somebody sees it."""
        counts = self._apply(0.0038, 0.932)
        self.assertEqual(counts["collision_rulings_applied"], 1)
        self.assertTrue(self.poor.owl_deprecated)

    def test_the_survivor_s_other_rows_are_left_alone(self):
        rich = _Row("rich", factors=(("ecotox", 0.000118), ("gwp", 9220.0)))
        poor = _Row("poor", factors=(("ecotox", 0.00011755),))
        apply_collision_rulings(
            flows=[_flow("rich"), _flow("poor")],
            elementary_flows=[rich, poor],
            rulings=_ruling(),
        )
        gwp = next(m for m in rich.lcia_methods if m.category.uuid == "gwp")
        self.assertEqual(gwp.amount, 9220.0)
        self.assertIsNone(gwp.provenance)
        self.assertEqual(gwp.superseded_values, [])
        self.assertEqual(len(rich.lcia_methods), 2)


class RulingsThatMustNotBeAppliedTestCase(unittest.TestCase):
    def test_a_ruling_whose_group_has_changed_is_not_obeyed(self):
        """A ruling is evidence about a named pair. A third flow in the group
        means it was written about different data, and #34's decisions file
        makes the same refusal for the same reason."""
        rich = _Row("rich", factors=(("gwp", 1.0),))
        poor = _Row("poor")
        third = _Row("third")
        counts = apply_collision_rulings(
            flows=[_flow("rich"), _flow("poor"), _flow("third")],
            elementary_flows=[rich, poor, third],
            rulings=_ruling(),
        )
        self.assertEqual(counts["collision_rulings_stale"], 1)
        self.assertEqual(counts["collision_rulings_applied"], 0)
        self.assertIsNone(poor.owl_deprecated)

    def test_a_ruling_for_a_collision_not_in_this_run_is_counted_not_raised(self):
        """A bounded run holds a few hundred flows and matches almost no ruling;
        a file only a full build could load is one nobody could develop
        against."""
        counts = apply_collision_rulings(
            flows=[], elementary_flows=[], rulings=_ruling()
        )
        self.assertEqual(counts["collision_rulings_absent"], 1)
        self.assertEqual(counts["collision_rulings_applied"], 0)

    def test_a_collision_already_resolved_is_not_ruled_on_again(self):
        rich = _Row("rich", factors=(("gwp", 1.0),))
        poor = _Row("poor", deprecated=True)
        counts = apply_collision_rulings(
            flows=[_flow("rich"), _flow("poor")],
            elementary_flows=[rich, poor],
            rulings=_ruling(),
        )
        self.assertEqual(counts["collision_rulings_absent"], 1)


class ARulingThatNamesTheWrongCollisionTestCase(unittest.TestCase):
    """Naming the wrong compartment used to read as a bounded run.

    Seven shipped rulings named `envi-air-hist15me` while every flow they named
    was in `envi-air-mest15me-ru10pesq`: EF 3.1 calls one compartment
    `Emissions to non-urban air or from high stacks`, the project maps that
    whole phrase to rural medium stack under 150 metres, and the rulings had
    been written from the second half of EF's own name for it.  Each applied to
    nothing and each was counted `collision_rulings_absent`, which is what a
    bounded run produces by the hundred -- so three collisions #44 had already
    decided went on being published twice and nothing said so (#106).
    """

    def setUp(self):
        # Both rows are live, together, in a context the ruling does not name.
        self.rich = _Row("rich", context_iri="ctx-2", factors=(("gwp", 1.0),))
        self.poor = _Row("poor", context_iri="ctx-2")

    def _apply(self):
        return apply_collision_rulings(
            flows=[_flow("rich"), _flow("poor")],
            elementary_flows=[self.rich, self.poor],
            rulings=_ruling(),
        )

    def test_it_is_counted_as_misplaced_and_not_as_absent(self):
        counts = self._apply()
        self.assertEqual(counts["collision_rulings_misplaced"], 1)
        self.assertEqual(counts["collision_rulings_absent"], 0)

    def test_it_is_still_not_applied(self):
        """Saying so is the fix; obeying a ruling keyed on the wrong collision
        is not, because the key is the whole of what a ruling is about."""
        counts = self._apply()
        self.assertEqual(counts["collision_rulings_applied"], 0)
        self.assertIsNone(self.poor.owl_deprecated)

    def test_a_ruling_whose_flows_are_simply_absent_stays_absent(self):
        """The other half: a bounded run must go on reading as a bounded run."""
        counts = apply_collision_rulings(
            flows=[], elementary_flows=[], rulings=_ruling()
        )
        self.assertEqual(counts["collision_rulings_misplaced"], 0)
        self.assertEqual(counts["collision_rulings_absent"], 1)

    def test_flows_scattered_over_two_other_collisions_are_not_misplaced(self):
        """Nor is a ruling whose pair has come apart, which is a different
        question and the one `collision_rulings_stale` is about."""
        counts = apply_collision_rulings(
            flows=[_flow("rich"), _flow("poor")],
            elementary_flows=[
                _Row("rich", context_iri="ctx-2", factors=(("gwp", 1.0),)),
                _Row("poor", context_iri="ctx-3"),
            ],
            rulings=_ruling(),
        )
        self.assertEqual(counts["collision_rulings_misplaced"], 0)
        self.assertEqual(counts["collision_rulings_absent"], 1)

    def test_a_half_deprecated_pair_is_not_misplaced(self):
        """A ruling one of whose rows has already been retired elsewhere has
        been answered, not mis-keyed."""
        counts = apply_collision_rulings(
            flows=[_flow("rich"), _flow("poor")],
            elementary_flows=[
                _Row("rich", context_iri="ctx-2", factors=(("gwp", 1.0),)),
                _Row("poor", context_iri="ctx-2", deprecated=True),
            ],
            rulings=_ruling(),
        )
        self.assertEqual(counts["collision_rulings_misplaced"], 0)
        self.assertEqual(counts["collision_rulings_absent"], 1)


class ReadingTheFileTestCase(unittest.TestCase):
    def _write(self, tmp, decisions):
        path = Path(tmp) / "rulings.json"
        path.write_text(json.dumps({"schema_version": 1, "decisions": decisions}))
        return path

    def test_a_ruling_is_keyed_on_the_collision(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, [{
                "flow_object_id": "fo-1", "context_iri": "ctx-1", "unit": "kg",
                "decision": "merge", "survivor_elementary_flow_id": "rich",
                "merged_elementary_flow_ids": ["poor"],
            }])
            index = load_collision_rulings(path)
        self.assertEqual(list(index), [("fo-1", "ctx-1", "kg")])
        self.assertEqual(index[("fo-1", "ctx-1", "kg")].survivor, "rich")

    def test_an_unreadable_ruling_raises_rather_than_being_skipped(self):
        """A malformed ruling that is silently ignored is a decision that looks
        applied and is not."""
        import tempfile

        cases = [
            {"decision": "separate", "flow_object_id": "fo-1",
             "context_iri": "ctx-1", "unit": "kg",
             "survivor_elementary_flow_id": "rich",
             "merged_elementary_flow_ids": ["poor"]},
            {"decision": "merge", "flow_object_id": "fo-1",
             "context_iri": "ctx-1", "unit": "kg",
             "survivor_elementary_flow_id": "",
             "merged_elementary_flow_ids": ["poor"]},
            {"decision": "merge", "flow_object_id": "fo-1",
             "context_iri": "ctx-1", "unit": "kg",
             "survivor_elementary_flow_id": "rich",
             "merged_elementary_flow_ids": ["rich"]},
            {"decision": "merge", "flow_object_id": "", "context_iri": "ctx-1",
             "unit": "kg", "survivor_elementary_flow_id": "rich",
             "merged_elementary_flow_ids": ["poor"]},
        ]
        for row in cases:
            with self.subTest(row=row), tempfile.TemporaryDirectory() as tmp:
                path = self._write(tmp, [row])
                with self.assertRaises(CollisionRulingError):
                    load_collision_rulings(path)

    def test_a_format_this_does_not_read_raises(self):
        """`DECISIONS_SCHEMA_VERSION` is checked here, not merely declared.

        The file is hand-edited, so a bump is something a person does and then
        runs a build against; reading the rows of a format this loader does not
        understand would apply half a decision."""
        import tempfile

        row = {
            "flow_object_id": "fo-1", "context_iri": "ctx-1", "unit": "kg",
            "decision": "merge", "survivor_elementary_flow_id": "rich",
            "merged_elementary_flow_ids": ["poor"],
        }
        for version in (DECISIONS_SCHEMA_VERSION + 1, None):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "rulings.json"
                payload = {"decisions": [row]}
                if version is not None:
                    payload["schema_version"] = version
                path.write_text(json.dumps(payload))
                with self.assertRaises(CollisionRulingError):
                    load_collision_rulings(path)

    def test_two_rulings_may_not_answer_one_collision(self):
        import tempfile

        row = {
            "flow_object_id": "fo-1", "context_iri": "ctx-1", "unit": "kg",
            "decision": "merge", "survivor_elementary_flow_id": "rich",
            "merged_elementary_flow_ids": ["poor"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, [row, dict(row)])
            with self.assertRaises(CollisionRulingError):
                load_collision_rulings(path)


class TheShippedRulingsTestCase(unittest.TestCase):
    """The file itself, as data: 28 collisions over the eight substances #44
    triaged, each one EF 3.1 publishing a substance twice in one context, the
    five carbon tetrachloride rulings (#105), the four renewable energy
    resources EF publishes twice under two names (#73), and ten more from #106
    -- hexafluoroethane and 1,1,1-trichloroethane in four air compartments each,
    and beryllium and thallium in one.  What the energy rulings do is checked in
    `test_ef31_renewable_energy_duplicates.py`, against the merge groups they
    depend on; here they are four more rows that have to satisfy what every
    ruling satisfies.

    Eight more come from #185: two hydrofluoroethers EF publishes twice in each
    of four air compartments, once under the chemical name and once under the
    industry designation, with the same registry number on both.  Those eight
    are the first rulings written because a source row could not be placed --
    Stepwise 2006's two ether rows were tied between the copies and published
    nowhere -- rather than because a duplicate was noticed."""

    def setUp(self):
        self.index = load_collision_rulings()

    def test_every_shipped_ruling_loads(self):
        self.assertEqual(len(self.index), 56)

    def test_no_ruling_names_the_compartment_ef_calls_high_stacks(self):
        """EF 3.1's `Emissions to non-urban air or from high stacks` maps to
        rural medium stack under 150 metres, and seven rulings had been keyed on
        the high-stack IRI instead -- so each named a collision that does not
        exist and applied to nothing, silently, for four months (#106).  No air
        flow this project publishes is in `envi-air-hist15me`, so a ruling that
        names it is the same slip again."""
        for key, ruling in self.index.items():
            with self.subTest(collision=key):
                self.assertFalse(ruling.context_iri.endswith("/envi-air-hist15me"))

    def test_every_ruling_states_its_evidence(self):
        """A ruling with no comment is a curator's decision nobody can check."""
        for key, ruling in self.index.items():
            with self.subTest(collision=key):
                self.assertGreater(len(ruling.comment), 120)

    def test_every_ruling_names_the_substance_it_was_written_about(self):
        for key, ruling in self.index.items():
            with self.subTest(collision=key):
                self.assertEqual(len(ruling.names), 2)

    def test_no_flow_is_ruled_on_twice(self):
        """One flow deprecated onto two survivors is a chain, and a curated
        collapse should not need a consumer to walk one."""
        seen: set[str] = set()
        for ruling in self.index.values():
            for uuid in ruling.members:
                self.assertNotIn(uuid, seen)
                seen.add(uuid)

    def test_the_file_the_pipeline_reads_is_the_file_in_the_package(self):
        self.assertTrue(DECISIONS_FILEPATH.exists())
        self.assertEqual(DECISIONS_FILEPATH.suffix, ".json")


class TheTwoEtherRulingsTestCase(unittest.TestCase):
    """#185's eight: two hydrofluoroethers EF publishes twice in four air
    compartments each, under a chemical name and an industry designation with
    the same registry number on both.

    They are held here rather than left to `TheShippedRulingsTestCase`'s
    file-wide checks because the two pairs are decided by *different* reasons,
    and a copy-paste between them would pass every file-wide check.  The first
    pair is decided by the factor -- 616.0 against nothing.  The second cannot
    be: both rows hold 60.7, so the survivor is chosen by what it carries, which
    is the carbon tetrachloride case (#105).
    """

    IRI = "https://vocab.brightway.one/flow-contexts/"
    CONTEXTS = (
        "envi-air-grle-ur10pesq",
        "envi-air-lote",
        "envi-air-mest15me-ru10pesq",
        "envi-air-unkn",
    )
    #: flow object -> (the pair's two names, {context slug: (survivor, merged)})
    PAIRS = {
        "fo-48ed32f86342331a": (
            ["HFE-143a", "Methyl trifluoromethyl ether"],
            {
                "envi-air-grle-ur10pesq": (
                    "9308d9b4-e251-11e6-bf01-fe55135034f3",
                    "341eab87-065e-40a8-87f4-87d78776999b",
                ),
                "envi-air-lote": (
                    "9308d5e0-e251-11e6-bf01-fe55135034f3",
                    "6ad38d57-385e-4cd7-8c2f-fad75b9a185f",
                ),
                "envi-air-mest15me-ru10pesq": (
                    "9308d8f6-e251-11e6-bf01-fe55135034f3",
                    "bf80615e-1c05-4274-aac2-78f4c0fcd390",
                ),
                "envi-air-unkn": (
                    "9308ce4c-e251-11e6-bf01-fe55135034f3",
                    "5a24f510-a2be-4ff7-b0f2-d90884572b90",
                ),
            },
        ),
        "fo-8e701ffd05fb4bc1": (
            ["HFE-569sf2", "n-HFE-7200"],
            {
                "envi-air-grle-ur10pesq": (
                    "1b258cbc-798d-4d86-81c1-3cb852a54e8f",
                    "a19b9bce-e251-11e6-bf01-fe55135034f3",
                ),
                "envi-air-lote": (
                    "f9c7caa5-1b99-4ce5-846c-9ca86fc074c2",
                    "a19b95ca-e251-11e6-bf01-fe55135034f3",
                ),
                "envi-air-mest15me-ru10pesq": (
                    "ed1c4bbd-43e8-432d-8752-1a211ae0e573",
                    "a19b98f4-e251-11e6-bf01-fe55135034f3",
                ),
                "envi-air-unkn": (
                    "b0681715-c852-4456-ab78-c88e68502c7a",
                    "a19b92e6-e251-11e6-bf01-fe55135034f3",
                ),
            },
        ),
    }

    def setUp(self):
        self.index = load_collision_rulings()

    def test_each_pair_is_ruled_on_in_all_four_air_compartments(self):
        """A ruling settles one context.  Four compartments hold both copies,
        and a pair settled in three of them leaves a row unplaceable in the
        fourth."""
        for obj, (_, rows) in self.PAIRS.items():
            self.assertEqual(sorted(rows), sorted(self.CONTEXTS))
            for slug in self.CONTEXTS:
                with self.subTest(obj=obj, context=slug):
                    self.assertIn((obj, self.IRI + slug, "kg"), self.index)

    def test_each_ruling_names_the_survivor_that_was_decided(self):
        for obj, (names, rows) in self.PAIRS.items():
            for slug, (survivor, merged) in rows.items():
                with self.subTest(obj=obj, context=slug):
                    ruling = self.index[(obj, self.IRI + slug, "kg")]
                    self.assertEqual(ruling.survivor, survivor)
                    self.assertEqual(list(ruling.merged), [merged])
                    self.assertEqual(list(ruling.names), names)

    def test_the_two_pairs_are_decided_by_different_reasons(self):
        """The check a copy-paste would fail.  One pair is settled by the
        factor and the other cannot be, so neither comment may be the other's:
        the ethers' rulings say `616.0` and `60.7` respectively, and only the
        tied pair cites #105."""
        first = self.index[("fo-48ed32f86342331a", self.IRI + "envi-air-unkn", "kg")]
        second = self.index[("fo-8e701ffd05fb4bc1", self.IRI + "envi-air-unkn", "kg")]
        self.assertIn("616.0", first.comment)
        self.assertNotIn("#105", first.comment)
        self.assertIn("60.7", second.comment)
        self.assertIn("#105", second.comment)

    def test_every_ruling_names_the_issue_the_rows_come_from(self):
        for obj, (_, rows) in self.PAIRS.items():
            for slug in rows:
                with self.subTest(obj=obj, context=slug):
                    self.assertIn("#185", self.index[(obj, self.IRI + slug, "kg")].comment)


class WaterVapourPairTestCase(unittest.TestCase):
    """EF's double m3 water-vapour flow in unspecified air is one flow (#191).

    EF 3.1 ships `Water` and `Water (evapotranspiration)` live in one
    compartment, one unit, on one substance, told apart only by a general
    comment EF itself attributes to `some water people`.  Everything that maps
    anywhere maps onto the bare row -- ecoinvent's correspondence tables and
    AGRIBALYSE's Water/m3 override (#353) -- so it survives and the
    evapotranspiration copy is deprecated onto it.
    """

    KEY = (
        "fo-757b6ee59c695209",
        "https://vocab.brightway.one/flow-contexts/envi-air-unkn",
        "m3",
    )
    SURVIVOR = "0342f5e5-b53e-4cec-9e67-fb197f24fff0"
    MERGED = "4b772bba-b5c1-4098-9c1d-3d9d8c74c7fa"

    def test_the_ruling_names_the_pair_and_the_row_every_list_reaches(self):
        ruling = load_collision_rulings().get(self.KEY)
        assert ruling is not None, "the #191 ruling is missing"
        self.assertEqual(ruling.survivor, self.SURVIVOR)
        self.assertEqual(ruling.merged, (self.MERGED,))
        self.assertEqual(
            set(ruling.names), {"Water", "Water (evapotranspiration)"}
        )

    def test_the_survivor_is_the_flow_agribalyses_override_names(self):
        """The guarantee `test_collision_rulings_ecoinvent.py` makes for
        ecoinvent's tables, made for the one override written against this
        pair: collapsing the flow a curated target points at would strand the
        row #353 placed."""
        overrides_path = (
            Path(__file__).resolve().parent.parent
            / "src" / "brightway_flows" / "data"
            / "agribalyse-3.2-match-overrides.json"
        )
        targets = {
            row["target_uuid"]
            for row in json.loads(overrides_path.read_text())["overrides"]
            if "target_uuid" in row
        }
        self.assertIn(self.SURVIVOR, targets)
        self.assertNotIn(self.MERGED, targets)

    def test_ef_ships_both_rows_the_ruling_is_written_about(self):
        """The ruling against the vendor's own file: both uuids, one context,
        one unit, or the ruling has drifted from the data it rules on."""
        from brightway_flows.sources import base_source_list

        flows_path = base_source_list().flows_path
        if not flows_path.exists():
            raise unittest.SkipTest("EF 3.1 is not extracted here")
        rows = {
            row.get("uuid") or row.get("identifier"): row
            for row in json.loads(flows_path.read_text())
            if (row.get("uuid") or row.get("identifier"))
            in (self.SURVIVOR, self.MERGED)
        }
        self.assertEqual(set(rows), {self.SURVIVOR, self.MERGED})
        for uuid, row in rows.items():
            with self.subTest(uuid=uuid):
                self.assertEqual(row.get("unit"), "m3")
                self.assertEqual(
                    row.get("context"),
                    ["Emissions", "Emissions to air", "Emissions to air, unspecified"],
                )


if __name__ == "__main__":
    unittest.main()
