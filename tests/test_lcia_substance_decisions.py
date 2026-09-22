"""A curator says which flow a publisher's row is about, or that none is.

The table #347 asked for, and what it must not become: a way for a curated row
to land on whatever a uuid happens to hold later, and a way for a decline to look
like an oversight.

Two halves. The first is the file's own rules -- what a row must say to be read
at all -- checked against fixtures. The second is what the matching pass does
with one, checked against a small database, in the same shape as
`tests/test_substance_matching.py`. The numbers from the real package are in
`expectations/`; what is here is the mechanism.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import orjson

from brightway_flows.context_mapping import (
    context_iri_by_source_context,
    normalize_context_key,
)
from brightway_flows.domain.lcia.records import StatedFactor, stated_category
from brightway_flows.domain.lcia.crosswalk import ef_method
from brightway_flows.lcia.matching import match
from brightway_flows.lcia.report import FindingKind
from brightway_flows.lcia.sources import FactorSource
from brightway_flows.lcia.substance_decisions import (
    BY_DECISION,
    DECLINED,
    REACHES,
    SUBSTANCE_DECISIONS_FILEPATH,
    SUBSTANCE_DECISIONS_SCHEMA_VERSION,
    SubstanceDecision,
    SubstanceDecisionError,
    decisions_for,
    load_substance_decisions,
)
from brightway_flows.lcia.substance_matching import (
    BY_REGISTRY_NUMBER,
    substance_index,
    substance_targets,
)

#: EF 3.1's implementations, read from its method file rather than from an enum:
#: an implementation belongs to a method, and which four these are is what
#: `data/lcia-impact-categories.json` says.
_METHOD = ef_method()
JRC_IMPL = _METHOD.reference
ECOINVENT_IMPL = _METHOD.implementation("ecoinvent-centre")
GREENDELTA_IMPL = _METHOD.implementation("greendelta")
CONSENSUS_IMPL = _METHOD.consensus
IMPLEMENTATION_NAMES = {row.name for row in _METHOD.implementations}

CAS = "http://semanticscience.org/resource/CHEMINF_000446"
THEIR_WATER = "Elementary flows/Emission to water/unspecified"


def _row(**overrides):
    row = {
        "implemented_by": "GreenDelta",
        "source_flow_uuid": "gd-1",
        "source_flow_name": "Copper ion",
        "source_context": ["Elementary flows", "Emission to water", "unspecified"],
        "decision": REACHES,
        "elementary_flow_uuid": "bwf-1",
        "substance": "Copper, Ion",
        "context": "Environmental → Water → Unknown",
        "unit": "kg",
        "comment": "7 of their 12 flows of this name resolve to `Copper, Ion`.",
    }
    row.update(overrides)
    return {key: value for key, value in row.items() if value is not None}


def _file(tmp: Path, *rows, version=SUBSTANCE_DECISIONS_SCHEMA_VERSION):
    path = tmp / "decisions.json"
    path.write_bytes(
        orjson.dumps(
            {
                "schema_version": version,
                "description": "a fixture",
                "decisions": list(rows),
            }
        )
    )
    return path


class TheFileIsReadOrItRaisesTestCase(unittest.TestCase):
    """A malformed curated decision is a decision that looks applied and is not,
    so every one of these raises rather than skipping the row."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_a_well_formed_row_is_read(self):
        decisions = load_substance_decisions(_file(self.dir, _row()))
        decision = decisions[("GreenDelta", "gd-1")]
        self.assertTrue(decision.reaches)
        self.assertEqual(decision.elementary_flow_uuid, "bwf-1")
        self.assertEqual(
            decision.source_context,
            ("Elementary flows", "Emission to water", "unspecified"),
        )

    def test_a_row_with_no_comment_is_refused(self):
        with self.assertRaises(SubstanceDecisionError) as caught:
            load_substance_decisions(_file(self.dir, _row(comment="")))
        self.assertIn("has no comment", str(caught.exception))

    def test_a_row_that_reaches_nothing_and_names_no_flow_is_refused(self):
        with self.assertRaises(SubstanceDecisionError):
            load_substance_decisions(
                _file(self.dir, _row(elementary_flow_uuid=None))
            )

    def test_a_declined_row_may_not_name_a_flow_to_reach(self):
        with self.assertRaises(SubstanceDecisionError) as caught:
            load_substance_decisions(_file(self.dir, _row(decision=DECLINED)))
        self.assertIn("declined and names a flow", str(caught.exception))

    def test_a_declined_row_needs_only_its_reasoning(self):
        decisions = load_substance_decisions(
            _file(
                self.dir,
                _row(
                    decision=DECLINED,
                    elementary_flow_uuid=None,
                    substance=None,
                    context=None,
                    unit=None,
                ),
            )
        )
        self.assertFalse(decisions[("GreenDelta", "gd-1")].reaches)

    def test_a_row_that_reaches_records_what_its_target_published(self):
        """The guard, and it is not optional: see `covers`."""
        for field in ("substance", "context", "unit"):
            with self.subTest(field):
                with self.assertRaises(SubstanceDecisionError) as caught:
                    load_substance_decisions(_file(self.dir, _row(**{field: ""})))
                self.assertIn(field, str(caught.exception))

    def test_a_row_with_no_compartment_is_refused(self):
        """A decision about a substance alone could put a freshwater number on
        an emission to air, which is the rule the matching pass holds to."""
        with self.assertRaises(SubstanceDecisionError) as caught:
            load_substance_decisions(_file(self.dir, _row(source_context=None)))
        self.assertIn("source_context", str(caught.exception))

    def test_two_rows_about_one_flow_are_refused(self):
        with self.assertRaises(SubstanceDecisionError) as caught:
            load_substance_decisions(_file(self.dir, _row(), _row()))
        self.assertIn("one flow of theirs has one decision", str(caught.exception))

    def test_another_schema_version_is_refused(self):
        with self.assertRaises(SubstanceDecisionError):
            load_substance_decisions(_file(self.dir, _row(), version=99))

    def test_a_missing_file_is_no_decisions_rather_than_a_crash(self):
        self.assertEqual(load_substance_decisions(self.dir / "absent.json"), {})


class TheGuardHoldsTestCase(unittest.TestCase):
    def _decision(self, **overrides):
        return SubstanceDecision(
            implemented_by="GreenDelta",
            source_flow_uuid="gd-1",
            source_flow_name="Copper ion",
            source_context=("Elementary flows", "Emission to water", "unspecified"),
            decision=REACHES,
            comment="because",
            elementary_flow_uuid="bwf-1",
            substance=overrides.get("substance", "Copper, Ion"),
            context=overrides.get("context", "Environmental → Water → Unknown"),
            unit=overrides.get("unit", "kg"),
        )

    def test_it_covers_the_flow_it_was_written_about(self):
        self.assertTrue(
            self._decision().covers(
                substance="Copper, Ion",
                context="Environmental → Water → Unknown",
                unit="kg",
            )
        )

    def test_a_uuid_that_now_publishes_another_substance_is_not_covered(self):
        """#108's lesson: a uuid ecoinvent 3.8 calls `Vanadium` is `Vanadium V`
        in 3.12, and a decision that silently followed it would move a factor
        onto a different chemical."""
        self.assertFalse(
            self._decision().covers(
                substance="Copper", context="Environmental → Water → Unknown", unit="kg"
            )
        )

    def test_a_flow_that_moved_compartment_is_not_covered(self):
        self.assertFalse(
            self._decision().covers(
                substance="Copper, Ion",
                context="Environmental → Water → Ocean",
                unit="kg",
            )
        )

    def test_a_flow_published_in_another_unit_is_not_covered(self):
        self.assertFalse(
            self._decision().covers(
                substance="Copper, Ion",
                context="Environmental → Water → Unknown",
                unit="MJ",
            )
        )

    def test_a_declined_row_has_no_target_and_so_nothing_to_guard(self):
        declined = SubstanceDecision(
            implemented_by="GreenDelta",
            source_flow_uuid="gd-1",
            source_flow_name="Cadmium II",
            source_context=("Elementary flows", "Emission to water", "lake"),
            decision=DECLINED,
            comment="Water → Lake publishes only BAFU's element-named flows.",
        )
        self.assertTrue(declined.covers(substance="", context="", unit=""))


class TheMatchingPassUsesThemTestCase(unittest.TestCase):
    """What a decision does to the row it is about, over a small database."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "build.sqlite3"
        connection = sqlite3.connect(self.db)
        connection.execute(
            "CREATE TABLE elementary_flows (uuid TEXT, flow_object_id TEXT, "
            "pref_label_value TEXT, context_iri TEXT, unit TEXT, "
            "context_display TEXT, is_deprecated INTEGER)"
        )
        connection.execute(
            "CREATE TABLE flow_objects (flow_object_id TEXT, "
            "classifications_json TEXT)"
        )
        self.connection = connection
        self.water = context_iri_by_source_context("GreenDelta")[
            normalize_context_key(["Emission to water", "unspecified"])
        ]
        self.display = "Environmental → Water → Unknown"

    def _flow(self, uuid, label, *, cas=None, unit="kg", display=None):
        object_id = f"fo-{uuid}"
        self.connection.execute(
            "INSERT INTO elementary_flows VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uuid, object_id, label, self.water, unit, display or self.display, 0),
        )
        self.connection.execute(
            "INSERT INTO flow_objects VALUES (?, ?)",
            (
                object_id,
                orjson.dumps({CAS: {"@value": [cas]}}).decode() if cas else "{}",
            ),
        )
        self.connection.commit()

    def _source(self, described, factors=1):
        return FactorSource(
            implementation=GREENDELTA_IMPL,
            by_flow={
                "gd-1": [
                    StatedFactor(
                        category=stated_category(uuid="c-1", name="Acidification"),
                        flow_uuid="gd-1",
                        amount=1.5,
                    )
                    for _ in range(factors)
                ]
            },
            flows_are_consensus=False,
            read_from="a file",
            descriptions={"gd-1": described},
        )

    def _run(self, described, decisions, factors=1):
        return substance_targets(
            self._source(described, factors),
            index=substance_index(self.db),
            outstanding={"gd-1"},
            decisions=decisions,
        )

    def test_a_decision_reaches_a_flow_no_name_of_theirs_would(self):
        self._flow("bwf-1", "Copper, Ion")
        targets, basis_of, findings, declined = self._run(
            {"name": "Copper ion", "context": THEIR_WATER, "unit": "kg"},
            {"gd-1": SubstanceDecision(**_decision_fields())},
        )
        self.assertEqual(targets["gd-1"].elementary_flow_uuid, "bwf-1")
        self.assertEqual(basis_of["gd-1"], BY_DECISION)
        self.assertEqual((findings, declined), ([], {}))

    def test_a_decision_outranks_a_registry_number(self):
        """The order is the claim. Nothing shipped exercises it -- none of the 25
        rows states a number -- and a later row that did would otherwise be
        overruled by the weaker statement without anybody choosing that."""
        self._flow("bwf-1", "Copper, Ion")
        self._flow("bwf-2", "Copper", cas="7440-50-8")
        targets, basis_of, _findings, _declined = self._run(
            {
                "name": "Copper ion",
                "context": THEIR_WATER,
                "unit": "kg",
                "cas": "7440-50-8",
            },
            {"gd-1": SubstanceDecision(**_decision_fields())},
        )
        self.assertEqual(targets["gd-1"].elementary_flow_uuid, "bwf-1")
        self.assertEqual(basis_of["gd-1"], BY_DECISION)

    def test_without_the_decision_that_same_row_goes_by_its_number(self):
        """The other half of the claim above: the number route still works, so
        the test before it is about precedence and not about a broken rule."""
        self._flow("bwf-1", "Copper, Ion")
        self._flow("bwf-2", "Copper", cas="7440-50-8")
        targets, basis_of, _findings, _declined = self._run(
            {
                "name": "Copper ion",
                "context": THEIR_WATER,
                "unit": "kg",
                "cas": "7440-50-8",
            },
            {},
        )
        self.assertEqual(targets["gd-1"].elementary_flow_uuid, "bwf-2")
        self.assertEqual(basis_of["gd-1"], BY_REGISTRY_NUMBER)

    def test_a_declined_row_reaches_nothing_and_carries_its_reasoning(self):
        self._flow("bwf-1", "Cadmium")
        targets, basis_of, findings, declined = self._run(
            {"name": "Cadmium II", "context": THEIR_WATER, "unit": "kg"},
            {
                "gd-1": SubstanceDecision(
                    implemented_by="GreenDelta",
                    source_flow_uuid="gd-1",
                    source_flow_name="Cadmium II",
                    source_context=(
                        "Elementary flows",
                        "Emission to water",
                        "lake",
                    ),
                    decision=DECLINED,
                    comment="Water → Lake publishes only the element.",
                )
            },
        )
        self.assertEqual((targets, basis_of, findings), ({}, {}, []))
        self.assertEqual(declined["gd-1"], "Water → Lake publishes only the element.")

    def test_the_decline_rides_on_the_finding_the_row_already_gets(self):
        """One row reached nothing, which is one thing that happened; a second
        finding would say it was two."""
        source = self._source(
            {"name": "Cadmium II", "context": THEIR_WATER, "unit": "kg"}, factors=6
        )
        _matched, findings = match(
            source, index={}, declined={"gd-1": "Water → Lake publishes the element."}
        )
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.kind, FindingKind.FLOW_NOT_REACHED)
        self.assertIn("decided rather than missed", finding.detail)
        self.assertEqual(
            finding.context["declined_because"], "Water → Lake publishes the element."
        )

    def test_a_row_with_no_decision_is_reported_the_way_it_always_was(self):
        source = self._source(
            {"name": "Zirconium", "context": THEIR_WATER, "unit": "kg"}, factors=2
        )
        _matched, findings = match(source, index={})
        self.assertEqual(len(findings), 1)
        self.assertNotIn("declined_because", findings[0].context)
        self.assertNotIn("decided rather than missed", findings[0].detail)

    def test_a_decision_whose_target_now_publishes_another_substance_raises(self):
        """It does not fall back to the name, and it does not skip. A curated
        decision that quietly lands somewhere else is worse than one that stops
        the build and asks."""
        self._flow("bwf-1", "Copper")
        with self.assertRaises(SubstanceDecisionError) as caught:
            self._run(
                {"name": "Copper ion", "context": THEIR_WATER, "unit": "kg"},
                {"gd-1": SubstanceDecision(**_decision_fields())},
            )
        self.assertIn("now publishes 'Copper'", str(caught.exception))

    def test_a_decision_reaching_a_flow_this_build_does_not_publish_raises(self):
        with self.assertRaises(SubstanceDecisionError) as caught:
            self._run(
                {"name": "Copper ion", "context": THEIR_WATER, "unit": "kg"},
                {"gd-1": SubstanceDecision(**_decision_fields())},
            )
        self.assertIn("does not publish", str(caught.exception))

    def test_the_units_travel_with_a_decided_match(self):
        """Same as the other two routes: a decision says which flow, never that
        a number stated per one unit may be published per another."""
        self._flow("bwf-1", "Copper, Ion", unit="MJ")
        targets, _basis, _findings, _declined = self._run(
            {"name": "Copper ion", "context": THEIR_WATER, "unit": "kg"},
            {
                "gd-1": SubstanceDecision(
                    **{**_decision_fields(), "unit": "MJ"}
                )
            },
        )
        crossing = targets["gd-1"].crossing
        self.assertEqual((crossing.source_unit, crossing.target_unit), ("kg", "MJ"))
        self.assertFalse(crossing.convertible)


    def test_a_unit_spelled_two_ways_is_not_a_crossing(self):
        """openLCA writes the area-time unit `m2*a` and this list publishes
        `m2.a`. One unit, two notations, and comparing them as text would drop
        every land occupation factor #166 reaches."""
        self._flow("bwf-1", "Copper, Ion", unit="m2.a")
        targets, _basis, _findings, _declined = self._run(
            {"name": "Copper ion", "context": THEIR_WATER, "unit": "m2*a"},
            {"gd-1": SubstanceDecision(**{**_decision_fields(), "unit": "m2.a"})},
        )
        crossing = targets["gd-1"].crossing
        self.assertEqual(crossing.source_unit, "m2.a")
        self.assertFalse(crossing.crosses)


def _decision_fields():
    return {
        "implemented_by": "GreenDelta",
        "source_flow_uuid": "gd-1",
        "source_flow_name": "Copper ion",
        "source_context": ("Elementary flows", "Emission to water", "unspecified"),
        "decision": REACHES,
        "comment": "their own package resolves this name to `Copper, Ion`",
        "elementary_flow_uuid": "bwf-1",
        "substance": "Copper, Ion",
        "context": "Environmental → Water → Unknown",
        "unit": "kg",
    }


#: The three compartments of theirs that name a place where this list names an
#: action or a kind of water, which is what #166's rows are about
#: (`lcia.substance_matching`).  ``Resource / in ground`` is deliberately not one:
#: it maps, and the single #347 row sitting in it is an ion's name on a resource
#: flow rather than a land class.
LAND_AND_WATER_COMPARTMENTS = {
    ("Resource", "land"),
    ("Resource", "in water"),
    ("Resource", "unspecified"),
}


#: The three rows that are none of the above: BAFU's own name for PM10, and two
#: metals whose number their own `in ground` copy already publishes.  Named
#: rather than derived, because what they have in common is only that a curator
#: answered them one at a time.
OTHER_ROWS = {
    "Particulates, < 10 um (stationary)",
    "Platinum",
    "Uranium",
}


def _is_other(decision):
    return decision.source_flow_name in OTHER_ROWS


def _is_land_or_water(decision):
    return not _is_other(decision) and (
        tuple(decision.source_context[1:]) in LAND_AND_WATER_COMPARTMENTS
    )


class TheShippedFileHoldsWhatIssue789SaysTestCase(unittest.TestCase):
    """The file is the decision, so what it holds is checked rather than assumed."""

    @classmethod
    def setUpClass(cls):
        cls.decisions = load_substance_decisions()
        cls.ionic = [
            d
            for d in cls.decisions.values()
            if not _is_land_or_water(d) and not _is_other(d)
        ]

    def test_it_is_the_twenty_five_rows_the_issue_counted(self):
        self.assertEqual(len(self.ionic), 25)

    def test_eighteen_reach_a_flow_and_seven_are_declined(self):
        reaching = [d for d in self.ionic if d.reaches]
        self.assertEqual(len(reaching), 18)
        self.assertEqual(len(self.ionic) - len(reaching), 7)

    def test_every_row_is_about_greendelta(self):
        self.assertEqual(
            {d.implemented_by for d in self.decisions.values()}, {"GreenDelta"}
        )
        self.assertEqual(len(decisions_for("GreenDelta")), len(self.decisions))

    def test_the_ionic_rows_are_emissions_and_one_resource(self):
        """What tells #347's rows from #166's: an ion's name in a compartment
        that maps, against a land class or a kind of water in one that cannot."""
        self.assertEqual(
            sorted({tuple(d.source_context[1:]) for d in self.ionic}),
            [
                ("Emission to soil", "agricultural"),
                ("Emission to soil", "industrial"),
                ("Emission to water", "fresh water"),
                ("Emission to water", "ground water"),
                ("Emission to water", "lake"),
                ("Emission to water", "unspecified"),
                ("Resource", "in ground"),
            ],
        )

    def test_every_declined_row_is_a_metal_emitted_to_a_lake(self):
        """The decline is one decision about one compartment, not a scatter of
        unrelated refusals."""
        declined = [d for d in self.ionic if not d.reaches]
        self.assertEqual(
            {d.source_context[-1] for d in declined},
            {"lake"},
        )
        self.assertEqual(
            sorted(d.source_flow_name for d in declined),
            [
                "Arsenic ion",
                "Cadmium II",
                "Copper ion",
                "Lead II",
                "Mercury II",
                "Nickel II",
                "Zinc II",
            ],
        )

    def test_no_row_reaches_into_the_lake_compartment(self):
        """The whole argument for declining those seven is that this list
        publishes no ionic flow there, so a row that reached one would be the
        decision undoing itself."""
        self.assertNotIn(
            "Lake",
            {d.context for d in self.decisions.values() if d.reaches},
        )

    def test_every_row_carries_its_reasoning(self):
        for decision in self.ionic:
            with self.subTest(decision.source_flow_name):
                self.assertGreater(len(decision.comment), 80)

    def test_the_file_is_where_the_register_says_it_is(self):
        self.assertTrue(SUBSTANCE_DECISIONS_FILEPATH.exists())



class TheLandAndWaterRowsHoldWhatIssue785SaysTestCase(unittest.TestCase):
    """56 rows in three compartments that map to nothing, and what each may say.

    The numbers those rows publish are graded in `expectations/`; these are the
    claims the file itself has to keep true, and each one is a way the table
    could go wrong quietly.
    """

    @classmethod
    def setUpClass(cls):
        cls.rows = [
            d for d in load_substance_decisions().values() if _is_land_or_water(d)
        ]

    def test_it_is_the_flows_the_two_issues_counted(self):
        """56 for #166, the six `Water, process` rows #170 added -- three stated
        per cubic metre, and three per kilogram against a flow published per
        cubic metre, which publish because the build already recorded the
        conversion -- and the one `GLO` row #166's second change added for the
        set of country names that has no site-generic member."""
        self.assertEqual(len(self.rows), 63)
        self.assertEqual(
            len([d for d in self.rows if d.source_flow_name.startswith("Water, process")]),
            6,
        )

    def test_every_one_of_them_reaches_a_flow(self):
        """Nothing is declined here. A land class this list does not publish
        would be a reason to mint one, which #166 says it is not."""
        self.assertEqual([d for d in self.rows if not d.reaches], [])

    def test_a_name_that_states_an_action_reaches_that_action_s_context(self):
        """The whole of what their name adds to their compartment: `Occupation`
        and `Transformation` are contexts of ours, so a row that read one as the
        other would put an occupation's number on a transformation's flow."""
        for decision in self.rows:
            action = decision.source_flow_name.split(",")[0].strip()
            if action not in {"Occupation", "Transformation"}:
                continue
            with self.subTest(decision.source_flow_name):
                self.assertEqual(decision.context, f"Land Use → {action}")

    def test_a_transformation_keeps_the_direction_its_name_states(self):
        """`from forest` and `to forest` are two flows and a balanced pair of
        factors, which is the defect the land taxonomy was restructured to make
        impossible (`land-taxonomy-overview.md`)."""
        for decision in self.rows:
            parts = [part.strip() for part in decision.source_flow_name.split(",")]
            if parts[0] != "Transformation":
                continue
            with self.subTest(decision.source_flow_name):
                self.assertTrue(
                    decision.substance.lower().startswith(parts[1].split()[0]),
                    f"{decision.source_flow_name} reaches {decision.substance}",
                )

    def test_every_water_row_reaches_a_water_resource(self):
        """Five for #166, six `Water, process` rows for #170 and the `GLO`
        member of `Water, unspecified natural origin` that stands for its 77
        country rows (#166 again), and every one of them a withdrawal: these
        compartments are where their file states what was taken, so a row
        reaching an emission context would have crossed the boundary the
        compartment does say something about."""
        water = [d for d in self.rows if d.source_flow_name.startswith("Water")]
        self.assertEqual(len(water), 12)
        for decision in water:
            with self.subTest(decision.source_flow_name):
                self.assertTrue(decision.context.startswith("Resource → Water →"))

    def test_the_units_are_the_three_these_flows_are_measured_in(self):
        """An occupation is an area held for a time, a transformation is an area
        and a withdrawal is a volume. A row reaching a flow published in some
        other unit would state a number nobody can use."""
        self.assertEqual(
            {d.unit for d in self.rows}, {"m2", "m2.a", "m3"}
        )

    def test_every_row_says_what_it_rests_on(self):
        """Each comment names the flow of BAFU's that settles the class, and the
        checks that agree with it. Longer than #347's floor because there are
        three sources of evidence to report rather than one count."""
        for decision in self.rows:
            with self.subTest(decision.source_flow_name):
                self.assertGreater(len(decision.comment), 200)
                self.assertIn("BAFU", decision.comment)


class TheRowsThatAreNeitherTestCase(unittest.TestCase):
    """Three rows answered one at a time, and two of them answered with a no."""

    @classmethod
    def setUpClass(cls):
        cls.rows = [d for d in load_substance_decisions().values() if _is_other(d)]

    def test_it_is_the_three(self):
        self.assertEqual(
            sorted(d.source_flow_name for d in self.rows),
            ["Particulates, < 10 um (stationary)", "Platinum", "Uranium"],
        )

    def test_the_particulate_reaches_the_size_class_bafu_gave_it(self):
        """`(stationary)` says where the dust came from and this list files a
        particulate by its size, so nothing about the string reaches a flow.
        BAFU's own flow of that name is merged onto PM10 in the same
        compartment."""
        row = next(
            d
            for d in self.rows
            if d.source_flow_name == "Particulates, < 10 um (stationary)"
        )
        self.assertTrue(row.reaches)
        self.assertEqual(row.substance, "Particles (PM10)")
        self.assertEqual(row.context, "Environmental → Air → Unknown")
        self.assertEqual(row.unit, "kg")

    def test_the_two_metals_are_declined(self):
        """Both are already published on `Resource → Ground` from the copy of
        theirs that arrived with an identifier, and `Resource / unspecified`
        gives no reason to prefer this one. A decline is how that is recorded
        rather than left looking like an oversight."""
        declined = [d for d in self.rows if not d.reaches]
        self.assertEqual(
            sorted(d.source_flow_name for d in declined), ["Platinum", "Uranium"]
        )
        for row in declined:
            with self.subTest(row.source_flow_name):
                self.assertEqual(tuple(row.source_context[1:]), ("Resource", "unspecified"))
                self.assertEqual(row.elementary_flow_uuid, "")
                self.assertIn("Resource → Ground", row.comment)

if __name__ == "__main__":  # pragma: no cover
    unittest.main()
