"""A place written into a publisher's flow name is not a substance, and the
number is published from the site-generic sibling instead.

`Water, well, CH` beside `Water, well`: the coded row is set aside, the
site-generic row carries the country's factor. The three shapes the rule
distinguishes are each a case here, over a `FactorSource` built by hand; what
the rule does to the real package is in `expectations/0785-...json`.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from brightway_flows.context_mapping import (
    context_iri_by_source_context,
    normalize_context_key,
)
from brightway_flows.domain.lcia.crosswalk import ef_method
from brightway_flows.domain.lcia.records import StatedFactor, stated_category
from brightway_flows.lcia.regionalised_names import (
    regionalised_names,
    set_aside,
)
from brightway_flows.lcia.sources import FactorSource
from brightway_flows.lcia.substance_decisions import (
    REACHES,
    SubstanceDecision,
)
from brightway_flows.lcia.substance_matching import (
    BY_DECISION,
    BY_REGISTRY_NUMBER,
    substance_index,
    substance_targets,
)

GREENDELTA_IMPL = ef_method().implementation("greendelta")
IN_WATER = "Elementary flows/Resource/in water"
IN_GROUND = "Elementary flows/Resource/in ground"
TO_RIVER = "Elementary flows/Emission to water/river"


def _source(**flows: tuple[str, str]) -> FactorSource:
    """A package stating one water-use factor per flow; *flows* maps a uuid to
    ``(name, compartment)``."""
    return FactorSource(
        implementation=GREENDELTA_IMPL,
        by_flow={
            uuid: [
                StatedFactor(
                    category=stated_category(uuid="c-1", name="Water use"),
                    flow_uuid=uuid,
                    amount=42.95,
                )
            ]
            for uuid in flows
        },
        flows_are_consensus=False,
        read_from="a file",
        descriptions={
            uuid: {"name": name, "context": context, "unit": "m3", "cas": "007732-18-5"}
            for uuid, (name, context) in flows.items()
        },
    )


class TheNameIsReadTestCase(unittest.TestCase):
    def test_a_country_after_the_last_comma_is_a_place(self):
        found = regionalised_names(
            _source(a=("Water, well, CH", IN_WATER), b=("Water, well", IN_WATER)),
            {"a", "b"},
        )
        self.assertEqual(
            [(row.stem, row.code) for row in found], [("Water, well", "CH")]
        )

    def test_glo_is_the_world(self):
        (row,) = regionalised_names(
            _source(a=("Water, unspecified natural origin, GLO", IN_WATER)), {"a"}
        )
        self.assertTrue(row.is_global)

    def test_a_region_no_code_covers_is_left_alone(self):
        """One flow and one factor in the real package, and not a place a rule
        can read: `Water, unspecified natural origin, Europe without
        Switzerland` is not split, so it is not set aside."""
        source = _source(
            a=(
                "Water, unspecified natural origin, Europe without Switzerland",
                IN_WATER,
            )
        )
        self.assertEqual(regionalised_names(source, {"a"}), [])
        self.assertEqual(set_aside(source, {"a"}), {})

    def test_a_land_name_ending_in_a_word_is_not_a_place(self):
        source = _source(
            a=("Transformation, to annual crop, non-irrigated, fallow", IN_WATER)
        )
        self.assertEqual(set_aside(source, {"a"}), {})


class TheThreeShapesTestCase(unittest.TestCase):
    def test_a_site_generic_sibling_carries_the_number(self):
        source = _source(
            ch=("Water, well, CH", IN_WATER),
            glo=("Water, well, GLO", IN_WATER),
            generic=("Water, well", IN_WATER),
        )
        aside = set_aside(source, {"ch", "glo", "generic"})
        self.assertEqual(set(aside), {"ch", "glo"})
        self.assertIn("states `Water, well` in the same compartment", aside["ch"])
        self.assertIn("#166", aside["ch"])

    def test_the_sibling_must_be_in_the_same_compartment(self):
        """`Water, well` as a withdrawal says nothing about `Water, well, CH`
        emitted to a river: a factor is a number about a flow in a place."""
        source = _source(
            ch=("Water, well, CH", TO_RIVER),
            generic=("Water, well", IN_WATER),
        )
        aside = set_aside(source, {"ch", "generic"})
        self.assertEqual(set(aside), {"ch"})
        self.assertIn("neither a site-generic", aside["ch"])

    def test_the_global_member_stands_for_a_set_with_no_generic_row(self):
        source = _source(
            ch=("Water, unspecified natural origin, CH", IN_WATER),
            de=("Water, unspecified natural origin, DE", IN_WATER),
            glo=("Water, unspecified natural origin, GLO", IN_WATER),
        )
        aside = set_aside(source, {"ch", "de", "glo"})
        self.assertEqual(set(aside), {"ch", "de"})
        self.assertIn(
            "`Water, unspecified natural origin, GLO` is the member", aside["ch"]
        )

    def test_a_set_of_countries_alone_publishes_nothing(self):
        source = _source(
            ch=("Water, well, CH", IN_GROUND),
            rer=("Water, well, RER", IN_GROUND),
        )
        aside = set_aside(source, {"ch", "rer"})
        self.assertEqual(set(aside), {"ch", "rer"})
        self.assertIn("none of the 2 members is published", aside["rer"])

    def test_a_sibling_spelled_with_its_unit_is_still_the_sibling(self):
        """`Water, cooling, unspecified natural origin/m3` is their site-generic
        row, with 209 country factors; six country rows stand beside it."""
        source = _source(
            ch=("Water, cooling, unspecified natural origin, CH", IN_WATER),
            generic=("Water, cooling, unspecified natural origin/m3", IN_WATER),
        )
        aside = set_aside(source, {"ch", "generic"})
        self.assertEqual(set(aside), {"ch"})
        self.assertIn(
            "states `Water, cooling, unspecified natural origin` in the same",
            aside["ch"],
        )

    def test_only_the_rows_asked_about_come_back(self):
        """A row an identifier already reached is not reconsidered, but it
        still counts as the sibling that carries the number."""
        source = _source(
            ch=("Water, well, CH", IN_WATER),
            generic=("Water, well", IN_WATER),
        )
        self.assertEqual(set(set_aside(source, {"ch"})), {"ch"})
        self.assertEqual(set_aside(source, {"generic"}), {})


class TheMatchingPassAppliesItTestCase(unittest.TestCase):
    """Where the rule sits among the routes: after a curated decision, before
    a number or a name -- over a small database, as
    `tests/test_lcia_substance_decisions.py` does."""

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
            "CREATE TABLE flow_objects (flow_object_id TEXT, classifications_json TEXT)"
        )
        river = context_iri_by_source_context("GreenDelta")[
            normalize_context_key(["Emission to water", "river"])
        ]
        connection.execute(
            "INSERT INTO elementary_flows VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "bwf-water",
                "fo-1",
                "Water",
                river,
                "m3",
                "Environmental → Water → River",
                0,
            ),
        )
        cas = "http://semanticscience.org/resource/CHEMINF_000446"
        connection.execute(
            "INSERT INTO flow_objects VALUES (?, ?)",
            ("fo-1", '{"%s": {"@value": ["7732-18-5"]}}' % cas),
        )
        connection.commit()
        connection.close()
        self.source = _source(
            ch=("Water, CH", TO_RIVER),
            generic=("Water", TO_RIVER),
        )

    def test_the_coded_row_is_set_aside_before_its_number_is_tried(self):
        """The number alone would reach `Water` -- it did, for 47 rows, and the
        build reported the collision -- so this is the claim that the rule comes
        first."""
        targets, basis_of, findings, declined = substance_targets(
            self.source,
            index=substance_index(self.db),
            outstanding={"ch", "generic"},
            decisions={},
        )
        self.assertEqual(set(targets), {"generic"})
        self.assertEqual(basis_of["generic"], BY_REGISTRY_NUMBER)
        self.assertEqual(set(declined), {"ch"})
        self.assertIn("published from that row", declined["ch"])
        self.assertEqual(findings, [])

    def test_a_curated_decision_outranks_the_rule(self):
        decision = SubstanceDecision(
            implemented_by="GreenDelta",
            source_flow_uuid="ch",
            source_flow_name="Water, CH",
            source_context=("Elementary flows", "Emission to water", "river"),
            decision=REACHES,
            comment="a curator read it otherwise",
            elementary_flow_uuid="bwf-water",
            substance="Water",
            context="Environmental → Water → River",
            unit="m3",
        )
        targets, basis_of, _findings, declined = substance_targets(
            self.source,
            index=substance_index(self.db),
            outstanding={"ch", "generic"},
            decisions={"ch": decision},
        )
        self.assertEqual(targets["ch"].elementary_flow_uuid, "bwf-water")
        self.assertEqual(basis_of["ch"], BY_DECISION)
        self.assertEqual(declined, {})

    def test_what_is_handed_in_is_what_is_applied(self):
        """*set_aside* given explicitly is used as given, so the pipeline can
        count the rule's rows apart from the curated declines."""
        targets, _basis, _findings, declined = substance_targets(
            self.source,
            index=substance_index(self.db),
            outstanding={"ch", "generic"},
            decisions={},
            set_aside={},
        )
        self.assertEqual(set(targets), {"ch", "generic"})
        self.assertEqual(declined, {})


if __name__ == "__main__":
    unittest.main()
