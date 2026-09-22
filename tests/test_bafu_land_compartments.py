"""#66 §1.9: BAFU files land rows in three compartments, and two of them are mixed.

A fifth of BAFU's land-named rows are not in `resources / land`:

    resources / land          123 land rows   (and 4 that are not land)
    resources / unspecified    26 land rows   among 42
    resources / in ground       3 land rows   among 164

Filed as they arrive, those 29 reach `Resource → Ground` instead of the land
dimension. Fifteen land classes therefore arrive twice, by two routes, one of
them as a resource -- which is what mistypes `Occupation, Forest, Unspecified`
as a class of molecules (§1.1): `classify` rule 7 declines to call an object
non-chemical unless *every* context it occurs in is, and `Resource` deliberately
is not.

#52 built the mechanism for this. What it did not have to handle is a **mixed**
compartment: every flow in ecoinvent's `natural resource / land` is a land flow,
so its rules partition it. BAFU's two are 177 ordinary resources with 29 land
rows among them, so the rules there have to *select* rather than partition --
see `UNMATCHED_SELECT`.
"""

import json
import unittest

from brightway_flows.context_mapping import (
    MANUAL_MAPPING_FILEPATH,
    UNMATCHED_PARTITION,
    UNMATCHED_SELECT,
    AmbiguousSourceContextError,
    ContextNameRuleError,
    NamePrefixRule,
    context_iri_by_source_context,
    name_prefix_context_iri,
    name_prefix_unmatched_policy,
)

BAFU = "bafu-2026-v1"
OCCUPATION = "https://vocab.brightway.one/flow-contexts/laus-occu"
TRANSFORMATION = "https://vocab.brightway.one/flow-contexts/laus-tran"
GROUND = "https://vocab.brightway.one/flow-contexts/reso-grou"

MIXED = (["resources", "unspecified"], ["resources", "in ground"])


class RoutingTestCase(unittest.TestCase):
    def test_a_land_name_reaches_the_land_dimension_from_any_compartment(self):
        for compartment in (*MIXED, ["resources", "land"]):
            for name, expected in (
                ("Occupation, forest, extensive", OCCUPATION),
                ("Transformation, to annual crop, irrigated", TRANSFORMATION),
                ("Transformation, from unspecified, used", TRANSFORMATION),
            ):
                with self.subTest(compartment=compartment, name=name):
                    self.assertEqual(
                        name_prefix_context_iri(BAFU, name, compartment), expected
                    )

    def test_an_ordinary_resource_in_a_mixed_compartment_is_left_alone(self):
        """The 177 rows the compartment rule already decides correctly.

        Under `partition` every one of these would raise, which is why the
        policy exists rather than the rules simply being added.
        """
        for compartment in MIXED:
            for name in ("Uranium", "Energy, from oil", "Barite", "Iridium"):
                with self.subTest(compartment=compartment, name=name):
                    self.assertIsNone(
                        name_prefix_context_iri(BAFU, name, compartment)
                    )

    def test_the_mixed_compartments_still_send_their_other_rows_to_ground(self):
        mapping = context_iri_by_source_context(BAFU)
        for compartment in MIXED:
            with self.subTest(compartment=compartment):
                self.assertEqual(mapping[tuple(compartment)], GROUND)


class PolicyTestCase(unittest.TestCase):
    def test_the_land_compartment_still_partitions(self):
        """`resources / land` maps to `laus-occu`, so a name that falls through
        is filed as a land occupation. For `Uranium` that would be wrong in
        exactly the way #52 was wrong, so the strict policy is right here."""
        policy = name_prefix_unmatched_policy(BAFU)
        self.assertEqual(policy[("resources", "land")], UNMATCHED_PARTITION)
        self.assertEqual(
            context_iri_by_source_context(BAFU)[("resources", "land")], OCCUPATION
        )

    def test_the_mixed_compartments_select(self):
        policy = name_prefix_unmatched_policy(BAFU)
        for compartment in MIXED:
            with self.subTest(compartment=compartment):
                self.assertEqual(policy[tuple(compartment)], UNMATCHED_SELECT)

    def test_ecoinvents_land_compartment_is_untouched(self):
        """#52's case keeps the default, and the default is the strict one."""
        for version in ("3.8", "3.9.1", "3.10.1", "3.11", "3.12"):
            policy = name_prefix_unmatched_policy(f"ecoinvent-{version}")
            with self.subTest(version=version):
                self.assertEqual(
                    policy[("natural resource", "land")], UNMATCHED_PARTITION
                )

    def test_a_partitioning_compartment_still_raises_on_an_unread_name(self):
        with self.assertRaises(AmbiguousSourceContextError):
            name_prefix_context_iri(BAFU, "Uranium", ["resources", "land"])

    def test_an_unknown_policy_is_an_error(self):
        rows = json.loads(MANUAL_MAPPING_FILEPATH.read_bytes())
        for row in rows["name_prefix_context_mappings"]:
            with self.subTest(prefix=row["name_prefix"]):
                self.assertIn(
                    row.get("unmatched", UNMATCHED_PARTITION),
                    (UNMATCHED_PARTITION, UNMATCHED_SELECT),
                )

    def test_rows_of_one_compartment_must_agree_about_the_policy(self):
        """It describes the compartment, so file order must not decide it."""
        import brightway_flows.context_mapping as module

        original = module._load_name_rows
        rows = (
            NamePrefixRule(
                source="made-up",
                source_context=("a", "b"),
                name_prefix="one, ",
                context_iri=OCCUPATION,
                comment="x",
                unmatched=UNMATCHED_SELECT,
            ),
            NamePrefixRule(
                source="made-up",
                source_context=("a", "b"),
                name_prefix="two, ",
                context_iri=OCCUPATION,
                comment="x",
                unmatched=UNMATCHED_PARTITION,
            ),
        )
        module._load_name_rows = lambda: rows
        name_prefix_unmatched_policy.cache_clear()
        try:
            with self.assertRaises(ContextNameRuleError):
                name_prefix_unmatched_policy("made-up")
        finally:
            module._load_name_rows = original
            name_prefix_unmatched_policy.cache_clear()


class AgainstTheFetchedListTestCase(unittest.TestCase):
    """Against BAFU's real rows, which is where §1.9 was measured."""

    @classmethod
    def setUpClass(cls):
        from brightway_flows.sources import known_source_lists

        source = known_source_lists()[BAFU]
        if not source.flows_path.exists():
            raise unittest.SkipTest(
                f"{source.flows_path.name} not present; run "
                f"`{source.fetch_command}`"
            )
        cls.flows = json.loads(source.flows_path.read_bytes())

    def _land_rows(self):
        return [
            flow
            for flow in self.flows
            if flow["name"].lower().startswith(("occupation", "transformation"))
        ]

    def test_every_land_named_row_reaches_the_land_dimension(self):
        for flow in self._land_rows():
            with self.subTest(name=flow["name"], context=flow["context"]):
                self.assertIn(
                    name_prefix_context_iri(BAFU, flow["name"], flow["context"]),
                    (OCCUPATION, TRANSFORMATION),
                )

    def test_no_ordinary_resource_is_dragged_into_the_land_dimension(self):
        for flow in self.flows:
            if flow["name"].lower().startswith(("occupation", "transformation")):
                continue
            if tuple(flow["context"]) not in {tuple(c) for c in MIXED}:
                continue
            with self.subTest(name=flow["name"]):
                self.assertIsNone(
                    name_prefix_context_iri(BAFU, flow["name"], flow["context"])
                )


if __name__ == "__main__":
    unittest.main()
