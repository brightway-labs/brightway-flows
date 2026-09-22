"""What `release-migrations` says happened between two releases.

Every case here is two small synthetic snapshots and the deltas between them:
a substance renamed, a flow merged into another, a flow whose source rows
split, a factor revalued.  The randonneur files are then applied with
randonneur's own functions to a toy consumer database, which is the only
test that the format written is the format read.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from randonneur import Datapackage, MigrationConfig, migrate_edges, migrate_nodes

from brightway_flows.domain.elementary_flow import minted_elementary_flow_id
from brightway_flows.domain.vocabulary import CHEMINF_CAS_REGISTRY_NUMBER
from brightway_flows.releases.alignment import AlignmentError, Fate, FateReason
from brightway_flows.releases.diff import Delta, DeltaKind, diff_releases
from brightway_flows.releases.randonneur_files import (
    MAPPINGS,
    UNRESOLVED_REPORT_SCHEMA_VERSION,
    entries,
    write_migration_files,
)
from brightway_flows.releases.rulings import (
    EntityKind,
    MigrationRuling,
    MigrationRulingError,
    RulingVerb,
)
from brightway_flows.releases.snapshot import (
    RELEASE_SNAPSHOT_SCHEMA_VERSION,
    ReleaseSnapshot,
    ReleaseStamp,
    SnapshotElementaryFlow,
    SnapshotFactor,
    SnapshotFlowObject,
    SnapshotRedirect,
    SnapshotSourceRow,
)

AIR = "https://vocab.brightway.one/flow-contexts/envi-air-unkn"
WATER = "https://vocab.brightway.one/flow-contexts/envi-wate-unkn"
CATEGORY = "3897dc04-68ec-5953-a76d-d40db54cc82a"
OTHER_CATEGORY = "5a0b2d1e-0000-5000-8000-000000000002"
LIST = ("ecoinvent", "3.12")


def _flow(
    identifier: str, obj: str, *, context: str = AIR, unit: str = "kg", label: str = "Cadmium",
    deprecated: bool = False, replaced_by: str | None = None, reason: str = "", **fields,
) -> SnapshotElementaryFlow:
    values = dict(
        identifier=identifier, source="EF 3.1", cas_numbers=[], ec_numbers=[],
        context_iri=context, unit=unit, unit_iri="", prefLabel=label, altLabel=[],
        properties={}, references=[], definition=[], jsonld_type=["skos:Concept"],
    )
    values.update(fields)
    return SnapshotElementaryFlow(
        **values, flow_object_id=obj, is_deprecated=deprecated,
        replaced_by_identifier=replaced_by, deprecation_reason=reason,
    )


def _object(object_id: str, label: str, cas: str | None = None, **fields) -> SnapshotFlowObject:
    return SnapshotFlowObject(
        flow_object_id=object_id, prefLabel=label,
        classifications={CHEMINF_CAS_REGISTRY_NUMBER: [cas]} if cas else {},
        **fields,
    )


def _factor(flow: str, amount: float, *, category: str = CATEGORY, geography: str = "") -> SnapshotFactor:
    return SnapshotFactor(
        impact_category_id=category, elementary_flow_uuid=flow, geography=geography,
        amount=amount, method="EF", category="Climate change", implemented_by="JRC",
    )


def _row(source_uuid: str, flow: str, list_key: tuple[str, str] = LIST) -> SnapshotSourceRow:
    return SnapshotSourceRow(
        list_name=list_key[0], list_version=list_key[1],
        source_flow_uuid=source_uuid, elementary_flow_uuid=flow,
    )


def _redirect(identifier: str, replaced_by: str | None, reason: str) -> SnapshotRedirect:
    return SnapshotRedirect(identifier=identifier, reason=reason, replaced_by_identifier=replaced_by)


def _snapshot(
    version: str, flows=(), objects=(), factors=(), rows=(), redirects=(),
    lists: tuple[str, ...] = ("ecoinvent-3.12",),
) -> ReleaseSnapshot:
    stamp = ReleaseStamp(
        version=version, development=False, run_id=f"run-{version}",
        revision="a" * 40 if version == "1.0.0" else "b" * 40, revision_dirty=False,
        timestamp="2026-09-02T06:01:34+00:00", merged_lists=list(lists),
    )
    return ReleaseSnapshot(
        schema_version=RELEASE_SNAPSHOT_SCHEMA_VERSION, stamp=stamp,
        flow_objects=list(objects), elementary_flows=list(flows), redirects=list(redirects),
        characterization_factors=list(factors), source_rows=list(rows),
    )


def _by(deltas: list[Delta], identifier: str) -> Delta:
    matching = [d for d in deltas if d.identifier == identifier]
    assert len(matching) == 1, f"{identifier}: {matching}"
    return matching[0]


def _key(flow: str, category: str = CATEGORY, geography: str = "") -> str:
    return SnapshotFactor.key_text((category, flow, geography))


class NothingChangedTestCase(unittest.TestCase):
    def test_a_release_diffed_against_itself_is_empty(self):
        snapshot = _snapshot(
            "1.0.0",
            flows=[_flow("f1", "fo-1"), _flow("f2", "fo-1", context=WATER)],
            objects=[_object("fo-1", "Cadmium", "7440-43-9")],
            factors=[_factor("f1", 1.0), _factor("f2", 2.0)],
            rows=[_row("s1", "f1"), _row("s2", "f2")],
        )
        diff = diff_releases(snapshot, snapshot)
        self.assertTrue(diff.is_empty())
        self.assertEqual(sum(diff.counts().values()), 0)

    def test_the_source_lists_must_match(self):
        before = _snapshot("1.0.0", lists=("ecoinvent-3.12",))
        after = _snapshot("1.1.0", lists=("ecoinvent-3.12", "bafu-2026-v1"))
        with self.assertRaises(AlignmentError):
            diff_releases(before, after)
        self.assertTrue(diff_releases(before, after, allow_different_sources=True).is_empty())


class FieldsChangedTestCase(unittest.TestCase):
    def test_a_renamed_flow_is_an_update_naming_the_field(self):
        before = _snapshot("1.0.0", flows=[_flow("f1", "fo-1", label="Cadmium")])
        after = _snapshot("1.1.0", flows=[_flow("f1", "fo-1", label="Cadmium(2+)")])
        delta = _by(diff_releases(before, after).elementary_flows, "f1")
        self.assertEqual(delta.kind, DeltaKind.UPDATED)
        self.assertEqual(delta.changed_fields, ["prefLabel"])
        self.assertEqual(delta.after, {"prefLabel": "Cadmium(2+)"})
        self.assertIn("'Cadmium' -> 'Cadmium(2+)'", delta.comment)

    def test_an_update_carries_the_whole_new_value_of_a_nested_field(self):
        """randonneur overwrites a nested value rather than merging into it."""
        before = _snapshot("1.0.0", flows=[_flow("f1", "fo-1", properties={"a": 1})])
        after = _snapshot("1.1.0", flows=[_flow("f1", "fo-1", properties={"a": 1, "b": 2})])
        delta = _by(diff_releases(before, after).elementary_flows, "f1")
        self.assertEqual(delta.after, {"properties": {"a": 1, "b": 2}})

    def test_a_corrected_registry_number_is_one_change_to_a_substance(self):
        before = _snapshot("1.0.0", objects=[_object("fo-1", "Cadmium", "7440-43-8")])
        after = _snapshot("1.1.0", objects=[_object("fo-1", "Cadmium", "7440-43-9")])
        delta = _by(diff_releases(before, after).flow_objects, "fo-1")
        self.assertEqual(delta.kind, DeltaKind.UPDATED)
        self.assertEqual(delta.changed_fields, ["classifications"])

    def test_a_revalued_factor_is_an_update_of_its_amount(self):
        flows = [_flow("f1", "fo-1")]
        before = _snapshot("1.0.0", flows=flows, factors=[_factor("f1", 1.0)])
        after = _snapshot("1.1.0", flows=flows, factors=[_factor("f1", 1.5)])
        delta = _by(diff_releases(before, after).factors, _key("f1"))
        self.assertEqual(delta.kind, DeltaKind.UPDATED)
        self.assertEqual((delta.before, delta.after), ({"amount": 1.0}, {"amount": 1.5}))

    def test_a_new_flow_and_its_factor_are_created_in_full(self):
        before = _snapshot("1.0.0", flows=[_flow("f1", "fo-1")])
        after = _snapshot(
            "1.1.0", flows=[_flow("f1", "fo-1"), _flow("f2", "fo-1", context=WATER)],
            factors=[_factor("f2", 3.0)],
        )
        diff = diff_releases(before, after)
        flow = _by(diff.elementary_flows, "f2")
        self.assertEqual(flow.kind, DeltaKind.CREATED)
        self.assertEqual(flow.after["context_iri"], WATER)
        self.assertNotIn("@id", flow.after)
        factor = _by(diff.factors, _key("f2"))
        self.assertEqual(factor.kind, DeltaKind.CREATED)
        self.assertEqual(factor.after["amount"], 3.0)


class RedirectTestCase(unittest.TestCase):
    """The after release's own redirects are asked first."""

    def _pair(self, reason: str, replaced_by: str | None = "f2"):
        before = _snapshot("1.0.0", flows=[_flow("f1", "fo-1"), _flow("f2", "fo-1")])
        after = _snapshot(
            "1.1.0",
            flows=[
                _flow("f1", "fo-1", deprecated=True, replaced_by=replaced_by, reason=reason),
                _flow("f2", "fo-1"),
            ],
            redirects=[_redirect("f1", replaced_by, reason)],
        )
        return diff_releases(before, after)

    def test_an_identity_merge_is_followed(self):
        delta = _by(self._pair("identity-merge").elementary_flows, "f1")
        self.assertEqual((delta.kind, delta.replaced_by), (DeltaKind.REPLACED, "f2"))
        self.assertEqual(delta.reason, FateReason.REDIRECT.value)
        self.assertEqual(delta.conversion_factor, 1.0)

    def test_a_scheme_change_is_followed(self):
        delta = _by(self._pair("identifier-scheme-change").elementary_flows, "f1")
        self.assertEqual((delta.kind, delta.replaced_by), (DeltaKind.REPLACED, "f2"))

    def test_a_context_collapse_is_refused_with_the_survivor_as_candidate(self):
        delta = _by(self._pair("context-collapse").elementary_flows, "f1")
        self.assertEqual(delta.kind, DeltaKind.UNRESOLVED)
        self.assertEqual(delta.reason, FateReason.REFUSED_REDIRECT.value)
        self.assertEqual(delta.candidates, ["f2"])

    def test_a_withdrawn_row_is_a_deletion(self):
        delta = _by(self._pair("source-row-withdrawn", None).elementary_flows, "f1")
        self.assertEqual(delta.kind, DeltaKind.DELETED)
        self.assertEqual(delta.reason, FateReason.WITHDRAWN.value)

    def test_a_redirect_to_an_unpublished_flow_raises(self):
        with self.assertRaises(AlignmentError):
            self._pair("identity-merge", replaced_by="nowhere")


class SourceRowTestCase(unittest.TestCase):
    """Where the after release does not say, the source rows are followed."""

    def test_a_regrouped_substance_moves_its_minted_flows_with_it(self):
        old_flow = minted_elementary_flow_id("fo-old", AIR)
        new_flow = minted_elementary_flow_id("fo-new", AIR)
        before = _snapshot(
            "1.0.0", flows=[_flow(old_flow, "fo-old")],
            objects=[_object("fo-old", "Cadmium", "7440-43-8")],
            factors=[_factor(old_flow, 1.0)], rows=[_row("s1", old_flow)],
        )
        after = _snapshot(
            "1.1.0", flows=[_flow(new_flow, "fo-new")],
            objects=[_object("fo-new", "Cadmium", "7440-43-9")],
            factors=[_factor(new_flow, 1.0)], rows=[_row("s1", new_flow)],
        )
        diff = diff_releases(before, after)
        flow = _by(diff.elementary_flows, old_flow)
        self.assertEqual((flow.kind, flow.replaced_by), (DeltaKind.REPLACED, new_flow))
        self.assertEqual(flow.reason, FateReason.SOURCE_ROWS.value)
        obj = _by(diff.flow_objects, "fo-old")
        self.assertEqual((obj.kind, obj.replaced_by), (DeltaKind.REPLACED, "fo-new"))
        # The factor follows the flow: the same amount under the new key is no change.
        self.assertEqual(diff.factors, [])
        self.assertEqual(diff.minted_identifiers_checked, 1)

    def test_a_split_is_unresolved_and_takes_its_factors_and_substance_with_it(self):
        before = _snapshot(
            "1.0.0", flows=[_flow("f1", "fo-1")], objects=[_object("fo-1", "Water")],
            factors=[_factor("f1", 1.0)], rows=[_row("s1", "f1"), _row("s2", "f1")],
        )
        after = _snapshot(
            "1.1.0", flows=[_flow("f2", "fo-2"), _flow("f3", "fo-3")],
            objects=[_object("fo-2", "Water"), _object("fo-3", "Water vapour")],
            factors=[_factor("f2", 1.0), _factor("f3", 0.5)],
            rows=[_row("s1", "f2"), _row("s2", "f3")],
        )
        diff = diff_releases(before, after)
        flow = _by(diff.elementary_flows, "f1")
        self.assertEqual((flow.kind, flow.reason), (DeltaKind.UNRESOLVED, FateReason.SPLIT.value))
        self.assertEqual(flow.candidates, ["f2", "f3"])
        factor = _by(diff.factors, _key("f1"))
        self.assertEqual((factor.kind, factor.reason), (DeltaKind.UNRESOLVED, "flow-unresolved"))
        obj = _by(diff.flow_objects, "fo-1")
        self.assertEqual((obj.kind, obj.reason), (DeltaKind.UNRESOLVED, FateReason.FLOWS_UNRESOLVED.value))
        self.assertEqual(len(diff.unresolved), 3)

    def test_a_row_shared_by_a_deprecated_pair_counts_the_live_flow_only(self):
        """`elementary_flow_sources` holds a deduplicated pair's rows on both
        flows; only the live one is a target."""
        before = _snapshot("1.0.0", flows=[_flow("f1", "fo-1")], rows=[_row("s1", "f1")])
        after = _snapshot(
            "1.1.0",
            flows=[_flow("f2", "fo-1"), _flow("f3", "fo-1", deprecated=True, replaced_by="f2")],
            rows=[_row("s1", "f2"), _row("s1", "f3")],
        )
        delta = _by(diff_releases(before, after).elementary_flows, "f1")
        self.assertEqual((delta.kind, delta.replaced_by), (DeltaKind.REPLACED, "f2"))

    def test_a_unit_change_is_unresolved(self):
        before = _snapshot("1.0.0", flows=[_flow("f1", "fo-1", unit="kg")], rows=[_row("s1", "f1")])
        after = _snapshot("1.1.0", flows=[_flow("f2", "fo-1", unit="m3")], rows=[_row("s1", "f2")])
        delta = _by(diff_releases(before, after).elementary_flows, "f1")
        self.assertEqual((delta.kind, delta.reason), (DeltaKind.UNRESOLVED, FateReason.UNIT_CHANGE.value))
        self.assertIn("m3", delta.comment)

    def test_rows_that_reach_nothing_delete_the_flow_and_its_factors(self):
        before = _snapshot(
            "1.0.0", flows=[_flow("f1", "fo-1"), _flow("f9", "fo-9")],
            objects=[_object("fo-1", "Cadmium"), _object("fo-9", "Nothing")],
            factors=[_factor("f1", 1.0)], rows=[_row("s1", "f1"), _row("s9", "f9")],
        )
        after = _snapshot(
            "1.1.0", flows=[_flow("f9", "fo-9")], objects=[_object("fo-9", "Nothing")],
            rows=[_row("s9", "f9")],
        )
        diff = diff_releases(before, after)
        self.assertEqual(_by(diff.elementary_flows, "f1").kind, DeltaKind.DELETED)
        self.assertEqual(_by(diff.flow_objects, "fo-1").kind, DeltaKind.DELETED)
        self.assertEqual(_by(diff.factors, _key("f1")).kind, DeltaKind.DELETED)

    def test_rows_of_a_list_the_after_release_did_not_merge_are_unresolved(self):
        before = _snapshot(
            "1.0.0", flows=[_flow("f1", "fo-1")], rows=[_row("s1", "f1", ("bafu", "2026-v1"))],
            lists=("ecoinvent-3.12", "bafu-2026-v1"),
        )
        after = _snapshot("1.1.0", lists=("ecoinvent-3.12",))
        delta = _by(
            diff_releases(before, after, allow_different_sources=True).elementary_flows, "f1"
        )
        self.assertEqual((delta.kind, delta.reason), (DeltaKind.UNRESOLVED, FateReason.LIST_NOT_MERGED.value))

    def test_a_flow_with_no_source_row_cannot_be_followed(self):
        before = _snapshot("1.0.0", flows=[_flow("f1", "fo-1")])
        after = _snapshot("1.1.0")
        delta = _by(diff_releases(before, after).elementary_flows, "f1")
        self.assertEqual(delta.reason, FateReason.NO_SOURCE_ROWS.value)

    def test_a_merge_into_a_surviving_flow_keeps_the_survivors_factor(self):
        """Two flows became one: the survivor's own factor row is the one the
        consumer keeps, and the merged flow's is not a second update on it."""
        before = _snapshot(
            "1.0.0", flows=[_flow("f1", "fo-1"), _flow("f2", "fo-1")],
            factors=[_factor("f1", 1.0), _factor("f2", 2.0)],
            rows=[_row("s1", "f1"), _row("s2", "f2")],
        )
        after = _snapshot(
            "1.1.0", flows=[_flow("f2", "fo-1")], factors=[_factor("f2", 2.0)],
            rows=[_row("s1", "f2"), _row("s2", "f2")],
        )
        diff = diff_releases(before, after)
        self.assertEqual(_by(diff.elementary_flows, "f1").replaced_by, "f2")
        self.assertEqual(diff.factors, [])

    def test_a_vanished_impact_category_leaves_its_factors_unresolved(self):
        flows = [_flow("f1", "fo-1")]
        before = _snapshot("1.0.0", flows=flows, factors=[_factor("f1", 1.0, category=OTHER_CATEGORY)])
        after = _snapshot("1.1.0", flows=flows)
        delta = _by(diff_releases(before, after).factors, _key("f1", OTHER_CATEGORY))
        self.assertEqual((delta.kind, delta.reason), (DeltaKind.UNRESOLVED, "category-gone"))


class RulingTestCase(unittest.TestCase):
    def _split(self):
        before = _snapshot(
            "1.0.0", flows=[_flow("f1", "fo-1")], factors=[_factor("f1", 1.0)],
            rows=[_row("s1", "f1"), _row("s2", "f1")],
        )
        after = _snapshot(
            "1.1.0", flows=[_flow("f2", "fo-1"), _flow("f3", "fo-1")],
            factors=[_factor("f2", 1.0), _factor("f3", 4.0)],
            rows=[_row("s1", "f2"), _row("s2", "f3")],
        )
        return before, after

    def _ruling(self, identifier="f1", verb=RulingVerb.REPLACE, replaced_by="f2",
                entity=EntityKind.ELEMENTARY_FLOW, versions=("1.0.0", "1.1.0")):
        return MigrationRuling(
            from_version=versions[0], to_version=versions[1], entity=entity,
            identifier=identifier, verb=verb, replaced_by=replaced_by, comment="the curator says",
        )

    def test_a_ruling_resolves_a_split_and_its_factors_follow(self):
        before, after = self._split()
        diff = diff_releases(before, after, rulings=(self._ruling(),))
        flow = _by(diff.elementary_flows, "f1")
        self.assertEqual((flow.kind, flow.replaced_by, flow.reason), (DeltaKind.REPLACED, "f2", "ruling"))
        self.assertEqual(flow.comment, "the curator says")
        # Translated to f2, whose factor is unchanged; f3's is new.
        self.assertEqual([d.identifier for d in diff.factors], [_key("f3")])
        self.assertEqual(diff.unresolved, [])

    def test_a_ruling_about_another_pair_is_ignored(self):
        before, after = self._split()
        diff = diff_releases(before, after, rulings=(self._ruling(versions=("0.9.0", "1.0.0")),))
        self.assertEqual(_by(diff.elementary_flows, "f1").kind, DeltaKind.UNRESOLVED)

    def test_a_stale_ruling_is_refused(self):
        before, after = self._split()
        with self.assertRaises(MigrationRulingError):
            diff_releases(before, after, rulings=(self._ruling(identifier="f-not-there"),))

    def test_a_ruling_naming_an_unpublished_flow_is_refused(self):
        before, after = self._split()
        with self.assertRaises(MigrationRulingError):
            diff_releases(before, after, rulings=(self._ruling(replaced_by="f-nowhere"),))

    def test_a_delete_ruling_deletes_the_factors_too(self):
        before, after = self._split()
        diff = diff_releases(
            before, after, rulings=(self._ruling(verb=RulingVerb.DELETE, replaced_by=None),)
        )
        self.assertEqual(_by(diff.elementary_flows, "f1").kind, DeltaKind.DELETED)
        self.assertEqual(_by(diff.factors, _key("f1")).kind, DeltaKind.DELETED)


class RandonneurFilesTestCase(unittest.TestCase):
    """The files are randonneur's format, and randonneur applies them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.before = _snapshot(
            "1.0.0",
            flows=[_flow("f1", "fo-1", label="Cadmium"), _flow("f2", "fo-1", context=WATER),
                   _flow("f3", "fo-3"), _flow("f4", "fo-4")],
            objects=[_object("fo-1", "Cadmium", "7440-43-8"), _object("fo-3", "Lead"),
                     _object("fo-4", "Gone")],
            factors=[_factor("f1", 1.0), _factor("f2", 2.0), _factor("f3", 3.0)],
            rows=[_row("s1", "f1"), _row("s2", "f2"), _row("s3", "f3"), _row("s4", "f4"),
                  _row("s5", "f4")],
        )
        self.after = _snapshot(
            "1.1.0",
            flows=[_flow("f1", "fo-1", label="Cadmium(2+)"), _flow("f2", "fo-1", context=WATER),
                   _flow("f5", "fo-3"), _flow("f6", "fo-6"), _flow("f7", "fo-7"),
                   _flow("f3", "fo-3", deprecated=True, replaced_by="f5", reason="identity-merge")],
            objects=[_object("fo-1", "Cadmium", "7440-43-9"), _object("fo-3", "Lead"),
                     _object("fo-6", "Split one"), _object("fo-7", "Split two")],
            factors=[_factor("f1", 1.5), _factor("f2", 2.0), _factor("f5", 3.0), _factor("f6", 6.0)],
            rows=[_row("s1", "f1"), _row("s2", "f2"), _row("s3", "f5"), _row("s4", "f6"),
                  _row("s5", "f7")],
            redirects=[_redirect("f3", "f5", "identity-merge")],
        )
        self.diff = diff_releases(self.before, self.after)
        self.files = write_migration_files(self.diff, self.root)

    def test_every_file_is_written_and_reads_back_as_a_datapackage(self):
        for path in self.files.migrations:
            package = Datapackage.from_json(path)
            self.assertEqual(package.source_id, "brightway-flows-1.0.0")
            self.assertEqual(package.target_id, "brightway-flows-1.1.0")
            self.assertEqual(package.version, "1.1.0")
        self.assertEqual(self.files.directory.name, "1.0.0__1.1.0")

    def test_the_flow_file_holds_the_four_verbs(self):
        package = Datapackage.from_json(self.files.elementary_flows)
        self.assertEqual(package.graph_context, ["nodes", "edges"])
        self.assertEqual(
            {verb: len(rows) for verb, rows in package.data.items()},
            {"create": 3, "update": 1, "replace": 1},
        )
        (replace,) = package.data["replace"]
        self.assertEqual(replace["source"], {"identifier": "f3"})
        self.assertEqual(replace["target"], {"identifier": "f5"})
        self.assertEqual(replace["conversion_factor"], 1.0)
        (update,) = package.data["update"]
        self.assertEqual(update, {
            "source": {"identifier": "f1"}, "target": {"prefLabel": "Cadmium(2+)"},
            "comment": "prefLabel: 'Cadmium' -> 'Cadmium(2+)'",
        })

    def test_the_split_is_in_the_report_and_in_no_file(self):
        report = json.loads(self.files.unresolved.read_text())
        self.assertEqual(report["schema_version"], UNRESOLVED_REPORT_SCHEMA_VERSION)
        self.assertEqual(report["counts"]["by_reason"], {"flows-unresolved": 1, "split": 1})
        (flow,) = [item for item in report["items"] if item["entity"] == "elementary-flow"]
        self.assertEqual((flow["identifier"], flow["candidates"]), ("f4", ["f6", "f7"]))
        for path in self.files.migrations:
            self.assertNotIn('"f4"', path.read_text())

    def test_randonneur_applies_the_flow_file_to_a_consumer_list(self):
        package = Datapackage.from_json(self.files.elementary_flows)
        consumer = [
            {"identifier": f.identifier, **f.published_fields()}
            for f in self.before.live_flows.values()
        ]
        migrate_nodes(consumer, package.data, MigrationConfig(verbs=["update", "delete", "create"]))
        by_id = {node["identifier"]: node for node in consumer}
        self.assertEqual(by_id["f1"]["prefLabel"], "Cadmium(2+)")
        self.assertIn("f6", by_id)
        expected = {
            f.identifier: f.published_fields() for f in self.after.live_flows.values()
        }
        # f3 and f4 are the two the node migration does not touch: a replace is
        # an edge verb, and a split is unresolved.
        for identifier, fields in expected.items():
            if identifier in ("f3",):
                continue
            self.assertEqual({k: v for k, v in by_id[identifier].items() if k != "identifier"}, fields, identifier)

    def test_randonneur_applies_the_replace_to_a_consumer_inventory(self):
        package = Datapackage.from_json(self.files.elementary_flows)
        inventory = [{"name": "a process", "edges": [{"identifier": "f3", "amount": 2.0}]}]
        migrate_edges(inventory, package.data, MigrationConfig(verbs=["replace"]))
        (edge,) = inventory[0]["edges"]
        self.assertEqual((edge["identifier"], edge["amount"]), ("f5", 2.0))

    def test_the_factor_file_is_stated_against_the_after_identifiers(self):
        package = Datapackage.from_json(self.files.characterization_factors)
        verbs = {verb: rows for verb, rows in package.data.items()}
        self.assertEqual([r["source"]["elementary_flow_uuid"] for r in verbs["update"]], ["f1"])
        self.assertEqual(verbs["update"][0]["target"], {"amount": 1.5})
        self.assertEqual([r["target"]["elementary_flow_uuid"] for r in verbs["create"]], ["f6"])
        self.assertNotIn("delete", verbs)  # f3's factor moved to f5, unchanged
        method = [{"impact_category_id": CATEGORY, "elementary_flow_uuid": "f1", "geography": "", "amount": 1.0}]
        migrate_nodes(method, package.data, MigrationConfig(verbs=["update", "create", "delete"]))
        self.assertEqual({row["elementary_flow_uuid"]: row["amount"] for row in method}, {"f1": 1.5, "f6": 6.0})

    def test_the_substance_file_replaces_and_deletes(self):
        package = Datapackage.from_json(self.files.flow_objects)
        self.assertEqual(package.graph_context, ["nodes"])
        self.assertNotIn("delete", package.data)  # fo-4 is unresolved, not deleted
        self.assertEqual([r["source"]["flow_object_id"] for r in package.data["update"]], ["fo-1"])
        self.assertEqual({r["target"]["flow_object_id"] for r in package.data["create"]}, {"fo-6", "fo-7"})

    def test_writing_twice_gives_the_same_bytes(self):
        first = {p.name: p.read_bytes() for p in (*self.files.migrations, self.files.unresolved)}
        again = write_migration_files(self.diff, self.root)
        second = {p.name: p.read_bytes() for p in (*again.migrations, again.unresolved)}
        self.assertEqual(first, second)

    def test_every_published_key_is_in_the_mapping(self):
        """`Datapackage.add_data` refuses a key the mapping does not name, so a
        create carrying every published field proves the mapping is complete."""
        for entity, deltas in self.diff.by_entity.items():
            labels = set(MAPPINGS[entity]()["labels"])
            for verb, rows in entries(entity, deltas).items():
                for row in rows:
                    for part in ("source", "target"):
                        self.assertLessEqual(set(row.get(part, {})), labels, (entity, verb))


class FateTestCase(unittest.TestCase):
    def test_every_fate_reason_is_a_string_the_report_can_carry(self):
        for reason in FateReason:
            self.assertIsInstance(reason.value, str)
        self.assertEqual(set(Fate), {Fate.REPLACED, Fate.DELETED, Fate.UNRESOLVED})


if __name__ == "__main__":
    unittest.main()
