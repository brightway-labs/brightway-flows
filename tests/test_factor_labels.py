"""No published label names a source list.

There are two implementations of EF 3.1 in this build and there will be more:
every source list that ships characterisation factors is one, and the ecoinvent
workbook alone holds 44 further methods.  A field called `jrc_amount`, a verdict
called `adopt`, a template column headed `ecoinvent Centre` -- each works exactly
until the third implementation arrives, and then it does not fail, it silently
describes two of the three.

So the shapes are long rather than wide, and the names say *what a thing is*
rather than *who said it*: `implemented_by` and `amount` rather than a column per
publisher.  This states that as a rule, because the failure it prevents is one
nothing else would catch -- a wide schema does not break when a third
implementation appears, it just stops mentioning it.

The exception, deliberately: `Implementation` itself, and the values it carries.
Those are identities rather than labels.  `implemented_by = "ecoinvent Centre"`
is data about a row; `ecoinvent_amount` is a column that only some rows can ever
use.
"""

from __future__ import annotations

import ast
import unittest
from dataclasses import fields
from pathlib import Path

import orjson

from brightway_flows.domain.lcia.records import (
    CharacterizationFactor,
    Difference,
    ImpactCategory,
    LCIAMethod,
    PublishedDifferences,
    PublishedFactors,
)
from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.lcia.rulings import Verdict, load_factor_rulings
from brightway_flows.lcia.store import (
    _CATEGORY_COLUMNS,
    _DIFFERENCE_COLUMNS,
    _FACTOR_COLUMNS,
    _FINDING_COLUMNS,
)

#: The names of the lists this project happens to merge today, in the spellings a
#: field name would use.  Not the display values -- those are data.
SOURCE_LIST_WORDS = ("jrc", "ecoinvent", "bafu", "simapro", "openlca", "stepwise")

SOURCE = Path(__file__).resolve().parent.parent / "src" / "brightway_flows"


def _names_a_source_list(name: str) -> bool:
    lowered = name.lower()
    return any(word in lowered for word in SOURCE_LIST_WORDS)


class NoColumnNamesAPublisherTestCase(unittest.TestCase):
    def test_no_lcia_table_column_does(self):
        for label, columns in (
            ("lcia_characterization_factors", _FACTOR_COLUMNS),
            ("lcia_impact_categories", _CATEGORY_COLUMNS),
            ("lcia_differences", _DIFFERENCE_COLUMNS),
            ("lcia_findings", _FINDING_COLUMNS),
        ):
            for column in columns:
                with self.subTest(table=label, column=column):
                    self.assertFalse(_names_a_source_list(column))

    def test_no_published_record_field_does(self):
        for record in (
            CharacterizationFactor, Difference, ImpactCategory, LCIAMethod,
            PublishedFactors, PublishedDifferences,
        ):
            for field in fields(record):
                with self.subTest(record=record.__name__, field=field.name):
                    self.assertFalse(_names_a_source_list(field.name))

    def test_no_verdict_does(self):
        """`jrc` and `ecoinvent` were verdicts once; `publish` and an
        `implemented_by` say the same thing about any number of them."""
        for verdict in Verdict:
            with self.subTest(verdict=str(verdict)):
                self.assertFalse(_names_a_source_list(str(verdict)))


class TheArtifactsAndTheTablesAgreeTestCase(unittest.TestCase):
    """One run should not describe one row two ways.

    A consumer moving between `lcia-factors.json.gz` and the SQLite table beside
    it was translating `flow_id` to `elementary_flow_uuid` and `source_flow_id` to
    `source_flow_uuid` -- in artifacts written by the same call.
    """

    def test_the_factor_artifact_uses_the_table_s_names(self):
        published = {
            field.name for field in fields(CharacterizationFactor)
        }
        self.assertLessEqual(
            published - set(_FACTOR_COLUMNS), set(),
            "a published factor field the table does not have under that name",
        )

    def test_the_difference_artifact_uses_the_table_s_names(self):
        published = {field.name for field in fields(Difference)}
        self.assertLessEqual(
            published - set(_DIFFERENCE_COLUMNS), set(),
            "a published difference field the table does not have under that name",
        )


class TheCuratedRulingsUseTheGenericShapeTestCase(unittest.TestCase):
    def test_every_ruling_publishes_or_declines(self):
        for ruling in load_factor_rulings().values():
            with self.subTest(ruling=ruling.item_key):
                self.assertIn(ruling.verdict, {Verdict.PUBLISH, Verdict.DECLINE})

    def test_ruled_about_is_keyed_by_implementation(self):
        """`{"jrc": [...]}` was the first shape; the keys are the same
        `implemented_by` the tables and artifacts use, so a third implementation
        is a third key rather than a schema question."""
        payload = orjson.loads(
            (PACKAGE_DATA_DIR / "lcia-factor-rulings.json").read_bytes()
        )
        for ruling in payload["rulings"]:
            with self.subTest(ruling=ruling["category_slug"]):
                for name in ruling["ruled_about"]:
                    self.assertNotIn(name, {"jrc", "ecoinvent"})
                    self.assertIn(" ", name)


class NoTemplateHardcodesAnImplementationColumnTestCase(unittest.TestCase):
    """The columns come from the data, and a template cannot be asked to know.

    A header written into the page is the same failure as a column in the schema:
    it renders two implementations correctly forever, including on the day there
    are three.
    """

    PAGES = (
        "templates/factor_differences.html",
        "templates/queue_factors.html",
        "templates/factors.html",
        "templates/flow_detail.html",
    )

    def test_no_page_writes_an_implementation_into_a_header(self):
        for page in self.PAGES:
            text = (SOURCE / "webapps" / "app" / page).read_text()
            for line in text.splitlines():
                if "<th" not in line:
                    continue
                with self.subTest(page=page, line=line.strip()[:60]):
                    self.assertNotIn("JRC", line)
                    self.assertNotIn("ecoinvent", line)


class NothingReadsATwoImplementationKeyTestCase(unittest.TestCase):
    """The LCIA modules do not index a payload by a publisher's name.

    An AST scan rather than a grep, so that `evidence["jrc"]` fails here and the
    word `jrc` in a docstring does not.
    """

    def test_no_lcia_module_subscripts_by_a_source_list_name(self):
        for path in sorted((SOURCE / "lcia").glob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Subscript):
                    continue
                index = node.slice
                if not (isinstance(index, ast.Constant) and isinstance(index.value, str)):
                    continue
                with self.subTest(module=path.name, key=index.value):
                    self.assertFalse(_names_a_source_list(index.value))


if __name__ == "__main__":
    unittest.main()
