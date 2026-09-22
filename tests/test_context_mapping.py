"""#11: one context mapping, one loader, both stages.

`context-manual-mapping.json` held the rules; a CLI command projected them into
`<list>-context-mapping.json`; the *transform* read the master and the *merge*
read the projection.  `build` never ran the projection step, so editing the
master moved one stage and left the other on a stale copy, with nothing
detecting the skew -- and a list whose projection was missing got an **empty**
index, which is not an error but "no row has a known context", so every row
failed into the report.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import orjson

from brightway_flows.context_mapping import (
    MANUAL_MAPPING_FILEPATH,
    context_iri_by_source_context,
    context_mapping_index,
    known_mapping_sources,
    normalize_context_key,
    normalize_mapping_text,
)
from brightway_flows.sources import (
    PACKAGE_DATA_DIR,
    base_source_list,
    known_source_lists,
    resolve_source_list,
)

#: Every registered source list, and how many rules it has.  Pinned: these
#: rules place every row an ecoinvent merge produces, so a count that moves is
#: output that moves.  3.8 and 3.12 are the counts the deleted projections
#: carried.
#:
#: 3.8 has a 26th because it keeps `air / indoor`, which 3.9.1 drops.  25 is
#: what the compartment list settles at from 3.9.1 onwards: 3.9.1, 3.10.1, 3.11
#: and 3.12 each ship exactly the same 25 pairs.
#:
#: It briefly had a 27th, `social / unspecified`, for the three exchanges
#: ecoinvent ships only in its APOS release (#25).  Those three are products
#: rather than elementary flows and are refused now (#115), so nothing carries
#: the compartment and the rule went with them: a mapping for a compartment no
#: flow has claims a decision nobody makes.
#:
#: Stepwise had a `Social / (unspecified)` rule of its own for the same
#: compartment, and lost it the same way.  Its three rows there are injury
#: counts, measured in persons, and #173 refused them: an injury is not an
#: emission, so the rows go and the eleventh rule goes with them.  Ten is
#: Stepwise's compartment list with `Social` taken out.
#: BAFU's 26 are its whole compartment list, and they came from a standalone
#: file that nothing read until #4 folded it in here.  26 is what the 2026 v1
#: export uses: every compartment covered, and no rule matching nothing.
MERGEABLE = {
    "agribalyse-3.2": 22,
    "bafu-2026-v1": 26,
    "ecoinvent-3.8": 26,
    "ecoinvent-3.9.1": 25,
    "ecoinvent-3.10.1": 25,
    "ecoinvent-3.11": 25,
    "ecoinvent-3.12": 25,
    "stepwise-2006-1.09": 10,
}


class OneFileTestCase(unittest.TestCase):
    def test_no_per_list_projection_is_checked_in_for_a_registered_list(self):
        """The generated files are gone, and nothing regenerates them.

        `bafu-2025-context-mapping.json` was the last standalone one, exempt
        while it was hand-authored input for #4 rather than a projection of
        anything.  Its 26 rules are in the master now, so the exemption is
        spent and the glob is expected to find nothing at all.
        """
        registered = {source.key for source in known_source_lists().values()}
        for path in sorted(PACKAGE_DATA_DIR.glob("*-context-mapping.json")):
            with self.subTest(path=path.name):
                stem = path.name.removesuffix("-context-mapping.json")
                self.assertNotIn(stem, registered)

    def test_the_projection_writer_is_gone(self):
        """It wrote into package data files the merge then read back."""
        from brightway_flows.application import context_commands

        self.assertFalse(
            hasattr(context_commands, "export_default_context_mappings_by_source")
        )


class BothStagesReadTheSameRulesTestCase(unittest.TestCase):
    """The skew that had nothing detecting it."""

    def test_the_merge_index_is_the_transform_index_filtered_by_source(self):
        for key in sorted(MERGEABLE):
            source = known_source_lists()[key]
            with self.subTest(source=key):
                merge_view = context_iri_by_source_context(source.source_label)
                transform_view = {
                    context: rule.context_iri
                    for (src, context), rule in context_mapping_index().items()
                    if src == normalize_mapping_text(source.source_label)
                }
                self.assertEqual(merge_view, transform_view)

    def test_one_normalisation_not_two(self):
        """The stages each carried their own spelling of this, agreeing by
        luck. Two that disagree place a row in one stage and not the other."""
        self.assertEqual(normalize_mapping_text("  Low  Population DENSITY "), "low population density")
        self.assertEqual(
            normalize_context_key(["Air", "  low population density, long-term "]),
            ("air", "low population density, long-term"),
        )

    def test_a_non_list_context_is_not_a_key(self):
        for value in (None, "air", 42, {}):
            with self.subTest(value=value):
                self.assertEqual(normalize_context_key(value), ())


class EveryMergeableListHasRulesTestCase(unittest.TestCase):
    def test_the_rule_counts_are_what_the_projections_carried(self):
        """Pinned. These rules place every row an ecoinvent merge produces, so
        a count that moves is output that moves."""
        for key, expected in sorted(MERGEABLE.items()):
            source = known_source_lists()[key]
            with self.subTest(source=key):
                self.assertEqual(len(context_iri_by_source_context(source.source_label)), expected)

    def test_a_mergeable_list_resolves(self):
        for key in sorted(MERGEABLE):
            with self.subTest(source=key):
                self.assertEqual(resolve_source_list(key).key, key)

    def test_every_registered_list_has_rules(self):
        """`MERGEABLE` is the whole registry, not a subset of it.

        It was a subset while 3.9.1, 3.10.1 and 3.11 were registered with no
        rules -- a state in which `--source ecoinvent-3.11` downloaded, ran the
        whole transform, and only then failed every row.  Asserting the two
        sets equal is what stops a list being registered and left there.
        """
        self.assertEqual(set(MERGEABLE), set(known_source_lists()))

    def test_a_source_no_row_names_gets_an_empty_mapping_not_a_guess(self):
        """Which is what makes the refusal in `resolve_source_list` possible.

        Stated against a label no row carries rather than a registered list:
        every registered list has rules now, and one acquiring the rules this
        test needed it to lack is not a regression.  That the refusal then
        happens, and names this file, is
        `tests/test_source_list.py::test_a_list_with_no_context_rules_is_refused_before_any_work`.
        """
        self.assertEqual(context_iri_by_source_context("no-such-list-2025"), {})
        self.assertNotIn(
            normalize_mapping_text("no-such-list-2025"), known_mapping_sources()
        )

    def test_the_base_list_has_rules_under_its_declared_label(self):
        """`EF 3.1`, with a space -- the label, not the key."""
        base = base_source_list()
        self.assertEqual(base.source_label, "EF 3.1")
        self.assertTrue(context_iri_by_source_context(base.source_label))
        self.assertFalse(context_iri_by_source_context(base.key))


class MasterFileTestCase(unittest.TestCase):
    def test_every_row_names_a_source_and_an_iri(self):
        payload = orjson.loads(MANUAL_MAPPING_FILEPATH.read_bytes())
        for idx, row in enumerate(payload["default_context_mappings"]):
            with self.subTest(index=idx):
                self.assertTrue(str(row.get("source") or "").strip())
                self.assertTrue(str(row.get("context_iri") or "").strip())
                self.assertTrue(normalize_context_key(row.get("source_context")))

    def test_a_source_and_context_pair_is_declared_once(self):
        """Two rows for one pair means the later silently wins."""
        payload = orjson.loads(MANUAL_MAPPING_FILEPATH.read_bytes())
        seen: set[tuple[str, tuple[str, ...]]] = set()
        duplicates = []
        for row in payload["default_context_mappings"]:
            key = (
                normalize_mapping_text(row["source"]),
                normalize_context_key(row.get("source_context")),
            )
            if key in seen:
                duplicates.append(key)
            seen.add(key)
        self.assertEqual(duplicates, [])

    def test_the_sources_it_knows_include_every_mergeable_list(self):
        known = known_mapping_sources()
        for key in MERGEABLE:
            with self.subTest(source=key):
                self.assertIn(
                    normalize_mapping_text(known_source_lists()[key].source_label), known
                )

    def test_a_missing_master_file_is_an_error_not_an_empty_mapping(self):
        """An empty mapping looks like a clean run that matched nothing."""
        from brightway_flows import context_mapping

        original = context_mapping.MANUAL_MAPPING_FILEPATH
        context_mapping.MANUAL_MAPPING_FILEPATH = Path("/nonexistent/mapping.json")
        context_mapping._load_rows.cache_clear()
        context_mapping.context_mapping_index.cache_clear()
        context_mapping.context_iri_by_source_context.cache_clear()
        try:
            with self.assertRaises(FileNotFoundError):
                context_mapping.context_mapping_index()
        finally:
            context_mapping.MANUAL_MAPPING_FILEPATH = original
            context_mapping._load_rows.cache_clear()
            context_mapping.context_mapping_index.cache_clear()
            context_mapping.context_iri_by_source_context.cache_clear()


class TemporalContextsAreReachedFromBothSidesTestCase(unittest.TestCase):
    """A `Long-term` context only means anything if both lists can reach it.

    #40 moved ecoinvent's `water / ground-, long-term` to `envi-wate-lote` and
    deliberately left EF 3.1's `Emissions to water, unspecified (long-term)` on
    `envi-wate-unkn`.  Nothing failed.  The rules were internally consistent,
    every IRI resolved, and the suite stayed green -- but no EF flow could ever
    occupy `envi-wate-lote`, so ecoinvent's 269 rows had nothing to meet there.

    What they did instead is the part a rule-level check cannot see: their
    correspondence table points 260 of them at EF's *own* long-term flow, which
    was collapsing onto unspecified water under deduplication, so the merge
    followed the deprecation redirect and put them back in `envi-wate-unkn` --
    where 180 of them picked up a short-term factor for a release ecoinvent
    defines as more than a hundred years out.  A one-sided temporal mapping does
    not leave its flows uncharacterised, which would be visible; it leaves them
    characterised by the wrong compartment, which is not.  #41.

    Asserting the *pair* rather than "every context a list names is reachable
    from EF": six contexts are legitimately ecoinvent-only in every version --
    `econ`, `inin`, `envi-grou-silv`, `envi-wate-unaq` and the two
    confined-aquifer rows, with `soci` a seventh in 3.8 alone -- because EF has
    no compartment for them at all, and their flows are created rather than
    matched.  A temporal context is different: it exists precisely to hold two
    sources' halves of one distinction.
    """

    def _temporal_context_iris(self):
        strings = orjson.loads(
            (PACKAGE_DATA_DIR / "consensus-flows-as-strings.json").read_bytes()
        )
        return sorted(
            iri for iri, values in strings.items()
            if isinstance(values, list) and values and values[-1] == "Long-term"
        )

    def _iris_named_by(self, source_label):
        return set(context_iri_by_source_context(source_label).values())

    def test_there_are_temporal_contexts_to_check(self):
        """Guards the test itself: a rename must not turn this into a no-op."""
        self.assertEqual(len(self._temporal_context_iris()), 2)

    def test_the_base_list_reaches_every_temporal_context(self):
        base = base_source_list().source_label
        named = self._iris_named_by(base)
        for iri in self._temporal_context_iris():
            with self.subTest(context=iri):
                self.assertIn(
                    iri, named,
                    f"{base} maps no compartment onto {iri}, so no {base} flow "
                    "can occupy it and anything mapped there is stranded",
                )

    def _long_term_compartments(self, label, medium):
        """The list's own compartments that say *medium* and `long-term`.

        Read off the vendor's spellings rather than off what they are mapped
        to, because the question is what the list distinguishes, and the answer
        has to be independent of the rules under test.
        """
        return {
            key
            for key in context_iri_by_source_context(label)
            if any("long-term" in part for part in key)
            and any(medium in part for part in key)
        }

    def test_a_long_term_compartment_reaches_a_long_term_context(self):
        """#41 itself: a compartment that says long-term and is mapped
        somewhere short-term is how 180 rows picked up the wrong factor."""
        temporal = set(self._temporal_context_iris())
        for key in MERGEABLE:
            label = resolve_source_list(key).source_label
            rules = context_iri_by_source_context(label)
            for compartment, iri in rules.items():
                if not any("long-term" in part for part in compartment):
                    continue
                with self.subTest(source=key, compartment=list(compartment)):
                    self.assertIn(iri, temporal)

    def test_every_mergeable_list_reaches_every_temporal_context_it_ships(self):
        """Both halves of a temporal pair move together -- for a list that has
        both halves.

        Stepwise 2006 does not.  Its water rows are split into `groundwater`
        and `groundwater, long-term`, exactly as ecoinvent's and BAFU's are,
        and its air rows are a single `Air / (unspecified)`: the method states
        one number per substance to air and never says when.  So there is no
        long-term air compartment to map, and a rule for one would claim a
        distinction the vendor does not make -- while nothing is stranded,
        because no row of this list is on the wrong side of it.

        The exemption cannot hide the defect it was written against:
        `test_a_long_term_compartment_reaches_a_long_term_context` reads the
        vendor's spellings, so a list that *does* ship a long-term compartment
        and maps it short-term fails there whatever this one skips.
        """
        for key in MERGEABLE:
            label = resolve_source_list(key).source_label
            named = self._iris_named_by(label)
            for iri in self._temporal_context_iris():
                medium = "air" if "-air-" in iri else "wate"
                if not self._long_term_compartments(
                    label, "air" if medium == "air" else "water"
                ):
                    continue
                with self.subTest(source=key, context=iri):
                    self.assertIn(
                        iri, named,
                        f"{key} maps no compartment onto {iri}; both halves of a "
                        "temporal pair move together or neither does",
                    )


if __name__ == "__main__":
    unittest.main()
