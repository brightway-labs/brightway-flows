"""What each install has to bring, and what it must not need.

The package is used three ways, by three kinds of user, and each should install
only what it uses:

* **the matcher** -- `brightway_flows.lookup`, asked "which consensus flow is
  this?" by another program, against a build somebody else ran. It is the plain
  install, and what it needs is what every user of that program installs;
* **the pipeline** -- fetching the source lists and running a build, the
  `pipeline` extra;
* **the review application**, the `webapp` extra, which reads a build and never
  runs one.

Nothing fails when a module on the matcher's path gains an import of `httpx`:
a checkout installs everything, so every test still passes, and the first to
find out is whoever installs the package without the extra. So each case here
runs one of the three in a fresh interpreter, records every third-party package
that interpreter was asked to import and by which of our modules, and compares
the record with what that install is allowed.

It records rather than refuses, so one run names every offender and the module
that imported it, which is the list somebody fixing it needs.

The cases that do not hold yet are marked as expected failures, and each says
which step of the split makes it true. An expected failure that starts passing
fails the suite, which is the reminder to remove the mark.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest

from pathlib import Path

from test_lookup_matcher import BAFU_AIR, _matcher_fixture

ROOT = Path(__file__).resolve().parent.parent
DOCS_ROOT = ROOT / "docs"

#: Import name -> distribution, for what only fetching a list or running a build
#: uses. `pandas` is here although nothing imports it: it was declared for years
#: on that basis, and this is what stops it coming back.
PIPELINE_ONLY = {
    "bw_simapro_csv": "bw-simapro-csv",
    "chemformula": "chemformula",
    "ecoinvent_interface": "ecoinvent-interface",
    "httpx": "httpx",
    "jsonschema": "jsonschema",
    "lxml": "lxml",
    "openpyxl": "openpyxl",
    "pandas": "pandas",
    "py2opsin": "py2opsin",
    "randonneur": "randonneur",
    "xmltodict": "xmltodict",
}

#: What only the review application uses.
WEBAPP_ONLY = {
    "flask": "flask",
    "gunicorn": "gunicorn",
    "markdown": "markdown",
    "markupsafe": "markupsafe",
    "pygments": "pygments",
    "pymdownx": "pymdown-extensions",
    "yaml": "pyyaml",
}

#: Used by the pipeline and by the application, and not by the matcher: `rdkit`
#: draws the structure on a substance's page, and `typer` is the command line
#: that starts either.
PIPELINE_AND_WEBAPP = {
    "rdkit": "rdkit",
    "typer": "typer",
}

#: The whole of the plain install. `tqdm` is on the matcher's import path and
#: depends on nothing, so it stays rather than being cut out of six modules.
BASE = {
    "orjson",
    "pint",
    "platformdirs",
    "pydantic",
    "pydantic-settings",
    "randonneur-data",
    "structlog",
    "tqdm",
}

#: Runs first in the child: note each watched package the first time one of our
#: own modules asks for it. Returning `None` hands the import on to the real
#: finders.
#:
#: Only an import one of our modules makes itself. A package that is installed
#: gets imported by others that can use it -- structlog draws its tracebacks
#: with rich, and rich with pygments, when they are there -- and that is not a
#: need of ours: in an install without them it does not happen.
_RECORDER = """
import json, os, sys

WATCHED = set(json.loads(os.environ["BOUNDARY_WATCHED"]))
SEEN = {}


class _Recorder:
    def find_spec(self, name, path=None, target=None):
        top = name.partition(".")[0]
        if top in WATCHED and top not in SEEN:
            frame = sys._getframe(1)
            while frame is not None and "importlib" in frame.f_code.co_filename:
                frame = frame.f_back
            importer = frame.f_globals.get("__name__", "") if frame else ""
            if importer.startswith("brightway_flows"):
                SEEN[top] = importer
        return None


sys.meta_path.insert(0, _Recorder())
"""

_MATCHER = """
from pathlib import Path

from brightway_flows.lookup import FlowMatcher, FlowQuery

matcher = FlowMatcher.from_results(
    db_path=Path(os.environ["BOUNDARY_DB"]), recorded_by_name=True
)
result = matcher.match_many(
    [
        FlowQuery(
            name="Benzene, chloro-",
            context=json.loads(os.environ["BOUNDARY_CONTEXT"]),
            cas="108-90-7",
            unit="kg",
            simapro_origin=True,
        )
    ]
)[0]
RESULT = {"matched": result.matched, "flow": result.elementary_flow_id}
"""

#: Every page that takes no argument, so a package imported inside a view is
#: seen as well as one imported at the top of a module.
_WEBAPP = """
from pathlib import Path

from brightway_flows.webapps.app import create_app

database = Path(os.environ["BOUNDARY_DB"])
app = create_app(database, docs_path=Path(os.environ["BOUNDARY_DOCS"]), data_dir=database.parent)
app.config["TESTING"] = True
client = app.test_client()
RESULT = {}
for rule in app.url_map.iter_rules():
    if rule.arguments or "GET" not in rule.methods:
        continue
    RESULT[rule.rule] = client.get(rule.rule, follow_redirects=True).status_code
RESULT["/substances/fo-benzene"] = client.get(
    "/substances/fo-benzene", follow_redirects=True
).status_code
"""

_REPORT = """
print("BOUNDARY" + json.dumps({"seen": SEEN, "result": RESULT}))
"""


def _run(body: str, *, watched: set[str], db_path: Path, data_dir: Path) -> dict:
    """Run *body* in a fresh interpreter and return what it recorded."""
    environment = dict(
        os.environ,
        BOUNDARY_WATCHED=json.dumps(sorted(watched)),
        BOUNDARY_DB=str(db_path),
        BOUNDARY_DOCS=str(DOCS_ROOT),
        BOUNDARY_CONTEXT=json.dumps(BAFU_AIR),
        BRIGHTWAY_FLOWS_DATA_DIR=str(data_dir),
    )
    completed = subprocess.run(
        [sys.executable, "-c", _RECORDER + body + _REPORT],
        capture_output=True,
        text=True,
        env=environment,
        cwd=db_path.parent,
    )
    if completed.returncode:
        raise AssertionError(completed.stderr[-4000:])
    line = next(
        line for line in completed.stdout.splitlines() if line.startswith("BOUNDARY")
    )
    return json.loads(line.removeprefix("BOUNDARY"))


def _offenders(seen: dict[str, str]) -> str:
    return "\n".join(
        f"  {package}, imported by {importer}" for package, importer in sorted(seen.items())
    )


class _Boundary(unittest.TestCase):
    """One fixture build and one fresh interpreter for the whole class."""

    body: str
    watched: set[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        _, db_path = _matcher_fixture()
        cls._data = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._data.cleanup)
        #: A directory that does not exist, which is what a program that only
        #: asks questions has: it never ran `download` or `build`.
        cls.data_dir = Path(cls._data.name) / "never-made"
        cls.report = _run(
            cls.body, watched=cls.watched, db_path=db_path, data_dir=cls.data_dir
        )


class ThePlainInstallAnswersAQuestionTestCase(_Boundary):
    """The matcher, as brightway-api calls it: one extract, a batch of rows."""

    body = _MATCHER
    watched = set(PIPELINE_ONLY) | set(WEBAPP_ONLY) | set(PIPELINE_AND_WEBAPP)

    def test_it_places_the_row(self):
        self.assertEqual(
            self.report["result"], {"matched": True, "flow": "ef-chlorobenzene-rural"}
        )

    def test_it_imports_nothing_the_plain_install_lacks(self):
        self.assertEqual(
            self.report["seen"],
            {},
            "The matcher imported packages the plain install does not bring:\n"
            + _offenders(self.report["seen"]),
        )

    # Step 2: `filesystem` makes the directory when it is imported.
    @unittest.expectedFailure
    def test_it_makes_no_data_directory(self):
        self.assertFalse(
            self.data_dir.exists(),
            "Asking a question created the data directory, which a program that "
            "only reads an extract has no use for.",
        )


class TheApplicationReadsABuildTestCase(_Boundary):
    """The review application over a build it did not make."""

    body = _WEBAPP
    watched = set(PIPELINE_ONLY)

    def test_every_page_without_an_argument_answers(self):
        failed = {
            path: status
            for path, status in self.report["result"].items()
            if status >= 500
        }
        self.assertEqual(failed, {})
        self.assertGreater(len(self.report["result"]), 20)

    def test_it_imports_nothing_only_the_pipeline_uses(self):
        self.assertEqual(
            self.report["seen"],
            {},
            "The application imported packages only the pipeline needs:\n"
            + _offenders(self.report["seen"]),
        )


class TheDeclaredDependenciesTestCase(unittest.TestCase):
    """`pyproject.toml` says the same thing the three lists above do."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        cls.base = {_name(spec) for spec in project["dependencies"]}
        cls.extras = {
            extra: {_name(spec) for spec in specs}
            for extra, specs in project.get("optional-dependencies", {}).items()
        }

    # Step 3.
    @unittest.expectedFailure
    def test_the_plain_install_is_the_matcher_s_and_nothing_else(self):
        self.assertEqual(self.base, BASE)

    # Step 3.
    @unittest.expectedFailure
    def test_the_pipeline_extra_brings_what_a_build_imports(self):
        wanted = set(PIPELINE_ONLY.values()) | set(PIPELINE_AND_WEBAPP.values())
        # Declared nowhere: it is what stops being installed.
        wanted.discard("pandas")
        self.assertEqual(self.extras.get("pipeline"), wanted)

    # Step 3 and 4: the extra exists once #464 lands, and gains `rdkit`,
    # `typer` and `markupsafe` here.
    @unittest.expectedFailure
    def test_the_webapp_extra_brings_what_the_application_imports(self):
        wanted = set(WEBAPP_ONLY.values()) | set(PIPELINE_AND_WEBAPP.values())
        self.assertEqual(self.extras.get("webapp"), wanted)

    # Step 3.
    @unittest.expectedFailure
    def test_nothing_declares_pandas(self):
        declared = self.base.union(*self.extras.values())
        self.assertNotIn("pandas", declared)


def _name(specifier: str) -> str:
    """`"flask>=3.1.3"` -> `"flask"`."""
    for index, character in enumerate(specifier):
        if not (character.isalnum() or character in "-_."):
            return specifier[:index].lower()
    return specifier.lower()


if __name__ == "__main__":
    unittest.main()
