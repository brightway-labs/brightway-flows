"""A compartment is the wrong granularity for land use.

ecoinvent files land occupation and land transformation in one compartment,
`natural resource / land`, and says which is which in the flow name:
`Occupation, annual crop` against `Transformation, from annual crop`.  Our
vocabulary has both -- `laus-occu` and `laus-tran` -- and they are siblings, not
a general and a specific, so the compartment rule had to choose one and be wrong
about the other.  It chose occupation, and was wrong about the 122
transformation flows of every registered version (#52).

`name_prefix_context_mappings` is how the name reaches the context: a prefix per
half of the compartment, five versions, ten rows.  The correspondence table to
EF 3.1 is a second, independent reading of the same names, and the last case
here checks ours against it.
"""

import unittest
from pathlib import Path

import orjson

from brightway_flows.context_mapping import (
    AmbiguousSourceContextError,
    ContextNameRuleError,
    MANUAL_MAPPING_FILEPATH,
    context_iri_by_source_context,
    name_prefix_context_iri,
    name_prefix_context_rules,
)
from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.sources import known_source_lists

PREFIX = "https://vocab.brightway.one/flow-contexts/"
OCCUPATION = PREFIX + "laus-occu"
TRANSFORMATION = PREFIX + "laus-tran"
LAND = ["natural resource", "land"]
EF = "EF 3.1"

REGISTERED_ECOINVENT = (
    "ecoinvent-3.8",
    "ecoinvent-3.9.1",
    "ecoinvent-3.10.1",
    "ecoinvent-3.11",
    "ecoinvent-3.12",
)



def _land_rows():
    """Every land-use split rule, whatever the vendor calls the compartment.

    Selected by what the rule *does* -- it sends a name to a land context --
    rather than by the compartment it reads, and the reason is that the
    compartment keeps turning out not to be the thing the lists share.  `LAND`
    is ecoinvent's spelling and stays that way in the tests above, which are
    about ecoinvent's own flows.  BAFU files the same distinction under
    `resources / land`, and selecting on ecoinvent's literal made its two rows
    invisible here while the registry check below went on passing.  Stepwise
    2006 has no land compartment at all: it is a SimaPro method file, so the
    land class is in the name and the rows sit in `Raw / (unspecified)` among
    the ores -- which the previous selector, keyed on a compartment ending in
    `land`, could not see either.
    """
    payload = orjson.loads(MANUAL_MAPPING_FILEPATH.read_bytes())
    return [
        row
        for row in payload["name_prefix_context_mappings"]
        if row.get("context_iri") in (OCCUPATION, TRANSFORMATION)
    ]


class TheNameDecidesTestCase(unittest.TestCase):
    def test_a_transformation_flow_is_a_transformation_in_every_version(self):
        for source in REGISTERED_ECOINVENT:
            with self.subTest(source=source):
                self.assertEqual(
                    name_prefix_context_iri(
                        source, "Transformation, from annual crop", LAND
                    ),
                    TRANSFORMATION,
                )

    def test_an_occupation_flow_is_an_occupation_in_every_version(self):
        for source in REGISTERED_ECOINVENT:
            with self.subTest(source=source):
                self.assertEqual(
                    name_prefix_context_iri(source, "Occupation, annual crop", LAND),
                    OCCUPATION,
                )

    def test_the_compartment_rule_still_says_occupation(self):
        """Which is the half of the defect a name rule does not remove: the
        compartment declaration is what a list needs to be mergeable at all, and
        it can only name one of the two."""
        for source in REGISTERED_ECOINVENT:
            with self.subTest(source=source):
                self.assertEqual(
                    context_iri_by_source_context(source)[tuple(LAND)], OCCUPATION
                )

    def test_a_compartment_with_no_rules_is_left_to_its_own_rule(self):
        """None, not a raise: this is every compartment but the land one."""
        self.assertIsNone(
            name_prefix_context_iri("ecoinvent-3.11", "Water, lake", ["natural resource", "in water"])
        )
        self.assertIsNone(name_prefix_context_iri(EF, "lake water", ["Resources"]))

    def test_a_name_no_rule_recognises_raises_rather_than_defaulting(self):
        """Falling through is #52: the compartment rule says occupation, so a
        land flow nobody read would be filed as one with nothing said."""
        with self.assertRaises(AmbiguousSourceContextError) as caught:
            name_prefix_context_iri("ecoinvent-3.11", "Land use change, forest", LAND)
        message = str(caught.exception)
        self.assertIn("Land use change, forest", message)
        self.assertIn("name_prefix_context_mappings", message)

    def test_a_flow_with_no_name_left_raises_too(self):
        """An empty name cannot decide, and the compartment must not decide for
        it."""
        with self.assertRaises(AmbiguousSourceContextError):
            name_prefix_context_iri("ecoinvent-3.11", "", LAND)

    def test_a_rewritten_context_is_not_a_compartment(self):
        """The transform is re-entrant and sees its own output: after one pass
        `flow.context` is a consensus dict, which is not a key to look up."""
        rewritten = {"dimension": "Land Use", "land_use": "Occupation"}
        self.assertIsNone(
            name_prefix_context_iri("ecoinvent-3.11", "Occupation, annual crop", rewritten)
        )
        self.assertIsNone(name_prefix_context_iri("ecoinvent-3.11", "x", []))
        self.assertIsNone(name_prefix_context_iri("ecoinvent-3.11", "x", None))


class TheRowsTestCase(unittest.TestCase):
    def test_every_registered_version_carries_both_halves(self):
        """One version left out is that version's transformation flows filed as
        occupations, which is the state this fixes."""
        for source in REGISTERED_ECOINVENT:
            with self.subTest(source=source):
                rules = name_prefix_context_rules(source)[tuple(LAND)]
                self.assertEqual(
                    dict(rules),
                    {"occupation,": OCCUPATION, "transformation,": TRANSFORMATION},
                )

    def test_the_rows_are_the_registry_and_nothing_else(self):
        sources = {row["source"] for row in _land_rows()}
        self.assertEqual(sources, set(known_source_lists()))

    def test_every_row_says_why(self):
        for row in _land_rows():
            with self.subTest(source=row["source"], prefix=row["name_prefix"]):
                self.assertTrue(str(row.get("comment") or "").strip())

    def test_a_row_missing_a_field_is_an_error_not_a_skip(self):
        from brightway_flows import context_mapping

        bad = {
            "default_context_mappings": [],
            "name_prefix_context_mappings": [
                {
                    "source": "test-list",
                    "source_context": LAND,
                    "name_prefix": "Occupation, ",
                    "context_iri": OCCUPATION,
                }
            ],
        }
        with self._file_holding(bad):
            with self.assertRaises(ContextNameRuleError) as caught:
                context_mapping.name_prefix_context_rules("test-list")
            self.assertIn("comment", str(caught.exception))

    def test_two_rows_for_one_prefix_are_an_error_not_a_last_wins(self):
        from brightway_flows import context_mapping

        row = {
            "source": "test-list",
            "source_context": LAND,
            "name_prefix": "Occupation, ",
            "context_iri": OCCUPATION,
            "comment": "why",
        }
        bad = {
            "default_context_mappings": [],
            "name_prefix_context_mappings": [row, {**row, "context_iri": TRANSFORMATION}],
        }
        with self._file_holding(bad):
            with self.assertRaises(ContextNameRuleError) as caught:
                context_mapping.name_prefix_context_rules("test-list")
            self.assertIn("One prefix, one rule", str(caught.exception))

    def test_the_longer_prefix_is_tested_first(self):
        """Where one prefix contains another, file order must not decide."""
        from brightway_flows import context_mapping

        payload = {
            "default_context_mappings": [],
            "name_prefix_context_mappings": [
                {
                    "source": "test-list",
                    "source_context": LAND,
                    "name_prefix": "Occupation",
                    "context_iri": OCCUPATION,
                    "comment": "why",
                },
                {
                    "source": "test-list",
                    "source_context": LAND,
                    "name_prefix": "Occupation, permanent crop",
                    "context_iri": TRANSFORMATION,
                    "comment": "why",
                },
            ],
        }
        with self._file_holding(payload):
            self.assertEqual(
                context_mapping.name_prefix_context_iri(
                    "test-list", "Occupation, permanent crop, irrigated", LAND
                ),
                TRANSFORMATION,
            )

    def _file_holding(self, payload):
        """Point the loader at *payload* for the duration of a `with` block."""
        import contextlib
        import tempfile
        from brightway_flows import context_mapping

        @contextlib.contextmanager
        def _swap():
            original = context_mapping.MANUAL_MAPPING_FILEPATH
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "mapping.json"
                path.write_bytes(orjson.dumps(payload))
                context_mapping.MANUAL_MAPPING_FILEPATH = path
                context_mapping._load_name_rows.cache_clear()
                context_mapping.name_prefix_context_rules.cache_clear()
                try:
                    yield
                finally:
                    context_mapping.MANUAL_MAPPING_FILEPATH = original
                    context_mapping._load_name_rows.cache_clear()
                    context_mapping.name_prefix_context_rules.cache_clear()

        return _swap()


class ThroughTheMergeTestCase(unittest.TestCase):
    """`ContextExpectations` is what the merge places rows with."""

    def _expectations(self, source="ecoinvent-3.11"):
        return ContextExpectations(
            _by_source_context=dict(context_iri_by_source_context(source)),
            _source_label=source,
        )

    def test_the_name_beats_the_compartment(self):
        expectations = self._expectations()
        self.assertEqual(
            expectations.resolve(
                "3e5d9b8f-0000-0000-0000-000000000000",
                LAND,
                "Transformation, from annual crop",
            ),
            TRANSFORMATION,
        )
        self.assertEqual(
            expectations.resolve(
                "3e5d9b8f-0000-0000-0000-000000000001", LAND, "Occupation, annual crop"
            ),
            OCCUPATION,
        )

    def test_a_row_the_rules_cannot_place_stops_the_merge(self):
        with self.assertRaises(AmbiguousSourceContextError):
            self._expectations().resolve("some-uuid", LAND, "Land use change, forest")


# `AgainstTheCorrespondenceTableTestCase` cross-checked the name rule against
# the composed 3.8 table -- a second opinion arrived at independently, which
# caught #52 (ours said occupation for all 182 rows, theirs transformation
# for 122).  The table went to git history with #141's last follow-up, and a
# frozen file stopped being a second opinion the day it stopped being
# maintained: the name rule's guards are the per-version sweeps above, which
# test the rule against every release's own rows rather than against one
# table's reading of 3.8's.


if __name__ == "__main__":
    unittest.main()
