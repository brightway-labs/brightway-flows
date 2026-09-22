"""The compartments SimaPro writes, and what this list makes of them (#328).

Somebody exporting a flow list from SimaPro gets SimaPro's compartment
vocabulary, whatever the flows in it came from: `Raw / in ground`, `Airborne
emissions / low. pop.`, `Waterborne emissions / river`. Most of those spellings
are nobody's *list*, so the phrasebook this project had -- the compartment rules
of every list it has mapped, read with the list dropped -- did not answer them,
and a row whose compartment could not be read is scored without one. For a
substance with more than one flow in the row's unit that is not a weaker answer;
it is a tie, and a tie is no answer at all.

So there is a fourth phrasebook. Its spellings come from the `randonneur_data`
table `SimaPro-2025-ecoinvent-3.12-context`, which is where the 63 strings a
SimaPro export actually carries are written down. Its *meanings* do not: that
table maps SimaPro onto ecoinvent 3.12, and this list's vocabulary is finer than
ecoinvent 3.12's -- ecoinvent has no lake and no river -- so a rule another list
has already written wins wherever there is one. `AgreementWithTheOtherListsTestCase`
is what keeps the two from drifting apart.

`Raw` with nothing after it is the case that shaped the design. It says *this is
a resource* and refuses to say which kind, and this list publishes no bare
`Resource` context to name. Naming one of its children instead would be worse
than saying nothing, because the selector rejects every candidate whose medium
is not the row's.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from brightway_flows.context_mapping import (
    MANUAL_MAPPING_FILEPATH,
    context_iri_by_any_source_context,
    context_mapping_index,
    normalize_context_key,
    normalize_mapping_text,
    simapro_context_rules,
    simapro_name_prefix_policy,
    simapro_name_prefix_rules,
)
from brightway_flows.lookup.query import (
    CONTEXT_AMBIGUOUS,
    CONTEXT_ANY_LIST,
    CONTEXT_DIMENSION_ONLY,
    CONTEXT_NAMED_LIST,
    CONTEXT_SIMAPRO,
    FlowQuery,
    resolve_context,
)

PREFIX = "https://vocab.brightway.one/flow-contexts/"

#: The three compartment names that say "a resource": the compartment spelling,
#: the section-heading spelling, and BAFU's spelling (#356, #360).
RESOURCE_HEADS = ("Raw", "Raw materials", "Resources")


def _resolve(context, name="Some substance"):
    return resolve_context(FlowQuery(name=name, context=context))


class AResourceWithNoMediumTestCase(unittest.TestCase):
    """`Raw`, and every way somebody writes "and I am not saying which kind".

    The row that prompted this asked for standing wood in `Raw /
    (unspecified)`, and got nothing -- not because the list has no standing
    wood, but because the compartment could not be read and every kilogram flow
    of the substance then tied.

    `Resources` is the second row that shaped it (#356). A process export
    writes `Raw` as the compartment and `Resources` as the section heading, and
    `bw_simapro_csv` builds its context from the heading, so every resource row
    it produces arrives spelled `Resources` with nothing after it. That
    spelling said `ground` while `Raw` refused, and a caller's uptake of carbon
    dioxide from the air, asked about under the heading, could never reach the
    air resource of its own substance.
    """

    HEADS = RESOURCE_HEADS

    #: The five ways each writes the nothing after it. The blank and the
    #: missing one are folded onto the bare compartment by
    #: `normalize_context_key` before anything sees them, which is why they are
    #: here rather than in the data file.
    TAILS = ((), ("(unspecified)",), ("unspecified",), ("",), (None,))

    def test_every_spelling_reaches_the_same_answer(self):
        for head in self.HEADS:
            for tail in self.TAILS:
                context = [head, *tail]
                with self.subTest(context=context):
                    resolved = _resolve([c for c in context if c is not None])
                    self.assertEqual(resolved.resolution, CONTEXT_DIMENSION_ONLY)
                    self.assertEqual(resolved.strings, ("Resource",))
                    self.assertEqual(resolved.context_iri, "")

    def test_it_names_no_context(self):
        """The dimension is not a context and must not be published as one: the
        IRI is what the exact-match short-circuit and the contradiction veto are
        enforced on, and there is no context here to enforce."""
        self.assertEqual(_resolve(["Raw", "(unspecified)"]).context_iri, "")

    def test_a_stated_medium_is_still_read(self):
        """The rule fills in what the row did not say and leaves alone what it
        did -- the half that stops it growing into a rule that overrides the
        source."""
        for context, expected in (
            (["Raw", "in ground"], "reso-grou"),
            (["Raw", "in water"], "reso-wate"),
            (["Raw", "biotic"], "reso-biot"),
            (["Raw", "in air"], "reso-air"),
        ):
            with self.subTest(context=context):
                resolved = _resolve(context)
                self.assertEqual(resolved.resolution, CONTEXT_SIMAPRO)
                self.assertEqual(resolved.context_iri, PREFIX + expected)
        # `Resources / <medium>` is BAFU's spelling, answered a step earlier by
        # BAFU's own rule; the refusal for the bare compartment must not reach
        # a subcompartment that does name the medium.
        for context, expected in (
            (["Resources", "in ground"], "reso-grou"),
            (["Resources", "in water"], "reso-wate"),
            (["Resources", "biotic"], "reso-biot"),
            (["Resources", "in air"], "reso-air"),
        ):
            with self.subTest(context=context):
                resolved = _resolve(context)
                self.assertEqual(resolved.resolution, CONTEXT_ANY_LIST)
                self.assertEqual(resolved.context_iri, PREFIX + expected)

    def test_the_list_that_writes_this_compartment_does_not_speak_for_it(self):
        """Stepwise 2006 is registered, and a SimaPro method file, so `Raw /
        (unspecified)` is its own compartment -- 134 rows of it.  Its rule says
        `ground`, which is what is left after its land, timber and uptake rows
        are taken out by name and by uuid, and reading that with the list
        dropped would answer every SimaPro caller `ground` for a compartment
        that refuses to say.  A caller who names the list gets the list's
        answer; a caller who does not gets the refusal."""
        named = resolve_context(
            FlowQuery(
                name="Wood, hard, standing",
                context=["Raw", "(unspecified)"],
                source_label="stepwise-2006-1.09",
            )
        )
        self.assertEqual(named.context_iri, PREFIX + "reso-grou")

        anybody = _resolve(["Raw", "(unspecified)"], name="Wood, hard, standing")
        self.assertEqual(anybody.resolution, CONTEXT_DIMENSION_ONLY)
        self.assertEqual(anybody.context_iri, "")

    def test_a_name_rule_still_picks_a_row_out_of_the_refused_compartment(self):
        """The refusal is about the compartment, not about a row somebody has
        ruled on: `Occupation, ` in `Raw / (unspecified)` is land whoever is
        asking, and answering the dimension there would be #52 again."""
        for head in self.HEADS:
            for tail in ((), ("(unspecified)",), ("unspecified",)):
                context = [head, *tail]
                with self.subTest(context=context, name="Occupation, arable"):
                    resolved = _resolve(context, name="Occupation, arable")
                    self.assertEqual(resolved.context_iri, PREFIX + "laus-occu")
                if context == ["Raw", "(unspecified)"]:
                    # Stepwise's own rule for this spelling names `occupation,`
                    # and nothing else, because Stepwise files no
                    # transformation there, and a spelling a list has ruled is
                    # answered by that list's name rules and not by SimaPro's.
                    # A transformation asked about here gets the refusal, which
                    # is not this test's claim and not #356's.
                    continue
                with self.subTest(context=context, name="Transformation, to arable"):
                    resolved = _resolve(context, name="Transformation, to arable")
                    self.assertEqual(resolved.context_iri, PREFIX + "laus-tran")

    def test_the_list_that_writes_resources_unspecified_does_not_speak_for_it_either(self):
        """`resources / unspecified` is BAFU's spelling of the same refusal,
        and BAFU's rule for it says `ground` -- true of BAFU's rows once its
        land rows are taken out by name, and not of the compartment: BAFU files
        `Carbon dioxide, in air` there, and that row was published as a
        resource taken from the ground until a curated target moved it (#135).
        Until #356 a caller who did not name BAFU got BAFU's answer here while
        the same caller writing `Raw / (unspecified)` got the refusal. The two
        are now read alike, and naming the list still gets the list's answer,
        exactly as for Stepwise above."""
        named = resolve_context(
            FlowQuery(
                name="Oxygen",
                context=["resources", "unspecified"],
                source_label="bafu-2026-v1",
            )
        )
        self.assertEqual(named.resolution, CONTEXT_NAMED_LIST)
        self.assertEqual(named.context_iri, PREFIX + "reso-grou")

        anybody = _resolve(["resources", "unspecified"], name="Oxygen")
        self.assertEqual(anybody.resolution, CONTEXT_DIMENSION_ONLY)
        self.assertEqual(anybody.context_iri, "")


class AResourceWithAMediumTestCase(unittest.TestCase):
    """The same three compartment names, with the medium actually said (#360).

    The case above holds the three heads together where they refuse to name a
    medium.  This one holds them together where they do: `Raw / in air`, `Raw
    materials / in air` and `Resources / in air` are one statement in three
    spellings, and until #360 the middle one resolved to nothing at all --
    which cost the row its strongest matching signal, while the documentation
    promised all three were read the same way.  An uptake of oxygen was the
    row that found it: readable under two spellings of its compartment and
    unreadable under the third, which no caller can predict.
    """

    HEADS = RESOURCE_HEADS

    #: Each medium a SimaPro resource row states, and the context it means.
    MEDIA = (
        ("biotic", "reso-biot"),
        ("in air", "reso-air"),
        ("in ground", "reso-grou"),
        ("in water", "reso-wate"),
    )

    def test_every_head_reads_every_medium_the_same_way(self):
        """The same context from the same statement, and from the step that
        owns the spelling: SimaPro's own rules answer `Raw` and `Raw
        materials`, BAFU's rule answers `Resources` a step earlier."""
        for head in self.HEADS:
            expected = CONTEXT_ANY_LIST if head == "Resources" else CONTEXT_SIMAPRO
            for medium, tail in self.MEDIA:
                with self.subTest(context=[head, medium]):
                    resolved = _resolve([head, medium])
                    self.assertEqual(resolved.resolution, expected)
                    self.assertEqual(resolved.context_iri, PREFIX + tail)

    def test_a_land_name_is_told_apart_under_every_spelling(self):
        """`in ground` holds land rows among its ores -- 3 among 161 in BAFU's
        equivalent -- so the name-prefix rules must reach it under all three
        spellings.  The first cut of #360 copied only the flat rule for `Raw
        materials / in ground`, and a land occupation there was confidently
        filed as a ground resource: worse than the unreadable compartment it
        replaced, because the wrong context rejects every land candidate."""
        for head in self.HEADS:
            context = [head, "in ground"]
            for name, expected in (
                ("Occupation, mineral extraction site", "laus-occu"),
                ("Transformation, to arable", "laus-tran"),
            ):
                with self.subTest(context=context, name=name):
                    resolved = _resolve(context, name=name)
                    self.assertEqual(resolved.context_iri, PREFIX + expected)
            with self.subTest(context=context, name="Some substance"):
                self.assertEqual(
                    _resolve(context).context_iri, PREFIX + "reso-grou"
                )


class AMethodFileCompartmentTestCase(unittest.TestCase):
    """The compartments a SimaPro *method* file writes (#328 again).

    A process export writes `Emissions to air / (unspecified)`; a method file
    writes the compartment bare -- `Air / (unspecified)` -- and the randonneur
    table ships only the export spellings, so the bare ones were nobody's.
    Measured on Stepwise 2006: 3,189 of its 6,064 rows write one of these
    three, and every one was scored without a compartment and tied.
    """

    #: Compartment as a method file capitalises it, and the context ecoinvent
    #: already gives the same compartment spelled without the parentheses.
    CASES = (
        ("Air", "envi-air-unkn"),
        ("Water", "envi-wate-unkn"),
        ("Soil", "envi-grou-unkn"),
    )

    def test_every_spelling_reaches_the_context(self):
        """The bare compartment is still nobody's list.  `(unspecified)` is
        Stepwise's, now that the list these rows were measured on is registered
        and writes that spelling itself -- so it is answered a step earlier, by
        a mapped list's own rule, and the row for it here would never have been
        consulted again.  The rows are gone and the answer has not moved, which
        is what `test_the_spelling_ecoinvent_writes_keeps_ecoinvent_s_ruling`
        says of ecoinvent's spelling and is now true of a second vendor."""
        for compartment, expected in self.CASES:
            for context in ([compartment], [compartment, ""]):
                with self.subTest(context=context):
                    resolved = _resolve([part for part in context if part])
                    self.assertEqual(resolved.resolution, CONTEXT_SIMAPRO)
                    self.assertEqual(resolved.context_iri, PREFIX + expected)
            with self.subTest(context=[compartment, "(unspecified)"]):
                resolved = _resolve([compartment, "(unspecified)"])
                self.assertEqual(resolved.resolution, CONTEXT_ANY_LIST)
                self.assertEqual(resolved.context_iri, PREFIX + expected)

    def test_the_spelling_ecoinvent_writes_keeps_ecoinvent_s_ruling(self):
        """`air / unspecified` -- no parentheses -- is ecoinvent's own
        compartment, reached through the mapped lists' rules before this table
        is consulted. The two routes name the same context, which is what makes
        the new rows a spelling and not a second opinion."""
        for compartment, expected in self.CASES:
            with self.subTest(compartment=compartment):
                resolved = _resolve([compartment, "unspecified"])
                self.assertEqual(resolved.resolution, CONTEXT_ANY_LIST)
                self.assertEqual(resolved.context_iri, PREFIX + expected)


class LandIsToldApartByTheNameTestCase(unittest.TestCase):
    """#52, for a third time and in a third place.

    `Raw / land` holds both land occupations and land transformations, and the
    flow's name is what tells them apart. A flat compartment rule has to choose
    one and is then wrong about the other -- which is exactly what the first
    draft of this did, and it cost 48 of BAFU's rows their match when measured.
    """

    def test_an_occupation_and_a_transformation_go_to_different_contexts(self):
        for name, expected in (
            ("Occupation, arable land, unspecified use", "laus-occu"),
            ("Transformation, from arable, organic", "laus-tran"),
        ):
            with self.subTest(name=name):
                resolved = _resolve(["Raw", "land"], name=name)
                self.assertEqual(resolved.context_iri, PREFIX + expected)

    def test_a_land_name_matching_neither_is_ambiguous_and_not_an_occupation(self):
        """Falling through to the compartment is #52: the compartment rule says
        occupation, so a transformation nobody caught would be filed silently."""
        resolved = _resolve(["Raw", "land"], name="Something else entirely")
        self.assertEqual(resolved.resolution, CONTEXT_AMBIGUOUS)
        self.assertEqual(resolved.context_iri, "")

    def test_a_mixed_compartment_falls_through_to_its_own_rule(self):
        """`Raw / in ground` holds land rows *among* ordinary resources -- 3
        among 161 in BAFU's equivalent -- so the prefixes are an override and
        the compartment still decides for everything else."""
        self.assertEqual(
            _resolve(["Raw", "in ground"], name="Occupation, mineral extraction site").context_iri,
            PREFIX + "laus-occu",
        )
        self.assertEqual(
            _resolve(["Raw", "in ground"], name="Molybdenum").context_iri,
            PREFIX + "reso-grou",
        )

    def test_every_land_bearing_resource_compartment_has_the_rules(self):
        """A compartment that can hold a land row and has no prefix rules is a
        compartment that files transformations as occupations."""
        for key, rule in simapro_context_rules().items():
            if rule.context_iri.endswith("laus-occu"):
                with self.subTest(compartment=list(key)):
                    self.assertIn(key, simapro_name_prefix_rules())

    def test_the_two_spellings_of_raw_carry_the_same_rules(self):
        """`raw` and `raw materials` are one compartment in two spellings, so
        every tail one spelling maps, or tells apart by name, the other must
        too.  The guard above cannot see a gap here: it starts from rules whose
        context is an occupation, and the flat rule of a mixed compartment like
        `in ground` names a resource -- which is how the first cut of #360
        shipped `raw materials / in ground` without its prefix rules and filed
        a land occupation there as a ground resource."""
        heads = ("raw", "raw materials")
        mapped = {head: set() for head in heads}
        for key in simapro_context_rules():
            if key and key[0] in mapped:
                mapped[key[0]].add(key[1:])
        prefixed = {head: set() for head in heads}
        for key in simapro_name_prefix_rules():
            if key and key[0] in prefixed:
                prefixed[key[0]].add(key[1:])
        self.assertEqual(mapped["raw"], mapped["raw materials"])
        self.assertEqual(prefixed["raw"], prefixed["raw materials"])


class AgreementWithTheOtherListsTestCase(unittest.TestCase):
    """The meanings are this project's, and they have to stay this project's.

    The randonneur table maps SimaPro onto ecoinvent 3.12 and this list's
    vocabulary is finer than ecoinvent 3.12's, so eight of its 63 rows would
    coarsen a compartment or get it plainly wrong: `Emissions to air/indoor`
    becomes non-urban air, and river and lake both become surface water. Each of
    those is taken from the list that has already ruled on the same
    subcompartment instead -- which is only safe while the two agree, and this
    is what says they do.
    """

    def _by_subcompartment(self):
        """`(dimension prefix, subcompartment) -> {iri}` over every mapped list."""
        out: dict[tuple[str, str], set[str]] = {}
        for (_source, key), rule in context_mapping_index().items():
            if len(key) == 2:
                dimension = rule.context_iri.rsplit("/", 1)[-1].split("-")[0]
                out.setdefault((dimension, key[1]), set()).add(rule.context_iri)
        return out

    def test_a_subcompartment_another_list_names_reaches_that_list_s_context(self):
        by_sub = self._by_subcompartment()
        checked = 0
        for key, rule in simapro_context_rules().items():
            if len(key) != 2 or not rule.context_iri:
                continue
            dimension = rule.context_iri.rsplit("/", 1)[-1].split("-")[0]
            others = by_sub.get((dimension, key[1]))
            if not others or len(others) != 1:
                continue
            checked += 1
            with self.subTest(compartment=list(key)):
                self.assertEqual(rule.context_iri, next(iter(others)))
        self.assertTrue(checked, "no SimaPro row shares a subcompartment with a list")

    def test_no_row_is_a_second_opinion_about_a_spelling_a_list_has_ruled(self):
        """A spelling a mapped list already writes is reached by that list's own
        rule first, name rules included. A row here for the same spelling could
        only differ from it, never be consulted.

        Rows that refuse to name a medium are exempt, and the refusal is why:
        they outrank the compartment half of that earlier step
        (`lookup.query._refused_medium`), so they are consulted rather than
        shadowed. `Raw / (unspecified)` is the one it matters for. Stepwise 2006
        is a SimaPro method file, so its compartments are these spellings, and
        its rule for that one says `ground` -- true of the 87 rows left once its
        41 land rows, 4 standing-timber rows and 1 uptake from air are taken out
        by name and by uuid, and false of the compartment, which is what a
        caller who has not named a list is asking about."""
        already = context_iri_by_any_source_context()
        for key, rule in simapro_context_rules().items():
            if not rule.context_iri:
                continue
            with self.subTest(compartment=list(key)):
                self.assertNotIn(key, already)


class TheTableItCameFromTestCase(unittest.TestCase):
    """Every spelling the published table ships is one this list can read.

    Read out of `randonneur_data` rather than restated here, so a release that
    adds a compartment fails this instead of drifting: a spelling nobody
    noticed is a caller whose row is scored without a compartment.
    """

    TABLE = "SimaPro-2025-ecoinvent-3.12-context"

    def setUp(self):
        import randonneur_data

        self.rows = randonneur_data.Registry().get_file(self.TABLE)["update"]

    def test_the_table_still_ships_what_this_was_built_from(self):
        self.assertEqual(len(self.rows), 63)

    def test_every_compartment_it_names_is_one_this_list_reads(self):
        """Read, not necessarily answered.

        A land compartment holds two contexts the flow's name chooses between,
        so asked about a substance it reports `ambiguous` -- which is a reading
        of the compartment and not a failure to recognise it. What must never
        happen is `unresolved`: that is a compartment nobody has written down,
        and a row carrying it is scored without one.
        """
        from brightway_flows.lookup.query import CONTEXT_UNRESOLVED

        for row in self.rows:
            shipped = row["source"]["context"]
            head, _, tail = shipped.partition("/")
            context = [head] + ([tail] if tail else [])
            with self.subTest(context=shipped):
                resolved = _resolve(context, name="Molybdenum")
                self.assertNotEqual(
                    resolved.resolution,
                    CONTEXT_UNRESOLVED,
                    f"{shipped!r} is a compartment a SimaPro export writes and "
                    f"nothing here reads it.",
                )

    def test_the_land_compartments_answer_once_the_name_says_which(self):
        for shipped in ("resources/land", "Raw/land", "Raw materials/land"):
            head, _, tail = shipped.partition("/")
            for name, expected in (
                ("Occupation, arable land, unspecified use", "laus-occu"),
                ("Transformation, from arable, organic", "laus-tran"),
            ):
                with self.subTest(context=shipped, name=name):
                    self.assertEqual(
                        _resolve([head, tail], name=name).context_iri, PREFIX + expected
                    )


class TheFileIsCheckedWhereItIsReadTestCase(unittest.TestCase):
    """A malformed ruling raises; it is never skipped."""

    def test_a_row_must_name_exactly_one_of_a_context_and_a_dimension(self):
        from brightway_flows import context_mapping

        payload = json.loads(MANUAL_MAPPING_FILEPATH.read_text())
        for broken in (
            {"source_context": ["raw"], "comment": "says nothing"},
            {
                "source_context": ["raw"],
                "context_iri": PREFIX + "reso-grou",
                "dimension": "Resource",
                "comment": "says it twice",
            },
        ):
            with self.subTest(row=broken):
                payload["simapro_context_mappings"] = [broken]
                with mock.patch.object(
                    context_mapping.orjson,
                    "loads",
                    lambda _b, payload=payload: payload,
                ):
                    context_mapping.simapro_context_rules.cache_clear()
                    with self.assertRaises(context_mapping.SimaproContextRuleError):
                        context_mapping.simapro_context_rules()
        context_mapping.simapro_context_rules.cache_clear()

    def test_the_merge_never_sees_these_rows(self):
        """They are a phrasebook for somebody else's list, read only by the
        lookup. A build reads `default_context_mappings`, and nothing here is
        in it, so no build number can move."""
        payload = json.loads(MANUAL_MAPPING_FILEPATH.read_text())
        defaults = {
            (
                normalize_mapping_text(row["source"]),
                normalize_context_key(row.get("source_context")),
            )
            for row in payload["default_context_mappings"]
        }
        for key in simapro_context_rules():
            with self.subTest(compartment=list(key)):
                self.assertNotIn(("simapro", key), defaults)

    def test_a_policy_is_recorded_only_where_the_rules_are_an_override(self):
        for key, policy in simapro_name_prefix_policy().items():
            with self.subTest(compartment=list(key)):
                self.assertEqual(policy, "select")
                self.assertIn(key, simapro_name_prefix_rules())


if __name__ == "__main__":
    unittest.main()
