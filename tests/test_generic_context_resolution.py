"""Placing a row from a list nobody has mapped.

Every context rule in this project is keyed on which list wrote it, and that is
right for a build: the merge is placing rows from one list, and it knows which.
Somebody outside the project asking "which consensus flow is this row of mine?"
is in the opposite position -- their compartments are their own, and no rule is
written under their list's name.

Two generalisations answer them, and each is sound only because of something
measured about the curated files rather than guaranteed by their format, so each
is checked here.

* :func:`context_iri_for_any_source_context` reads the compartment rules, and
  the name rules beside them, with the list dropped.  Sound because no
  compartment is mapped onto two contexts -- which, measured here, is mostly
  because the three vendors share no compartment spelling at all -- and because
  the four compartments a name has to decide are decided by the name here too,
  rather than by the compartment rule that is wrong about half of them (#52).
* :func:`context_iri_by_consensus_strings` reads this project's own renderings
  backwards.  Sound because no two contexts print the same.

`plans/lookup-api.md` §3.5.
"""

from __future__ import annotations

import unittest

from pathlib import Path
from tempfile import mkdtemp
from unittest import mock

import orjson

from brightway_flows import context_mapping
from brightway_flows.context_mapping import (
    CONSENSUS_STRINGS_FILEPATH,
    AmbiguousSourceContextError,
    ConflictingContextKeyError,
    consensus_context_strings,
    context_iri_by_any_source_context,
    context_iri_by_consensus_strings,
    context_iri_by_source_context,
    context_iri_for_any_source_context,
    context_mapping_index,
    normalize_context_key,
)
from brightway_flows.sources import known_source_lists

PREFIX = "https://vocab.brightway.one/flow-contexts/"

#: What the compartment rules collapse to on the 29 August 2026 package data:
#: 220 rows written by 9 lists, naming 118 distinct compartments.  Pinned
#: because the collapse is the whole capability -- a caller with an unmapped
#: list can be placed by 118 compartments, and no more.
#:
#: It was 190 and 90 until #115 refused ecoinvent 3.8's three `social /
#: unspecified` rows as products rather than elementary flows.  Nothing carries
#: that compartment now, so its rule went with them.  It was 189, 7 and 89
#: until Stepwise 2006 was registered and wrote 11 compartments of its own,
#: nine of them new here: a SimaPro method file's vocabulary, which until then
#: only the phrasebook had.  It was 200, 8 and 98 until GreenDelta's openLCA
#: package wrote 21 more, every one of them new here (#165).  It was 221, 9 and
#: 119 until #173 refused Stepwise's three injury counts, which were the only
#: rows in the `Social` compartment ecoinvent's refusal had already emptied --
#: so `social` has lost its rule twice, to two lists, for two reasons.
RULE_COUNT = 242
LIST_COUNT = 10
COMPARTMENT_COUNT = 122

#: Every consensus context, and every one of them printed differently.
CONTEXT_COUNT = 61


class _CachedLoaders:
    """Clear every cache the two loaders sit behind, before and after."""

    CACHED = (
        "_load_rows",
        "context_mapping_index",
        "context_iri_by_source_context",
        "context_iri_by_any_source_context",
        "_name_rules_for_any_source_context",
        "consensus_context_strings",
        "context_iri_by_consensus_strings",
    )

    def _clear(self) -> None:
        for name in self.CACHED:
            getattr(context_mapping, name).cache_clear()

    def setUp(self) -> None:  # noqa: N802 - unittest's spelling
        super().setUp()
        self._clear()
        self.addCleanup(self._clear)


class TheListsAgreeAboutTheirCompartmentsTestCase(_CachedLoaders, unittest.TestCase):
    """The rules read with the list dropped, and what that does and does not buy.

    The plan this implements says the seven lists "genuinely agree" about the
    compartments they share.  They do not disagree, which is not the same
    sentence, and the difference is worth pinning: measured here, the five
    *vendors* write twenty compartment strings in common and agree about every
    one -- eighteen of them being AGRIBALYSE 3.2 spelling its compartments the
    way BAFU does, both carrying SimaPro's export vocabulary.  So the collapse
    is a union of phrasebooks that overlap only where two lists share a
    lineage, and the absence of conflicts is mostly the absence of overlap.

    GreenDelta is the fifth and is not a list that gets merged: its rows say
    what the compartments of an LCIA *package* mean, so that a factor of theirs
    can reach a flow of ours by substance (#165).  One question, one file --
    which is why they are here rather than in a table of their own.
    """

    #: The five vocabularies, and how many compartments each names.  The five
    #: ecoinvent releases are counted as one vendor because their agreement is
    #: a release agreeing with its predecessor, which says nothing about whether
    #: an outside list would be understood.
    BY_VENDOR = {
        "agribalyse-3.2": 22,
        "bafu-2026-v1": 26,
        "ecoinvent": 26,
        "ef 3.1": 37,
        "greendelta": 21,
        "stepwise-2006-1.09": 10,
    }

    #: Where two vendors write one compartment string, and what they say about
    #: it.  Empty until Stepwise 2006 was registered: it is a SimaPro method
    #: file, and SimaPro's compartment vocabulary is close enough to
    #: ecoinvent's that two of its eleven spellings are ecoinvent's exactly.
    #: They agree, which is what makes this worth recording rather than a
    #: conflict -- `context_iri_by_any_source_context` raises where two lists
    #: disagree, so a row that did not agree would not reach this test at all.
    SHARED = {
        ("soil", "agricultural"): PREFIX + "envi-grou-agri",
        ("water", "ocean"): PREFIX + "envi-wate-ocea",
        # AGRIBALYSE 3.2 is a SimaPro process export and BAFU 2026 v1 is
        # SimaPro-shaped ecoSpold, so the two spell eighteen compartments
        # identically -- every one of AGRIBALYSE's except the four it writes
        # with the subcompartment cell empty, which BAFU spells `unspecified`.
        # They agree about all eighteen, which is what lets both be here.
        ("emissions to air", "high. pop."): PREFIX + "envi-air-grle-ur10pesq",
        ("emissions to air", "low. pop."): PREFIX + "envi-air-mest15me-ru10pesq",
        ("emissions to air", "low. pop., long-term"): PREFIX + "envi-air-lote",
        ("emissions to air", "stratosphere + troposphere"): PREFIX + "envi-air-aicrhe",
        ("emissions to soil", "agricultural"): PREFIX + "envi-grou-agri",
        ("emissions to soil", "forestry"): PREFIX + "envi-grou-silv",
        ("emissions to soil", "industrial"): PREFIX + "envi-grou-indu",
        ("emissions to water", "groundwater"): PREFIX + "envi-wate-unaq",
        ("emissions to water", "groundwater, long-term"): PREFIX + "envi-wate-lote",
        ("emissions to water", "lake"): PREFIX + "envi-wate-lake",
        ("emissions to water", "ocean"): PREFIX + "envi-wate-ocea",
        ("emissions to water", "river"): PREFIX + "envi-wate-rive",
        ("emissions to water", "river, long-term"): PREFIX + "envi-wate-lote",
        ("resources", "biotic"): PREFIX + "reso-biot",
        ("resources", "in air"): PREFIX + "reso-air",
        ("resources", "in ground"): PREFIX + "reso-grou",
        ("resources", "in water"): PREFIX + "reso-wate",
        ("resources", "land"): PREFIX + "laus-occu",
    }

    @staticmethod
    def _vendor(source: str) -> str:
        return "ecoinvent" if source.startswith("ecoinvent") else source

    def test_the_rules_still_come_from_several_lists(self):
        """Guards the tests below: one list cannot disagree with itself."""
        sources = {source for source, _ in context_mapping_index()}
        self.assertEqual(len(context_mapping_index()), RULE_COUNT)
        self.assertEqual(len(sources), LIST_COUNT)

    def test_the_compartments_collapse_to_one_context_each(self):
        collapsed = context_iri_by_any_source_context()
        self.assertEqual(len(collapsed), COMPARTMENT_COUNT)

    def test_each_vendor_names_the_compartments_the_docstring_says(self):
        by_vendor: dict[str, set] = {}
        for source, compartment in context_mapping_index():
            by_vendor.setdefault(self._vendor(source), set()).add(compartment)
        self.assertEqual(
            {vendor: len(keys) for vendor, keys in by_vendor.items()}, self.BY_VENDOR
        )

    def test_the_compartments_two_vendors_share_are_the_ones_recorded(self):
        """The measurement the docstring rests on, and it has moved.

        It used to assert that no compartment string was written by two
        vendors, and said that if it ever failed that would be *good* news for
        the capability -- two vocabularies have met -- and also the first
        chance for two lists to contradict each other about a compartment.
        Stepwise 2006 is that day: it is a SimaPro method file, so it writes
        `Soil / agricultural` and `Water / ocean` exactly as ecoinvent does.

        So the assertion is the same fact stated the other way round -- which
        strings are shared, and that the vendors sharing one agree about it --
        rather than a count somebody would later update and absorb the overlap
        into.
        """
        by_compartment: dict[tuple[str, ...], set[str]] = {}
        answers: dict[tuple[str, ...], set[str]] = {}
        for (source, compartment), rule in context_mapping_index().items():
            by_compartment.setdefault(compartment, set()).add(self._vendor(source))
            answers.setdefault(compartment, set()).add(rule.context_iri)
        overlapping = {k: sorted(v) for k, v in by_compartment.items() if len(v) > 1}
        self.assertEqual(sorted(overlapping), sorted(self.SHARED))
        for compartment, iri in self.SHARED.items():
            with self.subTest(compartment=list(compartment)):
                self.assertEqual(answers[compartment], {iri})
        self.assertEqual(
            len(by_compartment), sum(self.BY_VENDOR.values()) - len(self.SHARED)
        )

    def test_a_mapped_list_gets_the_same_answer_either_way(self):
        """The generalisation must not move a row of a list we *have* mapped.

        If it did, the API would answer one thing for a caller who names their
        list and another for a caller who does not, about the same compartment.
        """
        collapsed = context_iri_by_any_source_context()
        for key, source in sorted(known_source_lists().items()):
            own = context_iri_by_source_context(source.source_label)
            for compartment, context_iri in sorted(own.items()):
                with self.subTest(list=key, compartment=compartment):
                    self.assertEqual(collapsed[compartment], context_iri)


class ADisagreementIsRefusedTestCase(_CachedLoaders, unittest.TestCase):
    """Two lists, one compartment, two contexts.

    There are none today.  The loader's job is to make the day one appears a
    failure rather than a decision made by the order the rules happen to sit in
    the file -- which is how a curated statement gets overruled with nothing
    said (#31).

    A conflicting row is harmless to a build, because a build reads the rules of
    the one list it is merging, so it is refused here rather than in the file.
    """

    ONE = {
        "source": "list-one",
        "source_context": ["water", "unspecified"],
        "context_iri": PREFIX + "envi-wate-unkn",
        "comment": "because",
    }
    TWO_AGREEING = dict(ONE, source="list-two")
    TWO_DISAGREEING = dict(ONE, source="list-two", context_iri=PREFIX + "envi-wate-lake")

    def _collapsed(self, *rows):
        payload = {"default_context_mappings": list(rows)}
        path = Path(mkdtemp()) / "context-manual-mapping.json"
        path.write_bytes(orjson.dumps(payload))
        with mock.patch.object(context_mapping, "MANUAL_MAPPING_FILEPATH", path):
            self._clear()
            try:
                return context_iri_by_any_source_context()
            finally:
                self._clear()

    def test_two_lists_that_agree_collapse_to_one_entry(self):
        collapsed = self._collapsed(self.ONE, self.TWO_AGREEING)
        self.assertEqual(collapsed, {("water", "unspecified"): PREFIX + "envi-wate-unkn"})

    def test_two_lists_that_disagree_raise(self):
        with self.assertRaises(ConflictingContextKeyError) as caught:
            self._collapsed(self.ONE, self.TWO_DISAGREEING)
        message = str(caught.exception)
        self.assertIn("list-one", message)
        self.assertIn("list-two", message)
        self.assertIn("envi-wate-lake", message)

    def test_the_disagreement_is_refused_whichever_order_it_is_written_in(self):
        """Not "the first one wins" by another name."""
        with self.assertRaises(ConflictingContextKeyError):
            self._collapsed(self.TWO_DISAGREEING, self.ONE)


class ACompartmentIsNotAlwaysEnoughTestCase(_CachedLoaders, unittest.TestCase):
    """Four of the 89 compartments cannot be decided by the compartment.

    ecoinvent puts land occupation and land transformation in one compartment
    and says which is which in the flow name.  Read with the list dropped,
    `natural resource / land` answers `laus-occu`, so a caller's transformation
    flow would be filed as an occupation with nothing said -- which is #52
    exactly, one layer further out.

    So the generic resolution reads the name rules too, and
    `context_iri_by_any_source_context` is the half of it that does not.
    """

    #: The compartments some list has ruled its flows' names have to decide,
    #: and what the compartment-only index says about each.  Every one of them
    #: is a wrong answer for half the rows in it.
    NAME_DECIDED = {
        ("natural resource", "land"): PREFIX + "laus-occu",
        ("resources", "land"): PREFIX + "laus-occu",
        ("resources", "in ground"): PREFIX + "reso-grou",
        ("resources", "unspecified"): PREFIX + "reso-grou",
    }

    def test_the_compartment_only_index_answers_them_anyway(self):
        """The defect, stated as data. If this ever stops being true the
        resolver below is doing less than it looks."""
        collapsed = context_iri_by_any_source_context()
        self.assertEqual(
            {key: collapsed.get(key) for key in self.NAME_DECIDED}, self.NAME_DECIDED
        )

    def test_the_name_decides_where_the_compartment_cannot(self):
        for compartment in (["natural resource", "land"], ["resources", "land"]):
            with self.subTest(compartment=compartment):
                self.assertEqual(
                    context_iri_for_any_source_context(
                        compartment, "Occupation, annual crop"
                    ),
                    PREFIX + "laus-occu",
                )
                self.assertEqual(
                    context_iri_for_any_source_context(
                        compartment, "Transformation, from annual crop"
                    ),
                    PREFIX + "laus-tran",
                )

    def test_a_partition_compartment_refuses_a_name_it_does_not_know(self):
        """Falling through to the compartment rule is #52. A name this
        vocabulary has not seen is a curation question, not a default."""
        with self.assertRaises(AmbiguousSourceContextError):
            context_iri_for_any_source_context(
                ["natural resource", "land"], "Something nobody has ruled on"
            )

    def test_a_select_compartment_falls_through_for_everything_else(self):
        """BAFU's `resources / in ground` holds 3 land rows among 161. The
        rules pick those out; the compartment still decides for the rest."""
        self.assertEqual(
            context_iri_for_any_source_context(["resources", "in ground"], "Iron ore"),
            PREFIX + "reso-grou",
        )
        self.assertEqual(
            context_iri_for_any_source_context(
                ["resources", "in ground"], "Occupation, forest, intensive"
            ),
            PREFIX + "laus-occu",
        )

    def test_an_ordinary_compartment_is_unaffected(self):
        """A SimaPro export's own spelling, which is what BAFU's 26 rules are."""
        self.assertEqual(
            context_iri_for_any_source_context(
                ["emissions to air", "low. pop."], "Benzene"
            ),
            PREFIX + "envi-air-mest15me-ru10pesq",
        )

    def test_a_compartment_nobody_has_written_down_is_unresolved(self):
        """Not a guess. The IRI is what the dimension and media filter is
        enforced on, and a wrong one crosses a boundary the merge refuses to
        cross."""
        self.assertIsNone(
            context_iri_for_any_source_context(["somewhere else entirely"], "Benzene")
        )
        self.assertIsNone(context_iri_for_any_source_context([], "Benzene"))


class TheRenderingsReadBackwardsTestCase(_CachedLoaders, unittest.TestCase):
    """A caller who writes this project's own words for a context.

    `Environmental / Air / Indoor` is a context of ours, spelled the way we
    spell it, so reading it back is exact rather than a guess -- provided no two
    contexts are spelled the same.  #284 is what a shared rendering does inside
    the merge; read backwards it would file a caller's row in a compartment they
    did not name.
    """

    def test_every_context_is_printed_differently(self):
        strings = consensus_context_strings()
        self.assertEqual(len(strings), CONTEXT_COUNT)
        self.assertEqual(len(context_iri_by_consensus_strings()), CONTEXT_COUNT)

    def test_every_context_finds_its_own_iri_again(self):
        reverse = context_iri_by_consensus_strings()
        for iri, strings in sorted(consensus_context_strings().items()):
            with self.subTest(context=iri):
                self.assertEqual(reverse[normalize_context_key(strings)], iri)

    def test_indoor_air_is_read_back_as_indoor_air(self):
        """The worked example, and the one #284 was about: indoor air prints its
        `Indoor`, so it is not read back as unspecified outdoor air."""
        reverse = context_iri_by_consensus_strings()
        self.assertEqual(
            reverse[normalize_context_key(["Environmental", "Air", "Indoor"])],
            PREFIX + "envi-air-indr-unkn",
        )
        self.assertEqual(
            reverse[normalize_context_key(["Environmental", "Air"])],
            PREFIX + "envi-air-unkn",
        )

    def test_a_caller_who_shouts_is_still_understood(self):
        """The key is normalised the way every other context key is."""
        reverse = context_iri_by_consensus_strings()
        self.assertEqual(
            reverse[normalize_context_key(["  ENVIRONMENTAL ", "air", "Indoor"])],
            PREFIX + "envi-air-indr-unkn",
        )

    def _reverse_of(self, payload):
        path = Path(mkdtemp()) / "consensus-flows-as-strings.json"
        path.write_bytes(orjson.dumps(payload))
        with mock.patch.object(context_mapping, "CONSENSUS_STRINGS_FILEPATH", path):
            self._clear()
            try:
                return context_iri_by_consensus_strings()
            finally:
                self._clear()

    def test_two_contexts_printed_the_same_raise(self):
        with self.assertRaises(ConflictingContextKeyError) as caught:
            self._reverse_of({
                PREFIX + "envi-air-indr-unkn": ["Environmental", "Air"],
                PREFIX + "envi-air-unkn-unkn": ["Environmental", "Air"],
            })
        message = str(caught.exception)
        self.assertIn("envi-air-indr-unkn", message)
        self.assertIn("envi-air-unkn-unkn", message)


class TheRenderingsHaveOneLoaderTestCase(_CachedLoaders, unittest.TestCase):
    """`consensus-flows-as-strings.json` was parsed inline by the merge, behind
    an `if it exists`.

    That is the shape #11 removed from the compartment rules beside it: a
    missing vocabulary read as an empty one is not a clean run, it is every row
    scored against nothing and no row placed by its context.  One loader, and it
    raises.
    """

    def test_a_missing_file_is_an_error_not_an_empty_mapping(self):
        with mock.patch.object(
            context_mapping, "CONSENSUS_STRINGS_FILEPATH", Path("/nonexistent/strings.json")
        ):
            self._clear()
            try:
                with self.assertRaises(FileNotFoundError):
                    consensus_context_strings()
            finally:
                self._clear()

    def test_the_loader_returns_what_the_inline_parse_returned(self):
        """The merge scored every candidate on strings it parsed itself.  This
        is that parse, kept as the thing the loader has to still agree with --
        a refactor of a reader is only a refactor if it reads the same."""
        payload = orjson.loads(CONSENSUS_STRINGS_FILEPATH.read_bytes())
        inline: dict[str, list[str]] = {}
        for iri, value in payload.items():
            if not isinstance(iri, str) or not isinstance(value, list):
                continue
            inline[iri] = [str(x) for x in value if isinstance(x, str) and x.strip()]
        self.assertEqual(consensus_context_strings(), inline)

    def test_the_merge_reads_the_renderings_through_the_loader(self):
        """What `_load_context_expectation_indexes` hands the merge is what the
        loader holds, so the two sides of a candidate's score cannot drift."""
        from brightway_flows.merge.contexts import _load_context_expectation_indexes
        from brightway_flows.sources import base_source_list

        _expectations, strings = _load_context_expectation_indexes(base_source_list())
        self.assertEqual(strings, consensus_context_strings())

    def test_the_merge_cannot_write_through_to_the_cache(self):
        """It is handed to a frozen index every reader of a run shares."""
        from brightway_flows.merge.contexts import _load_context_expectation_indexes
        from brightway_flows.sources import base_source_list

        _expectations, strings = _load_context_expectation_indexes(base_source_list())
        iri = PREFIX + "envi-air-indr-unkn"
        strings[iri].append("Nonsense")
        self.assertNotIn("Nonsense", consensus_context_strings()[iri])

    def test_the_merge_module_no_longer_parses_the_file_itself(self):
        source = Path(
            __import__(
                "brightway_flows.merge.contexts", fromlist=["contexts"]
            ).__file__
        ).read_text()
        self.assertNotIn("consensus-flows-as-strings.json", source)

    def test_the_loader_reads_the_file_the_register_names(self):
        self.assertEqual(CONSENSUS_STRINGS_FILEPATH.name, "consensus-flows-as-strings.json")
        self.assertTrue(CONSENSUS_STRINGS_FILEPATH.exists())


if __name__ == "__main__":
    unittest.main()
