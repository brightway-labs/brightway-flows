"""A name can reach one substance and name another, and that splits it.

#74 asked for a check, because the failure it describes is invisible until a
second list happens to ship the same string and nothing about the first list's
run says it will.  The failure: the merge placed a row on a flow object by a
correspondence table, a registry number or a curated override, and none of those
leaves the row's name on the object.  So the name reaches that substance and is
published nowhere on it, and the next list carrying it mints the substance
again.

These assert what the check counts as a finding and, as much as anything, what
it *refuses* to count -- a metal and its ion share a name and are two things,
and a check that reported every such pair would be read as noise and then not
read at all.

Built against small hand-written databases rather than a real run: the shapes
being tested are one row of `merge_outcomes` against one row of `flow_objects`,
and a fixture that says so is the whole of what a reader needs.
"""

import sqlite3
import tempfile
import unittest

from pathlib import Path

import orjson

from brightway_flows.curation.unreachable_names import (
    PLACING_OUTCOMES,
    FlowObjectNames,
    read_flow_object_names,
    told_apart,
    unreachable_names,
)
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMINF_EC_NUMBER,
)
from brightway_flows.merge.store import Outcome

RUN = "run-1"


def _classifications(*cas, ec=()):
    row = {}
    if cas:
        row[CHEMINF_CAS_REGISTRY_NUMBER] = {"@value": list(cas)}
    if ec:
        row[CHEMINF_EC_NUMBER] = {"@value": list(ec)}
    return row


class _DatabaseTestCase(unittest.TestCase):
    """A database holding only the two tables the check reads."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.path = Path(self._directory.name) / "consensus-flows.sqlite3"

    def write(self, *, objects, outcomes, run=RUN):
        """*objects* as (id, prefLabel, altLabels, classifications, qualifier)."""
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "CREATE TABLE merge_runs (run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE flow_objects (flow_object_id TEXT PRIMARY KEY, "
                "pref_label_value TEXT, alt_label_json TEXT, "
                "classifications_json TEXT, origin_qualifier TEXT)"
            )
            connection.execute(
                "CREATE TABLE merge_outcomes (run_id TEXT, list_name TEXT, "
                "list_version TEXT, source_uuid TEXT, outcome TEXT, source_name TEXT, "
                "source_context_json TEXT, source_unit TEXT, source_cas TEXT, "
                "source_ec TEXT, reason TEXT, flow_object_id TEXT, "
                "target_elementary_flow_id TEXT, basis TEXT, basis_value TEXT, "
                "matching_method TEXT, has_flow_object_candidates INTEGER, "
                "has_context_inconsistency INTEGER DEFAULT 0, "
                "has_unit_mismatch INTEGER DEFAULT 0, detail_json TEXT)"
            )
            connection.execute(
                "INSERT INTO merge_runs VALUES (?, ?)", (run, "2026-08-14T00:00:00+00:00")
            )
            connection.executemany(
                "INSERT INTO flow_objects VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        object_id,
                        pref,
                        orjson.dumps([{"@value": v} for v in alt]).decode(),
                        orjson.dumps(classifications).decode(),
                        qualifier,
                    )
                    for object_id, pref, alt, classifications, qualifier in objects
                ],
            )
            connection.executemany(
                "INSERT INTO merge_outcomes (run_id, list_name, list_version, "
                "source_uuid, outcome, source_name, flow_object_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (run, list_name, "1", uuid, str(outcome), name, object_id)
                    for list_name, uuid, outcome, name, object_id in outcomes
                ],
            )
            connection.commit()
        finally:
            connection.close()
        return self.path


class WhatCountsAsASplitTestCase(_DatabaseTestCase):
    """#74's own case, reduced to the two rows that produce it.

    ecoinvent's `Energy, gross calorific value, in biomass` is placed by a
    correspondence table on the object EF 3.1 publishes as `Biomass`; BAFU's
    identical string reached nothing and became an object of its own.  Neither
    side carries a registry number, so nothing but the two names was ever going
    to bring them together.
    """

    NAME = "Energy, gross calorific value, in biomass"

    def _biomass(self, **overrides):
        objects = overrides.pop("objects", [
            ("fo-biomass", "Biomass", [], {}, ""),
            ("fo-dup", self.NAME, [], {}, ""),
        ])
        outcomes = overrides.pop("outcomes", [
            ("ecoinvent", "u-1", Outcome.PREPARED, self.NAME, "fo-biomass"),
        ])
        return unreachable_names(self.write(objects=objects, outcomes=outcomes))

    def test_a_name_that_reaches_one_object_and_names_another_is_reported(self):
        findings = self._biomass()
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].name, self.NAME)
        self.assertEqual(findings[0].placed_on, ["fo-biomass"])
        self.assertEqual(findings[0].placed_on_labels, ["Biomass"])
        self.assertEqual(findings[0].names, ["fo-dup"])
        self.assertEqual(findings[0].decided_by, ["ecoinvent 1/prepared"])
        self.assertEqual(findings[0].row_count, 1)

    def test_publishing_the_name_on_the_object_is_the_whole_fix(self):
        """An alternative label counts, which is what makes it reachable.

        The check and the merge's label index read the same two fields, so a
        name this stops reporting is a name the next list will match on.
        """
        self.assertEqual(self._biomass(objects=[
            ("fo-biomass", "Biomass", [self.NAME], {}, ""),
            ("fo-dup", self.NAME, [], {}, ""),
        ]), [])

    def test_a_name_reachable_where_it_was_placed_is_not_a_finding(self):
        """Matched on its own name, so nothing was lost on the way in."""
        self.assertEqual(self._biomass(objects=[
            ("fo-biomass", self.NAME, [], {}, ""),
            ("fo-dup", "Something Else", [], {}, ""),
        ]), [])

    def test_an_unreachable_name_that_names_nothing_yet_is_not_a_finding(self):
        """The cost is the split, and until a second list ships it there is none.

        Reporting every unreachable name instead would put 757 rows of one run
        in front of a reader to find the 129 that have already cost something.
        """
        self.assertEqual(self._biomass(objects=[
            ("fo-biomass", "Biomass", [], {}, ""),
        ]), [])

    def test_case_and_spacing_do_not_make_two_names(self):
        """`canonical_label_value`, as everywhere else labels are compared."""
        findings = self._biomass(outcomes=[
            ("ecoinvent", "u-1", Outcome.PREPARED, "Energy,  Gross Calorific Value, In Biomass",
             "fo-biomass"),
        ])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].names, ["fo-dup"])

    def test_the_spelling_reported_is_the_one_a_source_list_shipped(self):
        """A curator has to search for it, so it is not the canonical key."""
        findings = self._biomass(outcomes=[
            ("ecoinvent", "u-1", Outcome.PREPARED, "Energy, Gross Calorific Value, In Biomass",
             "fo-biomass"),
        ])
        self.assertEqual(findings[0].name, "Energy, Gross Calorific Value, In Biomass")

    def test_rows_are_counted_and_ordered_by_how_much_they_carry(self):
        """Three contexts of one name is a bigger split than one of another."""
        findings = self._biomass(
            objects=[
                ("fo-biomass", "Biomass", [], {}, ""),
                ("fo-dup", self.NAME, [], {}, ""),
                ("fo-heat", "Waste Heat", [], {}, ""),
                ("fo-heat-dup", "Heat, waste", [], {}, ""),
            ],
            outcomes=[
                ("ecoinvent", "u-1", Outcome.PREPARED, self.NAME, "fo-biomass"),
                ("ecoinvent", "u-2", Outcome.PREPARED, self.NAME, "fo-biomass"),
                ("ecoinvent", "u-3", Outcome.PREPARED, self.NAME, "fo-biomass"),
                ("ecoinvent", "u-4", Outcome.PREPARED, "Heat, waste", "fo-heat"),
            ],
        )
        self.assertEqual([(f.name, f.row_count) for f in findings],
                         [(self.NAME, 3), ("Heat, waste", 1)])

    def test_a_created_row_places_nothing_and_is_not_read(self):
        """It is the *result* of the split, not an assertion about a name.

        Reading it would report the duplicate object as having failed to reach
        itself.
        """
        self.assertEqual(self._biomass(outcomes=[
            ("bafu", "u-2", Outcome.CREATED, self.NAME, "fo-dup"),
        ]), [])

    def test_the_outcomes_read_are_the_ones_that_place_a_row(self):
        """Stated as a set so a new outcome has to be ruled on rather than dropped."""
        self.assertEqual(
            PLACING_OUTCOMES,
            frozenset(Outcome) - {Outcome.CREATED, Outcome.UNMATCHED},
        )

    def test_a_database_with_no_merge_run_reports_nothing(self):
        connection = sqlite3.connect(self.path)
        connection.execute("CREATE TABLE flow_objects (flow_object_id TEXT PRIMARY KEY)")
        connection.commit()
        connection.close()
        self.assertEqual(unreachable_names(self.path), [])


class WhatIsAlreadyTwoSubstancesTestCase(_DatabaseTestCase):
    """One name over two objects is not always one substance published twice.

    `Aluminium` names the metal in ordinary speech and the ion in a water
    analysis, and this list keeps them apart on purpose.  A check that reported
    every such pair would be mostly ions, so a pair is dropped when the list
    already separates the two by something other than the name.
    """

    def _findings(self, left, right):
        return unreachable_names(self.write(
            objects=[("fo-left", "Aluminium", [], *left),
                     ("fo-right", "Aluminium, Ion", [], *right)],
            outcomes=[("bafu", "u-1", Outcome.ALGORITHM, "Aluminium, Ion", "fo-left")],
        ))

    def test_two_registry_numbers_that_share_nothing_settle_it(self):
        self.assertEqual(
            self._findings((_classifications("7429-90-5"), ""),
                           (_classifications("22537-23-1"), "")),
            [],
        )

    def test_an_ec_number_separates_as_a_cas_does(self):
        """The question is whether *some* number tells them apart."""
        self.assertEqual(
            self._findings((_classifications(ec=("231-072-3",)), ""),
                           (_classifications(ec=("922-679-8",)), "")),
            [],
        )

    def test_a_shared_number_does_not_separate_them(self):
        """The same substance under two names is exactly the case being hunted."""
        self.assertEqual(
            len(self._findings((_classifications("7429-90-5"), ""),
                               (_classifications("7429-90-5"), ""))),
            1,
        )

    def test_a_number_on_only_one_side_does_not_separate_them(self):
        """Missing evidence is not evidence: `Biomass` carries no number at all."""
        self.assertEqual(
            len(self._findings((_classifications("7429-90-5"), ""), ({}, ""))),
            1,
        )

    def test_two_origin_qualifiers_settle_it(self):
        """Fossil against biogenic is the axis `qualifiers` exists for."""
        self.assertEqual(
            self._findings((_classifications("124-38-9"), "fossil"),
                           (_classifications("124-38-9"), "biogenic")),
            [],
        )

    def test_the_test_is_stated_over_the_pair_and_not_the_row(self):
        """`told_apart` is the whole rule, and reads only the two objects."""
        metal = FlowObjectNames("fo-left", "Aluminium", frozenset({"aluminium"}),
                                frozenset({"7429-90-5"}), "")
        ion = FlowObjectNames("fo-right", "Aluminium, Ion", frozenset({"aluminium, ion"}),
                              frozenset({"22537-23-1"}), "")
        self.assertTrue(told_apart(metal, ion))
        self.assertFalse(told_apart(metal, metal))


class ReadingTheObjectsTestCase(_DatabaseTestCase):
    """`read_flow_object_names` reads the two label fields the merge indexes."""

    def test_preferred_and_alternative_labels_are_both_names(self):
        path = self.write(
            objects=[("fo-1", "Biomass", ["Energy, gross calorific value, in biomass"],
                      _classifications("7732-18-5"), "fossil")],
            outcomes=[],
        )
        entry = read_flow_object_names(path)["fo-1"]
        self.assertEqual(entry.pref_label, "Biomass")
        self.assertEqual(
            entry.labels,
            frozenset({"biomass", "energy, gross calorific value, in biomass"}),
        )
        self.assertEqual(entry.identifiers, frozenset({"7732-18-5"}))
        self.assertEqual(entry.origin_qualifier, "fossil")

    def test_an_object_with_no_label_carries_no_names(self):
        path = self.write(objects=[("fo-1", "", [], {}, "")], outcomes=[])
        self.assertEqual(read_flow_object_names(path)["fo-1"].labels, frozenset())


if __name__ == "__main__":
    unittest.main()
