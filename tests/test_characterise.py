"""`characterise`: the two transcriptions, onto the consensus flows.

What the pass has to get right is not arithmetic -- neither implementation's
numbers are touched -- but placement, and there are exactly three ways a factor
can fail to land:

* its flow was never merged onto a consensus flow, which is a question for the
  merge and not something to fix here;
* two source rows reach one consensus flow and state different numbers for one
  category and place, which the model cannot represent and which is evidence
  about our matching;
* two rows state the *same* number, or two numbers that are one number written
  twice, which is not a disagreement at all.

The rest is a join. These cover the three, the two routes a factor takes to a
flow, and the invariant the tables hold as a primary key.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import orjson

from brightway_flows.domain.lcia.crosswalk import ef_method, impact_categories
from brightway_flows.domain.common import Provenance
from brightway_flows.domain.vocabulary import CHEMINF_CAS_REGISTRY_NUMBER
from brightway_flows.domain.lcia.records import (
    StatedFactor,
    SupersededValue,
    stated_category,
)
from brightway_flows.lcia.categories import (
    impact_categories_for,
    impact_category_id,
    impact_category_iri,
)
from brightway_flows.lcia.conversion import UnitCrossing
from brightway_flows.lcia.matching import (
    MatchedFactor,
    MergeTarget,
    match,
    merge_targets,
    recorded_conversions,
)
from brightway_flows.lcia.pipeline import (
    _declined_numbers,
    _definition_for,
    characterise,
)
from brightway_flows.lcia.report import FindingKind
from brightway_flows.lcia.sources import FactorSource
from brightway_flows.lcia.store import (
    CharacterisationRun,
    write_characterisation,
)
from brightway_flows.sources import LciaMethodSpec, LciaSpec, SourceList

#: EF 3.1, and its three implementations by role.
METHOD = ef_method()
JRC = METHOD.reference
ECOINVENT = METHOD.implementation("ecoinvent-centre")
CONSENSUS = METHOD.consensus

#: A category on each side, so a test names what the files name.
BY_METHOD_UUID = METHOD.by_stated_identifier(JRC.slug)
BY_ECOINVENT_NAME = METHOD.by_stated_name(ECOINVENT.slug)
JRC_CATEGORY = next(iter(BY_METHOD_UUID))
ECOINVENT_CATEGORY = next(iter(BY_ECOINVENT_NAME))


def _jrc_factor(amount: float, *, geography: str | None = None) -> StatedFactor:
    definition = BY_METHOD_UUID[JRC_CATEGORY]
    return StatedFactor(
        category=stated_category(
            uuid=JRC_CATEGORY, name=definition.stated[JRC.slug].name
        ),
        flow_uuid="",
        amount=amount,
        geography=geography,
    )


def _ecoinvent_factor(amount: float, *, flow: str) -> StatedFactor:
    return StatedFactor(
        category=stated_category(uuid=None, name=ECOINVENT_CATEGORY),
        flow_uuid=flow,
        amount=amount,
    )


def _source(by_flow, *, implementation, consensus):
    return FactorSource(
        implementation=implementation,
        by_flow=by_flow,
        flows_are_consensus=consensus,
        read_from="a test",
    )


class TheJrcNeedsNoMatchingTestCase(unittest.TestCase):
    """Its factors are already on consensus flows: EF is the base list."""

    def test_every_factor_stays_where_it_is(self):
        source = _source(
            {"ef-1": [_jrc_factor(1.5)], "ef-2": [_jrc_factor(2.5)]},
            implementation=JRC,
            consensus=True,
        )
        matched, findings = match(source)
        self.assertEqual(findings, [])
        self.assertEqual(
            sorted((row.elementary_flow_uuid, row.factor.amount) for row in matched),
            [("ef-1", 1.5), ("ef-2", 2.5)],
        )
        self.assertTrue(all(row.source_flow_uuid is None for row in matched))

    def test_two_places_are_two_factors(self):
        """EF states 42,871 factors about a named country, and `Land use` gives
        one flow 213 of them.  Without the place they would read as a collision
        and one number would be published out of 213."""
        source = _source(
            {"ef-1": [_jrc_factor(-522.81, geography="ES-CA"),
                      _jrc_factor(-227.0, geography="YE")]},
            implementation=JRC,
            consensus=True,
        )
        matched, findings = match(source)
        self.assertEqual(findings, [])
        self.assertEqual(
            sorted(row.factor.geography for row in matched), ["ES-CA", "YE"]
        )


class TheEcoinventFactorsTakeTwoHopsTestCase(unittest.TestCase):
    @staticmethod
    def _target(uuid, *, source_unit="kg", target_unit="kg", multiplier=None):
        return MergeTarget(
            elementary_flow_uuid=uuid,
            crossing=UnitCrossing(source_unit, target_unit, multiplier),
        )

    def _match(self, by_flow, index):
        return match(
            _source(by_flow, implementation=ECOINVENT, consensus=False),
            index=index,
        )

    def test_a_row_reaches_the_flow_the_merge_put_it_on(self):
        matched, findings = self._match(
            {"ei-1": [_ecoinvent_factor(3.02, flow="ei-1")]},
            {"ei-1": self._target("cf-1")},
        )
        self.assertEqual(findings, [])
        self.assertEqual(matched[0].elementary_flow_uuid, "cf-1")
        self.assertEqual(matched[0].source_flow_uuid, "ei-1")

    def test_a_flow_the_merge_never_placed_is_reported(self):
        """Two of ecoinvent 3.12's 9,850 flows are in this state, and their
        factors are not this pass's to place."""
        matched, findings = self._match(
            {"ei-9": [_ecoinvent_factor(1.0, flow="ei-9")]}, {}
        )
        self.assertEqual(matched, [])
        self.assertEqual(findings[0].kind, FindingKind.FLOW_NOT_REACHED)
        self.assertEqual(findings[0].context["source_flow_uuid"], "ei-9")
        self.assertEqual(findings[0].context["factor_count"], 1)

    def test_two_rows_agreeing_publish_one_factor(self):
        """130 consensus flows are reached by more than one ecoinvent row, and
        most of them agree; agreement is not an event."""
        matched, findings = self._match(
            {
                "ei-1": [_ecoinvent_factor(3.02, flow="ei-1")],
                "ei-2": [_ecoinvent_factor(3.02, flow="ei-2")],
            },
            {"ei-1": self._target("cf-1"), "ei-2": self._target("cf-1")},
        )
        self.assertEqual(findings, [])
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].factor.amount, 3.02)

    def test_two_rows_one_number_written_twice_keep_the_precise_one(self):
        matched, findings = self._match(
            {
                "ei-1": [_ecoinvent_factor(0.000118, flow="ei-1")],
                "ei-2": [_ecoinvent_factor(0.00011755, flow="ei-2")],
            },
            {"ei-1": self._target("cf-1"), "ei-2": self._target("cf-1")},
        )
        self.assertEqual(findings, [])
        self.assertEqual(matched[0].factor.amount, 0.00011755)

    def test_two_rows_far_apart_publish_nothing_and_say_so(self):
        """`Glufosinate` and `Glufosinate ammonium`, 7,068x apart on one flow.
        There is no faithful answer, and inventing one would hide the evidence."""
        matched, findings = self._match(
            {
                "ei-1": [_ecoinvent_factor(70304.9, flow="ei-1")],
                "ei-2": [_ecoinvent_factor(9.9469, flow="ei-2")],
            },
            {"ei-1": self._target("cf-1"), "ei-2": self._target("cf-1")},
        )
        self.assertEqual(matched, [])
        self.assertEqual(findings[0].kind, FindingKind.FACTOR_COLLISION)
        self.assertEqual(findings[0].elementary_flow_uuid, "cf-1")
        self.assertEqual(
            sorted(row["amount"] for row in findings[0].context["rows"]),
            [9.9469, 70304.9],
        )


class TheUnitsHaveToAgreeTestCase(unittest.TestCase):
    """A factor is per unit of a flow, and eight ecoinvent flows cross one.

    ecoinvent states uranium's energy content as a mass and this list publishes it
    as an energy: 560,000 CTUe per kg is 1.0 per MJ, which is what the JRC states
    for the same flow -- the check that the conversion runs the right way round.
    """

    @staticmethod
    def _target(uuid, source_unit, target_unit, multiplier=None):
        return MergeTarget(
            elementary_flow_uuid=uuid,
            crossing=UnitCrossing(source_unit, target_unit, multiplier),
        )

    def _match(self, target, amount=560000.0):
        return match(
            _source(
                {"ei-1": [_ecoinvent_factor(amount, flow="ei-1")]},
                implementation=ECOINVENT,
                consensus=False,
            ),
            index={"ei-1": target},
        )

    def test_a_factor_is_converted_onto_our_unit(self):
        matched, findings = self._match(self._target("cf-1", "kg", "MJ", 560000.0))
        self.assertEqual(findings, [])
        self.assertEqual(matched[0].factor.amount, 1.0)
        self.assertEqual(matched[0].stated_amount, 560000.0)

    def test_a_conversion_of_one_still_crosses(self):
        """`m2` to `m2.a` at 1.0 is the time-dimension crossing #272 admits: the
        number does not move and the unit does, and what was stated is kept."""
        matched, findings = self._match(
            self._target("cf-1", "m2", "m2.a", 1.0), amount=4.2
        )
        self.assertEqual(findings, [])
        self.assertEqual(matched[0].factor.amount, 4.2)
        self.assertEqual(matched[0].stated_amount, 4.2)

    def test_agreeing_units_convert_nothing(self):
        matched, findings = self._match(self._target("cf-1", "kg", "kg"), amount=3.02)
        self.assertEqual(findings, [])
        self.assertEqual(matched[0].factor.amount, 3.02)
        self.assertIsNone(matched[0].stated_amount)

    def test_a_stated_multiplier_between_two_masses_is_applied(self):
        """#118. Both sides are `kg` and the conversion is real: a kilogram of
        baddeleyite is 740 grams of zirconium, which is a change in what is being
        measured rather than in the unit it is measured in.

        Before this, `convert()` asked whether the two unit *names* differed and
        handed the amount back when they did not -- so a curator could write the
        number, the merge would record it against the pair, and the factor pass
        would ignore it."""
        matched, findings = self._match(
            self._target("cf-1", "kg", "kg", 0.74033), amount=4.027307698550536e-06
        )
        self.assertEqual(findings, [])
        self.assertAlmostEqual(matched[0].factor.amount, 5.4399e-06, places=10)
        self.assertEqual(matched[0].stated_amount, 4.027307698550536e-06)

    def test_it_reproduces_ecoinvents_own_zirconium_number(self):
        """The check that the direction is right, and #118's worked example.

        ecoinvent states 4.0273e-06 per kg of baddeleyite and 5.44e-06 per kg of
        zirconium. They are one number on two weighing bases, and the second is
        what the JRC states too -- so a build that applies the conversion stops
        reporting the two as 1.35x apart."""
        crossing = UnitCrossing("kg", "kg", 0.74033)
        self.assertAlmostEqual(
            crossing.convert(4.027307698550536e-06), 5.44e-06, places=9
        )

    def test_two_masses_still_do_not_cross(self):
        """`crosses` is deliberately unchanged: it answers whether publishing a
        number without a multiplier would put a mass where an energy was asked
        for, and for two masses it would not."""
        self.assertFalse(UnitCrossing("kg", "kg", 0.74033).crosses)
        self.assertTrue(UnitCrossing("kg", "MJ", 560000.0).crosses)

    def test_a_multiplier_of_one_between_agreeing_units_changes_nothing(self):
        # The arithmetic says so, and it is worth pinning: a pair the merge
        # recorded at 1.0 must not become a place where a number quietly moves.
        self.assertEqual(UnitCrossing("kg", "kg", 1.0).convert(3.02), 3.02)

    def test_a_crossing_with_no_conversion_publishes_nothing(self):
        """Publishing the number anyway would state a mass where an energy was
        asked for."""
        matched, findings = self._match(self._target("cf-1", "kg", "MJ"))
        self.assertEqual(matched, [])
        self.assertEqual(findings[0].kind, FindingKind.UNIT_CROSSING)
        self.assertEqual(findings[0].context["source_unit"], "kg")
        self.assertEqual(findings[0].context["target_unit"], "MJ")

    def test_the_conversion_reproduces_the_jrcs_own_number(self):
        """560,000 CTUe per kg of uranium and 1.0 per MJ are one statement."""
        crossing = UnitCrossing("kg", "MJ", 560000.0)
        self.assertEqual(crossing.convert(560000.0), 1.0)

    def test_a_conversion_the_build_recorded_for_that_flow_is_reused(self):
        """#170. GreenDelta states water use per kilogram and this list publishes
        water per cubic metre. The row itself carries no multiplier -- it was
        reached by a name, not by an identifier -- but BAFU's own kilogram water
        rows were merged onto the same flow carrying 0.001 m3/kg, so the number
        is already in the build."""
        matched, findings = self._match(
            self._target("cf-1", "kg", "m3"),
            amount=0.00698,
        )
        self.assertEqual(matched, [])
        self.assertEqual(findings[0].kind, FindingKind.UNIT_CROSSING)
        matched, findings = match(
            _source(
                {"ei-1": [_ecoinvent_factor(0.00698, flow="ei-1")]},
                implementation=ECOINVENT,
                consensus=False,
            ),
            index={"ei-1": self._target("cf-1", "kg", "m3")},
            conversions={("cf-1", "kg", "m3"): 0.001},
        )
        self.assertEqual(findings, [])
        self.assertAlmostEqual(matched[0].factor.amount, 6.98, places=9)
        self.assertEqual(matched[0].stated_amount, 0.00698)

    def test_it_is_the_flow_and_the_units_that_are_matched(self):
        """A conversion is a statement about a pair, so a multiplier recorded for
        another flow, or for another pair of units, is not this row's. A kilogram
        of standing wood is 0.00204 cubic metres and a kilogram of water is
        0.001, and neither flow is the other."""
        for conversions in (
            {("cf-2", "kg", "m3"): 0.00204},
            {("cf-1", "kg", "MJ"): 0.001},
            {("cf-1", "m3", "kg"): 1000.0},
        ):
            with self.subTest(sorted(conversions)):
                matched, findings = match(
                    _source(
                        {"ei-1": [_ecoinvent_factor(0.00698, flow="ei-1")]},
                        implementation=ECOINVENT,
                        consensus=False,
                    ),
                    index={"ei-1": self._target("cf-1", "kg", "m3")},
                    conversions=conversions,
                )
                self.assertEqual(matched, [])
                self.assertEqual(findings[0].kind, FindingKind.UNIT_CROSSING)

    def test_a_row_that_states_its_own_multiplier_keeps_it(self):
        """The recorded conversion is a fallback, never an override: a row that
        arrived with an identifier carries the merge's own answer for that row."""
        matched, findings = match(
            _source(
                {"ei-1": [_ecoinvent_factor(560000.0, flow="ei-1")]},
                implementation=ECOINVENT,
                consensus=False,
            ),
            index={"ei-1": self._target("cf-1", "kg", "MJ", 560000.0)},
            conversions={("cf-1", "kg", "MJ"): 2.0},
        )
        self.assertEqual(findings, [])
        self.assertEqual(matched[0].factor.amount, 1.0)

    def test_the_reuse_is_counted(self):
        """A run says how many factors were published on a number it went
        looking for, because that is a weaker claim than a row stating its own."""
        counts = Counter()
        match(
            _source(
                {"ei-1": [_ecoinvent_factor(0.00698, flow="ei-1")]},
                implementation=ECOINVENT,
                consensus=False,
            ),
            index={"ei-1": self._target("cf-1", "kg", "m3")},
            conversions={("cf-1", "kg", "m3"): 0.001},
            counts=counts,
        )
        self.assertEqual(counts["conversions_reused"], 1)
        self.assertEqual(counts["factors_converted_by_a_recorded_conversion"], 1)

    def test_converting_without_a_factor_raises(self):
        with self.assertRaises(ValueError):
            UnitCrossing("kg", "MJ").convert(1.0)


class TheDeclinedNumbersAreSurfacedTestCase(unittest.TestCase):
    """196 factor rows carry a number this list declined, and a reader comparing
    two implementations has to know the one they see was chosen from two."""

    def _run(self, published, declined, *, relative=None, generated_by="x"):
        factor = _jrc_factor(published)
        factor.superseded_values.append(
            SupersededValue(
                amount=declined,
                provenance=Provenance(
                    was_generated_by=generated_by,
                    was_attributed_to="brightway-flows",
                    had_primary_source=["urn:uuid:ef-2"],
                ),
                relative_difference=relative,
            )
        )
        source = _source(
            {"ef-1": [factor]}, implementation=JRC, consensus=True
        )
        matched, _findings = match(source)
        return _declined_numbers(source, matched)

    def test_each_declined_number_is_a_row(self):
        findings = self._run(134.73, 53540.0)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].kind, FindingKind.SUPERSEDED_VALUE)
        self.assertEqual(findings[0].elementary_flow_uuid, "ef-1")

    def test_it_names_both_numbers_and_the_gap(self):
        """#64's kresoxim-methyl: 134.73 published, 53,540 declined, 397x."""
        finding = self._run(134.73, 53540.0)[0]
        self.assertEqual(finding.context["published"], 134.73)
        self.assertEqual(finding.context["declined"], 53540.0)
        self.assertEqual(round(finding.context["ratio"]), 397)
        self.assertIn("397x apart", finding.detail)

    def test_it_says_which_pass_settled_it(self):
        """A number a curator's ruling settled is not the same event as one a
        signature collapsed."""
        finding = self._run(
            1.0, 2.0, generated_by="pipeline.collision_decisions"
        )[0]
        self.assertEqual(finding.context["settled_by"], "pipeline.collision_decisions")
        self.assertEqual(finding.context["declined_by"], ["urn:uuid:ef-2"])

    def test_a_rounding_difference_is_still_a_row(self):
        """Small is not nothing: the number was still chosen from two, and #63
        is about the choice being findable rather than about its size."""
        finding = self._run(0.00011755, 0.000118, relative=0.0038)[0]
        self.assertNotIn("apart", finding.detail)
        self.assertEqual(finding.context["relative_difference"], 0.0038)

    def test_a_factor_nobody_settled_says_nothing(self):
        source = _source(
            {"ef-1": [_jrc_factor(1.0)]},
            implementation=JRC,
            consensus=True,
        )
        matched, _ = match(source)
        self.assertEqual(_declined_numbers(source, matched), [])


class TheSourceIndexTestCase(unittest.TestCase):
    """What the merge recorded about a source row: where it went, and in what."""

    def _database(self, rows, flows=(("cf-1", "kg"), ("cf-2", "kg"))):
        handle = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        handle.close()
        path = Path(handle.name)
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE TABLE elementary_flow_sources (elementary_flow_uuid TEXT, "
            "list_name TEXT, list_version TEXT, source_flow_uuid TEXT, "
            "source_metadata_json TEXT)"
        )
        connection.execute("CREATE TABLE elementary_flows (uuid TEXT, unit TEXT)")
        connection.executemany(
            "INSERT INTO elementary_flow_sources VALUES (?, ?, ?, ?, ?)",
            [(*row[:4], orjson.dumps(row[4]).decode()) for row in rows],
        )
        connection.executemany("INSERT INTO elementary_flows VALUES (?, ?)", flows)
        connection.commit()
        connection.close()
        return path

    def test_it_reads_one_list(self):
        path = self._database(
            [
                ("cf-1", "ecoinvent", "3.12", "ei-1", {"unit": "kg"}),
                ("cf-2", "ecoinvent", "3.8", "ei-1", {"unit": "kg"}),
            ]
        )
        index = merge_targets(path, list_name="ecoinvent", list_version="3.12")
        self.assertEqual(list(index), ["ei-1"])
        self.assertEqual(index["ei-1"].elementary_flow_uuid, "cf-1")
        self.assertFalse(index["ei-1"].crossing.crosses)

    def test_it_carries_the_units_and_the_conversion(self):
        """A factor is per unit of a flow, so which flow is not the whole
        question."""
        path = self._database(
            [
                (
                    "cf-1",
                    "ecoinvent",
                    "3.12",
                    "ei-1",
                    {"unit": "kg", "qudt:conversionMultiplier": 560000.0},
                )
            ],
            flows=(("cf-1", "MJ"),),
        )
        crossing = merge_targets(
            path, list_name="ecoinvent", list_version="3.12"
        )["ei-1"].crossing
        self.assertTrue(crossing.crosses)
        self.assertEqual(crossing.multiplier, 560000.0)
        self.assertEqual(crossing.convert(560000.0), 1.0)

    def test_every_conversion_the_build_recorded_is_indexed_by_its_pair(self):
        """#170. What a row reached by a name or a decision has instead of a
        multiplier of its own."""
        path = self._database(
            [
                (
                    "cf-1",
                    "bafu",
                    "2026-v1",
                    "bafu-1",
                    {"unit": "kg", "qudt:conversionMultiplier": 0.001},
                ),
                ("cf-2", "bafu", "2026-v1", "bafu-2", {"unit": "m3"}),
            ],
            flows=(("cf-1", "m3"), ("cf-2", "m3")),
        )
        self.assertEqual(
            recorded_conversions(path), {("cf-1", "kg", "m3"): 0.001}
        )

    def test_a_unit_written_two_ways_is_one_pair(self):
        """The source list writes `m2*a` and the flow says `m2.a`; a pair that
        differed only in spelling would look like a conversion nobody made."""
        path = self._database(
            [
                (
                    "cf-1",
                    "ecoinvent",
                    "3.12",
                    "ei-1",
                    {"unit": "m2", "qudt:conversionMultiplier": 1.0},
                )
            ],
            flows=(("cf-1", "m2*a"),),
        )
        self.assertEqual(recorded_conversions(path), {("cf-1", "m2", "m2.a"): 1.0})

    def test_a_pair_two_rows_disagree_about_is_left_out(self):
        """Natural gas carries 34.5 and 36.0 megajoules per cubic metre, from two
        lists that measured different gas. Picking one would invent an answer
        where the evidence is that there is more than one."""
        path = self._database(
            [
                (
                    "cf-1",
                    "bafu",
                    "2026-v1",
                    "bafu-1",
                    {"unit": "m3", "qudt:conversionMultiplier": 34.5},
                ),
                (
                    "cf-1",
                    "ecoinvent",
                    "3.12",
                    "ei-1",
                    {"unit": "m3", "qudt:conversionMultiplier": 36.0},
                ),
            ],
            flows=(("cf-1", "MJ"),),
        )
        self.assertEqual(recorded_conversions(path), {})

    def test_two_rows_stating_one_conversion_are_one_answer(self):
        """Every ecoinvent release records the same 0.001 for its own water row,
        and agreeing about a number is not disagreeing about it."""
        path = self._database(
            [
                (
                    "cf-1",
                    "ecoinvent",
                    version,
                    f"ei-{version}",
                    {"unit": "kg", "qudt:conversionMultiplier": 0.001},
                )
                for version in ("3.8", "3.12")
            ],
            flows=(("cf-1", "m3"),),
        )
        self.assertEqual(recorded_conversions(path), {("cf-1", "kg", "m3"): 0.001})

    def test_a_source_flow_on_two_consensus_flows_raises(self):
        """One published number would be on two flows, and nothing here should
        choose which."""
        path = self._database(
            [
                ("cf-1", "ecoinvent", "3.12", "ei-1", {"unit": "kg"}),
                ("cf-2", "ecoinvent", "3.12", "ei-1", {"unit": "kg"}),
            ]
        )
        with self.assertRaises(ValueError):
            merge_targets(path, list_name="ecoinvent", list_version="3.12")


class TheCategoryOfAFactorTestCase(unittest.TestCase):
    def test_the_jrc_is_keyed_by_its_method_uuid(self):
        definition = _definition_for(METHOD, _jrc_factor(1.0), implementation=JRC)
        self.assertEqual(definition.stated[JRC.slug].identifier, JRC_CATEGORY)

    def test_ecoinvent_is_keyed_by_its_category_name(self):
        definition = _definition_for(
            METHOD,
            _ecoinvent_factor(1.0, flow="ei-1"),
            implementation=ECOINVENT,
        )
        self.assertEqual(definition.stated[ECOINVENT.slug].name, ECOINVENT_CATEGORY)

    def test_a_category_the_crosswalk_does_not_have_raises(self):
        """The crosswalk and the ingested data disagreeing about what the words
        mean is not something to publish a number under."""
        stray = StatedFactor(
            category=stated_category(uuid="not-a-method", name="Nothing"),
            flow_uuid="ef-1",
            amount=1.0,
        )
        with self.assertRaises(ValueError):
            _definition_for(METHOD, stray, implementation=JRC)


class TheTablesTestCase(unittest.TestCase):
    """What `characterise` writes, and the invariant it holds as a key."""

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        handle.close()
        self.path = Path(handle.name)
        self.categories = {
            str(category.id): category
            for category in impact_categories_for("ef", JRC.slug)
        }
        self.category_id = next(iter(self.categories))

    def _write(self, factors, findings=()):
        write_characterisation(
            self.path,
            run=CharacterisationRun(
                run_id="run-1", started_at="2026-08-17T00:00:00Z", build_run_id="build-1"
            ),
            categories=self.categories,
            factors=factors,
            findings=list(findings),
            differences=[],
            coverage=[],
            stats={"factors_published": sum(len(v) for v in factors.values())},
        )

    def _rows(self, table):
        connection = sqlite3.connect(self.path)
        try:
            return connection.execute(f"SELECT * FROM {table}").fetchall()
        finally:
            connection.close()

    def _matched(self, amount, *, flow="cf-1", geography=None):
        return MatchedFactor(
            elementary_flow_uuid=flow,
            factor=_jrc_factor(amount, geography=geography),
        )

    def test_the_categories_and_their_counts(self):
        self._write({self.category_id: [self._matched(1.0)]})
        rows = {row[0]: row for row in self._rows("lcia_impact_categories")}
        self.assertEqual(len(rows), 25)
        self.assertEqual(rows[self.category_id][-2], 1)

    def test_a_factor_carries_its_place(self):
        self._write({self.category_id: [self._matched(-522.81, geography="ES-CA")]})
        row = self._rows("lcia_characterization_factors")[0]
        self.assertEqual(row[2], "ES-CA")
        self.assertEqual(row[3], -522.81)

    def test_a_factor_with_no_place_stores_the_empty_string(self):
        """Not NULL: SQLite treats NULLs as distinct in a key, and the invariant
        is the key."""
        self._write({self.category_id: [self._matched(1.0)]})
        self.assertEqual(self._rows("lcia_characterization_factors")[0][2], "")

    def test_two_factors_for_one_flow_category_and_place_are_refused(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self._write({self.category_id: [self._matched(1.0), self._matched(2.0)]})

    def test_two_places_are_two_rows(self):
        self._write(
            {
                self.category_id: [
                    self._matched(-522.81, geography="ES-CA"),
                    self._matched(-227.0, geography="YE"),
                ]
            }
        )
        self.assertEqual(len(self._rows("lcia_characterization_factors")), 2)

    def test_a_second_run_replaces_the_first(self):
        """The tables are a projection of one build; there is no history here."""
        self._write({self.category_id: [self._matched(1.0)]})
        self._write({self.category_id: [self._matched(2.0)]})
        self.assertEqual(len(self._rows("lcia_runs")), 1)
        self.assertEqual(self._rows("lcia_characterization_factors")[0][3], 2.0)

    def test_the_run_records_which_build_it_read(self):
        self._write({})
        self.assertEqual(self._rows("lcia_runs")[0][4], "build-1")


class EndToEndTestCase(unittest.TestCase):
    """A whole run over a database with two flows and one merged source row."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "consensus-flows.sqlite3"
        definition = BY_METHOD_UUID[JRC_CATEGORY]
        entry = {
            "method_uuid": JRC_CATEGORY,
            "name": definition.stated[JRC.slug].name,
            "methodology": "Environmental Footprint",
            "impact_category": definition.stated[JRC.slug].name,
            "impact_indicator": definition.stated[JRC.slug].indicator,
            "characterization_factor": 1.5,
        }
        connection = sqlite3.connect(self.db)
        connection.execute(
            "CREATE TABLE elementary_flows (uuid TEXT, flow_object_id TEXT, "
            "pref_label_value TEXT, context_display TEXT, context_iri TEXT, "
            "unit TEXT, is_deprecated INTEGER, replaced_by_uuid TEXT, "
            "flow_json TEXT, context_dimension TEXT, context_media TEXT)"
        )
        connection.execute(
            "CREATE TABLE elementary_flow_sources (elementary_flow_uuid TEXT, "
            "list_name TEXT, list_version TEXT, source_flow_uuid TEXT, "
            "source_metadata_json TEXT)"
        )
        connection.execute("CREATE TABLE pipeline_runs (run_id TEXT, timestamp TEXT)")
        # A build has flow objects, and `characterise` reads their registry
        # numbers: a statement about somebody else's model arrives keyed on CAS
        # and nothing else (`lcia.contradictions`).
        connection.execute(
            "CREATE TABLE flow_objects (flow_object_id TEXT, "
            "pref_label_value TEXT, classifications_json TEXT, "
            "properties_json TEXT)"
        )
        connection.executemany(
            "INSERT INTO flow_objects (flow_object_id, pref_label_value, "
            "classifications_json) VALUES (?, ?, ?)",
            [
                (
                    "fo-1",
                    "Ammonia",
                    orjson.dumps({
                        CHEMINF_CAS_REGISTRY_NUMBER: {"@value": ["7664-41-7"]}
                    }).decode(),
                ),
                ("fo-2", "Copper", orjson.dumps({}).decode()),
            ],
        )
        connection.executemany(
            "INSERT INTO elementary_flows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "cf-1",
                    "fo-1",
                    "Ammonia",
                    "Environmental → Air → Unknown",
                    "ctx-air",
                    "kg",
                    0,
                    None,
                    orjson.dumps({"lcia_methods": [entry]}).decode(),
                    "Environmental",
                    "Air",
                ),
                (
                    "cf-2",
                    "fo-2",
                    "Copper",
                    "Environmental → Ground → Silvicultural",
                    "ctx-silv",
                    "kg",
                    0,
                    None,
                    orjson.dumps({"lcia_methods": []}).decode(),
                    "Environmental",
                    "Ground",
                ),
            ],
        )
        connection.execute(
            "INSERT INTO elementary_flow_sources VALUES (?, ?, ?, ?, ?)",
            ("cf-1", "ecoinvent", "3.12", "ei-1", orjson.dumps({"unit": "kg"}).decode()),
        )
        connection.execute(
            "INSERT INTO pipeline_runs VALUES (?, ?)", ("build-9", "2026-08-17")
        )
        connection.commit()
        connection.close()

        factors_path = root / "ecoinvent-3.12-lcia-factors.json"
        factors_path.write_bytes(
            orjson.dumps(
                {
                    "schema_version": 1,
                    "methods": [
                        {
                            "method": "EF v3.1",
                            "categories": [
                                {"category": ECOINVENT_CATEGORY, "indicator": "i",
                                 "unit": "u"}
                            ],
                            "factors": [
                                {"flow_uuid": "ei-1",
                                 "category": ECOINVENT_CATEGORY, "amount": 9.9},
                                {"flow_uuid": "ei-404",
                                 "category": ECOINVENT_CATEGORY, "amount": 1.0},
                            ],
                        }
                    ],
                }
            )
        )
        self.source = SourceList(
            list_name="ecoinvent",
            list_version="3.12",
            flows_path=root / "flows.json",
            lcia=LciaSpec(
                adapter="brightway_flows.integrations.ecoinvent_lcia:fetch",
                factors_path=factors_path,
                methods=(LciaMethodSpec(name="EF v3.1", no_long_term=None),),
                implemented_by="ecoinvent Centre",
            ),
        )
        self.stats = characterise(self.db, source_lists={"ecoinvent-3.12": self.source})

    def tearDown(self):
        self.tmp.cleanup()

    def _rows(self, sql):
        connection = sqlite3.connect(self.db)
        try:
            return connection.execute(sql).fetchall()
        finally:
            connection.close()

    def test_both_implementations_are_published(self):
        self.assertEqual(self.stats["ef_jrc_factors_published"], 1)
        self.assertEqual(self.stats["ef_ecoinvent_centre_factors_published"], 1)

    def test_every_category_of_every_method_is_written(self):
        """Including the ones no implementation filled: the category set is what
        the list publishes, and a count of zero is honest where leaving them out
        would say they do not exist.

        138 -- EF 3.1's 25 times four implementations, Stepwise 2006's 19 times
        two. This fixture merges no Stepwise flows, so all 19 of its consensus
        categories are awaiting factors alongside EF's 25."""
        self.assertEqual(len(self._rows("SELECT * FROM lcia_impact_categories")), 138)
        self.assertEqual(self.stats["consensus_categories_awaiting_factors"], 44)

    def test_each_factor_is_on_its_own_implementation(self):
        jrc = impact_category_id(
            impact_category_iri(
                METHOD, BY_METHOD_UUID[JRC_CATEGORY], JRC
            )
        )
        ecoinvent = impact_category_id(
            impact_category_iri(
                METHOD, BY_ECOINVENT_NAME[ECOINVENT_CATEGORY], ECOINVENT
            )
        )
        rows = dict(
            self._rows(
                "SELECT impact_category_id, amount FROM lcia_characterization_factors"
            )
        )
        self.assertEqual(rows[str(jrc)], 1.5)
        self.assertEqual(rows[str(ecoinvent)], 9.9)

    def test_the_row_that_reached_no_flow_is_a_finding(self):
        rows = self._rows("SELECT kind, implemented_by FROM lcia_findings")
        self.assertEqual(
            rows, [(str(FindingKind.FLOW_NOT_REACHED), "ecoinvent Centre")]
        )

    def test_running_it_again_produces_the_same_tables(self):
        """`characterise` reads a build and writes a projection of it; a second
        run against an unchanged build has nothing new to say."""
        before = self._rows(
            "SELECT * FROM lcia_characterization_factors ORDER BY 1, 2, 3"
        )
        characterise(self.db, source_lists={"ecoinvent-3.12": self.source})
        self.assertEqual(
            self._rows("SELECT * FROM lcia_characterization_factors ORDER BY 1, 2, 3"),
            before,
        )

    def test_the_crosswalk_is_the_whole_category_set(self):
        # Every method's, which is what `impact_categories()` returns: EF 3.1's
        # 25 and Stepwise 2006's 19.
        self.assertEqual(len(impact_categories()), 44)


#: Biphenyl's six compartments, with the factor EF 3.1 states for each under
#: `Human toxicity, non-cancer` -- the numbers `data/lcia-underlying-model-factors.json`
#: was measured against, so this exercises the shipped file rather than a fixture
#: of its own.
BIPHENYL = (
    ("https://vocab.brightway.one/flow-contexts/envi-air-grle-ur10pesq", 0.19957),
    ("https://vocab.brightway.one/flow-contexts/envi-air-mest15me-ru10pesq", 0.014939),
    ("https://vocab.brightway.one/flow-contexts/envi-wate-suwa", 0.0044065),
    ("https://vocab.brightway.one/flow-contexts/envi-wate-ocea", 0.00015794),
    ("https://vocab.brightway.one/flow-contexts/envi-grou-agri", 0.00089871),
    ("https://vocab.brightway.one/flow-contexts/envi-grou-noag", 0.0008987),
)
NON_CANCER = "7cfdcfcf-b222-4b26-888a-a55f9fbf7ac8"

#: The media each of those contexts is in, as the real table records it.  Kept
#: beside the contexts rather than parsed out of the IRI, so a fixture cannot
#: quietly disagree with the build about what kind of place a flow is in.
_MEDIA_OF = {
    "https://vocab.brightway.one/flow-contexts/envi-air-grle-ur10pesq": "Air",
    "https://vocab.brightway.one/flow-contexts/envi-air-mest15me-ru10pesq": "Air",
    "https://vocab.brightway.one/flow-contexts/envi-wate-suwa": "Water",
    "https://vocab.brightway.one/flow-contexts/envi-wate-ocea": "Water",
    "https://vocab.brightway.one/flow-contexts/envi-grou-agri": "Ground",
    "https://vocab.brightway.one/flow-contexts/envi-grou-noag": "Ground",
}


class WhatTheUnderlyingModelContradictsTestCase(unittest.TestCase):
    """EF 3.1's number is published under the JRC's name and withheld from ours.

    The whole shape of #107's fix, end to end and on the shipped evidence: the
    transcription is what the JRC published and does not move, and the
    implementation that is ours declines to publish a number USEtox 2.1 puts four
    to six orders of magnitude away, until a curator rules.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "consensus-flows.sqlite3"
        definition = BY_METHOD_UUID[NON_CANCER]
        connection = sqlite3.connect(self.db)
        connection.execute(
            "CREATE TABLE elementary_flows (uuid TEXT, flow_object_id TEXT, "
            "pref_label_value TEXT, context_display TEXT, context_iri TEXT, "
            "unit TEXT, is_deprecated INTEGER, replaced_by_uuid TEXT, "
            "flow_json TEXT, context_dimension TEXT, context_media TEXT)"
        )
        connection.execute(
            "CREATE TABLE elementary_flow_sources (elementary_flow_uuid TEXT, "
            "list_name TEXT, list_version TEXT, source_flow_uuid TEXT, "
            "source_metadata_json TEXT)"
        )
        connection.execute(
            "CREATE TABLE flow_objects (flow_object_id TEXT, "
            "pref_label_value TEXT, classifications_json TEXT, "
            "properties_json TEXT)"
        )
        connection.execute("CREATE TABLE pipeline_runs (run_id TEXT, timestamp TEXT)")
        connection.execute(
            "CREATE TABLE review_queue (queue_name TEXT NOT NULL, "
            "item_key TEXT NOT NULL, item_index INTEGER NOT NULL DEFAULT 0, "
            "title TEXT NOT NULL DEFAULT '', severity TEXT NOT NULL DEFAULT 'info', "
            "elementary_flow_uuid TEXT NOT NULL DEFAULT '', "
            "flow_object_id TEXT NOT NULL DEFAULT '', cas TEXT NOT NULL DEFAULT '', "
            "payload_json TEXT NOT NULL DEFAULT '{}', "
            "PRIMARY KEY (queue_name, item_key))"
        )
        connection.execute(
            "INSERT INTO flow_objects (flow_object_id, pref_label_value, "
            "classifications_json) VALUES (?, ?, ?)",
            (
                "fo-biphenyl",
                "Biphenyl",
                orjson.dumps({
                    CHEMINF_CAS_REGISTRY_NUMBER: {"@value": ["92-52-4"]}
                }).decode(),
            ),
        )
        connection.executemany(
            "INSERT INTO elementary_flows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    f"cf-{index}",
                    "fo-biphenyl",
                    "Biphenyl",
                    context_iri.rsplit("/", 1)[-1],
                    context_iri,
                    "kg",
                    0,
                    None,
                    orjson.dumps({
                        "lcia_methods": [{
                            "method_uuid": NON_CANCER,
                            "name": definition.stated[JRC.slug].name,
                            "methodology": "Environmental Footprint",
                            "impact_category": definition.stated[JRC.slug].name,
                            "impact_indicator": definition.stated[JRC.slug].indicator,
                            "characterization_factor": amount,
                        }]
                    }).decode(),
                    "Environmental",
                    # Biphenyl's six compartments are air, water and soil; the
                    # media is read off the context the fixture names so that the
                    # air-compartment pass sees what the real table would show.
                    _MEDIA_OF[context_iri],
                )
                for index, (context_iri, amount) in enumerate(BIPHENYL)
            ],
        )
        connection.execute(
            "INSERT INTO pipeline_runs VALUES (?, ?)", ("build-552", "2026-08-17")
        )
        connection.commit()
        connection.close()

        factors_path = root / "ecoinvent-3.12-lcia-factors.json"
        factors_path.write_bytes(
            orjson.dumps({"schema_version": 1, "methods": []})
        )
        self.source = SourceList(
            list_name="ecoinvent",
            list_version="3.12",
            flows_path=root / "flows.json",
            lcia=LciaSpec(
                adapter="brightway_flows.integrations.ecoinvent_lcia:fetch",
                factors_path=factors_path,
                methods=(LciaMethodSpec(name="EF v3.1", no_long_term=None),),
                implemented_by="ecoinvent Centre",
            ),
        )
        self.stats = characterise(self.db, source_lists={"ecoinvent-3.12": self.source})

    def tearDown(self):
        self.tmp.cleanup()

    def _rows(self, sql, parameters=()):
        connection = sqlite3.connect(self.db)
        try:
            return connection.execute(sql, parameters).fetchall()
        finally:
            connection.close()

    def _published_by(self, implemented_by):
        return self._rows(
            "SELECT f.elementary_flow_uuid, f.amount "
            "FROM lcia_characterization_factors f "
            "JOIN lcia_impact_categories c ON c.id = f.impact_category_id "
            "WHERE c.implemented_by = ? ORDER BY 1",
            (implemented_by,),
        )

    def test_the_jrc_s_transcription_still_says_what_ef_says(self):
        self.assertEqual(
            [amount for _uuid, amount in self._published_by("European Commission — JRC")],
            [amount for _context_iri, amount in BIPHENYL],
        )

    def test_the_consensus_implementation_publishes_none_of_them(self):
        self.assertEqual(self._published_by("brightway-flows"), [])
        self.assertEqual(self.stats["ef_consensus_sole"], 0)

    def test_the_run_says_what_the_evidence_reached(self):
        self.assertEqual(self.stats["ef_underlying_model_evidence"], 38)
        self.assertEqual(self.stats["ef_underlying_model_contradicted"], 1)
        self.assertEqual(self.stats["ef_underlying_model_substances"], 1)

    def test_it_is_one_question_over_six_factors(self):
        rows = self._rows(
            "SELECT item_key, severity, payload_json FROM review_queue "
            "WHERE queue_name = 'contradicted-factor'"
        )
        self.assertEqual(len(rows), 1)
        item_key, severity, payload = rows[0]
        self.assertEqual(item_key, "ef|fo-biphenyl|human-toxicity-non-cancer")
        self.assertEqual(severity, "blocking")
        payload = orjson.loads(payload)
        self.assertEqual(payload["factor_count"], len(BIPHENYL))
        self.assertEqual(payload["contradicts"]["model"], "USEtox 2.1")
        self.assertGreater(payload["contradicts"]["widest_ratio"], 1_000_000)


if __name__ == "__main__":
    unittest.main()
