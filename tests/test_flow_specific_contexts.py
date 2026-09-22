"""A compartment is the wrong granularity for a water withdrawal.

EF 3.1 gives all six of its water bodies the single compartment `Resources /
Resources from water / Renewable material resources from water`.  `lake water`,
`river water` and `sea water` are told apart by their names, and a name is not
something a compartment rule can key on.  `flow_specific_context_mappings` is
how the body reaches the context anyway -- one flow at a time, each row carrying
its reasoning.

The key had been in `context-manual-mapping.json` with a template row and no
code reading it since before #11.
"""

import dataclasses
import json
import unittest
from functools import cache
from pathlib import Path
from tempfile import mkdtemp
from unittest import mock

import orjson

from brightway_flows import context_mapping
from brightway_flows.context_mapping import (
    context_iri_by_source_context,
    MANUAL_MAPPING_FILEPATH,
    FlowContextRuleError,
    flow_context_iri,
    flow_context_rules,
    normalize_context_key,
)
from brightway_flows.domain.context import Dimension, Media, WaterBody
from brightway_flows.domain.context_registry import context_for_iri
from brightway_flows.pipeline.loading import _normalize_input_flow_record
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.creations import create_flows_for_unmatched_rows
from brightway_flows.merge.report import UnmatchedReason, UnmatchedRow
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes
from brightway_flows.sources import (
    base_source_list,
    known_source_lists,
    resolve_source_list,
)
from brightway_flows.transformers.unit_normalization import build_units_index

EF = "EF 3.1"
EF_WATER = [
    "Resources",
    "Resources from water",
    "Renewable material resources from water",
]
PREFIX = "https://vocab.brightway.one/flow-contexts/"
LAKE = PREFIX + "reso-wate-lake"


def _ef_flows_path() -> Path:
    """Where *this* data directory keeps the extracted base list.

    Asked of the source list rather than spelled out.  Two tests below read
    `Path.home() / ".local/share/brightway-flows/ef-31-flows.json"`
    directly, which is the one file a worktree must not share: a worktree has
    its own data directory precisely because two branches write different
    extractions to that name, and a test reading past
    `BRIGHTWAY_FLOWS_DATA_DIR` reports on whichever branch built last
    (#82).
    """
    return base_source_list().flows_path


@cache
def _ef_water_flows() -> tuple[dict, ...]:
    """EF 3.1's rows in the water-resource compartment, parsed once.

    The file is 207 MB and holds 94,062 rows.  Parsed per test method it cost
    about 1.3 s five times over in a 57 s suite, for one answer that does not
    change between them.

    Raw rows, not records: this is the extracted file as it was written, which
    is an external payload and stays a dict.
    """
    return tuple(
        flow
        for flow in json.loads(_ef_flows_path().read_bytes())
        if flow["context"] == EF_WATER
    )

REGISTERED_ECOINVENT = (
    "ecoinvent-3.8",
    "ecoinvent-3.9.1",
    "ecoinvent-3.10.1",
    "ecoinvent-3.11",
    "ecoinvent-3.12",
)


def _rows():
    payload = orjson.loads(MANUAL_MAPPING_FILEPATH.read_bytes())
    return payload["flow_specific_context_mappings"]


@cache
def _shipped_ecoinvent_flows() -> dict[str, dict[str, dict]] | None:
    """``source_label -> uuid -> flow`` for every registered ecoinvent release.

    ``None`` when the vendor files are not fetched, so a check that needs them
    skips rather than failing for a reason that is not about the rules.  Cached
    because two tests read the same five files and they are tens of megabytes.
    """
    sources = {
        source.source_label: source.flows_path
        for source in known_source_lists().values()
        if source.source_label in REGISTERED_ECOINVENT
    }
    if set(sources) != set(REGISTERED_ECOINVENT):
        return None
    if any(not path.exists() for path in sources.values()):
        return None
    return {
        label: {f["uuid"]: f for f in json.loads(path.read_bytes())}
        for label, path in sources.items()
    }


class ResolutionTestCase(unittest.TestCase):
    """The rule, and the order the two rules are consulted in."""

    def test_a_named_flow_gets_its_own_context(self):
        # EF's `lake water`, which shares its compartment with five other bodies.
        self.assertEqual(
            flow_context_iri(EF, "c506b970-7b92-452f-8d6f-05d4f203d958", EF_WATER),
            LAKE,
        )

    def test_an_unnamed_flow_gets_nothing_and_falls_through(self):
        self.assertIsNone(flow_context_iri(EF, "not-a-flow-in-any-list", EF_WATER))

    def test_the_specific_rule_beats_the_compartment_rule(self):
        """The point of the file. `lake water` and `water` share a compartment;
        only one of them has a body."""
        expectations = ContextExpectations(
            _by_source_context={tuple(x.lower() for x in EF_WATER): "reso-wate-DEFAULT"},
            _source_label=EF,
        )
        self.assertEqual(
            expectations.resolve(
                "c506b970-7b92-452f-8d6f-05d4f203d958", EF_WATER, "lake water"
            ),
            LAKE,
        )
        self.assertEqual(
            # `water`, which has no per-flow row and no body.
            expectations.resolve(
                "419682fe-60fb-4b43-be89-bf2824b51104", EF_WATER, "water"
            ),
            "reso-wate-DEFAULT",
        )

    def test_there_is_no_way_to_the_compartment_rule_alone(self):
        """`by_compartment` was an escape hatch for a caller summarising a
        compartment rather than placing a row, and the one caller it had was
        placing a row: `_add_flow_in_missing_context` created a flow in whatever
        context the compartment defaults to, for a row whose uuid and name were
        both in hand (#52). One way in, and it takes the row."""
        self.assertFalse(hasattr(ContextExpectations, "by_compartment"))


class StaleRowTestCase(unittest.TestCase):
    """A rule that names a flow by uuid outlives the flow moving compartment."""

    def test_a_row_describing_the_wrong_compartment_raises(self):
        with self.assertRaises(FlowContextRuleError) as caught:
            flow_context_iri(
                EF,
                "c506b970-7b92-452f-8d6f-05d4f203d958",
                ["Emissions", "Emissions to water", "Emissions to fresh water"],
            )
        message = str(caught.exception)
        self.assertIn("the vendor moved it", message.lower())

    def test_it_does_not_silently_skip_instead(self):
        """Skipping would be worse than raising: the curated body would vanish
        from the output with nothing said."""
        with self.assertRaises(FlowContextRuleError):
            flow_context_iri(EF, "c506b970-7b92-452f-8d6f-05d4f203d958", ["nonsense"])


class ReentrantTransformTestCase(unittest.TestCase):
    """The transform sees its own output, and that is not a vendor move.

    `default_context_mapping` writes the consensus context, and the pipeline
    runs it more than once, so on the second pass the flow already has one.  The
    first version of this feature read the *context* field to find the
    compartment and so raised `FlowContextRuleError` on every EF water flow with
    a rule -- a full 80,000-flow pipeline run found it, and the 400-flow harness
    could not, because `--max-flows N` takes `flows[:N]` and EF's water
    withdrawals sit at indices 12,722 to 75,846 of 94,062.

    The confusion the fix worked around is now gone at the source: `context`
    holds the consensus context and nothing else, and the compartment is
    `provided.context` (#97).  These tests stay because the rule lookup is
    still handed whatever a caller has, and must answer "not a move" rather than
    raise when that is not a compartment.
    """

    LAKE_WATER = "c506b970-7b92-452f-8d6f-05d4f203d958"

    def test_an_already_rewritten_context_is_not_a_move(self):
        rewritten = {"dimension": "Resource", "media": "Water", "water_body": "Lake"}
        self.assertIsNone(flow_context_iri(EF, self.LAKE_WATER, rewritten))

    def test_an_empty_context_is_not_a_move(self):
        self.assertIsNone(flow_context_iri(EF, self.LAKE_WATER, []))
        self.assertIsNone(flow_context_iri(EF, self.LAKE_WATER, None))

    def test_a_real_disagreement_still_raises(self):
        """Softening the unreadable case must not soften the real one."""
        with self.assertRaises(FlowContextRuleError):
            flow_context_iri(
                EF,
                self.LAKE_WATER,
                ["Emissions", "Emissions to water", "Emissions to fresh water"],
            )

    def test_the_transformer_reads_the_input_snapshot(self):
        """Both stages key on `provided.context`; `merge/rows.py` already did."""
        from brightway_flows.transformers.default_context_mapping import (
            DefaultContextMappingTransformer,
        )

        flow = Flow.from_dict(
            _normalize_input_flow_record(
                {
                    "uuid": self.LAKE_WATER,
                    "name": "lake water",
                    "source": EF,
                    "unit": "m3",
                    "context": list(EF_WATER),
                }
            )
        )
        transformer = DefaultContextMappingTransformer()
        transformer.setup()

        first = transformer.transform([flow])
        self.assertIn(LAKE, [c.new_value for c in first if c.field == "context_iri"])

        # Apply what the first pass decided, then run again over our own output.
        for change in first:
            setattr(flow, change.field, change.new_value)
        self.assertEqual(transformer.transform([flow]), [])


def _compartment_iri(row):
    """What the row's compartment alone would have said."""
    return context_iri_by_source_context(row["source"]).get(
        normalize_context_key(row["source_context"])
    )


def _water_body_refinements():
    """Rows that split one water compartment into its bodies.

    What this file was built for, and for a long time all it held: EF 3.1 gives
    six water bodies one compartment, so the body can only come from the name.
    BAFU's rows are the other kind -- a vendor filing a mineral, two water
    resources and standing timber under `resources / land` -- and they are not
    refining a compartment, they are leaving it.
    """
    return [
        row
        for row in _rows()
        if (iri := _compartment_iri(row))
        and context_for_iri(iri).dimension is Dimension.RESOURCE
        and context_for_iri(iri).media is Media.WATER
    ]


class RowsTestCase(unittest.TestCase):
    def test_every_water_refinement_names_a_water_resource_context(self):
        """A row splitting a water compartment must land in that compartment."""
        rows = _water_body_refinements()
        self.assertTrue(rows, "no water refinements left; this test proves nothing")
        for row in rows:
            with self.subTest(source=row["source"], name=row["source_name"]):
                context = context_for_iri(row["context_iri"])
                self.assertEqual(context.dimension, Dimension.RESOURCE)
                self.assertEqual(context.media, Media.WATER)

    def test_no_water_refinement_asserts_unknown(self):
        """A row exists to say something the compartment could not. `Unknown` is
        what the compartment already says, so a row asserting it is noise that
        reads like a decision.

        Scoped to the refinements. A row that moves a flow out of its
        compartment entirely says plenty even when the body is unknown: BAFU's
        process water goes from `Land use / Occupation` to a water resource, and
        which body it came from is genuinely not recorded."""
        for row in _water_body_refinements():
            with self.subTest(name=row["source_name"]):
                self.assertNotEqual(
                    context_for_iri(row["context_iri"]).water_body, WaterBody.UNKNOWN
                )

    def test_every_row_says_something_its_compartment_could_not(self):
        """The invariant both kinds share, and the reason a row is allowed.

        A row whose target is what the compartment rule already gives is not a
        decision, it is a duplicate that will go stale silently when the
        compartment rule moves."""
        for row in _rows():
            with self.subTest(source=row["source"], name=row["source_name"]):
                self.assertNotEqual(row["context_iri"], _compartment_iri(row))

    def test_every_row_carries_its_reasoning(self):
        for row in _rows():
            with self.subTest(name=row["source_name"]):
                self.assertGreater(len(row.get("comment", "")), 40)

    def test_the_same_flow_is_read_the_same_way_in_every_ecoinvent_version(self):
        """#40 repointed two contexts for 3.8 and 3.12 only, and left the other
        three behind (#41). Not repeating that: a body decided for one release
        is decided for every release that ships the same flow.

        **Which is not the same as every registered release.** This used to
        require all five, keyed on the flow's name, and that held only because
        the five families it covered happen to be shipped by all five releases
        under one name. Neither is guaranteed. `Water, green` reaches the list
        in 3.11 and 3.12 and does not exist in 3.8, 3.9.1 or 3.10.1, so a rule
        for it in all five would name a uuid three releases do not carry --
        which the sibling test below rejects, and rightly, because a uuid no
        version carries is indistinguishable from a typo.

        And the identity a rule is about is the uuid *and* the name together,
        not either alone. ecoinvent reuses flow identifiers between releases:
        `c5035ce2-5ee5-431f-a287-4b25da42be74` is `Peat` in 3.9.1 through 3.12
        and `Peat, in ground` in 3.8, and those are two separately published
        substances -- BAFU's own curated peat row reaches the second one. #89
        rules the first and deliberately leaves the second alone, so grouping by
        name would demand five releases for a four-release flow, and grouping by
        uuid alone would demand a rule for a substance the issue was never
        about. Keyed on the pair, scoped to the releases that ship it (#89).
        """
        shipped = _shipped_ecoinvent_flows()
        if shipped is None:
            self.skipTest("vendor flow files not fetched")
        by_identity: dict[tuple[str, str], dict[str, str]] = {}
        for row in _rows():
            if not row["source"].startswith("ecoinvent-"):
                continue
            key = (row["source_uuid"], row["source_name"])
            by_identity.setdefault(key, {})[row["source"]] = row["context_iri"]
        self.assertTrue(by_identity)
        for (uuid, name), by_version in by_identity.items():
            with self.subTest(uuid=uuid, name=name):
                ships_it = {
                    source
                    for source in REGISTERED_ECOINVENT
                    if (flow := shipped[source].get(uuid)) is not None
                    and flow["name"] == name
                }
                self.assertEqual(
                    set(by_version),
                    ships_it,
                    "every release shipping this flow needs the same rule",
                )
                self.assertEqual(len(set(by_version.values())), 1)

    def test_every_rule_names_a_flow_the_source_actually_ships(self):
        """A uuid no version carries is inert, and inert is indistinguishable
        from a typo. These rows are few enough to check against the vendor
        files, so a mistyped uuid fails here rather than doing nothing."""
        # Keyed off the registry rather than a literal list of versions: a row
        # naming a list this dict had never heard of used to raise `KeyError`
        # from a subtest, which reads like a broken test rather than a rule
        # nobody checked. Every registered list is covered by being registered.
        files = {
            source.source_label: source.flows_path
            for source in (base_source_list(), *known_source_lists().values())
        }
        named = {row["source"] for row in _rows()}
        if unknown := named - set(files):
            self.fail(f"rows name lists that are not registered: {sorted(unknown)}")
        missing = [files[source] for source in sorted(named) if not files[source].exists()]
        if missing:
            self.skipTest(f"vendor flow files not fetched: {missing[0].name}")

        shipped = {
            source: {f["uuid"]: f for f in json.loads(files[source].read_bytes())}
            for source in sorted(named)
        }
        for row in _rows():
            with self.subTest(source=row["source"], name=row["source_name"]):
                flow = shipped[row["source"]].get(row["source_uuid"])
                self.assertIsNotNone(flow, "uuid is in no version of this list")
                self.assertEqual(flow["name"], row["source_name"])
                self.assertEqual(list(flow["context"]), list(row["source_context"]))


class SeparationTestCase(unittest.TestCase):
    """What the body axis buys, measured on EF 3.1's own compartment.

    Deduplication signs on `(flow_object_id, context_iri, unit)` among other
    fields, so two flows sharing a `(context, unit)` are not guaranteed to
    collapse -- but two flows *not* sharing one cannot.  Splitting the buckets is
    the necessary half, and it is the half a body can do.
    """

    def _water_flows(self):
        if not _ef_flows_path().exists():
            self.skipTest("ef-31-flows.json not fetched")
        return list(_ef_water_flows())

    def _expectations(self):
        from brightway_flows.context_mapping import context_iri_by_source_context

        return ContextExpectations(
            _by_source_context=dict(context_iri_by_source_context(EF)),
            _source_label=EF,
        )

    def _buckets(self, flows, resolve):
        buckets: dict[tuple, list[str]] = {}
        for flow in flows:
            key = (resolve(flow), flow["unit"])
            buckets.setdefault(key, []).append(flow["name"])
        return buckets

    def test_eleven_flows_go_from_two_buckets_to_six(self):
        flows = self._water_flows()
        expectations = self._expectations()
        self.assertEqual(len(flows), 11)

        # "Before" is the compartment rules on their own, read from the loader
        # rather than through `ContextExpectations`: placing a row without its
        # uuid and name is not something that object offers any more (#52).
        compartments = context_iri_by_source_context(EF)
        before = self._buckets(
            flows,
            lambda f: compartments.get(
                tuple(str(x).lower() for x in f["context"])
            ),
        )
        after = self._buckets(
            flows, lambda f: expectations.resolve(f["uuid"], f["context"], f["name"])
        )
        self.assertEqual(len(before), 2, sorted(before))
        self.assertEqual(len(after), 6, sorted(after))

    def test_what_is_left_over_needs_the_material_axis_not_the_body(self):
        """The residue is not a gap in this PR; it is the other axis's work.

        `sea water` and `Water Cooling sea` are both drawn from the ocean in
        kilograms, so no water body can separate them -- `sea water` against
        `cooling water` is a material distinction.  Likewise the five m3 flows
        with no body: brine, cooling water, turbine water, fresh water and
        unqualified water.  See `plans/water-taxonomy.md` sections 1 and 3.
        """
        flows = self._water_flows()
        expectations = self._expectations()
        after = self._buckets(
            flows, lambda f: expectations.resolve(f["uuid"], f["context"], f["name"])
        )
        still_shared = {
            key: sorted(names) for key, names in after.items() if len(names) > 1
        }
        self.assertEqual(
            still_shared,
            {
                (PREFIX + "reso-wate", "m3"): [
                    "Water to Cooling",
                    "Water to turbine",
                    "Water, salt, sole",
                    "freshwater",
                    "water",
                ],
                (PREFIX + "reso-wate-ocea", "kg"): ["Water Cooling sea", "sea water"],
            },
        )


class WhyTheSplitRecoversFlowsTestCase(unittest.TestCase):
    """The mechanism, not the correlation.

    `pipeline/deduplication.py` signs on every field of the `ElementaryFlow`
    record except identity, `lcia_methods`, `source_refs` and the deprecation
    flags -- so `general_comment` is in the signature.  EF 3.1 gives `ground
    water`, `freshwater`, `river water` and `lake water` a **byte-identical**
    comment, and before this PR all four shared a flow object, a unit and the
    single `reso-wate` context.  One signature, four flows: three were
    deprecated onto the fourth.

    Splitting three of them onto their own bodies leaves the fourth alone in its
    signature group, so this PR frees `freshwater` as well -- and `freshwater`
    has no per-flow rule.  It is rescued by the others leaving.

    `Water to Cooling`, `Water to turbine` and `Water, salt, sole` are the other
    signature group: all three carry no comment at all.  No water body separates
    them, so they still collapse, and that is #31 waiting on the material axis.
    """

    RESCUED = {"ground water", "freshwater", "river water", "lake water"}
    STILL_COLLIDING = {"Water to Cooling", "Water to turbine", "Water, salt, sole"}

    def _by_name(self):
        if not _ef_flows_path().exists():
            self.skipTest("ef-31-flows.json not fetched")
        return {flow["name"]: flow for flow in _ef_water_flows()}

    def test_the_four_scarcity_flows_share_one_comment(self):
        """If EF ever gives them different comments, the collapse dissolves on
        its own and this PR stops being what fixes it."""
        flows = self._by_name()
        comments = {flows[name]["general_comment"] for name in self.RESCUED}
        self.assertEqual(len(comments), 1, "the four no longer share a comment")
        self.assertIsNotNone(comments.pop())

    def test_the_colliding_three_share_the_absence_of_one(self):
        flows = self._by_name()
        for name in self.STILL_COLLIDING:
            with self.subTest(name=name):
                self.assertIsNone(flows[name]["general_comment"])

    def test_the_split_separates_the_first_group_and_not_the_second(self):
        """What the bodies can and cannot do, stated as one assertion."""
        flows = self._by_name()
        expectations = ContextExpectations(
            _by_source_context=dict(context_iri_by_source_context(EF)),
            _source_label=EF,
        )

        def contexts(names):
            return {
                expectations.resolve(
                    flows[n]["uuid"], flows[n]["context"], flows[n]["name"]
                )
                for n in names
            }

        # Three of the four leave, so all four end up alone in their group.
        self.assertEqual(len(contexts(self.RESCUED)), 4)
        # Nothing separates the other three; the material axis has to.
        self.assertEqual(len(contexts(self.STILL_COLLIDING)), 1)

    def test_general_comment_is_still_in_the_dedup_signature(self):
        """The premise of everything above. If `general_comment` were excluded,
        the four would collapse whatever their contexts."""
        from brightway_flows.pipeline import deduplication

        excluded = deduplication._elementary_duplicate_signature.__doc__ or ""
        self.assertNotIn("general_comment", excluded)
        fields = {f.name for f in dataclasses.fields(ElementaryFlow)}
        self.assertIn("general_comment", fields)
        self.assertIn("context_iri", fields)


class LoaderValidationTestCase(unittest.TestCase):
    """What a row has to carry, and what happens when it does not.

    These are hand-written exceptions to an automatic rule, in a file a curator
    edits. Every field is load-bearing: without ``source_uuid`` the row names no
    flow, without ``context_iri`` it asserts nothing, without ``source_context``
    it cannot be checked against the vendor's next release, and without
    ``comment`` nobody can re-check the reasoning that put it there.
    """

    GOOD = {
        "source": "test-list",
        "source_uuid": "u-1",
        "source_context": ["natural resource", "in water"],
        "context_iri": PREFIX + "reso-wate-lake",
        "comment": "because",
    }

    def _rules(self, *rows):
        """Load *rows* through the real loader, with its caches cleared."""
        payload = {"default_context_mappings": [], "flow_specific_context_mappings": list(rows)}
        path = Path(mkdtemp()) / "context-manual-mapping.json"
        path.write_bytes(orjson.dumps(payload))
        with mock.patch.object(context_mapping, "MANUAL_MAPPING_FILEPATH", path):
            context_mapping._load_flow_rows.cache_clear()
            context_mapping.flow_context_rules.cache_clear()
            try:
                return context_mapping.flow_context_rules("test-list")
            finally:
                context_mapping._load_flow_rows.cache_clear()
                context_mapping.flow_context_rules.cache_clear()

    def test_a_complete_row_loads(self):
        self.assertEqual(set(self._rules(self.GOOD)), {"u-1"})

    def test_every_required_field_is_required(self):
        for field in ("source", "source_uuid", "source_context", "context_iri", "comment"):
            with self.subTest(missing=field):
                row = {k: v for k, v in self.GOOD.items() if k != field}
                if field == "source":
                    # A row with no source belongs to no list, so it is filtered
                    # out rather than reported -- assert that, not an exception.
                    self.assertEqual(self._rules(row), {})
                    continue
                with self.assertRaises(FlowContextRuleError) as caught:
                    self._rules(row)
                self.assertIn(field, str(caught.exception))

    def test_an_empty_field_counts_as_missing(self):
        for field in ("source_uuid", "context_iri", "comment"):
            with self.subTest(empty=field):
                with self.assertRaises(FlowContextRuleError):
                    self._rules({**self.GOOD, field: "   "})
        with self.assertRaises(FlowContextRuleError):
            self._rules({**self.GOOD, "source_context": []})

    def test_two_rows_for_one_flow_is_an_error_rather_than_last_wins(self):
        """Two curated statements about one flow, arbitrated by file order, is
        how #31's survivor got chosen. One flow, one rule."""
        other = {**self.GOOD, "context_iri": PREFIX + "reso-wate-ocea"}
        with self.assertRaises(FlowContextRuleError) as caught:
            self._rules(self.GOOD, other)
        message = str(caught.exception)
        self.assertIn("reso-wate-lake", message)
        self.assertIn("reso-wate-ocea", message)

    def test_the_same_uuid_under_two_sources_is_fine(self):
        """ecoinvent's uuids are stable across versions, so one flow legitimately
        has a row per version."""
        rules = self._rules(self.GOOD, {**self.GOOD, "source": "other-list"})
        self.assertEqual(set(rules), {"u-1"})

    def test_rows_for_other_lists_are_ignored(self):
        self.assertEqual(self._rules({**self.GOOD, "source": "somebody-else"}), {})

    def test_the_shipped_rows_all_load(self):
        for source in (EF, *REGISTERED_ECOINVENT):
            with self.subTest(source=source):
                self.assertTrue(flow_context_rules(source))

    def test_a_list_with_no_rows_is_not_an_error(self):
        self.assertEqual(flow_context_rules("a list nobody has mapped"), {})


class BafuCatchAllCompartmentTestCase(unittest.TestCase):
    """BAFU's two catch-all compartments, and the water filed in them.

    `resources / land` and `resources / unspecified` are where BAFU puts a row
    it has not classified.  Each maps wholesale to one context -- land use and
    ground resources -- which is right for the rows that fill them and wrong for
    the water, because neither compartment says anything about where water was
    drawn from.  `unspecified` least of all: it is the absence of a statement,
    not a statement that the water came out of the ground.

    `Water, well` sits in the same compartment and used to be the test that
    stopped this growing into a rule about water in general, on the reasoning
    that a well draws groundwater and the ground is where the compartment
    already sent it.  #89 found that backwards -- groundwater is a water body,
    not a ground resource -- so the well row moves here too, and what stops the
    rule widening now is that it is keyed on four named uuids rather than on the
    compartment: BAFU files 42 names under `resources / unspecified`, and the
    minerals and energy carriers among them are where they belong.
    """

    BAFU = "bafu-2026-v1"
    UNSPECIFIED = ["resources", "unspecified"]
    LAND = ["resources", "land"]
    WATER = PREFIX + "reso-wate"

    #: The three rows of water drawn from nature that BAFU leaves unclassified.
    NATURAL_ORIGIN = {
        "73f0a5ef-ddb2-5c74-876a-1eb50b695ac5": "Water, process ... /kg",
        "17fde9eb-4767-5355-a586-2b35fc61649f": "Water, process ... /m3",
        "bd517b6b-af3f-5c85-a1d0-4828353ba2c2": "Water, unspecified natural origin/m3",
    }

    #: Groundwater by name and by material, in the same compartment.
    WELL = "c13a514d-6615-592c-b0d2-af333adec22b"

    def test_natural_origin_water_leaves_the_ground(self):
        for uuid, name in self.NATURAL_ORIGIN.items():
            with self.subTest(name=name):
                self.assertEqual(
                    flow_context_iri(self.BAFU, uuid, self.UNSPECIFIED), self.WATER
                )

    def test_well_water_in_the_same_compartment_is_water_too(self):
        """Rewritten by #89, and the reasoning it replaces is worth keeping.

        This used to assert that the well-water row needed no rule, because "a
        well draws groundwater, so `Resource / Ground` is what its compartment
        already gives and there is nothing for a row to say."  The premise is
        right and the conclusion does not follow: groundwater is not a resource
        taken from the *ground* in this vocabulary.  `Resource / Ground` is
        where the ores, minerals and fossil fuels go; water pumped out of an
        aquifer is `Resource / Water / Unconfined aquifer`, which is where EF
        3.1 publishes it with 209 characterisation factors and where BAFU's own
        four `resources / in water` well rows already land.

        So the compartment rule's answer was wrong for this row, quietly, and
        the row minted a second `Groundwater` in `Resource / Ground` carrying no
        factor at all -- one substance in two places, and an inventory reaching
        this half scored zero against every water-use method.  The rule places
        it in water of no stated body; `water_body_from_material` then refines
        the body from the name, exactly as it does for the in-water siblings.
        """
        self.assertEqual(
            flow_context_iri(self.BAFU, self.WELL, self.UNSPECIFIED), self.WATER
        )

    def test_both_catch_alls_send_their_water_to_one_context(self):
        """The reason to do the second compartment at all.

        `resources / land` was settled first (#83).  Water of unstated origin
        is one substance in one context however BAFU filed it, and a list that
        published it in two contexts would be splitting it on nothing but which
        blank compartment the vendor happened to use.
        """
        land = flow_context_iri(
            self.BAFU, "8b11be39-c8a8-5db2-8ec6-0adf69830e77", self.LAND
        )
        unspecified = flow_context_iri(
            self.BAFU, "bd517b6b-af3f-5c85-a1d0-4828353ba2c2", self.UNSPECIFIED
        )
        self.assertEqual(land, unspecified)

    def test_a_row_still_has_to_describe_the_compartment_it_is_in(self):
        """Named here as well as in `StaleRowTestCase` because these rows are
        the ones most likely to go stale: BAFU reclassifying a row out of a
        catch-all is exactly the improvement that would make it happen, and the
        reasoning above -- that the compartment says nothing -- would no longer
        be true of it."""
        with self.assertRaises(FlowContextRuleError):
            flow_context_iri(
                self.BAFU,
                "bd517b6b-af3f-5c85-a1d0-4828353ba2c2",
                ["resources", "in water"],
            )


class BiomassEnergyCorrectionTestCase(unittest.TestCase):
    """The energy in biomass, credited back from BAFU's blank compartment.

    A resource correction is an amount of a resource written with the opposite
    sign, so it cancels an extraction only if the two land on one flow (#294).
    The biomass-energy correction is the one of BAFU's ten that the vendor files
    in two compartments, and the two did not meet: `biotic` reached EF 3.1's
    `biomass`, `unspecified` followed the compartment rule into the ground and
    minted a second flow there (#69).

    Both halves are tested.  The correction moves; the resource it corrects does
    not, because that row is one of five #89 is still holding, and a rule that
    swept up every biomass row in the compartment would be answering a question
    this one was not asked.
    """

    BAFU = "bafu-2026-v1"
    UNSPECIFIED = ["resources", "unspecified"]
    BIOTIC = PREFIX + "reso-biot"

    #: `Energy, gross calorific value, in biomass, resource correction`, the
    #: half of the pair BAFU leaves unclassified.
    CORRECTION = "d7a1eef3-0c63-51ff-bb0c-30a617e4ade9"

    #: The same correction in `resources / biotic`, which needs no rule.
    CORRECTION_BIOTIC = "c203821f-3ecf-594b-89d2-ef20f80959d0"

    #: The resource itself, in the same blank compartment.  #89's.
    RESOURCE = "feece912-d5e6-5bb7-bac0-166faf4f9552"

    def test_the_correction_is_read_as_a_biotic_resource(self):
        self.assertEqual(
            flow_context_iri(self.BAFU, self.CORRECTION, self.UNSPECIFIED), self.BIOTIC
        )

    def test_the_biotic_half_needs_no_rule_of_its_own(self):
        """`resources / biotic` already reaches biotic resources, and a rule
        restating a compartment rule is a duplicate that goes stale silently."""
        self.assertNotIn(self.CORRECTION_BIOTIC, flow_context_rules(self.BAFU))

    def test_the_resource_in_the_same_compartment_now_moves_too(self):
        """#89 answered the question this test was holding open.

        `Energy, gross calorific value, in biomass` sits in the same blank
        compartment and is split the same way.  It was left alone here because
        an extraction charged twice is a different defect from a credit that
        misses what it was crediting, and this issue was asked only about the
        credit -- #69's own comment records that the ground flow would stay
        published until #89 settled the resource.  It is settled: the energy in
        a tree is a biotic resource whichever of BAFU's three compartments the
        row was filed in, and the flow this credit was minted beside is now
        empty.
        """
        self.assertEqual(
            flow_context_iri(self.BAFU, self.RESOURCE, self.UNSPECIFIED), self.BIOTIC
        )

    def test_a_row_still_has_to_describe_the_compartment_it_is_in(self):
        with self.assertRaises(FlowContextRuleError):
            flow_context_iri(self.BAFU, self.CORRECTION, ["resources", "biotic"])


class EcoinventSideTestCase(unittest.TestCase):
    """The other list with rows, which the EF-centred tests above do not cover."""

    #: `Water, lake`, in every registered version.
    WATER_LAKE = "1acb026e-a4ff-4c40-bf22-5c34f6d1b7a3"
    IN_WATER = ["natural resource", "in water"]

    def test_it_resolves_in_every_version(self):
        uuid = next(
            row["source_uuid"]
            for row in _rows()
            if row["source"] == "ecoinvent-3.12" and row["source_name"] == "Water, lake"
        )
        for source in REGISTERED_ECOINVENT:
            with self.subTest(source=source):
                self.assertEqual(
                    flow_context_iri(source, uuid, self.IN_WATER),
                    PREFIX + "reso-wate-lake",
                )

    def test_ecoinvent_and_ef_reach_the_same_context_for_the_same_body(self):
        """The point of doing both lists: `Water, lake` and `lake water` are one
        body, and a merge can only put them together if they agree."""
        ecoinvent_uuid = next(
            row["source_uuid"]
            for row in _rows()
            if row["source"] == "ecoinvent-3.12" and row["source_name"] == "Water, lake"
        )
        self.assertEqual(
            flow_context_iri("ecoinvent-3.12", ecoinvent_uuid, self.IN_WATER),
            flow_context_iri(EF, "c506b970-7b92-452f-8d6f-05d4f203d958", EF_WATER),
        )


class EcoinventGroundCompartmentTestCase(unittest.TestCase):
    """ecoinvent's `natural resource / in ground`, and the water filed in it.

    The compartment holds ores, minerals and fossil fuels, so it maps wholesale
    to `Resource / Ground`, which is right for all of them.  One row in it is
    water drawn from an aquifer, and for that row `in ground` is the coarse half
    of the statement: the substance says which resource it is and the
    compartment only says where it was found.  The same shape as BAFU's two
    catch-alls above (#83), one list over, and found while measuring #48.

    Both halves are tested.  `Water, green` is filed in the same compartment and
    has to stay, which is the test that stops this growing into a rule about
    water in the ground.
    """

    IN_GROUND = ["natural resource", "in ground"]
    UNCONFINED_AQUIFER = PREFIX + "reso-wate-unaq"

    #: `Water, unspecified natural origin`, m3, CAS 7732-18-5.  One flow, the
    #: same uuid in all five registered releases.
    NATURAL_ORIGIN = "478e8437-1c21-4032-8438-872a6b5ddcdf"

    #: Rainfall held in soil, in the same compartment, which is not a slip.
    GREEN = "36dfb44d-db99-4cc5-bfb7-f266d69abf3e"

    def test_water_drawn_from_the_ground_is_groundwater(self):
        self.assertEqual(
            flow_context_iri("ecoinvent-3.12", self.NATURAL_ORIGIN, self.IN_GROUND),
            self.UNCONFINED_AQUIFER,
        )

    def test_it_resolves_in_every_version(self):
        """ecoinvent's flow uuids are stable across releases and this row is in
        all five, so a rule reaching one release and not another would move the
        withdrawal depending on which ecoinvent a build merged."""
        for source in REGISTERED_ECOINVENT:
            with self.subTest(source=source):
                self.assertEqual(
                    flow_context_iri(source, self.NATURAL_ORIGIN, self.IN_GROUND),
                    self.UNCONFINED_AQUIFER,
                )

    def test_green_water_in_the_same_compartment_is_decided_not_defaulted(self):
        """#89 settled the disagreement this test was holding open.

        Green water is rainfall held in soil and used by plants, which is where
        a plant reaches it, so ecoinvent filing it in the ground is a position
        rather than a slip -- EF 3.1 files its `Green water` as a resource from
        air and the two lists genuinely disagree.  That is why it was left to
        fall through to the compartment rule while the question was open.

        Leaving it open meant publishing green water in two places that cannot
        be added together, which is the defect #89 is about, so the list picks:
        EF's, because EF 3.1 is the base list and its flow is the one a method
        would characterise without this project minting a target.  The rule is
        still per-flow and still says so out loud -- what changed is that the
        answer is now written down rather than arrived at by default.
        """
        self.assertEqual(
            flow_context_iri("ecoinvent-3.12", self.GREEN, self.IN_GROUND),
            PREFIX + "reso-air",
        )

    def test_ecoinvent_and_ef_reach_the_same_context_for_groundwater(self):
        """The point of the rule.

        EF 3.1's `ground water` is the flow ecoinvent's own correspondence table
        names for this row, and it carries 209 characterisation factors.  While
        the two lists resolved to different contexts the merge refused to
        publish the row on it -- rightly, because `Ground` and `Water` are
        different media -- and minted a second groundwater flow carrying
        nothing, so the withdrawal was published twice and the half ecoinvent
        reached scored zero against every water-use method (#89).
        """
        self.assertEqual(
            flow_context_iri("ecoinvent-3.12", self.NATURAL_ORIGIN, self.IN_GROUND),
            flow_context_iri(EF, "4f462198-40cd-4184-8733-86648a20dc3f", EF_WATER),
        )

    def test_a_row_still_has_to_describe_the_compartment_it_is_in(self):
        """ecoinvent moving this row into `natural resource / in water`, where
        its four siblings already are, is exactly the improvement that would
        make this rule redundant -- and the reasoning above, that the
        compartment is the coarse half, would no longer be true of it."""
        with self.assertRaises(FlowContextRuleError):
            flow_context_iri(
                "ecoinvent-3.12", self.NATURAL_ORIGIN, ["natural resource", "in water"]
            )


class MergeIntegrationTestCase(unittest.TestCase):
    """Through the merge, not just the resolver.

    `ContextExpectations` is consulted at six call sites; the tests above hold
    the object directly. This one runs a source row through the merge's own
    creation path with the real EF 3.1 rules loaded, so the wiring is exercised
    rather than the class.
    """

    def _indexes(self):
        return MergeIndexes(
            flow_objects_by_id={},
            flow_object_label_by_id={},
            cas_index={},
            ec_index={},
            label_index={},
            pref_label_index={},
            qualifier_index={},
            flow_objects_with_cas=set(),
            context_expectations=ContextExpectations(
                _by_source_context=dict(context_iri_by_source_context(EF)),
                _source_label=EF,
            ),
            consensus_context_strings={},
            prepared_context_decisions={},
            mapping_file=None,
            source=resolve_source_list("ecoinvent-3.12"),
        )

    def _create(self, uuid, name):
        """Run one unplaceable row through the merge's creation path."""
        row = UnmatchedRow(
            source_uuid=uuid,
            source_name=name,
            source_context=list(EF_WATER),
            source_unit="m3",
            source_cas="7732-18-5",
            source_ec="",
            reason=UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE,
            matching_method="algorithm",
        )
        flow = Flow.from_dict(
            {
                "uuid": uuid,
                "identifier": uuid,
                "source": EF,
                "unit": "m3",
                "cas_numbers": ["7732-18-5"],
                "prefLabel": [{"@value": name, "@language": "en"}],
                "altLabel": [],
            }
        )
        _objects, created = create_flows_for_unmatched_rows(
            unmatched=[row],
            source_flow_by_uuid={uuid: flow},
            units_index=build_units_index(),
            indexes=self._indexes(),
            accumulator=MergeAccumulator(),
        )
        self.assertEqual(len(created), 1, "expected exactly one created flow")
        return created[0].source_context_iri

    def test_a_named_withdrawal_is_created_in_its_own_body(self):
        self.assertEqual(
            self._create("c506b970-7b92-452f-8d6f-05d4f203d958", "lake water"),
            PREFIX + "reso-wate-lake",
        )

    def test_an_unnamed_withdrawal_falls_back_to_the_compartment(self):
        """Same compartment, no per-flow rule, so the compartment rule stands."""
        self.assertEqual(
            self._create("419682fe-60fb-4b43-be89-bf2824b51104", "water"),
            PREFIX + "reso-wate",
        )

    def test_the_two_reach_different_contexts_from_one_compartment(self):
        """The whole point, asserted through the merge rather than the resolver."""
        self.assertNotEqual(
            self._create("c506b970-7b92-452f-8d6f-05d4f203d958", "lake water"),
            self._create("419682fe-60fb-4b43-be89-bf2824b51104", "water"),
        )


class VolumeOccupationTestCase(unittest.TestCase):
    """Four volumes EF 3.1 files as a use of land, which the lists that wrote
    them file as resources.

    A cavern hollowed out to hold radioactive waste, the same for low-active
    waste, an underground deposit, and the water a reservoir holds behind a dam.
    EF puts all four under `Land use / Land occupation`; ecoinvent 3.8, ecoinvent
    3.12 and BAFU put the same four under their in-ground and in-water
    compartments.  Both halves already agree about what each thing *is* -- they
    share the flow object -- so the compartment was the only thing keeping them
    apart, and while it did, each was two flows that could never meet (#72).

    Both halves are tested here too.  A rule that moves a volume out of the
    land-use dimension has to leave the 76 real occupations in EF's own list
    where they are, and `test_an_ordinary_occupation_of_land_is_left_alone` is
    what stops this growing into a rule about the compartment.
    """

    OCCUPATION = ["Land use", "Land occupation"]
    GROUND = PREFIX + "reso-grou"
    WATER = PREFIX + "reso-wate"

    #: The three underground volumes, which ecoinvent and BAFU both file in the
    #: ground.
    UNDERGROUND = {
        "da841aa2-7d85-4a6f-929c-7db64b4c4e59": "underground deposit",
        "0fdfa11c-0397-4f46-b1cf-d9266d5a5a13": "final repository, radioactive",
        "1fc2328b-d860-4aa7-ac27-34aa1cce4f9d": "final repository, low-active",
    }

    #: The fourth, which they both file in water.
    RESERVOIR = "1bd103da-4de0-4913-a45e-4dfaf79af96a"

    #: EF 3.1's `arable`: a surface, held for a time, in square-metre-years, and
    #: carrying 213 characterisation factors.  A real land occupation.
    ARABLE = "b88d3b6d-229e-477e-bce1-e16376f75c7b"

    def test_the_underground_volumes_are_ground_resources(self):
        for uuid, name in self.UNDERGROUND.items():
            with self.subTest(name=name):
                self.assertEqual(
                    flow_context_iri(EF, uuid, self.OCCUPATION), self.GROUND
                )

    def test_the_reservoir_is_a_water_resource(self):
        """The one of the four that is not a hole in the ground.

        Water impounded behind a dam is water, and both vendors file it that
        way.  The body is left unstated because they left it unstated.
        """
        self.assertEqual(
            flow_context_iri(EF, self.RESERVOIR, self.OCCUPATION), self.WATER
        )

    def test_an_ordinary_occupation_of_land_is_left_alone(self):
        """The half that stops the rule widening.

        `arable` sits in the same compartment as all four volumes and is exactly
        what that compartment means.  `None` is the resolver falling through to
        the compartment rule, which is the answer.
        """
        self.assertIsNone(flow_context_iri(EF, self.ARABLE, self.OCCUPATION))

    def test_only_the_four_volumes_are_named(self):
        """The bound on the rule, stated as a set rather than as an intention.

        EF 3.1 ships 80 flows in this compartment.  A row here for a fifth would
        be a claim about land that this reasoning does not make.
        """
        named = {
            rule.source_uuid
            for rule in flow_context_rules(EF).values()
            if rule.source_context == normalize_context_key(self.OCCUPATION)
        }
        self.assertEqual(named, set(self.UNDERGROUND) | {self.RESERVOIR})

    def test_ef_and_ecoinvent_reach_the_same_context_for_one_volume(self):
        """The point of the change, in one assertion.

        `Volume occupied, underground deposit` is one flow object on both sides.
        Once EF's half resolves to the context ecoinvent's compartment already
        gives, the two are one flow rather than two.
        """
        ecoinvent = context_iri_by_source_context("ecoinvent-3.12")[
            normalize_context_key(["natural resource", "in ground"])
        ]
        self.assertEqual(
            flow_context_iri(
                EF, "da841aa2-7d85-4a6f-929c-7db64b4c4e59", self.OCCUPATION
            ),
            ecoinvent,
        )

    def test_a_row_still_has_to_describe_the_compartment_it_is_in(self):
        """If EF ever re-files these where their authors put them, the reasoning
        above stops describing them and the row has to be re-read rather than
        applied."""
        with self.assertRaises(FlowContextRuleError):
            flow_context_iri(
                EF,
                "da841aa2-7d85-4a6f-929c-7db64b4c4e59",
                [
                    "Resources",
                    "Resources from ground",
                    "Non-renewable material resources from ground",
                ],
            )
