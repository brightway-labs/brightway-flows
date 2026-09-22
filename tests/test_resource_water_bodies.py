"""Withdrawals carry the body they were taken from.

`water_body` used to be an emissions-only field, which left every source's water
resources sharing one context: EF 3.1 gives all six of its bodies the single
compartment `Resources / Resources from water / Renewable material resources
from water`, so `lake water`, `sea water` and `ground water` arrived
indistinguishable.  See `plans/water-taxonomy.md`.

The move that makes this cost nothing is `reso-wate` keeping its bare IRI while
gaining `water_body: "Unknown"` -- `to_list()` drops `"Unknown"`, so the string
expression is byte-identical and no published flow needs remapping.  Most of what
is asserted here is that nothing moved.
"""

import unittest
from pathlib import Path
from tempfile import mkdtemp

import orjson

from brightway_flows.application.context_commands import (
    STRINGS_FILEPATH,
    validate_contexts_and_generate_strings,
)
from brightway_flows.context_mapping import MANUAL_MAPPING_FILEPATH
from brightway_flows.domain.context import (
    Context,
    Dimension,
    Media,
    ProhibitedContextCombinationError,
    WaterBody,
)
from brightway_flows.domain.context_registry import (
    CONTEXTS_FILEPATH,
    context_dict_for_iri,
    context_for_iri,
    context_from_dict,
)

PREFIX = "https://vocab.brightway.one/flow-contexts/"

#: The bodies a withdrawal can name, and the IRI each takes.
WITHDRAWAL_BODIES = {
    WaterBody.UNKNOWN: "reso-wate",
    WaterBody.SURFACE_WATER: "reso-wate-suwa",
    WaterBody.LAKE: "reso-wate-lake",
    WaterBody.RIVER: "reso-wate-rive",
    WaterBody.OCEAN: "reso-wate-ocea",
    WaterBody.UNCONFINED_AQUIFER: "reso-wate-unaq",
    WaterBody.CONFINED_AQUIFER: "reso-wate-coaqwifo",
}

#: The bodies it cannot.  Two name a stage in somebody's effluent handling, and
#: the third is a temporal qualifier on a release.
EMISSION_ONLY = (
    WaterBody.WWTP,
    WaterBody.SECONDARY_TREATMENT,
    WaterBody.LONG_TERM,
)

REGISTERED_ECOINVENT = (
    "ecoinvent-3.8",
    "ecoinvent-3.9.1",
    "ecoinvent-3.10.1",
    "ecoinvent-3.11",
    "ecoinvent-3.12",
)


class WithdrawalContextsTestCase(unittest.TestCase):
    def test_a_withdrawal_must_name_its_body(self):
        with self.assertRaises(ProhibitedContextCombinationError):
            Context(dimension=Dimension.RESOURCE, media=Media.WATER)

    def test_every_withdrawal_body_is_constructible(self):
        for body in WITHDRAWAL_BODIES:
            with self.subTest(body=body):
                context = Context(
                    dimension=Dimension.RESOURCE, media=Media.WATER, water_body=body
                )
                self.assertEqual(context.water_body, body)

    def test_the_three_emission_only_bodies_are_refused(self):
        for body in EMISSION_ONLY:
            with self.subTest(body=body):
                with self.assertRaises(ProhibitedContextCombinationError):
                    Context(
                        dimension=Dimension.RESOURCE, media=Media.WATER, water_body=body
                    )

    def test_they_are_still_allowed_on_an_emission(self):
        """The prohibition is about the dimension, not about the values."""
        for body in EMISSION_ONLY:
            with self.subTest(body=body):
                Context(
                    dimension=Dimension.ENVIRONMENTAL, media=Media.WATER, water_body=body
                )

    def test_the_enum_is_fully_partitioned(self):
        """No water body is neither a withdrawal body nor emission-only.

        A value added later has to be placed deliberately rather than defaulting
        into whichever list the validator happens to leave open.
        """
        self.assertEqual(set(WaterBody), set(WITHDRAWAL_BODIES) | set(EMISSION_ONLY))


class NothingMovedTestCase(unittest.TestCase):
    def test_reso_wate_still_serialises_to_two_strings(self):
        """The whole reason `reso-wate` keeps its bare IRI.

        Published flows express their context as this list; if the required
        `Unknown` showed up in it, every one of them would need remapping.
        """
        context = Context(
            dimension=Dimension.RESOURCE,
            media=Media.WATER,
            water_body=WaterBody.UNKNOWN,
        )
        self.assertEqual(context.to_list(), ["Resource", "Water"])
        self.assertEqual(Context.from_list(["Resource", "Water"]), context)

    def test_reso_wate_keeps_its_iri_and_gains_the_body(self):
        self.assertEqual(
            context_dict_for_iri(PREFIX + "reso-wate"),
            {"dimension": "Resource", "media": "Water", "water_body": "Unknown"},
        )


class VocabularyTestCase(unittest.TestCase):
    def test_every_withdrawal_body_has_a_row_with_the_right_body(self):
        for body, slug in WITHDRAWAL_BODIES.items():
            with self.subTest(slug=slug):
                self.assertEqual(context_for_iri(PREFIX + slug).water_body, body)

    def test_no_row_gives_a_withdrawal_an_emission_only_body(self):
        rows = orjson.loads(CONTEXTS_FILEPATH.read_bytes())
        forbidden = {body.value for body in EMISSION_ONLY}
        for row in rows:
            if row["dimension"] != Dimension.RESOURCE.value:
                continue
            with self.subTest(iri=row["context_iri"]):
                self.assertNotIn(row.get("water_body"), forbidden)

    def test_the_vocabulary_carries_exactly_these_resource_water_rows(self):
        rows = orjson.loads(CONTEXTS_FILEPATH.read_bytes())
        found = {
            row["context_iri"].removeprefix(PREFIX)
            for row in rows
            if row["dimension"] == Dimension.RESOURCE.value
            and row.get("media") == Media.WATER.value
        }
        self.assertEqual(found, set(WITHDRAWAL_BODIES.values()))


class TwoSidesOfTheSameBodyTestCase(unittest.TestCase):
    """`envi-wate-lake` and `reso-wate-lake` are the same body, two directions.

    Adding a second dimension to a field that had one is where a serialisation
    collides, and `to_list()` drops `"Unknown"`, so the two water dimensions do
    not simply differ by a prefix.
    """

    def test_a_body_serialises_differently_on_each_side(self):
        for body in WITHDRAWAL_BODIES:
            with self.subTest(body=body):
                emission = Context(
                    dimension=Dimension.ENVIRONMENTAL, media=Media.WATER, water_body=body
                )
                withdrawal = Context(
                    dimension=Dimension.RESOURCE, media=Media.WATER, water_body=body
                )
                self.assertNotEqual(emission.to_list(), withdrawal.to_list())
                self.assertEqual(
                    Context.from_list(withdrawal.to_list()).dimension,
                    Dimension.RESOURCE,
                )

    def test_the_same_body_has_two_iris_and_they_resolve_apart(self):
        for body, reso in WITHDRAWAL_BODIES.items():
            envi = reso.replace("reso-wate", "envi-wate", 1)
            if envi == "envi-wate":  # the Unknown pair, spelled -unkn on that side
                envi = "envi-wate-unkn"
            with self.subTest(body=body):
                self.assertEqual(context_for_iri(PREFIX + envi).water_body, body)
                self.assertEqual(context_for_iri(PREFIX + reso).water_body, body)
                self.assertEqual(
                    context_for_iri(PREFIX + envi).dimension, Dimension.ENVIRONMENTAL
                )
                self.assertEqual(
                    context_for_iri(PREFIX + reso).dimension, Dimension.RESOURCE
                )


class IRIConventionTestCase(unittest.TestCase):
    """The IRIs are hand-written, so a typo is a silently wrong context.

    Nothing generates these slugs, and `reso-wate-rive` carrying `Ocean` would
    pass every other test in this file: the row would be valid, the context
    constructible, the vocabulary consistent with itself. Only the name would
    lie, and only to a human.
    """

    def test_each_withdrawal_slug_matches_the_body_it_carries(self):
        for body, slug in WITHDRAWAL_BODIES.items():
            with self.subTest(slug=slug):
                self.assertEqual(context_for_iri(PREFIX + slug).water_body, body)

    @staticmethod
    def _suffix_by_body_and_dimension():
        rows = orjson.loads(CONTEXTS_FILEPATH.read_bytes())
        out: dict[str, dict[str, str]] = {}
        for row in rows:
            if row.get("media") != Media.WATER.value:
                continue
            slug = row["context_iri"].removeprefix(PREFIX)
            suffix = slug.split("-", 2)[2] if slug.count("-") >= 2 else ""
            out.setdefault(row.get("water_body"), {})[row["dimension"]] = suffix
        return out

    def test_each_slug_is_the_emission_side_spelling_of_the_same_body(self):
        """The two sides use one abbreviation per body, so a reader who knows
        `envi-wate-unaq` can read `reso-wate-unaq` without a lookup.

        `Unknown` is the exception and has its own test below.
        """
        for body, sides in self._suffix_by_body_and_dimension().items():
            if len(sides) < 2 or body == WaterBody.UNKNOWN.value:
                continue
            with self.subTest(body=body):
                self.assertEqual(
                    len(set(sides.values())),
                    1,
                    f"{body} is abbreviated differently on each side: {sides}",
                )

    def test_unknown_is_the_one_body_spelled_differently_on_each_side(self):
        """And it must stay that way.

        The emission side is `envi-wate-unkn`; the withdrawal side is bare
        `reso-wate`, because that IRI predates the field being required there
        and published flows already carry it. Regularising it to
        `reso-wate-unkn` would be tidier and would remap every unqualified water
        withdrawal, so this test exists to make that a decision rather than a
        cleanup.
        """
        sides = self._suffix_by_body_and_dimension()[WaterBody.UNKNOWN.value]
        self.assertEqual(
            sides, {"Environmental": "unkn", "Resource": ""}
        )


class StoredContextTestCase(unittest.TestCase):
    """What a flow record carries, which is the dict rather than the IRI."""

    def test_a_withdrawal_context_round_trips_through_the_registry(self):
        for slug in WITHDRAWAL_BODIES.values():
            with self.subTest(slug=slug):
                stored = context_dict_for_iri(PREFIX + slug)
                self.assertEqual(context_from_dict(stored), context_for_iri(PREFIX + slug))

    def test_every_withdrawal_context_names_its_body_in_the_stored_dict(self):
        """`to_list()` drops `Unknown`; the stored dict must not, or the field
        cannot be filtered on and the IRI cannot be recovered from the record."""
        for body, slug in WITHDRAWAL_BODIES.items():
            with self.subTest(slug=slug):
                self.assertEqual(
                    context_dict_for_iri(PREFIX + slug).get("water_body"), body.value
                )


class GeneratedStringsTestCase(unittest.TestCase):
    """`consensus-flows-as-strings.json` is generated and nothing checked it.

    `merge/contexts.py` reads it to decide which consensus context a source row
    lands in -- an expected context absent from it has no candidates, and
    `_context_taxonomy_distance` falls back to the nearest one in the same media.
    So a vocabulary row added without re-running `brightway-flows contexts`
    does not fail; it silently puts the flows somewhere else. That is how
    `water / ground-, long-term` landed on `envi-wate-unkn` for 263 flows while
    the rule said `envi-wate-unaq`.
    """

    def test_it_is_in_sync_with_the_vocabulary(self):
        regenerated = validate_contexts_and_generate_strings(
            strings_path=Path(mkdtemp()) / "strings.json"
        )
        published = orjson.loads(STRINGS_FILEPATH.read_bytes())
        self.assertEqual(published, regenerated)

    def test_every_withdrawal_body_reaches_the_merge(self):
        published = orjson.loads(STRINGS_FILEPATH.read_bytes())
        for slug in WITHDRAWAL_BODIES.values():
            with self.subTest(slug=slug):
                self.assertIn(PREFIX + slug, published)


class FossilWellTestCase(unittest.TestCase):
    """ecoinvent's one water compartment that names its body.

    Every other withdrawal needs a per-flow rule, because EF 3.1 gives all six
    of its bodies one compartment and the body is in the flow's name.

    `fossil well` is not defined in ecoinvent's public documentation and the
    name reads two ways -- a well into a fossil aquifer, or a fossil-fuel well
    producing formation water.  They converge on this body rather than
    diverging: produced water from a hydrocarbon well is connate water in a
    confined formation with negligible modern recharge, which is fossil
    groundwater.  The readings differ in why somebody drilled, not in what the
    water is, and this axis is the body.  Salinity does not separate them
    either; it is a material property carried on the other axis.

    Curator's check against the release: no dataset uses the emission-side
    `water / fossil well` flow, and the resource side is used only for
    `Water, unspecified natural origin`.  So the mapping is exercised by exactly
    one flow and reads cleanly onto the confined aquifer.
    """

    #: The only flow in `natural resource / fossil well`, in every version.
    WATER_UNSPECIFIED = "2caa889e-8187-459d-963a-fa47a79c5378"

    @staticmethod
    def _mappings():
        payload = orjson.loads(MANUAL_MAPPING_FILEPATH.read_bytes())
        return payload["default_context_mappings"]

    def test_every_registered_version_points_at_the_confined_aquifer(self):
        seen = set()
        for row in self._mappings():
            if row["source_context"] == ["natural resource", "fossil well"]:
                seen.add(row["source"])
                with self.subTest(source=row["source"]):
                    self.assertEqual(row["context_iri"], PREFIX + "reso-wate-coaqwifo")
        self.assertEqual(
            seen,
            set(REGISTERED_ECOINVENT),
            "one reading of the compartment, stated once per version",
        )

    def test_the_two_sides_agree_on_the_body(self):
        """`natural resource / fossil well` and `water / fossil well` are the
        same body approached from opposite directions, and did not agree while
        only the emission side asserted it."""
        by_context = {
            (row["source"], tuple(row["source_context"])): row["context_iri"]
            for row in self._mappings()
        }
        for source in REGISTERED_ECOINVENT:
            with self.subTest(source=source):
                withdrawal = by_context[(source, ("natural resource", "fossil well"))]
                emission = by_context[(source, ("water", "fossil well"))]
                self.assertEqual(
                    context_for_iri(withdrawal).water_body,
                    context_for_iri(emission).water_body,
                )
                self.assertEqual(
                    context_for_iri(withdrawal).water_body, WaterBody.CONFINED_AQUIFER
                )

    def test_it_no_longer_collapses_onto_unspecified_withdrawals(self):
        """The reason this row is worth writing at all.

        While it pointed at `reso-wate`, `natural resource / fossil well` and
        `natural resource / in water` were two ecoinvent compartments in one
        consensus context -- a source distinction discarded, which is the defect
        #251 and #31 are about.
        """
        by_context = {
            (row["source"], tuple(row["source_context"])): row["context_iri"]
            for row in self._mappings()
        }
        for source in REGISTERED_ECOINVENT:
            with self.subTest(source=source):
                self.assertNotEqual(
                    by_context[(source, ("natural resource", "fossil well"))],
                    by_context[(source, ("natural resource", "in water"))],
                )

    def test_the_row_states_the_reading_it_took(self):
        """ecoinvent publishes no definition, so ours has to be re-checkable."""
        for row in self._mappings():
            if row["source_context"] == ["natural resource", "fossil well"]:
                with self.subTest(source=row["source"]):
                    comment = row.get("comment", "")
                    self.assertIn("#263", comment)
                    self.assertIn("connate", comment)
