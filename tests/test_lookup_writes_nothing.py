"""`lookup` cannot write, and `merge` cannot depend on it.

"It does not write" is the kind of property that decays: nothing fails when a
later change imports one convenient helper that happens to mint an identifier,
and the failure it causes is silent -- a lookup that adds a flow to a database
somebody else is reading.

`plans/lookup-api.md` §3.7 enforces it in three places. The connection is opened
`mode=ro` (`tests/test_lookup_index.py`), the accumulator handed to
`resolve_flow_object` is constructed per query and discarded, and no module under
`lookup/` can reach a function that creates anything. This file is the third,
plus the architectural half of it: the arrow between the two sections runs one
way.
"""

from __future__ import annotations

import ast
import unittest

from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "brightway_flows"
LOOKUP = SRC / "lookup"
MERGE = SRC / "merge"

#: The write path. Every one of these creates a flow, mints an identifier or
#: writes a row, and none of them is reachable from anywhere in `lookup`.
#:
#: `merge.matching` and `merge.state` are deliberately absent: they are the pure
#: half, and calling them is the entire design. `merge.report` and
#: `merge.contexts` likewise -- they are records and rules, not writers.
FORBIDDEN = (
    "brightway_flows.merge.creations",
    "brightway_flows.merge.additions",
    "brightway_flows.merge.datastores",
    "brightway_flows.merge.pipeline",
    "brightway_flows.merge.rows",
    "brightway_flows.pipeline.sqlite",
    "brightway_flows.pipeline.review_tables",
)

#: `merge.store` is the one module with a reading half and a writing half, and
#: the split matters here: `read_outcomes` is how `lookup/replay.py` asks a build
#: what it decided, while `write_source_outcomes` is how a merge records it.
#:
#: So the module is not blanket-forbidden -- that would push `replay` into
#: reimplementing a reader -- and these three names are refused instead. A name
#: list is more brittle than a module list, which is why it is *only* used here:
#: everywhere else the module list stands, and the answering path below may not
#: touch `merge.store` at all.
FORBIDDEN_STORE_NAMES = (
    "write_source_outcomes",
    "write_merge_run",
    "start_run",
    "finish_run",
    "create_merge_tables",
    "detect_conflicts",
)

#: The modules a question actually travels through. Nothing here may reach the
#: writing half of the merge by any route, including the reading half of a
#: module that has both. `replay` is not among them: it verifies the answering
#: path and is never called by it.
ANSWERING_PATH = ("__init__.py", "index.py", "query.py", "matcher.py")


def _imports(path: Path) -> set[str]:
    """Every module *path* imports, by dotted name.

    A `from x import y` contributes both `x` and `x.y`, because a forbidden
    module can be reached either way.
    """
    tree = ast.parse(path.read_text())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


class TheArrowRunsOneWayTestCase(unittest.TestCase):
    """`lookup` imports from `merge`. `merge` must not import from `lookup`.

    The merge is the stage that decides; the lookup is a way of asking what it
    would decide. A build that consulted the lookup would be asking itself, and
    the guarantee -- an answer from the lookup is the answer the build would have
    given -- would become a tautology instead of a claim.
    """

    def test_the_lookup_section_exists_and_is_a_package(self):
        """Guards the two tests below: a glob over nothing passes."""
        self.assertTrue((LOOKUP / "__init__.py").exists())
        self.assertTrue(sorted(LOOKUP.glob("*.py")))

    def test_no_module_under_merge_imports_lookup(self):
        offenders = []
        for path in sorted(MERGE.rglob("*.py")):
            if any(name.startswith("brightway_flows.lookup") for name in _imports(path)):
                offenders.append(path.name)
        self.assertEqual(offenders, [], f"merge modules importing lookup: {offenders}")

    #: What may depend on `lookup`, and why.
    #:
    #: Not a rule against depending on it -- a CLI command or an HTTP endpoint
    #: over `FlowMatcher` is a wrapper anyone may add. It is here so that each
    #: thing which does is a deliberate act with a reason written beside it,
    #: rather than an import that drifted in.
    ALLOWED_DEPENDENTS = {
        # `lookup.evidence.other_flow` and its siblings: how much of a build the
        # lookup reproduces, graded against every build by `assess` rather than
        # measured once and quoted in a pull request nobody re-reads.
        "assessment/measures.py",
    }

    def test_only_the_declared_dependents_import_the_lookup(self):
        offenders = {
            str(path.relative_to(SRC))
            for path in sorted(SRC.rglob("*.py"))
            if LOOKUP not in path.parents
            and any(name.startswith("brightway_flows.lookup") for name in _imports(path))
        }
        self.assertEqual(offenders - self.ALLOWED_DEPENDENTS, set())

    def test_every_declared_dependent_still_imports_it(self):
        """The other half: an entry left behind after its importer stopped
        importing is an allowance nobody is checking."""
        for name in sorted(self.ALLOWED_DEPENDENTS):
            with self.subTest(module=name):
                self.assertTrue(
                    any(
                        imported.startswith("brightway_flows.lookup")
                        for imported in _imports(SRC / name)
                    )
                )


class NothingUnderLookupCanReachTheWritePathTestCase(unittest.TestCase):
    """The whole answer to "does it write" that a reader can check in a second.

    `add_flow`, `create_flows_for_unmatched_rows`, `apply_manual_additions` and
    `write_source_outcomes` are all in modules named below. If none of them is
    importable from here, no amount of reading the code is needed to know the
    lookup mints nothing.
    """

    def test_no_forbidden_module_is_imported(self):
        offenders = []
        for path in sorted(LOOKUP.rglob("*.py")):
            for name in sorted(_imports(path)):
                if any(
                    name == forbidden or name.startswith(f"{forbidden}.")
                    for forbidden in FORBIDDEN
                ):
                    offenders.append(f"{path.name} imports {name}")
        self.assertEqual(
            offenders,
            [],
            "a lookup that can reach the write path is one import away from "
            "writing to a database somebody else is reading:\n  "
            + "\n  ".join(offenders),
        )

    def test_no_writing_function_of_the_merge_store_is_imported(self):
        """The module has both halves; only the writing one is refused."""
        offenders = []
        for path in sorted(LOOKUP.rglob("*.py")):
            for name in sorted(_imports(path)):
                if any(
                    name == f"brightway_flows.merge.store.{forbidden}"
                    for forbidden in FORBIDDEN_STORE_NAMES
                ):
                    offenders.append(f"{path.name} imports {name}")
        self.assertEqual(offenders, [])

    def test_the_answering_path_does_not_touch_the_merge_store_at_all(self):
        """`replay` reads `merge_outcomes` because that is what it is for. The
        modules a question travels through have no business there, and keeping
        the strong rule where it matters is what lets the weaker one exist."""
        offenders = []
        for name in ANSWERING_PATH:
            path = LOOKUP / name
            self.assertTrue(path.exists(), f"{name} is not there; update ANSWERING_PATH")
            if any(
                imported.startswith("brightway_flows.merge.store")
                for imported in _imports(path)
            ):
                offenders.append(name)
        self.assertEqual(offenders, [])

    def test_the_answering_path_never_imports_the_replay(self):
        """Which is what makes the paragraph above true rather than hopeful."""
        offenders = []
        for name in ANSWERING_PATH:
            if any(
                imported.startswith("brightway_flows.lookup.replay")
                for imported in _imports(LOOKUP / name)
            ):
                offenders.append(name)
        self.assertEqual(offenders, [])

    def test_the_pure_half_of_the_merge_is_still_reachable(self):
        """The premise. If `merge.matching` were forbidden too, the rule above
        would be satisfied by a lookup that reimplemented matching -- which is
        the one thing this design must not do."""
        imported = set()
        for path in sorted(LOOKUP.rglob("*.py")):
            imported |= _imports(path)
        self.assertIn("brightway_flows.merge.matching", imported)


if __name__ == "__main__":
    unittest.main()
