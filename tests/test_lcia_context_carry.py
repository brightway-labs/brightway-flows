"""The context convention is read whole, checked against the vocabulary, and
refuses what it cannot vouch for.

The file says which neighbour's number a blank takes.  What these tests hold it
to is the part a reader cannot see: every context it names is one of ours, the
display name beside each IRI is that IRI's, no rule names a wall or itself, and
the decisions of 2026-09-01 are the ones written down -- silvicultural soil from
non-agricultural then unspecified, a river from surface water then unspecified,
the unconfined aquifer and agricultural soil from nobody.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from brightway_flows.lcia.context_carry import (
    CONTEXT_CARRY_RULES_FILEPATH,
    CarryDirection,
    ContextCarryRuleError,
    load_context_carry_rules,
)

CTX = "https://vocab.brightway.one/flow-contexts/"
SILVI = ("Environmental → Ground → Silvicultural", CTX + "envi-grou-silv")
NOAG = ("Environmental → Ground → Non-agricultural", CTX + "envi-grou-noag")
UNKNOWN_SOIL = ("Environmental → Ground → Unknown", CTX + "envi-grou-unkn")
LONG_TERM_AIR = ("Environmental → Air → Long-term", CTX + "envi-air-lote")


def _rule(recipient, *donors, comment="because"):
    return {
        "recipient": recipient[0],
        "recipient_iri": recipient[1],
        "donors": [donor[0] for donor in donors],
        "donor_iris": [donor[1] for donor in donors],
        "comment": comment,
    }


def _document(**overrides):
    document = {
        "schema_version": 1,
        "walls": [{"context": LONG_TERM_AIR[0], "context_iri": LONG_TERM_AIR[1], "comment": "zero"}],
        "downward": [_rule(SILVI, NOAG, UNKNOWN_SOIL)],
        "upward": [_rule(UNKNOWN_SOIL, SILVI, NOAG)],
    }
    document.update(overrides)
    return document


class LoadingTest(unittest.TestCase):
    def _load(self, document):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            path.write_text(json.dumps(document))
            return load_context_carry_rules(path)

    def test_a_well_formed_file_reads_as_records(self):
        rules = self._load(_document())
        self.assertEqual([wall.context for wall in rules.walls], [LONG_TERM_AIR[0]])
        (down,) = rules.downward
        self.assertEqual(down.direction, CarryDirection.DOWNWARD)
        self.assertEqual(down.recipient_iri, SILVI[1])
        self.assertEqual(down.donor_iris, (NOAG[1], UNKNOWN_SOIL[1]))
        self.assertEqual(down.rule_id, "downward:envi-grou-silv")
        self.assertEqual([rule.direction for rule in rules.rules], [CarryDirection.DOWNWARD, CarryDirection.UPWARD])

    def test_an_unknown_context_is_refused(self):
        bad = ("Environmental → Ground → Mars", CTX + "envi-grou-mars")
        with self.assertRaisesRegex(ContextCarryRuleError, "not a context"):
            self._load(_document(downward=[_rule(bad, UNKNOWN_SOIL)]))

    def test_a_display_name_that_is_not_the_iris_is_refused(self):
        mislabelled = ("Environmental → Ground → Industrial", SILVI[1])
        with self.assertRaisesRegex(ContextCarryRuleError, "calls it"):
            self._load(_document(downward=[_rule(mislabelled, UNKNOWN_SOIL)]))

    def test_a_rule_may_not_name_a_wall(self):
        with self.assertRaisesRegex(ContextCarryRuleError, "is a wall"):
            self._load(_document(downward=[_rule(SILVI, LONG_TERM_AIR)]))
        with self.assertRaisesRegex(ContextCarryRuleError, "is a wall"):
            self._load(_document(downward=[_rule(LONG_TERM_AIR, UNKNOWN_SOIL)]))

    def test_a_recipient_is_not_its_own_donor_and_has_one_rule(self):
        with self.assertRaisesRegex(ContextCarryRuleError, "its own donor"):
            self._load(_document(downward=[_rule(SILVI, SILVI)]))
        with self.assertRaisesRegex(ContextCarryRuleError, "two rules"):
            self._load(_document(downward=[_rule(SILVI, NOAG), _rule(SILVI, UNKNOWN_SOIL)]))

    def test_a_comment_is_required(self):
        with self.assertRaisesRegex(ContextCarryRuleError, "comment is required"):
            self._load(_document(downward=[_rule(SILVI, NOAG, comment="")]))

    def test_the_schema_version_is_read(self):
        with self.assertRaisesRegex(ContextCarryRuleError, "schema_version"):
            self._load(_document(schema_version=2))


class TheCuratedFileTest(unittest.TestCase):
    """The decisions of 2026-09-01, as data."""

    @classmethod
    def setUpClass(cls):
        cls.rules = load_context_carry_rules()
        cls.down = {rule.recipient: rule for rule in cls.rules.downward}
        cls.up = {rule.recipient: rule for rule in cls.rules.upward}

    def test_it_is_the_shipped_file(self):
        self.assertTrue(CONTEXT_CARRY_RULES_FILEPATH.exists())

    def test_the_walls(self):
        self.assertEqual(
            {wall.context for wall in self.rules.walls},
            {
                "Environmental → Air → Long-term",
                "Environmental → Water → Long-term",
                "Environmental → Air → Indoor",
                "Environmental → Water → Ocean",
                "Resource → Water → Ocean",
            },
        )

    def test_the_soils(self):
        for recipient in ("Silvicultural", "Industrial"):
            self.assertEqual(
                self.down[f"Environmental → Ground → {recipient}"].donors,
                ("Environmental → Ground → Non-agricultural", "Environmental → Ground → Unknown"),
            )
        self.assertEqual(
            self.down["Environmental → Ground → Non-agricultural"].donors,
            ("Environmental → Ground → Unknown",),
        )
        self.assertNotIn("Environmental → Ground → Agricultural", self.down)

    def test_the_waters(self):
        for recipient in ("River", "Lake"):
            self.assertEqual(
                self.down[f"Environmental → Water → {recipient}"].donors,
                ("Environmental → Water → Surface water", "Environmental → Water → Unknown"),
            )
        self.assertEqual(
            self.down["Environmental → Water → Surface water"].donors,
            ("Environmental → Water → Unknown",),
        )
        for left_blank in ("Unconfined aquifer", "Confined aquifer with fossil groundwater"):
            self.assertNotIn(f"Environmental → Water → {left_blank}", self.down)

    def test_the_air(self):
        rural = "Environmental → Air → Medium stack, <150 meters → Rural (<1000 people/square mile)"
        urban = "Environmental → Air → Ground level → Urban (>1000 people/square mile)"
        unknown = "Environmental → Air → Unknown"
        self.assertEqual(self.down[rural].donors, (unknown,))
        self.assertEqual(self.down[urban].donors, (unknown,))
        self.assertNotIn("Environmental → Air → Aircraft cruise height", self.down)
        follows_density = "Environmental → Air → Low stack, <25 meters → Urban (>1000 people/square mile)"
        self.assertEqual(self.down[follows_density].donors, (urban, unknown))
        behaves_as_rural = "Environmental → Air → High stack, >150 meters → Urban (>1000 people/square mile)"
        self.assertEqual(self.down[behaves_as_rural].donors, (rural, unknown))
        self.assertEqual(len([r for r in self.rules.downward if r.recipient.startswith("Environmental → Air")]), 8)

    def test_every_parent_takes_its_children_upward(self):
        """The four class roots, and surface water -- the one parent below a
        root, so that a river-only number can climb at all."""
        self.assertEqual(
            set(self.up),
            {
                "Environmental → Ground → Unknown",
                "Environmental → Water → Unknown",
                "Environmental → Water → Surface water",
                "Environmental → Air → Unknown",
                "Resource → Water → Unknown",
            },
        )
        self.assertEqual(
            self.up["Environmental → Water → Surface water"].donors,
            ("Environmental → Water → River", "Environmental → Water → Lake"),
        )
        for rule in self.rules.upward:
            self.assertIs(rule.direction, CarryDirection.UPWARD)
            for donor in rule.donors:
                self.assertNotIn(donor, {wall.context for wall in self.rules.walls})


if __name__ == "__main__":
    unittest.main()
