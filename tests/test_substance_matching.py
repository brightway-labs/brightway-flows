"""Reaching a flow by its substance, when no identifier connects the two.

The rule #165 asked for, and the two things it must not do: reach a flow in
another compartment, and pick one when the evidence says there is more than one.

Every case builds its own small database. The numbers from the real package are
in `tests/test_greendelta_lcia.py` and in `expectations/`; what is here is the
rule.
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
from brightway_flows.lcia.sources import FactorSource
from brightway_flows.lcia.substance_matching import (
    BY_NAME,
    BY_NUMBER_AND_NAME,
    BY_REGISTRY_NUMBER,
    compartment_key,
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
#: A compartment their package uses and the mapping has a rule for.
THEIR_AIR = "Elementary flows/Emission to air/unspecified"
#: And one it also uses, so a match in the wrong one is visible.
THEIR_WATER = "Elementary flows/Emission to water/unspecified"


def _factor(amount: float = 1.5) -> StatedFactor:
    return StatedFactor(
        category=stated_category(uuid="c-1", name="Acidification"),
        flow_uuid="gd-1",
        amount=amount,
    )


class SubstanceMatchingTestCase(unittest.TestCase):
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
        self.air = context_iri_by_source_context("GreenDelta")[
            normalize_context_key(["Emission to air", "unspecified"])
        ]
        self.water = context_iri_by_source_context("GreenDelta")[
            normalize_context_key(["Emission to water", "unspecified"])
        ]

    def _flow(self, uuid, label, context_iri, *, cas=None, unit="kg",
              deprecated=0, display=None):
        object_id = f"fo-{uuid}"
        self.connection.execute(
            "INSERT INTO elementary_flows VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                uuid,
                object_id,
                label,
                context_iri,
                unit,
                display or context_iri.rsplit("/", 1)[-1],
                deprecated,
            ),
        )
        classifications = (
            orjson.dumps({CAS: {"@value": [cas]}}).decode() if cas else "{}"
        )
        self.connection.execute(
            "INSERT INTO flow_objects VALUES (?, ?)", (object_id, classifications)
        )
        self.connection.commit()

    def _source(self, described, factors=1):
        return FactorSource(
            implementation=GREENDELTA_IMPL,
            by_flow={"gd-1": [_factor() for _ in range(factors)]},
            flows_are_consensus=False,
            read_from="a file",
            descriptions={"gd-1": described},
        )

    def _run(self, described, factors=1, decisions=None):
        """The three routes over one row.  ``decisions`` defaults to none rather
        than to the shipped table: what a rule does is a different question from
        what a curator overruled, and a fixture that quietly read the real file
        would answer the second."""
        targets, basis_of, findings, _declined = substance_targets(
            self._source(described, factors),
            index=substance_index(self.db),
            outstanding={"gd-1"},
            decisions=decisions or {},
        )
        return targets, basis_of, findings

    def _run_all(self, described, factors=1, decisions=None):
        return substance_targets(
            self._source(described, factors),
            index=substance_index(self.db),
            outstanding={"gd-1"},
            decisions=decisions or {},
        )

    def test_a_registry_number_reaches_the_flow_that_carries_it(self):
        self._flow("u-1", "Ammonia", self.air, cas="7664-41-7")
        targets, basis, findings = self._run(
            {"name": "Ammonia", "context": THEIR_AIR, "unit": "kg",
             "cas": "007664-41-7"}
        )
        self.assertEqual(targets["gd-1"].elementary_flow_uuid, "u-1")
        self.assertEqual(basis["gd-1"], BY_REGISTRY_NUMBER)
        self.assertEqual(findings, [])

    def test_the_padding_their_file_writes_is_not_part_of_the_number(self):
        """`000056-23-5` is carbon tetrachloride, spelled SimaPro's way."""
        self._flow("u-1", "Tetrachloromethane", self.air, cas="56-23-5")
        targets, _basis, _findings = self._run(
            {"name": "Carbon tetrachloride", "context": THEIR_AIR, "unit": "kg",
             "cas": "000056-23-5"}
        )
        self.assertEqual(targets["gd-1"].elementary_flow_uuid, "u-1")

    def test_a_name_reaches_a_flow_where_no_number_is_stated(self):
        self._flow("u-1", "Ammonia", self.air)
        targets, basis, _findings = self._run(
            {"name": "ammonia", "context": THEIR_AIR, "unit": "kg", "cas": ""}
        )
        self.assertEqual(targets["gd-1"].elementary_flow_uuid, "u-1")
        self.assertEqual(basis["gd-1"], BY_NAME)

    def test_the_number_outranks_the_name(self):
        """#146 and #157 are both cases where the two disagreed and the number
        was right."""
        self._flow("u-number", "Something else", self.air, cas="7664-41-7")
        self._flow("u-name", "Ammonia", self.air)
        targets, basis, _findings = self._run(
            {"name": "Ammonia", "context": THEIR_AIR, "unit": "kg",
             "cas": "7664-41-7"}
        )
        self.assertEqual(targets["gd-1"].elementary_flow_uuid, "u-number")
        self.assertEqual(basis["gd-1"], BY_REGISTRY_NUMBER)

    def test_it_does_not_reach_across_a_compartment(self):
        """A freshwater number on an emission to air is a wrong factor, which is
        worse than a missing one."""
        self._flow("u-1", "Ammonia", self.water, cas="7664-41-7")
        targets, _basis, findings = self._run(
            {"name": "Ammonia", "context": THEIR_AIR, "unit": "kg",
             "cas": "7664-41-7"}
        )
        self.assertEqual(targets, {})
        self.assertEqual(findings, [])

    def test_a_number_two_flows_carry_is_settled_by_the_name(self):
        """`Water` and `Water vapour` are two flows under 7732-18-5, and 50 of
        their rows state it."""
        self._flow("u-water", "Water", self.water, cas="7732-18-5")
        self._flow("u-vapour", "Water vapour", self.water, cas="7732-18-5")
        targets, basis, findings = self._run(
            {"name": "Water", "context": THEIR_WATER, "unit": "kg",
             "cas": "007732-18-5"}
        )
        self.assertEqual(targets["gd-1"].elementary_flow_uuid, "u-water")
        self.assertEqual(basis["gd-1"], BY_NUMBER_AND_NAME)
        self.assertEqual(findings, [])

    def test_a_number_two_flows_carry_and_a_name_that_settles_neither(self):
        """`Water, DK` is one of theirs with the place in the name, which no
        label of ours carries. Reported, and matched to neither.

        Since #166's second change that row never gets this far -- the place
        in its name sets it aside before the number is tried
        (`lcia.regionalised_names`) -- so the rule is exercised here with
        nothing set aside, which is what the tie looks like on its own."""
        self._flow("u-water", "Water", self.water, cas="7732-18-5")
        self._flow("u-vapour", "Water vapour", self.water, cas="7732-18-5")
        described = {"name": "Water, DK", "context": THEIR_WATER, "unit": "kg",
                     "cas": "007732-18-5"}
        targets, basis, findings, _declined = substance_targets(
            self._source(described, 2),
            index=substance_index(self.db),
            outstanding={"gd-1"},
            decisions={},
            set_aside={},
        )
        self.assertEqual(targets, {})
        self.assertEqual(basis, {})
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.context["matched_on"], BY_REGISTRY_NUMBER)
        self.assertEqual(sorted(finding.context["candidates"]),
                         ["u-vapour", "u-water"])
        self.assertEqual(finding.context["factor_count"], 2)
        self.assertIn("Water, DK", finding.detail)

    def test_a_place_in_the_name_is_set_aside_before_the_number_is_tried(self):
        """The same row left to the default: the tie is never reached, and the
        row comes back declined with the reason (#166)."""
        self._flow("u-water", "Water", self.water, cas="7732-18-5")
        self._flow("u-vapour", "Water vapour", self.water, cas="7732-18-5")
        targets, basis, findings, declined = self._run_all(
            {"name": "Water, DK", "context": THEIR_WATER, "unit": "kg",
             "cas": "007732-18-5"}, factors=2
        )
        self.assertEqual((targets, basis, findings), ({}, {}, []))
        self.assertIn("writes the place into the flow name", declined["gd-1"])

    def test_a_name_two_flows_carry_is_reported_and_not_chosen_between(self):
        self._flow("u-1", "Ammonia", self.air)
        self._flow("u-2", "ammonia", self.air)
        targets, _basis, findings = self._run(
            {"name": "Ammonia", "context": THEIR_AIR, "unit": "kg", "cas": ""}
        )
        self.assertEqual(targets, {})
        self.assertEqual(findings[0].context["matched_on"], BY_NAME)

    def test_a_compartment_with_no_rule_reaches_nothing_and_is_not_a_second_finding(self):
        """`Resource / land` is #166: the action is in their name and this list
        files it as a context, so the compartment cannot say which is meant.
        `matching.match` reports the flow; saying it twice would say two things
        happened."""
        self._flow("u-1", "Occupation, agriculture", self.air)
        targets, _basis, findings = self._run(
            {"name": "Occupation, agriculture",
             "context": "Elementary flows/Resource/land", "unit": "m2*a",
             "cas": ""}
        )
        self.assertEqual(targets, {})
        self.assertEqual(findings, [])

    def test_a_withdrawn_flow_is_not_a_place_to_put_a_factor(self):
        self._flow("u-1", "Ammonia", self.air, cas="7664-41-7", deprecated=1)
        targets, _basis, findings = self._run(
            {"name": "Ammonia", "context": THEIR_AIR, "unit": "kg",
             "cas": "7664-41-7"}
        )
        self.assertEqual(targets, {})
        self.assertEqual(findings, [])

    def test_the_units_travel_with_the_match(self):
        """No multiplier: a conversion is a statement about a pair that somebody
        recorded, and nobody recorded one for a pair this pass invented. The
        crossing is reported by `matching.match`."""
        self._flow("u-1", "Uranium", self.air, cas="7440-61-1", unit="MJ")
        targets, _basis, _findings = self._run(
            {"name": "Uranium", "context": THEIR_AIR, "unit": "kg",
             "cas": "7440-61-1"}
        )
        crossing = targets["gd-1"].crossing
        self.assertEqual((crossing.source_unit, crossing.target_unit), ("kg", "MJ"))
        self.assertTrue(crossing.crosses)
        self.assertFalse(crossing.convertible)


class CompartmentKeyTestCase(unittest.TestCase):
    def test_the_openlca_root_is_not_part_of_the_compartment(self):
        self.assertEqual(
            compartment_key("Elementary flows/Emission to air/unspecified"),
            ("emission to air", "unspecified"),
        )

    def test_it_is_normalised_the_way_every_other_rule_is_looked_up(self):
        self.assertEqual(
            compartment_key("Elementary flows/Emission to Water/Fresh Water"),
            ("emission to water", "fresh water"),
        )

    def test_a_compartment_with_no_root(self):
        self.assertEqual(compartment_key("Resource/land"), ("resource", "land"))


class TheCuratedCompartmentsTestCase(unittest.TestCase):
    """The rows in `data/context-manual-mapping.json` under `GreenDelta`."""

    def setUp(self):
        self.rules = context_iri_by_source_context("GreenDelta")

    def test_every_compartment_their_package_uses_that_can_be_placed(self):
        self.assertEqual(len(self.rules), 21)

    def test_the_two_water_compartments_this_list_does_not_separate(self):
        """Their vocabulary keeps `fresh water` and `surface water` apart and
        ours does not, so both point at one context. EF 3.1's own 7,217
        freshwater flows are published there."""
        self.assertEqual(
            self.rules[normalize_context_key(["Emission to water", "fresh water"])],
            self.rules[normalize_context_key(["Emission to water", "surface water"])],
        )

    def test_the_resource_compartments_are_deliberately_absent(self):
        """#166. Their name carries the action -- `Occupation, agriculture` --
        which this list files as the context, so the compartment alone cannot
        say which context is meant."""
        for compartment in (["Resource", "land"], ["Resource", "in water"],
                            ["Resource", "unspecified"]):
            with self.subTest(compartment=compartment):
                self.assertNotIn(normalize_context_key(compartment), self.rules)

    def test_long_term_is_a_context_and_not_a_qualifier(self):
        for compartment in (["Emission to water", "ground water, long-term"],
                            ["Emission to water", "river, long-term"]):
            with self.subTest(compartment=compartment):
                self.assertTrue(
                    self.rules[normalize_context_key(compartment)].endswith("lote")
                )


if __name__ == "__main__":
    unittest.main()
