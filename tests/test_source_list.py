"""`SourceList` must reproduce, exactly, the literals it replaced.

Several of the values it derives are published: the `source` of a created flow,
the `list_name`/`list_version` of a source reference, and the IRI prefix used
for `xkos:sourceConcept`, which is read by a downstream consumer.
Deriving them from the source list is only safe if the derivation is the
identity for ecoinvent, so that is what is asserted here rather than that the
properties merely exist.

The registry is now data -- one manifest per list in `data/sources/` (#12) --
so the manifests are under test too: a mistake in one of them is a build that
resolves and then produces the wrong artifact.
"""

import shutil
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path

import orjson

from brightway_flows.domain.vocabulary import (
    MintedNamespace,
    ecoinvent_flow_iri_prefix,
)
from brightway_flows.filesystem import DATA_DIR
from brightway_flows.simapro_names import name_without_unit_suffix
from brightway_flows.sources import (
    _CURATED_INPUTS,
    BASE_ROLE,
    PACKAGE_DATA_DIR,
    SOURCE_MANIFEST_DIR,
    SOURCE_ROLE,
    SourceList,
    base_source_label,
    base_source_list,
    known_source_lists,
    load_prepared_match_table,
    merge_order,
    resolve_source_list,
    simapro_origin_source_labels,
    source_flows_path,
)


@contextmanager
def _registry_with_an_extra_list(payload: dict):
    """The shipped manifests plus one more, for the duration of the block.

    Copies rather than replaces, because `_registry` requires exactly one
    manifest with `role: "base"` and a registry holding only the list under test
    would fail for that reason instead of the one being asserted.

    `_manifest_payloads` is cached -- the manifests are package data and cannot
    change during a run -- so the cache is cleared on the way in and on the way
    out, and the module attribute is restored either way.
    """
    from brightway_flows import sources as sources_module

    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        for path in SOURCE_MANIFEST_DIR.glob("*.json"):
            shutil.copy(path, directory / path.name)
        key = f"{payload['list_name']}-{payload['list_version']}"
        (directory / f"{key}.json").write_bytes(orjson.dumps(payload))

        original = sources_module.SOURCE_MANIFEST_DIR
        sources_module.SOURCE_MANIFEST_DIR = directory
        sources_module._manifest_payloads.cache_clear()
        try:
            yield
        finally:
            sources_module.SOURCE_MANIFEST_DIR = original
            sources_module._manifest_payloads.cache_clear()


class DerivedValuesMatchThePreviousLiteralsTestCase(unittest.TestCase):
    def setUp(self):
        self.source = resolve_source_list("ecoinvent-3.12")

    def test_addition_source_strings(self):
        """These land in `flow.source` in the published artifact."""
        self.assertEqual(
            self.source.algorithm_addition_source, "ecoinvent algorithm addition"
        )
        self.assertEqual(
            self.source.manual_addition_source, "ecoinvent manual addition"
        )
        self.assertEqual(
            self.source.addition_sources,
            frozenset({"ecoinvent algorithm addition", "ecoinvent manual addition"}),
        )

    def test_provenance_activity(self):
        """`prov:wasGeneratedBy`, previously the literal "merge_ecoinvent"."""
        self.assertEqual(self.source.merge_activity, "merge_ecoinvent")

    def test_flow_iri_prefix_is_the_published_one(self):
        self.assertEqual(
            self.source.flow_iri_prefix, ecoinvent_flow_iri_prefix("3.12")
        )
        self.assertTrue(self.source.flow_iri_prefix.endswith("/3.12/flow/"))

    def test_no_ecoinvent_version_declares_a_prepared_table(self):
        """The published correspondence tables are retired (#141): every
        ecoinvent row is decided by this project's own matching plus the rows
        in `ecoinvent-match-overrides.json`, which the loader applies onto an
        empty table.  3.12 used to reuse 3.11's table by name; the indirection
        went with the tables."""
        for key, source in known_source_lists().items():
            if source.list_name == "ecoinvent":
                with self.subTest(key=key):
                    self.assertIsNone(source.prepared_match_table)

    def test_key_identifies_list_and_version(self):
        self.assertEqual(self.source.key, "ecoinvent-3.12")
        self.assertEqual(str(self.source), "ecoinvent-3.12")

    def test_source_label_is_the_key_for_a_list_we_fetch_ourselves(self):
        """What `flow.source` says. Only the base list declares another."""
        self.assertEqual(self.source.source_label, "ecoinvent-3.12")


class IdentityIsListAndVersionTestCase(unittest.TestCase):
    """The point of the change: two versions of a list are two source lists."""

    def test_versions_do_not_collide(self):
        registry = known_source_lists()
        self.assertEqual(sorted(registry), sorted({s.key for s in registry.values()}))

    def test_each_version_has_its_own_inputs(self):
        registry = known_source_lists()
        older, newer = registry["ecoinvent-3.11"], registry["ecoinvent-3.12"]
        self.assertNotEqual(older.flows_path, newer.flows_path)
        self.assertNotEqual(older.flow_iri_prefix, newer.flow_iri_prefix)
        self.assertNotEqual(older.source_label, newer.source_label)

    def test_a_second_list_derives_its_own_identity(self):
        """The case the merge could not previously express at all."""
        other = SourceList(
            list_name="bafu",
            list_version="2025",
            flows_path=Path("/nonexistent/bafu-2025.json"),
        )
        self.assertEqual(other.key, "bafu-2025")
        self.assertEqual(other.algorithm_addition_source, "bafu algorithm addition")
        self.assertEqual(other.merge_activity, "merge_bafu")
        self.assertIsNone(other.prepared_match_table)


class ManifestsAreTheRegistryTestCase(unittest.TestCase):
    """Adding a list is a file in `data/sources/`, and nothing else.

    `known_source_lists` used to be a comprehension over `ECOINVENT_VERSIONS`:
    a function over one list's releases, which is why BAFU sat in `data/`
    unreachable.  These assert the properties of the manifest directory that
    the claim depends on.
    """

    def _payloads(self):
        for path in sorted(SOURCE_MANIFEST_DIR.glob("*.json")):
            yield path, orjson.loads(path.read_bytes())

    def test_every_manifest_is_registered_under_its_own_key(self):
        for key, source in known_source_lists().items():
            with self.subTest(source=key):
                self.assertEqual(key, source.key)
                self.assertEqual(source.role, SOURCE_ROLE)

    def test_a_manifest_is_the_only_thing_that_declares_a_list(self):
        """No Python names a list the manifest directory does not."""
        keys = set(known_source_lists()) | {base_source_list().key}
        from_disk = {
            f"{payload['list_name']}-{payload['list_version']}"
            for _, payload in self._payloads()
        }
        self.assertEqual(keys, from_disk)

    def test_exactly_one_manifest_is_the_base_list(self):
        bases = [p for _, p in self._payloads() if p.get("role") == BASE_ROLE]
        self.assertEqual(len(bases), 1)
        self.assertEqual(bases[0]["list_name"], "EF")
        self.assertEqual(bases[0]["list_version"], "3.1")

    def test_the_base_list_is_not_a_source(self):
        """Merging the base list into itself is not a build anyone means."""
        self.assertNotIn("EF-3.1", known_source_lists())
        with self.assertRaises(ValueError):
            resolve_source_list("EF-3.1")

    def test_the_base_list_declares_the_published_source_string(self):
        base = base_source_list()
        self.assertEqual(base.source_label, "EF 3.1")
        self.assertEqual(base_source_label(), "EF 3.1")
        self.assertEqual(base.list_name, "EF")
        self.assertEqual(base.list_version, "3.1")

    def test_flow_iri_prefixes_are_the_one_way_door(self):
        """Published as the `xkos:sourceConcept` `@id`.  A change here breaks
        every consumer that resolved one."""
        prefixes = {
            key: source.flow_iri_prefix
            for key, source in known_source_lists().items()
        }
        base = base_source_list()
        prefixes[base.key] = base.flow_iri_prefix
        self.assertEqual(
            prefixes,
            {
                "EF-3.1": MintedNamespace.EF31_FLOW.value,
                "bafu-2026-v1": "https://vocab.brightway.one/bafu/2026-v1/flow/",
                "stepwise-2006-1.09": (
                    "https://vocab.brightway.one/stepwise/2006-1.09/flow/"
                ),
                "agribalyse-3.2": "https://vocab.brightway.one/agribalyse/3.2/flow/",
                "ecoinvent-3.8": "https://vocab.brightway.one/ecoinvent/3.8/flow/",
                "ecoinvent-3.9.1": "https://vocab.brightway.one/ecoinvent/3.9.1/flow/",
                "ecoinvent-3.10.1": "https://vocab.brightway.one/ecoinvent/3.10.1/flow/",
                "ecoinvent-3.11": "https://vocab.brightway.one/ecoinvent/3.11/flow/",
                "ecoinvent-3.12": "https://vocab.brightway.one/ecoinvent/3.12/flow/",
            },
        )

    def test_the_merge_order_is_declared_not_typed(self):
        """Pinned, because it decides which list defines a substance.

        The first list to reach a substance mints its flow object, and every
        list merged after it matches against what that list created.  ecoinvent
        carries vendor UUIDs, CAS and EC numbers on its rows; BAFU carries a
        name, and a registry number on fewer than half -- 711 of its 1,187 names
        have none at all.  Merging BAFU first would leave ecoinvent's
        better-identified rows matching against objects BAFU invented from bare
        names, which is the failure five manual-fixes files argue about for
        ecoinvent's brine arriving before EF 3.1's.

        Stepwise 2006 is at 300, one step further along the same argument.
        AGRIBALYSE 3.2 is last at 400: 87% of its rows carry a registry
        number, but it is the newest arrival, its review queues are unworked,
        and a new list matches against what the established stack created
        rather than the other way around.
        It is not a flow list at all: it is an LCIA method, its rows are
        whatever its nineteen categories happen to characterise, it carries no
        identifiers of its own -- a SimaPro method file has none, so its UUIDs
        are derived from its names -- and 164 of its 6,064 rows carry no
        registry number either.
        """
        priorities = {
            key: source.merge_priority
            for key, source in known_source_lists().items()
        }
        self.assertEqual(
            priorities,
            {
                "bafu-2026-v1": 200,
                "stepwise-2006-1.09": 300,
                "agribalyse-3.2": 400,
                "ecoinvent-3.8": 100,
                "ecoinvent-3.9.1": 100,
                "ecoinvent-3.10.1": 100,
                "ecoinvent-3.11": 100,
                "ecoinvent-3.12": 100,
            },
        )

    def test_versions_of_one_list_merge_newest_first(self):
        """Whatever order the `--source` flags were typed in.

        Five ecoinvent releases share a priority, and this used to leave the tie
        to the caller -- so `-s ecoinvent-3.8 -s ecoinvent-3.12` and the same two
        flags reversed built different lists out of the same data (#100).  3.12
        has better names and more registry numbers than 3.8, and the list that
        reaches a substance first mints its flow object, so the newer release has
        to be the one that gets there.
        """
        keys = ["ecoinvent-3.8", "ecoinvent-3.10.1", "ecoinvent-3.12"]
        for order in (keys, list(reversed(keys))):
            with self.subTest(requested=order):
                requested = [known_source_lists()[key] for key in order]
                self.assertEqual(
                    [s.key for s in merge_order(requested)],
                    ["ecoinvent-3.12", "ecoinvent-3.10.1", "ecoinvent-3.8"],
                )

    def test_a_dotted_version_orders_by_number_not_by_string(self):
        """3.10.1 is newer than 3.9.1, and sorting the strings says otherwise."""
        ordered = merge_order([
            known_source_lists()["ecoinvent-3.9.1"],
            known_source_lists()["ecoinvent-3.10.1"],
        ])
        self.assertEqual(
            [s.key for s in ordered], ["ecoinvent-3.10.1", "ecoinvent-3.9.1"]
        )

    def test_what_a_version_string_sorts_as(self):
        """Digits in order, which is all the comparison needs to be.

        A version is only ever compared against another version of the same
        list, so this does not have to understand release channels or
        pre-release tags -- and an unnumbered version sorting first is the safe
        end of the range, since it merges last and matches against what the
        numbered releases built.
        """
        for version, expected in (
            ("3.8", (3, 8)),
            ("3.9.1", (3, 9, 1)),
            ("3.10.1", (3, 10, 1)),
            ("2026-v1", (2026, 1)),
            ("draft", ()),
        ):
            with self.subTest(version=version):
                source = SourceList.from_manifest(
                    {
                        "list_name": "somelist",
                        "list_version": version,
                        "role": SOURCE_ROLE,
                        "merge_priority": 100,
                        "flow_iri_prefix": "https://example.invalid/flow/",
                        "inputs": {"flows": "somelist-flows.json"},
                    },
                    path=SOURCE_MANIFEST_DIR / "somelist.json",
                )
                self.assertEqual(source.version_sort_key, expected)

    def test_priority_still_beats_version(self):
        """The rule inside a list does not reach across two of them.

        BAFU at 200 merges after every ecoinvent at 100, and its `2026-v1` is a
        larger number than any of them.
        """
        ordered = merge_order([
            known_source_lists()["bafu-2026-v1"],
            known_source_lists()["ecoinvent-3.8"],
            known_source_lists()["ecoinvent-3.12"],
        ])
        self.assertEqual(
            [s.key for s in ordered],
            ["ecoinvent-3.12", "ecoinvent-3.8", "bafu-2026-v1"],
        )

    def test_which_lists_simapro_shaped_the_names_of(self):
        """Pinned, because it is what a name-matching strategy is allowed on.

        BAFU and Stepwise 2006. ecoinvent's names are its own and EF 3.1's are
        the ILCD archive's, so a strategy that de-inverts `Benzene, chloro-` or
        strips the country off `Water, RER` must not reach either of them.

        The evidence for BAFU is in its own data: SimaPro's compartment
        vocabulary (`emissions to air / high. pop.`), the geography and the
        unit written into flow names, and 22 chemicals in CAS-index order --
        #65, #285, #67 and #286.

        Stepwise's is not evidence but provenance: it *is* a SimaPro file, a
        `{methods}` CSV export, so the habits are not inherited at a remove the
        way BAFU's are. They are all there -- `Occupation, arable`, `Gas,
        natural/m3`, `Uranium, 451 GJ per kg`, `Benzene, chloro-` -- and the
        lineage's own fixes were written naming this list before it had an
        adapter to reach them with."""
        flagged = {
            key for key, source in known_source_lists().items() if source.simapro_origin
        }
        self.assertEqual(
            flagged, {"bafu-2026-v1", "stepwise-2006-1.09", "agribalyse-3.2"}
        )
        self.assertFalse(base_source_list().simapro_origin)
        self.assertEqual(
            simapro_origin_source_labels(),
            frozenset({"bafu-2026-v1", "stepwise-2006-1.09", "agribalyse-3.2"}),
        )

    def test_the_flag_is_read_by_label_not_by_key(self):
        """A strategy holds a flow, and a flow carries `source`, not the key.

        The two coincide for every list but the base, whose flows say `EF 3.1`
        where its key is `EF-3.1`, so asserting "these are not keys" would be
        vacuous. What is asserted is the derivation: the labels are exactly the
        `source` strings of the flagged lists, so a flagged base list would be
        found by what its flows carry rather than by what its manifest is
        called.
        """
        base = base_source_list()
        self.assertNotEqual(base.source_label, base.key)
        self.assertEqual(
            simapro_origin_source_labels(),
            frozenset(
                source.source_label
                for source in (base, *known_source_lists().values())
                if source.simapro_origin
            ),
        )

    def test_flows_live_in_the_data_directory_and_curation_in_the_package(self):
        """The one derived input is fetched; the rest are decisions we keep."""
        for key, source in known_source_lists().items():
            with self.subTest(source=key):
                self.assertEqual(source.flows_path.parent, DATA_DIR)
                for path in (source.manual_fixes_path, source.manual_additions_path):
                    if path is not None:
                        self.assertEqual(path.parent, PACKAGE_DATA_DIR)

    def test_source_flows_path_comes_from_the_manifest(self):
        self.assertEqual(
            source_flows_path("ecoinvent-3.12"),
            DATA_DIR / "ecoinvent-biosphere-flows-3.12.json",
        )

    def test_fetching_an_unregistered_list_is_refused(self):
        """It would write a file nothing ever opens."""
        with self.assertRaises(ValueError):
            source_flows_path("ecoinvent-4.0")


class RegistryTestCase(unittest.TestCase):
    def test_resolve_returns_the_registered_list(self):
        self.assertEqual(resolve_source_list("ecoinvent-3.12").list_version, "3.12")

    def test_unknown_key_names_the_alternatives(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_source_list("ecoinvent-4.0")
        self.assertIn("ecoinvent-3.12", str(ctx.exception))

    def test_a_list_with_no_context_rules_is_refused_before_any_work(self):
        """The registry used to over-promise.

        Five ecoinvent versions resolved, but only two had context rules, so
        `--source ecoinvent-3.11` resolved, downloaded, ran the whole transform
        and *then* failed every row's context.  `build` resolves every
        `--source` before doing any work; this is what makes that early
        resolution worth something.

        The rules used to be a per-list file the manifest named, so this was
        "the file it declares is missing". They are now rows in one file keyed
        by `source` (#11), so it is "no row names this list" -- the same class
        of mistake, caught in the same place.

        Stated against a manifest written here rather than a shipped one: this
        test named ecoinvent 3.11 until 3.11 was mapped, and it is the last
        registered list that was in this state.  A registry with nothing in it
        to point at is exactly when an invariant stops being checked, which is
        why the state is constructed rather than borrowed.
        """
        with _registry_with_an_extra_list(
            {
                "list_name": "unmapped",
                "list_version": "2025",
                "role": SOURCE_ROLE,
                "merge_priority": 200,
                "flow_iri_prefix": "https://vocab.brightway.one/unmapped/2025/flow/",
                "inputs": {"flows": "unmapped-2025-flows.json"},
            }
        ):
            with self.assertRaises(ValueError) as ctx:
                resolve_source_list("unmapped-2025")
        message = str(ctx.exception)
        self.assertIn("unmapped-2025", message)
        self.assertIn("context mapping rules", message)
        self.assertIn("context-manual-mapping.json", message)

    def test_a_list_whose_inputs_all_exist_resolves(self):
        for key in ("ecoinvent-3.8", "ecoinvent-3.12"):
            with self.subTest(source=key):
                self.assertEqual(resolve_source_list(key).key, key)

    def test_an_absent_curated_input_is_not_a_missing_one(self):
        """`null` says the list has none, which is normal on the day it lands.

        Stated against a manifest built here rather than a shipped one: this
        test named ecoinvent 3.8 until 3.8 gained a fixes file, and a list
        acquiring the input the test needed it to lack is not a regression.
        """
        source = SourceList.from_manifest(
            {
                "list_name": "bafu",
                "list_version": "2025",
                "role": SOURCE_ROLE,
                "merge_priority": 200,
                "flow_iri_prefix": "https://vocab.brightway.one/bafu/2025/flow/",
                "inputs": {"flows": "bafu-2025.json", "manual_fixes": None},
            },
            path=Path("bafu-2025.json"),
        )
        self.assertIsNone(source.manual_fixes_path)
        self.assertEqual(source.missing_curated_inputs(), [])

    def test_a_curated_input_a_manifest_names_is_shipped(self):
        """The other half: a named input that is not there is a broken list."""
        for key in ("ecoinvent-3.8", "ecoinvent-3.12"):
            with self.subTest(source=key):
                source = resolve_source_list(key)
                self.assertIsNotNone(source.manual_fixes_path)
                self.assertEqual(source.missing_curated_inputs(), [])

    def test_a_missing_flows_file_is_not_a_resolution_error(self):
        """It is fetched, not authored, and `--dry-run` never reads it."""
        source = resolve_source_list("ecoinvent-3.12")
        self.assertNotIn(
            "flows", [name for name, _ in source.missing_curated_inputs()]
        )

    def test_a_list_with_no_correspondence_table_is_constructible(self):
        """A list nobody has mapped yet is still a list.

        This used to raise, which contradicted `SourceList`'s own docstring --
        every curated input is optional -- and made `load_prepared_match_table`
        returning `[]` for a table-less list unreachable.
        """
        unmapped = SourceList.from_manifest(
            {
                "list_name": "bafu",
                "list_version": "2025",
                "role": SOURCE_ROLE,
                "merge_priority": 200,
                "flow_iri_prefix": "https://vocab.brightway.one/bafu/2025/flow/",
                "prepared_match_table": None,
                "inputs": {"flows": "bafu-2025.json"},
            },
            path=Path("bafu-2025.json"),
        )
        self.assertEqual(unmapped.key, "bafu-2025")
        self.assertIsNone(unmapped.prepared_match_table)
        self.assertEqual(load_prepared_match_table(unmapped), [])

    def test_registry_is_built_per_call_not_frozen_at_import(self):
        """The harness overrides the data directory per run; a module-level
        dict would freeze the paths of whichever run imported first."""
        self.assertIsNot(known_source_lists(), known_source_lists())


class ManifestValidationTestCase(unittest.TestCase):
    """A manifest that does not describe a list says so, and says which file."""

    BASE = {
        "list_name": "bafu",
        "list_version": "2025",
        "role": "source",
        "merge_priority": 200,
        "flow_iri_prefix": "https://vocab.brightway.one/bafu/2025/flow/",
        "inputs": {"flows": "bafu-2025.json", "manual_fixes": "fixes.json"},
    }

    def _build(self, **overrides):
        return SourceList.from_manifest(
            {**self.BASE, **overrides}, path=Path("bafu-2025.json")
        )

    def test_a_source_without_a_merge_priority_is_rejected(self):
        """Silently defaulting would put it wherever the flags happened to fall."""
        payload = {k: v for k, v in self.BASE.items() if k != "merge_priority"}
        with self.assertRaises(ValueError) as ctx:
            SourceList.from_manifest(payload, path=Path("bafu-2025.json"))
        message = str(ctx.exception)
        self.assertIn("merge_priority", message)
        self.assertIn("mints its flow object", message)

    def test_simapro_origin_defaults_to_false(self):
        """Optional, unlike `merge_priority`, and the difference is the failure.

        A missing merge priority silently produces the wrong output. A missing
        flag here declines an opportunity: the extra strategies do not run and
        the rows stay unmatched, which the merge report shows."""
        payload = {k: v for k, v in self.BASE.items() if k != "simapro_origin"}
        source = SourceList.from_manifest(payload, path=Path("bafu-2025.json"))
        self.assertFalse(source.simapro_origin)

    def test_a_non_boolean_simapro_origin_is_rejected(self):
        """`"true"` and `1` both read as true and are not what the key means."""
        for value in ("true", 1, "yes", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as ctx:
                    self._build(simapro_origin=value)
                self.assertIn("simapro_origin", str(ctx.exception))

    def test_simapro_origin_is_carried_through(self):
        self.assertTrue(self._build(simapro_origin=True).simapro_origin)

    def test_a_boolean_merge_priority_is_rejected(self):
        """`True` is an `int` in Python, and is not a position in an order."""
        with self.assertRaises(ValueError):
            self._build(merge_priority=True)

    def test_the_base_list_needs_no_merge_priority(self):
        """It is what the sources are merged *into*, so it is always first."""
        base = SourceList.from_manifest(
            {
                "list_name": "EF",
                "list_version": "3.1",
                "role": "base",
                "flow_iri_prefix": "https://vocab.brightway.one/ef/3.1/flow/",
                "inputs": {"flows": "ef-31-flows.json"},
            },
            path=Path("ef-3.1.json"),
        )
        self.assertEqual(base.role, "base")

    def test_an_unknown_role_is_rejected_by_name(self):
        with self.assertRaises(ValueError) as ctx:
            self._build(role="primary")
        self.assertIn("bafu-2025.json", str(ctx.exception))

    def test_a_missing_flows_input_is_rejected(self):
        with self.assertRaises(ValueError):
            self._build(inputs={"manual_fixes": "fixes.json"})

    def test_an_empty_iri_prefix_is_rejected(self):
        """The one-way door cannot be left ajar."""
        with self.assertRaises(ValueError):
            self._build(flow_iri_prefix="")

    def test_paths_resolve_against_the_right_root(self):
        source = self._build()
        self.assertEqual(source.flows_path, DATA_DIR / "bafu-2025.json")
        self.assertEqual(source.manual_fixes_path, PACKAGE_DATA_DIR / "fixes.json")

    def test_an_absent_input_key_is_the_same_as_null(self):
        source = self._build(inputs={"flows": "bafu-2025.json"})
        self.assertIsNone(source.manual_fixes_path)
        self.assertIsNone(source.manual_additions_path)

    def test_a_list_publishing_no_mappings_declares_none(self):
        self.assertIsNone(self._build().concept_associations)

    def test_a_concept_association_block_is_parsed(self):
        source = self._build(concept_associations={
            "scheme": "simapro-10.2",
            "pairs_from": "glad",
        })
        self.assertEqual(source.concept_associations.scheme, "simapro-10.2")
        self.assertEqual(source.concept_associations.pairs_from, "glad")

    def test_a_block_that_is_not_an_object_names_the_file(self):
        with self.assertRaises(ValueError) as ctx:
            self._build(concept_associations="glad")
        self.assertIn("bafu-2025.json", str(ctx.exception))

    def test_context_rules_are_not_a_per_list_input(self):
        """They are rows in one file keyed by `source`, not a path a list owns.

        The path used to name a *generated* projection of that file which
        `build` never regenerated, so editing the master moved the transform
        and left the merge on a stale copy (#11). An input a manifest can
        declare is one a curator can be told to author; this one cannot be.
        """
        self.assertNotIn("context_mapping", _CURATED_INPUTS)
        for path in sorted(SOURCE_MANIFEST_DIR.glob("*.json")):
            with self.subTest(manifest=path.name):
                payload = orjson.loads(path.read_bytes())
                self.assertNotIn("context_mapping", payload.get("inputs", {}))


class FrozenTestCase(unittest.TestCase):
    def test_source_lists_are_immutable(self):
        """A merge must not be able to change which list it is merging."""
        source = resolve_source_list("ecoinvent-3.12")
        with self.assertRaises(FrozenInstanceError):
            source.list_name = "something-else"


class LoadFlowsTestCase(unittest.TestCase):
    """A source list produces its own flows, as records.

    The merge read and repaired the file inline, so its source flows were the
    last dict-shaped data in the pipeline and could not be handed to a
    transformer. These pin what the merge reads off the record, since a
    mismatch there is a silently unmatched flow rather than an error.
    """

    ROW = {
        "uuid": "u-1",
        "name": "Carbon dioxide",
        "unit": "kg",
        "context": ["air", "unspecified"],
        "cas_number": "124-38-9",
        "synonyms": ["CO2"],
        "source": "ecoinvent-3.12",
    }

    def _source(self, tmp, rows, *, fixes=None):
        data_dir = Path(tmp)
        flows_path = data_dir / "flows.json"
        flows_path.write_bytes(orjson.dumps(rows))
        fixes_path = data_dir / "fixes.json"
        if fixes is not None:
            fixes_path.write_bytes(orjson.dumps({"fixes": fixes}))
        return SourceList(
            list_name="ecoinvent",
            list_version="3.12",
            flows_path=flows_path,
            manual_fixes_path=fixes_path,
            adapter="brightway_flows.integrations.ecoinvent:fetch",
        )

    def test_rows_become_flow_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            flows = self._source(tmp, [self.ROW]).load_flows()
        self.assertEqual([type(f).__name__ for f in flows], ["Flow"])
        self.assertEqual(flows[0].uuid, "u-1")
        self.assertEqual(flows[0].name, "Carbon dioxide")
        self.assertEqual(flows[0].unit, "kg")
        self.assertEqual(flows[0].provided.context, ["air", "unspecified"])
        self.assertEqual(flows[0].synonyms, ["CO2"])

    def test_the_singular_cas_number_becomes_the_record_list(self):
        """The merge reads `cas_numbers[0]` where it used to read `cas_number`."""
        with tempfile.TemporaryDirectory() as tmp:
            flows = self._source(tmp, [self.ROW]).load_flows()
        self.assertEqual(flows[0].cas_numbers, ["124-38-9"])

    def test_manual_fixes_are_applied(self):
        """They name the source list's own fields, so they run before
        normalisation -- `cas_number`, not `cas_numbers`."""
        with tempfile.TemporaryDirectory() as tmp:
            source = self._source(tmp, [dict(self.ROW)], fixes=[{
                "uuid": "u-1",
                "field": "cas_number",
                "new_value": "000124-38-9",
                "comment": "leading zeros",
            }])
            flows = source.load_flows()
        self.assertEqual(flows[0].cas_numbers, ["000124-38-9"])

    def test_a_list_that_declares_no_manual_fixes_loads(self):
        """`None`, not a path to a file that was never going to be there."""
        with tempfile.TemporaryDirectory() as tmp:
            flows_path = Path(tmp) / "flows.json"
            flows_path.write_bytes(orjson.dumps([self.ROW]))
            source = SourceList(
                list_name="bafu", list_version="2025", flows_path=flows_path
            )
            self.assertEqual([f.uuid for f in source.load_flows()], ["u-1"])

    def test_a_row_with_no_identifier_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            flows = self._source(tmp, [self.ROW, {"name": "no uuid"}]).load_flows()
        self.assertEqual([f.uuid for f in flows], ["u-1"])

    def test_a_missing_file_names_the_source_and_the_command(self):
        """The command follows from the key, for every list.

        It was `if self.list_name == "ecoinvent"` in this function, then a
        `fetch_command` string per manifest, and is now derived from the key
        because one command fetches any list (#15).
        """
        with tempfile.TemporaryDirectory() as tmp:
            source = self._source(tmp, [])
            source.flows_path.unlink()
            with self.assertRaises(FileNotFoundError) as ctx:
                source.load_flows()
        self.assertIn("ecoinvent-3.12", str(ctx.exception))
        self.assertIn("fetch-source ecoinvent-3.12", str(ctx.exception))

    def test_a_list_with_no_adapter_is_offered_no_command(self):
        """A hint naming a command that would fail is worse than none."""
        with tempfile.TemporaryDirectory() as tmp:
            flows_path = Path(tmp) / "flows.json"
            source = SourceList(
                list_name="bafu", list_version="2025", flows_path=flows_path
            )
            self.assertEqual(source.fetch_command, "")
            with self.assertRaises(FileNotFoundError) as ctx:
                source.load_flows()
        self.assertNotIn("Run `", str(ctx.exception))

    def test_a_payload_that_is_not_a_list_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._source(tmp, [])
            source.flows_path.write_bytes(orjson.dumps({"flows": []}))
            with self.assertRaises(ValueError):
                source.load_flows()


class PreparedMatchTableLoadingTestCase(unittest.TestCase):
    """A table is named by its verb and located by name *or* path.

    `randonneur_data` publishes no ecoinvent 3.8 to EF 3.1 correspondence, so
    that table is composed here, reviewed and checked in -- which means the
    loader has to accept a local file as well as a registry name.  And it used
    to read `data["replace"]` unconditionally, so any table using the `update`
    verb raised `KeyError` rather than loading.
    """

    ROWS = [{"source": {"uuid": "s-1"}, "target": {"uuid": "t-1"}}]

    def _source_with_table(self, table):
        return SourceList(
            list_name="ecoinvent",
            list_version="3.8",
            flows_path=Path("/nonexistent/flows.json"),
            prepared_match_table=table,
        )

    def _write(self, tmp, payload):
        path = Path(tmp) / "table.json"
        path.write_bytes(orjson.dumps(payload))
        return path

    def test_a_replace_table_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"replace": self.ROWS})
            rows = load_prepared_match_table(self._source_with_table(str(path)))
        self.assertEqual(rows, self.ROWS)

    def test_an_update_table_loads(self):
        """The verb the transitive tables use.  This used to raise KeyError."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"update": self.ROWS})
            rows = load_prepared_match_table(self._source_with_table(str(path)))
        self.assertEqual(rows, self.ROWS)

    def test_a_delete_only_table_yields_no_decisions(self):
        """`delete` names a source with no target: the absence of a decision."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"delete": [{"source": {"uuid": "s-1"}}]})
            rows = load_prepared_match_table(self._source_with_table(str(path)))
        self.assertEqual(rows, [])

    def test_a_missing_local_table_is_an_error_not_an_empty_table(self):
        """Silently merging with no decisions would look like a clean run."""
        with self.assertRaises(FileNotFoundError):
            load_prepared_match_table(
                self._source_with_table("/nonexistent/table.json")
            )

    def test_a_null_table_still_loads_the_overrides(self):
        """The retirement's load contract (#141): with no table declared, the
        loader starts from an empty table and the override file's rewrite rows
        are appended onto it, which is how this project's own correspondence
        reaches the merge.  3.8's checked-in composed table used to be the
        local-path case here; it retired with the rest."""
        source = resolve_source_list("ecoinvent-3.8")
        self.assertIsNone(source.prepared_match_table)
        rows = load_prepared_match_table(source)
        self.assertTrue(rows)
        self.assertTrue(all((row.get("route") == "override") or "comment" in row
                            for row in rows))

    def test_a_registry_name_is_still_a_registry_name(self):
        """A bare name must not be mistaken for a path."""
        rows = load_prepared_match_table(
            self._source_with_table("ecoinvent-3.11-biosphere-EF-3.1-biosphere")
        )
        self.assertTrue(rows)
        self.assertIn("source", rows[0])


class UnitSuffixInNamesTestCase(unittest.TestCase):
    """`load_flows` takes the unit back out of the names of a list SimaPro
    shaped (#67).

    BAFU ships `Water/m3` and `Water, process, unspecified natural origin/kg`:
    the unit is in the name because SimaPro keys its flows on names alone.
    This list holds the unit as its own field, so the copy says the same thing
    twice -- and stops the row matching the flow it names.

    Applied to the name rather than offered as an alias while matching, because
    it also has to reach the name a *created* flow is published under.
    """

    ROWS = (
        {"uuid": "u-1", "name": "Water/m3", "unit": "m3",
         "context": ["resources", "in water"], "synonyms": []},
        {"uuid": "u-2", "name": "Carbon dioxide", "unit": "kg",
         "context": ["emissions to air", "unspecified"]},
    )

    #: One base name, two units, both spelled with the suffix.  The suffix is
    #: the only thing telling the two apart, so it stays on both.
    AMBIGUOUS = (
        {"uuid": "u-4", "name": "Water, process/kg", "unit": "kg",
         "context": ["resources", "in water"]},
        {"uuid": "u-5", "name": "Water, process/m3", "unit": "m3",
         "context": ["resources", "in water"]},
    )

    def _source(self, tmp, rows, *, simapro, fixes=None):
        flows_path = Path(tmp) / "flows.json"
        flows_path.write_bytes(orjson.dumps(rows))
        fixes_path = Path(tmp) / "fixes.json"
        if fixes is not None:
            fixes_path.write_bytes(orjson.dumps({"fixes": fixes}))
        return SourceList(
            list_name="bafu",
            list_version="2026-v1",
            flows_path=flows_path,
            manual_fixes_path=fixes_path if fixes is not None else None,
            simapro_origin=simapro,
        )

    def _rows(self):
        return [dict(row) for row in self.ROWS]

    def test_the_suffix_comes_off_a_list_simapro_shaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            flows = self._source(tmp, self._rows(), simapro=True).load_flows()
        self.assertEqual([flow.name for flow in flows], ["Water", "Carbon dioxide"])
        self.assertEqual(flows[0].unit, "m3")

    def test_a_list_simapro_did_not_shape_keeps_its_names(self):
        """The flag is what gates it. On any other list a trailing `/kg` is
        somebody's name for a substance, and not ours to edit."""
        with tempfile.TemporaryDirectory() as tmp:
            flows = self._source(tmp, self._rows(), simapro=False).load_flows()
        self.assertEqual(
            [flow.name for flow in flows], ["Water/m3", "Carbon dioxide"]
        )

    def test_the_vendor_spelling_is_kept_as_a_synonym(self):
        """A consumer holding a BAFU inventory searches for the name their own
        file has. It has to keep leading to the flow they mean."""
        with tempfile.TemporaryDirectory() as tmp:
            flows = self._source(tmp, self._rows(), simapro=True).load_flows()
        self.assertEqual(flows[0].synonyms, ["Water/m3"])

    def test_manual_fixes_run_first(self):
        """A correction is written by reading the vendor's file, so it names a
        flow the way the vendor shipped it -- and rewriting the name is how a
        row this pattern declines gets corrected at all."""
        rows = [{"uuid": "u-3", "name": "Gas, natural/m3", "unit": "Nm3",
                 "context": ["resources", "in ground"]}]
        with tempfile.TemporaryDirectory() as tmp:
            flows = self._source(tmp, rows, simapro=True, fixes=[{
                "match": {"name": "Gas, natural/m3", "unit": "Nm3"},
                "field": "name",
                "new_value": "Gas, natural",
                "comment": "the unit field says Nm3, so the pattern declines it",
            }]).load_flows()
        self.assertEqual([flow.name for flow in flows], ["Gas, natural"])

    def test_a_tail_that_is_not_the_row_s_unit_survives(self):
        """Declined rather than guessed at: a normal cubic metre is a different
        measure from a cubic metre, and here the name and the unit field
        disagree about which was meant."""
        rows = [{"uuid": "u-3", "name": "Gas, natural/m3", "unit": "Nm3",
                 "context": ["resources", "in ground"]}]
        with tempfile.TemporaryDirectory() as tmp:
            flows = self._source(tmp, rows, simapro=True).load_flows()
        self.assertEqual([flow.name for flow in flows], ["Gas, natural/m3"])

    def test_two_units_under_one_name_both_lose_their_suffixes(self):
        """A flow's identity is its substance and its context and not its unit,
        so two rows that agree on a name and a compartment reach one flow
        whatever their names say. The suffix was not holding them apart, it was
        holding two names apart above one flow -- and costing both rows their
        match, because no flow object answers to a name with a unit on the end.

        Each row keeps its own unit and its own uuid; what a consumer needs to
        know about the two being one quantity, or not, is a conversion stated in
        that list's manual fixes (#67, #78)."""
        with tempfile.TemporaryDirectory() as tmp:
            flows = self._source(
                tmp, [dict(row) for row in self.AMBIGUOUS], simapro=True
            ).load_flows()
        self.assertEqual(
            [flow.name for flow in flows],
            ["Water, process", "Water, process"],
        )
        self.assertEqual([flow.unit for flow in flows], ["kg", "m3"])
        self.assertEqual(
            [flow.synonyms for flow in flows],
            [["Water, process/kg"], ["Water, process/m3"]],
        )

    def test_one_unit_under_one_name_loses_them(self):
        """The same two rows once they agree about the measure. Nothing is
        being told apart, so nothing is kept."""
        rows = [dict(row) for row in self.AMBIGUOUS]
        rows[0]["name"], rows[0]["unit"] = "Water, process/m3", "m3"
        with tempfile.TemporaryDirectory() as tmp:
            flows = self._source(tmp, rows, simapro=True).load_flows()
        self.assertEqual(
            [flow.name for flow in flows], ["Water, process", "Water, process"]
        )


class BafuUnitSuffixesTestCase(unittest.TestCase):
    """What the rule does to the list it was written for.

    The unit tests above pin the rule; this pins the answer on BAFU 2026 v1,
    because that is the thing a release can change underneath us. Skipped when
    the list has not been fetched.
    """

    @classmethod
    def setUpClass(cls):
        source = resolve_source_list("bafu-2026-v1")
        if not source.flows_path.exists():
            raise unittest.SkipTest(
                "BAFU 2026 v1 has not been fetched into the data directory."
            )
        cls.flows = source.load_flows()

    #: Every name BAFU ships with its unit in it that the rule rewrites, and
    #: what it becomes. The real set rather than a sample: this is the whole of
    #: what the rule has to get right, and a release adding a shape it reads
    #: differently should fail here.
    REWRITTEN = {
        "Gas, mine, off-gas, process, coal mining/m3":
            "Gas, mine, off-gas, process, coal mining",
        "Gas, natural/m3": "Gas, natural",
        "Waste water/m3": "Waste water",
        "Water, cooling, unspecified natural origin/m3":
            "Water, cooling, unspecified natural origin",
        "Water, process, unspecified natural origin/m3":
            "Water, process, unspecified natural origin",
        "Water, unspecified natural origin/m3": "Water, unspecified natural origin",
        "Water/m3": "Water",
        "Wood, unspecified, standing/m3": "Wood, unspecified, standing",
    }

    #: Nothing, now, and it used to be a pair.
    #:
    #: The rule refuses to strip a suffix where two suffixed rows would strip to
    #: one name in two units, and `Water, process, unspecified natural origin`
    #: was that case: over the 11,947 datasets of the release the mass spelling
    #: is used in 71 and the volume spelling in 78, and 63 carry **both**, in
    #: the same subcompartment, so the suffix was the only thing telling them
    #: apart. What removed the case was removing the second unit: the kilogram
    #: rows are carried in cubic metres with the density stated (#78), so the
    #: rule sees one unit and strips the volume spelling on its own, and the
    #: mass spelling is renamed by hand in the fixes -- which it has to be,
    #: because rewriting the unit is what makes `/kg` stop matching it. The two
    #: rows keep their own uuids and their own mappings; what they no longer
    #: keep is two names for one substance in one compartment.
    KEPT: tuple[str, ...] = ()

    #: Renamed by hand in `bafu-2026-v1-manual-fixes.json` rather than by the
    #: rule, for the reason above. Pinned here beside the rule's own rewrites so
    #: the two are read together: between them they are every BAFU name that
    #: loses a unit, however it loses it.
    RENAMED_BY_FIX = {
        "Water, process, unspecified natural origin/kg":
            "Water, process, unspecified natural origin",
        "Wood, unspecified, standing/kg": "Wood, unspecified, standing",
    }

    def test_every_rewritten_name_reaches_its_flow(self):
        names = {flow.name for flow in self.flows}
        for shipped, expected in sorted(self.REWRITTEN.items()):
            with self.subTest(name=shipped):
                self.assertIn(expected, names)
                self.assertNotIn(shipped, names)

    def test_the_vendor_spelling_survives_as_a_synonym(self):
        by_synonym = {
            synonym: flow
            for flow in self.flows
            for synonym in (flow.synonyms or [])
        }
        for shipped, expected in sorted(self.REWRITTEN.items()):
            with self.subTest(name=shipped):
                self.assertIn(shipped, by_synonym)
                self.assertEqual(by_synonym[shipped].name, expected)

    def test_no_pair_needs_its_suffix_to_be_told_apart(self):
        names = {flow.name for flow in self.flows}
        for shipped in self.KEPT:
            with self.subTest(name=shipped):
                self.assertIn(shipped, names)
        self.assertIn("Water, process, unspecified natural origin", names)

    def test_the_names_a_fix_rewrites_by_hand_are_rewritten(self):
        """The rule cannot do these: a fix has already changed the unit, so the
        suffix no longer matches it and the rule correctly declines to strip
        something that is no longer redundant."""
        names = {flow.name for flow in self.flows}
        by_synonym = {
            synonym: flow
            for flow in self.flows
            for synonym in (flow.synonyms or [])
        }
        for shipped, expected in sorted(self.RENAMED_BY_FIX.items()):
            with self.subTest(name=shipped):
                self.assertIn(expected, names)
                self.assertNotIn(shipped, names)
                self.assertIn(shipped, by_synonym)

    def test_every_row_of_that_name_is_now_cubic_metres(self):
        """What made the suffix necessary was two units under one name. The
        claim that replaces it is that there is only one."""
        units = {
            flow.unit
            for flow in self.flows
            if flow.name == "Water, process, unspecified natural origin"
        }
        self.assertEqual(units, {"m3"})

    def test_no_other_name_still_carries_a_unit(self):
        """A slash in a name is fine -- BAFU's `rail/road embankment` has one --
        but a name whose tail is this row's own unit is a copy of a field, and
        after this only the pair above may still be one."""
        left = {
            flow.name
            for flow in self.flows
            if name_without_unit_suffix(flow.name, flow.unit) is not None
        }
        self.assertEqual(left, set(self.KEPT))
        self.assertEqual(left, set())


if __name__ == "__main__":
    unittest.main()
