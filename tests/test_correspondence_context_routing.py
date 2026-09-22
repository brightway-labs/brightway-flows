"""
A correspondence row's target context must mean what its source context means.

The ecoinvent-to-EF tables are curated -- GLAD's mappings plus algorithmic and
manual matches -- and nothing checked their target contexts.  A name-match layer
that did not constrain the long-term axis pointed 66 ordinary-groundwater rows at
EF's long-term water flow, which EF characterises as zero for all four USEtox
categories (#48).  Reading both contexts through our own vocabulary is what
catches it: `envi-wate-unaq` is not `envi-wate-lote`.

Plain IRI equality is too strict -- most disagreements are correct coarsening,
because EF has no forestry soil and no groundwater -- so the guard is equality
plus a file of permitted coarsenings, and `known_violations` is a ratchet over
what survives both.
"""

import unittest

from brightway_flows.context_mapping import (
    context_iri_by_source_context,
    normalize_context_key,
)
from brightway_flows.correspondence_contexts import (
    ContextRoutingViolation,
    audit_correspondence_contexts,
    known_violations,
    permitted_coarsenings,
    publishable_coarsenings,
)
from brightway_flows.sources import (
    base_source_label,
    known_source_lists,
    load_prepared_match_table,
)

NS = "https://vocab.brightway.one/flow-contexts/"


def _tables():
    """Every source list whose loaded correspondence has rows to audit.

    Gated on what the loader returns, not on the manifest declaring a table:
    with every `prepared_match_table` null (#141) the manifests declare none,
    but the match-override files still build rows that reach the merge, and a
    future override row routing a context wrongly is exactly what this guard
    exists to catch.  A gate on the attribute made every test here skip
    silently -- found by review on #336.
    """
    for key, source in sorted(known_source_lists().items()):
        rows = load_prepared_match_table(source)
        if rows:
            yield key, source, rows


class RealTablesTestCase(unittest.TestCase):
    """The guard, over the tables the pipeline actually consumes."""

    @classmethod
    def setUpClass(cls):
        cls.found = {}
        for key, _source, rows in _tables():
            cls.found[key] = audit_correspondence_contexts(rows, key)
        if not cls.found:
            raise unittest.SkipTest("no source list loads any correspondence rows")

    def test_every_table_is_audited(self):
        """A table nobody audits is the state this guard exists to end."""
        self.assertTrue(self.found, "no prepared match tables were audited")

    def test_no_unlisted_violation(self):
        """A new routing error fails the build rather than reaching the merge."""
        allowed = known_violations()
        surprises = {
            (key, v.pair, v.source_name, v.target_name)
            for key, violations in self.found.items()
            for v in violations
            if v.pair not in allowed
        }
        self.assertEqual(
            surprises,
            set(),
            "correspondence rows route a source context onto a target context that "
            "means something else, and the pair is not in "
            "`correspondence-context-routing.json`:\n"
            + "\n".join(
                f"  {key}: {'/'.join(pair[0])} -> {'/'.join(pair[1])} "
                f"({src!r} -> {tgt!r})"
                for key, pair, src, tgt in sorted(surprises)
            ),
        )

    def test_no_stale_known_violation(self):
        """Fixing one must show up as an entry that is removed, not silently pass."""
        seen = {v.pair for violations in self.found.values() for v in violations}
        stale = known_violations() - seen
        self.assertEqual(
            stale,
            set(),
            "`known_violations` lists pairs no table produces any more; delete them:\n"
            + "\n".join(
                f"  {'/'.join(s)} -> {'/'.join(t)}" for s, t in sorted(stale)
            ),
        )

    def test_the_groundwater_defect_is_still_visible(self):
        """#48's rows, pinned: this is the class the guard was built for."""
        pair_iris = {
            (v.source_iri, v.target_iri)
            for violations in self.found.values()
            for v in violations
        }
        # #48's pinned pair was dropped as this message instructs: #141
        # retired the tables, so ordinary groundwater is no longer routed
        # anywhere by anyone but this project, and the audit now runs over the
        # authored rows in ecoinvent-match-overrides.json.  What it must find
        # there is nothing.
        self.assertEqual(pair_iris, set())


class PermittedCoarseningTestCase(unittest.TestCase):
    """The allow-list is decisions, so it must stay small and stay used."""

    def test_the_allow_list_is_empty(self):
        """Three coarsenings were permitted while tables shipped -- forestry
        and industrial soil to non-agricultural, groundwater to fresh water --
        because a table naming the nearest flow EF has was doing its job.  The
        tables are retired (#141) and the rows this project authors name
        same-compartment targets, so the allow-list holds nothing, and the next
        entry is a new decision rather than an inheritance."""
        self.assertEqual(permitted_coarsenings(), frozenset())

    def test_a_pair_a_row_may_be_published_on_is_a_pair_a_table_may_state(self):
        """The two questions are asked of one file, and one answer bounds the other."""
        self.assertLessEqual(publishable_coarsenings(), permitted_coarsenings())

    def test_every_entry_is_permitted_and_not_publishable(self):
        """#84 and #77: the entries that make the two questions worth asking apart.

        EF 3.1 has no forestry soil compartment, folds industrial soil into
        non-agricultural, and has no groundwater emission compartment at all, so
        a table pointing any of the three at the nearest flow EF has is doing
        its job.  The emission still belongs in the compartment the source list
        named: reading the target's compartment as well made atrazine on forest
        soil a non-agricultural emission and pyrethrins on forest soil a
        silvicultural one, on no difference between the two emissions (#84),
        and split ecoinvent's groundwater from BAFU's onto surface water
        (#77).

        Every entry answers the second question no as of #77, so
        `publishable_coarsenings()` is empty.  Asserted as a property of each
        entry rather than of the set, because the file's default is still true:
        the next entry added is publishable unless it says otherwise, and this
        test should fail then rather than quietly widen.
        """
        for pair in permitted_coarsenings():
            with self.subTest(pair=pair):
                self.assertNotIn(pair, publishable_coarsenings())

    def test_entries_are_well_formed(self):
        """A coarsening to the same IRI is not a coarsening."""
        for source_iri, target_iri in permitted_coarsenings():
            self.assertTrue(source_iri.startswith(NS), source_iri)
            self.assertTrue(target_iri.startswith(NS), target_iri)
            self.assertNotEqual(source_iri, target_iri)

    def test_every_permitted_coarsening_is_used(self):
        """An unused entry is a decision nothing rests on; it should be deleted.

        Recomputed without the allow-list, so this sees the pairs it suppresses.
        """
        target_rules = context_iri_by_source_context(base_source_label())
        exercised = set()
        for key, _source, rows in _tables():
            source_rules = context_iri_by_source_context(key)
            for row in rows:
                source_iri = source_rules.get(
                    normalize_context_key((row.get("source") or {}).get("context"))
                )
                target_iri = target_rules.get(
                    normalize_context_key((row.get("target") or {}).get("context"))
                )
                if source_iri and target_iri and source_iri != target_iri:
                    exercised.add((source_iri, target_iri))
        unused = permitted_coarsenings() - exercised
        self.assertEqual(
            unused,
            set(),
            "permitted coarsenings that no correspondence row uses; delete them:\n"
            + "\n".join(f"  {s} -> {t}" for s, t in sorted(unused)),
        )


class AuditLogicTestCase(unittest.TestCase):
    """The comparison itself, on rows authored here."""

    def _row(self, source_context, target_context, name="Substance"):
        return {
            "source": {"name": name, "context": list(source_context)},
            "target": {"name": name.lower(), "context": list(target_context)},
        }

    def test_matching_contexts_are_not_reported(self):
        row = self._row(
            ["water", "surface water"],
            ["Emissions", "Emissions to water", "Emissions to fresh water"],
        )
        self.assertEqual(audit_correspondence_contexts([row], "ecoinvent-3.11"), [])

    def test_permitted_coarsening_is_not_reported(self):
        """The allow-list mechanics, on a synthetic entry.

        The live list is empty since #141 -- there are no tables left whose
        nearest-flow habit needed permitting -- so the mechanics are exercised
        against an injected pair: an allow-listed coarsening is not a
        violation, and the same row without the entry is.  That keeps the
        machinery testable for the next entry somebody records.
        """
        from unittest import mock

        row = self._row(
            ["soil", "forestry"],
            ["Emissions", "Emissions to soil", "Emissions to non-agricultural soil"],
        )
        self.assertEqual(len(audit_correspondence_contexts([row], "ecoinvent-3.11")), 1)
        pair = frozenset({(NS + "envi-grou-silv", NS + "envi-grou-noag")})
        with mock.patch(
            "brightway_flows.correspondence_contexts.permitted_coarsenings",
            return_value=pair,
        ):
            self.assertEqual(
                audit_correspondence_contexts([row], "ecoinvent-3.11"), []
            )

    def test_the_long_term_axis_is_caught(self):
        """#48 in one row: ordinary groundwater onto EF's long-term water flow."""
        row = self._row(
            ["water", "ground-"],
            [
                "Emissions",
                "Emissions to water",
                "Emissions to water, unspecified (long-term)",
            ],
            name="Triallate",
        )
        found = audit_correspondence_contexts([row], "ecoinvent-3.11")
        self.assertEqual(len(found), 1)
        self.assertIsInstance(found[0], ContextRoutingViolation)
        self.assertEqual(found[0].source_iri, NS + "envi-wate-unaq")
        self.assertEqual(found[0].target_iri, NS + "envi-wate-lote")
        self.assertEqual(found[0].source_name, "Triallate")

    def test_the_land_axis_is_read_off_the_name(self):
        """#52: `natural resource / land` is both land contexts, and the name
        is what separates them. A guard reading only the compartment called all
        122 transformation rows per table violations -- of a rule the transform
        and the merge no longer apply to them."""
        transformation = self._row(
            ["natural resource", "land"],
            ["Land use", "Land transformation"],
            name="Transformation, from annual crop",
        )
        occupation = self._row(
            ["natural resource", "land"],
            ["Land use", "Land occupation"],
            name="Occupation, annual crop",
        )
        self.assertEqual(
            audit_correspondence_contexts([transformation, occupation], "ecoinvent-3.11"),
            [],
        )

    def test_a_land_row_pointed_at_the_wrong_half_is_still_caught(self):
        """Reading the name must not soften the check it feeds."""
        row = self._row(
            ["natural resource", "land"],
            ["Land use", "Land occupation"],
            name="Transformation, from annual crop",
        )
        found = audit_correspondence_contexts([row], "ecoinvent-3.11")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].source_iri, NS + "laus-tran")
        self.assertEqual(found[0].target_iri, NS + "laus-occu")

    def test_the_reverse_direction_is_caught(self):
        """A genuinely long-term source pointed at a short-term target."""
        row = self._row(
            ["water", "ground-, long-term"],
            ["Emissions", "Emissions to water", "Emissions to fresh water"],
        )
        found = audit_correspondence_contexts([row], "ecoinvent-3.11")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].source_iri, NS + "envi-wate-lote")

    def test_unmapped_context_is_skipped_not_reported(self):
        """A gap in the context rules is a different defect with a different fix."""
        row = self._row(["water", "no such compartment"], ["Emissions", "x", "y"])
        self.assertEqual(audit_correspondence_contexts([row], "ecoinvent-3.11"), [])

    def test_rows_without_contexts_are_skipped(self):
        self.assertEqual(
            audit_correspondence_contexts([{"source": {}, "target": {}}], "ecoinvent-3.11"),
            [],
        )


if __name__ == "__main__":
    unittest.main()
