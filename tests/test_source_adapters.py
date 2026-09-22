"""Every list is fetched the same way, and the manifest says how.

`docs/operating/sources.md` step 1 says "write an adapter that converts the
source into the record shape and save the result to the data directory". Until
#15 there was nowhere for one to live and no protocol for it to satisfy, so
"add a list" meant a module, a CLI command, a `filesystem.py` path function and
a registry edit — and the base list's own extraction sat inline in `cli.py`,
which is the strongest evidence there was no concept.

These pin the three things that make the claim true: a manifest names an adapter
that can actually be imported, one command runs any of them, and an adapter that
writes to the wrong place fails loudly rather than leaving a file nothing opens.
"""

import unittest
from pathlib import Path
from unittest.mock import patch

import orjson
import typer

from brightway_flows.application.cli import app
from brightway_flows.sources import (
    SOURCE_MANIFEST_DIR,
    SourceList,
    _registry,
    base_source_list,
    fetch_source_flows,
    known_source_lists,
    load_adapter,
    registered_source_list,
)


def command_names() -> set[str]:
    return set(typer.main.get_command(app).commands)


def writes_to_the_declared_path(source: SourceList, *, force: bool = False) -> Path:
    """A minimal well-behaved adapter: it satisfies the protocol exactly."""
    source.flows_path.write_bytes(orjson.dumps([]))
    return source.flows_path


class EveryManifestNamesAnImportableAdapterTestCase(unittest.TestCase):
    def test_every_registered_list_declares_one(self):
        """Including the base list.  `role: "base"` says which list is merged
        into, not that it arrives by a different route."""
        for key, source in _registry().items():
            with self.subTest(source=key):
                self.assertTrue(source.adapter, f"{key} declares no adapter")
                self.assertIn(":", source.adapter)

    def test_every_declared_adapter_imports_and_is_callable(self):
        """A dotted path is a string until something dereferences it.  This is
        what stops a typo from surviving until someone runs the fetch."""
        for key, source in _registry().items():
            with self.subTest(source=key):
                self.assertTrue(callable(load_adapter(source)))

    def test_the_five_ecoinvent_manifests_share_one_adapter(self):
        """The point of passing the `SourceList`: they differ in `list_version`,
        which the adapter reads off it.  A no-argument `fetch()` would need five
        near-identical functions."""
        adapters = {
            source.adapter
            for key, source in known_source_lists().items()
            if source.list_name == "ecoinvent"
        }
        self.assertEqual(adapters, {"brightway_flows.integrations.ecoinvent:fetch"})
        self.assertEqual(
            len([s for s in known_source_lists().values() if s.list_name == "ecoinvent"]),
            5,
        )


class AdapterResolutionFailsAgainstTheListTestCase(unittest.TestCase):
    """A manifest mistake is reported as a manifest mistake."""

    def _source(self, adapter):
        return SourceList(
            list_name="bafu",
            list_version="2025",
            flows_path=Path("/nonexistent/bafu-2025.json"),
            adapter=adapter,
        )

    def test_a_list_with_no_adapter_says_what_to_add(self):
        with self.assertRaises(ValueError) as ctx:
            load_adapter(self._source(""))
        message = str(ctx.exception)
        self.assertIn("bafu-2025", message)
        self.assertIn("adapter", message)

    def test_a_path_with_no_colon_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            load_adapter(self._source("brightway_flows.integrations.bafu"))
        self.assertIn("module:attribute", str(ctx.exception))

    def test_an_unimportable_module_names_the_list(self):
        """Not an `ImportError` from a module the reader has never heard of."""
        with self.assertRaises(ValueError) as ctx:
            load_adapter(self._source("brightway_flows.no_such_module:fetch"))
        self.assertIn("bafu-2025", str(ctx.exception))

    def test_a_missing_attribute_names_the_list(self):
        with self.assertRaises(ValueError) as ctx:
            load_adapter(
                self._source("brightway_flows.integrations.ef31:no_such_fetch")
            )
        self.assertIn("bafu-2025", str(ctx.exception))


class FetchWritesWhereTheManifestSaysTestCase(unittest.TestCase):
    """The half of the contract that used to be a coincidence.

    Before #12 the fetch built the flows filename from a convention and
    `filesystem.ecoinvent_flows_filepath` built it again from the same
    convention, so they agreed by luck. The manifest is now the single answer,
    and this is what holds an adapter to it: a fetch that writes elsewhere has
    produced a file the merge will never open, and without this check the run
    that notices is the one an hour later reporting the flows missing.
    """

    def _source(self, tmp):
        return SourceList(
            list_name="bafu",
            list_version="2025",
            flows_path=Path(tmp) / "bafu-2025-flows.json",
            adapter="tests.test_source_adapters:writes_to_the_declared_path",
        )

    def test_an_adapter_writing_the_declared_path_is_accepted(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            source = self._source(tmp)
            with patch(
                "brightway_flows.sources.load_adapter",
                return_value=writes_to_the_declared_path,
            ):
                written = fetch_source_flows(source)
            self.assertEqual(written, source.flows_path)
            self.assertTrue(written.exists())

    def test_an_adapter_writing_elsewhere_is_refused(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            source = self._source(tmp)
            stray = Path(tmp) / "somewhere-else.json"
            with patch(
                "brightway_flows.sources.load_adapter",
                return_value=lambda src, *, force=False: stray,
            ):
                with self.assertRaises(ValueError) as ctx:
                    fetch_source_flows(source)
        message = str(ctx.exception)
        self.assertIn("somewhere-else.json", message)
        self.assertIn("bafu-2025-flows.json", message)

    def test_force_reaches_the_adapter(self):
        """The one argument the protocol carries beyond the list itself."""
        import tempfile

        seen: list[bool] = []

        def adapter(src, *, force=False):
            seen.append(force)
            src.flows_path.write_bytes(orjson.dumps([]))
            return src.flows_path

        with tempfile.TemporaryDirectory() as tmp:
            source = self._source(tmp)
            with patch(
                "brightway_flows.sources.load_adapter", return_value=adapter
            ):
                fetch_source_flows(source, force=True)
        self.assertEqual(seen, [True])


class OneCommandFetchesAnyListTestCase(unittest.TestCase):
    def test_fetch_source_is_a_command(self):
        self.assertIn("fetch-source", command_names())

    def test_the_per_list_commands_survive_as_aliases(self):
        """Both are in the README quick start and in existing runbooks, so
        neither is removed -- but neither has an implementation of its own."""
        for name in ("extract", "download-ecoinvent-flows"):
            with self.subTest(name):
                self.assertIn(name, command_names())

    def test_no_command_reimplements_a_fetch(self):
        """The aliases route through the adapter, so they cannot drift from
        `fetch-source`. `extract` held ~55 lines of ILCD extraction until #15.
        """
        import inspect

        commands = typer.main.get_command(app).commands
        for name in ("extract", "download-ecoinvent-flows", "fetch-source"):
            with self.subTest(name):
                body = inspect.getsource(commands[name].callback)
                self.assertNotIn("ZipFile", body)
                self.assertNotIn("extract_flow_data", body)

    def test_fetching_an_unregistered_list_is_refused_by_name(self):
        """It would write a file nothing ever opens."""
        with self.assertRaises(ValueError) as ctx:
            registered_source_list("ecoinvent-4.0")
        self.assertIn("ecoinvent-3.12", str(ctx.exception))

    def test_the_base_list_is_fetchable_even_though_it_is_not_a_source(self):
        """`resolve_source_list` refuses it, because merging it into itself is
        not a build anyone means. Fetching it is an ordinary thing to do."""
        base = base_source_list()
        self.assertEqual(registered_source_list(base.key).key, base.key)
        self.assertNotIn(base.key, known_source_lists())


class TheFetchCommandIsDerivedTestCase(unittest.TestCase):
    """It was a string per manifest until #15.

    Which meant a new list had to invent a command *and* write the code behind
    it, and renaming a command left five manifests telling readers to run
    something that no longer existed.
    """

    def test_no_manifest_declares_one(self):
        for path in sorted(SOURCE_MANIFEST_DIR.glob("*.json")):
            with self.subTest(manifest=path.name):
                payload = orjson.loads(path.read_bytes())
                self.assertNotIn("fetch_command", payload)

    def test_it_follows_from_the_key(self):
        for key, source in _registry().items():
            with self.subTest(source=key):
                self.assertEqual(source.fetch_command, f"fetch-source {key}")

    def test_a_list_with_no_adapter_has_no_command(self):
        source = SourceList(
            list_name="bafu", list_version="2025", flows_path=Path("/nonexistent")
        )
        self.assertEqual(source.fetch_command, "")


if __name__ == "__main__":
    unittest.main()
