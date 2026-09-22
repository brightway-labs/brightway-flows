"""Adding a flow list is data. This is the test that says so.

#239 asked one question — *can a new flow list be added as data, or does it
require code?* — and answered it: code, in eleven places, three of them silent.
A list merged and produced wrong output rather than failing, so no build broke
and no curator saw it.

The three silent ones shared a shape: a value keyed to nothing, so ecoinvent's
answer was every list's answer.

- **#240** `_load_manual_additions()` was called with no argument and defaulted
  to ecoinvent's pesticide groupings, for every list. Rows it placed left the
  unmatched queue, so nobody was asked about them.
- **#241** `prepared-context-decisions.json` was keyed on a bare `source_uuid`.
  Source lists do not agree to keep out of each other's UUID space, so two lists
  applied each other's curated rulings.
- **#11** The merge read a *generated projection* of the context mapping that
  `build` never regenerated. It agreed with the master for ecoinvent by
  coincidence.

None of them is findable by reading the docs or by running a build that appears
to work. What finds all three is this: a list added purely as a manifest plus
data files, merged end to end into a temporary data directory, asked whether it
can see any of ecoinvent's curated decisions.

The fixture list is called ``fixturelist``. That name appears nowhere under
``src/``, and :meth:`AddingAListIsDataTestCase.test_no_python_names_the_fixture_list`
is what keeps it that way — if making this test pass ever needs a branch in the
pipeline, the branch is the defect.
"""

import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import orjson

import brightway_flows.context_mapping as context_mapping
import brightway_flows.sources as sources_module
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.context_registry import context_for_iri
from brightway_flows.merge.prepared_context_decisions import (
    DECISIONS_FILEPATH,
    load_prepared_context_decision_index,
)
from brightway_flows.merge.store import Outcome

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "brightway_flows"
PACKAGE_DATA = SRC / "data"

FIXTURE_LIST = "fixturelist"
FIXTURE_VERSION = "1.0"
FIXTURE_KEY = f"{FIXTURE_LIST}-{FIXTURE_VERSION}"

#: A real consensus context IRI, so the merge's own context validation passes
#: and `consensus-flows-as-strings.json` can name its canonical strings — which
#: is what the elementary-flow selector compares against. Which IRI does not
#: matter; that it is genuine does.
AIR_UNSPECIFIED = "https://vocab.brightway.one/flow-contexts/envi-air-unkn"
AIR_UNSPECIFIED_STRINGS = ["Environmental", "Air"]
#: The same context as a record.  Resolved from the IRI beside it rather than
#: rebuilt from the strings, which is the one thing `context_registry` says not
#: to do -- and now the only way to build one that agrees with `context_iri`.
AIR_UNSPECIFIED_CONTEXT = context_for_iri(AIR_UNSPECIFIED)

#: The compartment ecoinvent 3.12 spells this way, and which the master mapping
#: has a rule for *under ecoinvent's source string*. The fixture list uses the
#: same words and declares no rule for them: it must not inherit ecoinvent's.
SHARED_SPELLING = ["air", "low population density, long-term"]

FIXTURE_MANIFEST = {
    "list_name": FIXTURE_LIST,
    "list_version": FIXTURE_VERSION,
    "role": "source",
    # Where it belongs in the merge order, which is data like everything else
    # here: the first list to reach a substance mints its flow object, so this
    # cannot be left to the order the `--source` flags happen to be typed in.
    "merge_priority": 300,
    "adapter": "tests.test_new_source_list_is_data:fetch",
    "flow_iri_prefix": f"https://vocab.brightway.one/{FIXTURE_LIST}/{FIXTURE_VERSION}/flow/",
    "prepared_match_table": None,
    "concept_associations": None,
    "inputs": {
        "flows": f"{FIXTURE_KEY}-flows.json",
        "manual_fixes": None,
        "manual_additions": None,
    },
}


def fetch(source, *, force: bool = False) -> Path:
    """The fixture list's adapter. Named by its manifest, like any other."""
    source.flows_path.write_bytes(orjson.dumps([]))
    return source.flows_path


def _flow_object(flow_object_id: str, label: str, cas: str = "") -> FlowObject:
    classifications = {}
    if cas:
        classifications["http://semanticscience.org/resource/CHEMINF_000446"] = {
            "@value": [cas]
        }
    return FlowObject(
        flow_object_id=flow_object_id,
        prefLabel=[{"@value": label, "@language": "en"}],
        altLabel=[],
        classifications=classifications,
        properties={},
        references=[],
        # `_load_working_set` builds a `FlowObject` from what is stored, so a
        # seeded object has to be a whole one.  Building the record here rather
        # than a payload is the shorter way of saying it.
        created_from={"resolver": "test_fixture"},
    )


def _consensus_flow(
    uuid: str, flow_object_id: str, label: str, unit: str = "kg"
) -> tuple[Flow, ElementaryFlow]:
    """A `Flow` and the `ElementaryFlow` record beside it.

    The two carry the *same* context, because that is what the pipeline
    writes: all 94,433 flows of the 2026-08-07 build hold the structured form
    in `flow_json`, identical to the elementary record's.  This fixture used to
    give the flow `{"@id": ...}` and the elementary record the strings, which
    only went unnoticed while the two were stored in separate columns -- the
    merge read one and the export the other, so nothing compared them (#255).
    """
    flow = Flow(
        uuid=uuid,
        flow_object_id=flow_object_id,
        name=label,
        prefLabel=[{"@value": label, "@language": "en"}],
        source="EF 3.1",
        unit=unit,
        context=AIR_UNSPECIFIED_CONTEXT,
        context_iri=AIR_UNSPECIFIED,
        lcia_methods=[],
    )
    elementary = ElementaryFlow(
        elementary_flow_id=uuid,
        flow_object_id=flow_object_id,
        source="EF 3.1",
        unit=unit,
        unit_iri="",
        context=AIR_UNSPECIFIED_CONTEXT,
        context_iri=AIR_UNSPECIFIED,
        source_refs=[],
        lcia_methods=[],
        general_comment=None,
        concept_associations=[],
    )
    return flow, elementary


@contextmanager
def fixture_world():
    """A data directory, a manifest directory and a context mapping of our own.

    Everything the fixture list needs, and nothing of ecoinvent's except what is
    deliberately planted for it to fail to see. The real manifests are copied in
    so that the registry's "exactly one base list" invariant still holds — the
    fixture is an *addition* to the registry, which is the situation under test.
    """
    with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
        root = Path(tmp)
        data_dir = root / "data"
        manifests = root / "sources"
        data_dir.mkdir()
        manifests.mkdir()

        for path in sorted(sources_module.SOURCE_MANIFEST_DIR.glob("*.json")):
            (manifests / path.name).write_bytes(path.read_bytes())
        (manifests / f"{FIXTURE_KEY}.json").write_text(
            json.dumps(FIXTURE_MANIFEST, indent=2)
        )

        # One rule for the fixture list, and ecoinvent's rule for a compartment
        # spelled exactly the same way. If the merge reads rules by anything
        # other than the list's own `source` string, the second one applies.
        mapping = data_dir / "context-manual-mapping.json"
        mapping.write_text(json.dumps({
            "schema_version": 1,
            "namespace": "https://vocab.brightway.one/flow-contexts/",
            "allowed_context_combinations": [],
            "default_context_mappings": [
                {
                    "source": FIXTURE_KEY,
                    "source_context": ["atmosphere"],
                    "context_iri": AIR_UNSPECIFIED,
                },
                {
                    "source": "ecoinvent-3.12",
                    "source_context": SHARED_SPELLING,
                    "context_iri": AIR_UNSPECIFIED,
                },
            ],
            "flow_specific_context_mappings": [],
        }))

        db = data_dir / "consensus-flows.sqlite3"
        stack.enter_context(patch.object(sources_module, "SOURCE_MANIFEST_DIR", manifests))
        stack.enter_context(patch.object(sources_module, "DATA_DIR", data_dir))
        stack.enter_context(patch.object(context_mapping, "MANUAL_MAPPING_FILEPATH", mapping))

        for module, name, value in (
            ("brightway_flows.merge.pipeline", "CONSENSUS_DB_FILEPATH", db),
            ("brightway_flows.merge.pipeline", "HARMONISED_FLOWS_SIMPLE_FILEPATH",
             data_dir / "harmonised-flows-simple.json.gz"),
            ("brightway_flows.merge.datastores", "CONSENSUS_DB_FILEPATH", db),
            ("brightway_flows.pipeline.sqlite", "CONSENSUS_DB_FILEPATH", db),
        ):
            stack.enter_context(patch(f"{module}.{name}", value))

        # The caches are the point of the patches: both modules memoise package
        # data, correctly, because it cannot change within a run.
        #
        # Found rather than listed.  `context_mapping` has eight memoised
        # loaders and this named three of them, so the fixture's mapping file
        # stayed in the other five after the fixture exited -- which no test
        # noticed while every user of this fixture sorted after the tests that
        # read the real rules, and which nine of them noticed the moment one
        # sorted before them.
        for cached in (
            sources_module._manifest_payloads,
            sources_module.base_source_label,
            *(
                member
                for member in vars(context_mapping).values()
                if callable(member) and hasattr(member, "cache_clear")
            ),
        ):
            cached.cache_clear()
            stack.callback(cached.cache_clear)

        yield data_dir, db


def seed_consensus_database(
    flow_objects: list[FlowObject], pairs: list[tuple[Flow, ElementaryFlow]]
) -> None:
    """Write a consensus database through the writer the transform uses.

    Not hand-rolled SQL: the schema would drift out from under this test the
    first time a column moved, and the failure would look like a merge defect.
    """
    from brightway_flows.pipeline.sqlite import _write_consensus_sqlite

    _write_consensus_sqlite(
        [flow for flow, _ in pairs],
        [],
        flow_objects,
        [elementary for _, elementary in pairs],
    )


def merge_fixture_list(rows: list[dict], **bounds) -> tuple[str, Path]:
    """Merge *rows* as the fixture list, end to end. Returns (run id, db path).

    *bounds* are passed through to `merge_source_list`, which is how
    `tests/test_bounded_merge.py` asks for a merge of the first N rows without
    a second copy of this fixture.
    """
    from brightway_flows.merge.pipeline import merge_source_list

    source = sources_module.resolve_source_list(FIXTURE_KEY)
    source.flows_path.write_bytes(orjson.dumps(rows))
    return merge_source_list(source, **bounds), source.flows_path


def outcomes(db: Path, run_id: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return list(
            conn.execute(
                "SELECT * FROM merge_outcomes WHERE run_id = ? ORDER BY source_uuid",
                (run_id,),
            )
        )
    finally:
        conn.close()


class AddingAListIsDataTestCase(unittest.TestCase):
    """The claim, stated as a test rather than as a sentence in a document."""

    def test_a_manifest_and_a_flows_file_register_a_list(self):
        """No Python edit anywhere: a file in `data/sources/` and a file of rows."""
        with fixture_world():
            registry = sources_module.known_source_lists()
            self.assertIn(FIXTURE_KEY, registry)
            source = registry[FIXTURE_KEY]
            self.assertEqual(source.list_name, FIXTURE_LIST)
            self.assertEqual(source.list_version, FIXTURE_VERSION)
            # Derived, not declared: the whole point of `SourceList`.
            self.assertEqual(source.merge_activity, "merge_fixturelist")
            self.assertEqual(
                source.addition_sources,
                frozenset({
                    "fixturelist algorithm addition",
                    "fixturelist manual addition",
                }),
            )

    def test_no_python_names_the_fixture_list(self):
        """If making this test pass needs a branch in the pipeline, the branch
        is the defect. This is what would notice."""
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path in sorted(SRC.rglob("*.py"))
            if FIXTURE_LIST in path.read_text()
        ]
        self.assertEqual(
            offenders, [],
            "the pipeline names the fixture list, so adding a list is code",
        )

    def test_the_list_resolves_and_merges_end_to_end(self):
        with fixture_world() as (data_dir, db):
            seed_consensus_database(
                [_flow_object("fo-co2", "Carbon dioxide", cas="124-38-9")],
                [_consensus_flow("ef-co2", "fo-co2", "Carbon dioxide")],
            )
            run_id, flows_path = merge_fixture_list([{
                "uuid": "fx-1",
                "name": "Carbon dioxide",
                "unit": "kg",
                "context": ["atmosphere"],
                "cas_number": "124-38-9",
                "source": FIXTURE_KEY,
            }])
            rows = outcomes(db, run_id)

        self.assertEqual(flows_path.parent, data_dir)
        self.assertEqual([row["source_uuid"] for row in rows], ["fx-1"])
        self.assertEqual(rows[0]["list_name"], FIXTURE_LIST)
        self.assertEqual(rows[0]["list_version"], FIXTURE_VERSION)


class ItSeesNoneOfEcoinventsCuratedDecisionsTestCase(unittest.TestCase):
    """The three silent defects, each stated as what it would have produced."""

    def test_it_is_given_no_manual_additions(self):
        """#240. `_load_manual_additions()` defaulted to ecoinvent's pesticide
        groupings, and the rows it placed left the unmatched queue — so a
        curator was never asked about a decision they never made.

        The row below is one of ecoinvent's grouped pesticides, by name *and* by
        UUID, and the flow object the grouping puts it on is in the database.
        Nothing else in the consensus list matches it, so it reaches the manual
        additions step unplaced — which is the only way to find out what that
        step was given.

        With the fixture list's declared `manual_additions: null`, the row is
        `created`: a substance the consensus list does not have, minted from the
        row. With ecoinvent's file defaulted back in, it becomes
        `manual-addition` against `Herbicides, Unspecified` and leaves the
        queue. Verified by reintroducing the default and watching this fail.

        The row used to be read out of ecoinvent's own groupings file, so that
        it was a grouping somebody had really written. #76 removed all thirty
        of those, leaving only the `not_pesticide` rows, and that lookup began
        raising `StopIteration`. It is written out here instead, copied from the
        Beflubutamid row as it stood at `fa1f4aa`: the claim is about what a new
        list is *given*, and it should not stop being testable because the file
        it borrowed an example from has been emptied.
        """
        mapping = {
            "source_name": "Beflubutamid",
            "flow_object_id": "fo-601ee65225568e0a",
            "flow_object_label": "Herbicides, Unspecified",
            "source_uuids": ["42bed682-0ec5-5f40-825f-0721eca416fe"],
        }

        with fixture_world() as (_data_dir, db):
            # The grouping's *target*, under its real id and label. Deliberately
            # not something the row can match on its own: the row is called
            # "Beflubutamid", the object is called "Herbicides, Unspecified".
            seed_consensus_database(
                [_flow_object(mapping["flow_object_id"], mapping["flow_object_label"])],
                [_consensus_flow(
                    "ef-grouped", mapping["flow_object_id"], mapping["flow_object_label"]
                )],
            )
            source = sources_module.resolve_source_list(FIXTURE_KEY)
            self.assertIsNone(source.manual_additions_path)

            run_id, _ = merge_fixture_list([{
                "uuid": mapping["source_uuids"][0],
                "name": mapping["source_name"],
                "unit": "kg",
                "context": ["atmosphere"],
                "source": FIXTURE_KEY,
            }])
            rows = outcomes(db, run_id)

        self.assertEqual([row["outcome"] for row in rows], [Outcome.CREATED])
        self.assertNotEqual(rows[0]["flow_object_id"], mapping["flow_object_id"])

    def test_it_is_given_none_of_another_lists_prepared_context_decisions(self):
        """#241. The decisions file was keyed on a bare `source_uuid`, and
        source lists do not agree to keep out of each other's UUID space."""
        with fixture_world():
            source = sources_module.resolve_source_list(FIXTURE_KEY)
            self.assertEqual(load_prepared_context_decision_index(source), {})

    def test_every_checked_in_decision_names_the_list_it_was_made_about(self):
        """The other half of #241: an unstamped decision belongs to every list,
        which is the defect itself. It is skipped, so a file that quietly lost
        its stamps would look like a file with no decisions."""
        payload = orjson.loads(DECISIONS_FILEPATH.read_bytes())
        unstamped = [
            row for row in payload.get("decisions", [])
            if isinstance(row, dict) and not str(row.get("list_name") or "").strip()
        ]
        self.assertEqual(unstamped, [])

    def test_it_does_not_inherit_another_lists_context_rules(self):
        """#11. Both lists spell the compartment identically; only ecoinvent
        has a rule for it. A rule read by anything other than the list's own
        `source` string would place this row somewhere plausible and silent.

        Instead the merge stops. That is the designed behaviour and the right
        one: a context nobody has mapped is a decision nobody has made, and
        guessing puts the flow somewhere arbitrary. The error names the list
        being merged and the row to add — it said "All ecoinvent contexts must
        map to a known harmonised context" for every list until #242.
        """
        with fixture_world() as (_data_dir, _db):
            seed_consensus_database(
                [_flow_object("fo-co2", "Carbon dioxide", cas="124-38-9")],
                [_consensus_flow("ef-co2", "fo-co2", "Carbon dioxide")],
            )
            fixture_rules = context_mapping.context_iri_by_source_context(FIXTURE_KEY)
            ecoinvent_rules = context_mapping.context_iri_by_source_context(
                "ecoinvent-3.12"
            )
            with self.assertRaises(ValueError) as ctx:
                merge_fixture_list([{
                    "uuid": "fx-shared-spelling",
                    "name": "Carbon dioxide",
                    "unit": "kg",
                    "context": SHARED_SPELLING,
                    "cas_number": "124-38-9",
                    "source": FIXTURE_KEY,
                }])

        self.assertEqual(list(fixture_rules), [("atmosphere",)])
        self.assertIn(("air", "low population density, long-term"), ecoinvent_rules)
        message = str(ctx.exception)
        self.assertIn(FIXTURE_KEY, message)
        self.assertNotIn("ecoinvent", message)

    def test_the_rules_it_does_have_place_its_rows(self):
        """The control. Without this the test above passes for a list whose
        rules were never read at all, which is a different bug wearing the same
        result."""
        with fixture_world() as (_data_dir, db):
            seed_consensus_database(
                [_flow_object("fo-co2", "Carbon dioxide", cas="124-38-9")],
                [_consensus_flow("ef-co2", "fo-co2", "Carbon dioxide")],
            )
            run_id, _ = merge_fixture_list([{
                "uuid": "fx-own-spelling",
                "name": "Carbon dioxide",
                "unit": "kg",
                "context": ["atmosphere"],
                "cas_number": "124-38-9",
                "source": FIXTURE_KEY,
            }])
            rows = outcomes(db, run_id)

        self.assertEqual([row["outcome"] for row in rows], [Outcome.ALGORITHM])
        self.assertEqual(rows[0]["target_elementary_flow_id"], "ef-co2")
        self.assertEqual(rows[0]["basis"], "cas")


class WhatTheRegistryRefusesTestCase(unittest.TestCase):
    """A list that cannot be merged is refused before the transform runs.

    The registry used to over-promise: five ecoinvent versions resolved, but
    only two had context rules, so `--source ecoinvent-3.11` resolved,
    downloaded, ran the whole transform and *then* failed every row.
    """

    def _manifest(self, **overrides):
        payload = {**FIXTURE_MANIFEST, **overrides}
        return payload

    def test_a_list_with_no_context_rules_is_refused_by_name(self):
        with fixture_world() as (_data_dir, _db):
            manifests = sources_module.SOURCE_MANIFEST_DIR
            (manifests / "unmapped-1.0.json").write_text(json.dumps(self._manifest(
                list_name="unmapped",
                inputs={"flows": "unmapped-1.0-flows.json"},
            )))
            sources_module._manifest_payloads.cache_clear()
            with self.assertRaises(ValueError) as ctx:
                sources_module.resolve_source_list("unmapped-1.0")
        message = str(ctx.exception)
        self.assertIn("unmapped-1.0", message)
        self.assertIn("context mapping rules", message)

    def test_a_declared_input_that_is_absent_is_refused_by_name(self):
        with fixture_world() as (_data_dir, _db):
            manifests = sources_module.SOURCE_MANIFEST_DIR
            (manifests / f"{FIXTURE_KEY}.json").write_text(json.dumps(self._manifest(
                inputs={
                    "flows": f"{FIXTURE_KEY}-flows.json",
                    "manual_fixes": "no-such-fixes.json",
                },
            )))
            sources_module._manifest_payloads.cache_clear()
            with self.assertRaises(ValueError) as ctx:
                sources_module.resolve_source_list(FIXTURE_KEY)
        self.assertIn("no-such-fixes.json", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
