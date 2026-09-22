"""A name this project chose, and the four ways that can go wrong.

`flow-object-overrides.json` grew a third shape for #139.  The first two place a
flow; this one *renames a published substance*, and none of its behaviour had a
test -- the build-level expectations pin that one object comes out called
`Carbon Dioxide (sequestration from land management)`, but not the rules that got
it there, so every claim made for the shape rested on one build.

The four rules, each pinned below:

* the rename is **opt in**.  `_axes_for` reads a flow's prefLabel, so renaming an
  object in `pipeline.engine`'s pre-pass -- whose groupings `consensus_match`
  carries back onto the member flows -- makes the next pass read a name no
  qualifier pattern matches and mint on the bare CAS an unqualified substance
  already owns.  Measured when it happened: eight rows lost, one object short.
* a **malformed** row raises rather than being dropped, because a row that
  silently does nothing is a rename a curator believes happened.
* a row written about a name the vendor has since changed is **stale**: skipped
  and counted, never obeyed.
* a row about an object this pass did not build is **not this pass's business**,
  and is not counted as anything.  A layering pass resolves one source list, so
  it cannot tell a curator's typo from a row about a substance another list
  mints -- and counting it anyway reported both shipped rows as broken on every
  build (#337).  The question belongs to the finished artifact, where every
  object exists, and `names.rows_unpublished` asks it there.

And the thing the shape exists to produce: a curated name is the one string in
the published list that no source list supplied, so it is the label that most
needs provenance saying who chose it.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from brightway_flows.assessment.measures import _curated_name_measures
from brightway_flows.domain.flow import Flow
from brightway_flows.flow_layers import resolve_flow_layers
from brightway_flows.flow_layers.layering import (
    _ObjectName,
    _load_overrides,
    curated_object_names,
)
from brightway_flows.sources import SourceList, resolve_source_list

_EF31 = SourceList(
    list_name="EF",
    list_version="3.1",
    flows_path=Path("/nonexistent/ef-31-flows.json"),
    declared_source_label="EF 3.1",
)

#: What `bootstrap_labels` writes: the source list's own name for the flow.  The
#: demoted name must keep this -- being moved to `altLabel` does not change who
#: wrote it.
_BOOTSTRAP = {
    "prov:wasGeneratedBy": "bootstrap_labels",
    "prov:wasAttributedTo": "brightway-flows",
    "prov:hadPrimarySource": ["EF 3.1"],
    "prov:wasDerivedFrom": "legacy name field",
}

_VENDOR_NAME = "Carbon Dioxide, To Soil Or Biomass Stock"
_CURATED_NAME = "Carbon Dioxide (sequestration from land management)"


def _flow() -> Flow:
    return Flow(
        uuid="11111111-2222-3333-4444-555555555555",
        source="EF 3.1",
        unit="kg",
        context=["Emissions", "Emissions to air"],
        cas_numbers=["124-38-9"],
        prefLabel=[
            {"@value": _VENDOR_NAME, "@language": "en", "source": _BOOTSTRAP}
        ],
    )


def _overrides_file(rows: list[Any], directory: str) -> Path:
    path = Path(directory) / "flow-object-overrides.json"
    path.write_text(json.dumps({"names": rows}), encoding="utf-8")
    return path


def _resolve(path: Path | None, *, apply_names: bool):
    return resolve_flow_layers(
        [_flow()],
        source_list=_EF31,
        overrides_path=path,
        apply_curated_names=apply_names,
    )


def _the_object(objects):
    """The one object built from the one flow above."""
    return next(obj for obj in objects if obj.prefLabel)


def _pref_row(obj) -> dict[str, Any]:
    return obj.prefLabel[0]


def _alt_row(obj, value: str) -> dict[str, Any]:
    return next(row for row in (obj.altLabel or []) if row.get("@value") == value)


def _object_id(objects) -> str:
    return _the_object(objects).flow_object_id


def _a_row(object_id: str, **overrides: Any) -> dict[str, Any]:
    row = {
        "flow_object_id": object_id,
        "current_label": _VENDOR_NAME,
        "preferred_label": _CURATED_NAME,
        "comment": "why this list calls it something else",
    }
    row.update(overrides)
    return row


class RenamesWhenAskedTestCase(unittest.TestCase):
    """The rename itself, and the promise that the vendor's spelling survives."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        objects, _flows, _stats = _resolve(None, apply_names=False)
        self.path = _overrides_file([_a_row(_object_id(objects))], self._dir.name)

    def test_the_curated_name_is_published(self):
        objects, _flows, _stats = _resolve(self.path, apply_names=True)
        self.assertEqual(_pref_row(_the_object(objects))["@value"], _CURATED_NAME)

    def test_the_vendor_name_stays_findable(self):
        objects, _flows, _stats = _resolve(self.path, apply_names=True)
        values = [row["@value"] for row in (_the_object(objects).altLabel or [])]
        self.assertIn(_VENDOR_NAME, values)

    def test_the_counts_say_one_was_applied(self):
        _objects, _flows, stats = _resolve(self.path, apply_names=True)
        self.assertEqual(stats["object_names_stated"], 1)
        self.assertEqual(stats["object_names_applied"], 1)
        self.assertEqual(stats["object_names_stale"], 0)

    def test_stated_is_applied_plus_stale(self):
        """The invariant that keeps the three numbers readable together.

        `stated` counts rows whose object is in this pass, so every one of them
        was either renamed or found stale.  A row about an object that is not
        here is not stated, which is what stops a pass holding none of them from
        reporting a number a reader would take for a rename that did not happen.
        """
        _objects, _flows, stats = _resolve(self.path, apply_names=True)
        self.assertEqual(
            stats["object_names_stated"],
            stats["object_names_applied"] + stats["object_names_stale"],
        )


class ProvenanceTestCase(unittest.TestCase):
    """The label no source list supplied still says where it came from.

    The first version of the rename wrote a bare `{"@value", "@language"}` pair,
    so the only name in the published list that is this project's own decision
    was also the only one arriving anonymously -- among labels that all name
    their origin (AGENTS 17).
    """

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        objects, _flows, _stats = _resolve(None, apply_names=False)
        path = _overrides_file([_a_row(_object_id(objects))], self._dir.name)
        objects, _flows, _stats = _resolve(path, apply_names=True)
        self.obj = _the_object(objects)

    def test_the_curated_name_carries_provenance(self):
        self.assertIn("provenance", _pref_row(self.obj))

    def test_it_names_the_activity_that_chose_it(self):
        provenance = _pref_row(self.obj)["provenance"]
        self.assertEqual(provenance["prov:wasGeneratedBy"], "flow_object_names")

    def test_it_names_the_file_the_decision_is_written_in(self):
        provenance = _pref_row(self.obj)["provenance"]
        self.assertIn(
            "flow-object-overrides.json", provenance["prov:hadPrimarySource"]
        )

    def test_it_does_not_claim_the_source_list_supplied_it(self):
        """EF 3.1 published the vendor name; it never published the curated one."""
        provenance = _pref_row(self.obj)["provenance"]
        self.assertNotIn("EF 3.1", provenance["prov:hadPrimarySource"])
        self.assertNotEqual(provenance["prov:wasGeneratedBy"], "bootstrap_labels")

    def test_the_demoted_name_keeps_its_own_attribution(self):
        provenance = _alt_row(self.obj, _VENDOR_NAME)["provenance"]
        self.assertEqual(provenance["prov:wasGeneratedBy"], "bootstrap_labels")
        self.assertIn("EF 3.1", provenance["prov:hadPrimarySource"])

    def test_both_rows_carry_a_language(self):
        for row in (_pref_row(self.obj), _alt_row(self.obj, _VENDOR_NAME)):
            with self.subTest(value=row["@value"]):
                self.assertEqual(row["@language"], "en")
                self.assertEqual(row["@lang"], "en")


class OptInTestCase(unittest.TestCase):
    """A pass that does not ask for names leaves them alone, and says so."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        objects, _flows, _stats = _resolve(None, apply_names=False)
        self.path = _overrides_file([_a_row(_object_id(objects))], self._dir.name)

    def test_the_default_does_not_rename(self):
        objects, _flows, _stats = _resolve(self.path, apply_names=False)
        self.assertEqual(_pref_row(_the_object(objects))["@value"], _VENDOR_NAME)

    def test_the_counts_describe_the_pass_and_not_the_file(self):
        """`stated: 2` from a pass that applied none is the failure, not the fix.

        It is the number a curator reads as a rename that happened.  What the
        file holds is a property of the file; what a build did is a property of
        the build.
        """
        _objects, _flows, stats = _resolve(self.path, apply_names=False)
        self.assertEqual(stats["object_names_stated"], 0)
        self.assertEqual(stats["object_names_applied"], 0)


class RowsThatDoNotApplyTestCase(unittest.TestCase):
    """Stale and unresolved: two different mistakes, counted separately."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        objects, _flows, _stats = _resolve(None, apply_names=False)
        self.object_id = _object_id(objects)

    def test_a_row_about_a_name_that_moved_on_is_not_obeyed(self):
        path = _overrides_file(
            [
                _a_row(
                    self.object_id,
                    current_label="A Name The Vendor No Longer Uses",
                    comment="written before the vendor renamed it",
                )
            ],
            self._dir.name,
        )
        objects, _flows, stats = _resolve(path, apply_names=True)
        self.assertEqual(_pref_row(_the_object(objects))["@value"], _VENDOR_NAME)
        self.assertEqual(stats["object_names_stale"], 1)
        self.assertEqual(stats["object_names_applied"], 0)

    def test_an_object_this_pass_did_not_build_is_not_counted(self):
        """Not an error here, because here it cannot be told from one (#337).

        A layering pass resolves a single source list.  An id it built no object
        for is a typo *or* a row about a substance another list mints, and both
        are ordinary -- the base pass resolves EF 3.1, and both shipped rows name
        objects the merge mints out of ecoinvent rows.  Counting it reported two
        correct rows as broken on every build, with `applied: 0` beside them
        saying the renames had not happened.
        """
        path = _overrides_file(
            [_a_row("fo-0000000000000000", comment="not this pass's object")],
            self._dir.name,
        )
        objects, _flows, stats = _resolve(path, apply_names=True)
        self.assertEqual(_pref_row(_the_object(objects))["@value"], _VENDOR_NAME)
        self.assertEqual(stats["object_names_stated"], 0)
        self.assertEqual(stats["object_names_stale"], 0)
        self.assertEqual(stats["object_names_applied"], 0)

    def test_the_pass_reports_nothing_rather_than_a_failure(self):
        """The count a curator reads must not describe a pass that had no part.

        This is the whole of #337's second finding: `unresolved: 2` and
        `applied: 0` were published by the one pass that could never have applied
        either row, on builds where both renames succeeded.
        """
        path = _overrides_file(
            [_a_row("fo-0000000000000000", comment="not this pass's object")],
            self._dir.name,
        )
        _objects, _flows, stats = _resolve(path, apply_names=True)
        self.assertNotIn("object_names_unresolved", stats)


class MalformedRowTestCase(unittest.TestCase):
    """Unlike the two shapes beside it, this one refuses to be guessed at."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def _assert_raises(self, row: dict[str, Any]):
        path = _overrides_file([row], self._dir.name)
        with self.assertRaises(ValueError):
            _load_overrides(path)

    def test_a_row_with_no_comment_raises(self):
        """Same argument as `lcia-factor-rulings.json`: a decision states why."""
        row = _a_row("fo-1234567890abcdef")
        del row["comment"]
        self._assert_raises(row)

    def test_a_row_with_no_current_label_raises(self):
        row = _a_row("fo-1234567890abcdef")
        del row["current_label"]
        self._assert_raises(row)

    def test_a_row_with_no_preferred_label_raises(self):
        row = _a_row("fo-1234567890abcdef")
        del row["preferred_label"]
        self._assert_raises(row)

    def test_a_row_with_a_blank_string_raises(self):
        self._assert_raises(_a_row("fo-1234567890abcdef", preferred_label="   "))

    def test_a_row_that_is_not_a_mapping_is_dropped(self):
        """The one tolerated case: a list entry that is not a row at all."""
        path = _overrides_file(["not a row"], self._dir.name)
        self.assertEqual(_load_overrides(path).names, ())


class ShippedFileTestCase(unittest.TestCase):
    """The file this project ships parses, and every row in it is well formed."""

    def test_the_shipped_names_load(self):
        overrides = _load_overrides()
        for name in overrides.names:
            with self.subTest(flow_object_id=name.flow_object_id):
                self.assertTrue(name.flow_object_id.startswith("fo-"))
                self.assertTrue(name.current_label)
                self.assertTrue(name.preferred_label)
                self.assertTrue(name.comment)


class PublishedInTheArtifactTestCase(unittest.TestCase):
    """The half of the question a layering pass cannot answer (#337).

    `names.rows_unpublished` is taken from the finished build, where every object
    exists at once, so it can say the thing a pass cannot: that this id names a
    published object and that object is called what the row says. A mistyped id
    fails the first half; a rename that silently stopped happening fails the
    second; a build where both hold reports zero.
    """

    def _measure(self, published: dict[str, str], names: tuple) -> int:
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE flow_objects "
            "(flow_object_id TEXT PRIMARY KEY, pref_label_value TEXT)"
        )
        connection.executemany(
            "INSERT INTO flow_objects VALUES (?, ?)", sorted(published.items())
        )
        with mock.patch(
            "brightway_flows.flow_layers.layering.curated_object_names",
            return_value=names,
        ):
            measures = _curated_name_measures(connection)
        self.assertEqual([m.key for m in measures], ["names.rows_unpublished"])
        return measures[0].value

    def _name(self, object_id: str) -> _ObjectName:
        return _ObjectName(
            flow_object_id=object_id,
            current_label=_VENDOR_NAME,
            preferred_label=_CURATED_NAME,
            comment="why this list calls it something else",
        )

    def test_a_published_rename_reports_zero(self):
        self.assertEqual(
            self._measure(
                {"fo-abc": _CURATED_NAME}, (self._name("fo-abc"),)
            ),
            0,
        )

    def test_a_mistyped_id_is_caught_here(self):
        """What the per-pass counter was reaching for, asked where it works."""
        self.assertEqual(
            self._measure(
                {"fo-abc": _CURATED_NAME}, (self._name("fo-typo"),)
            ),
            1,
        )

    def test_an_object_published_under_the_old_name_is_caught(self):
        """The rename stopped happening, and the artifact still shows it."""
        self.assertEqual(
            self._measure(
                {"fo-abc": _VENDOR_NAME}, (self._name("fo-abc"),)
            ),
            1,
        )

    def test_case_and_spacing_are_not_a_difference(self):
        self.assertEqual(
            self._measure(
                {"fo-abc": "  carbon DIOXIDE   (sequestration from land management) "},
                (self._name("fo-abc"),),
            ),
            0,
        )

    def test_a_build_with_no_flow_objects_table_yields_no_measure(self):
        """An `assess` against a partial build reports on what it does have."""
        connection = sqlite3.connect(":memory:")
        self.assertEqual(_curated_name_measures(connection), [])

    def test_the_shipped_rows_are_the_ones_it_would_check(self):
        """Guards the accessor, so a renamed loader cannot quietly return ()."""
        names = curated_object_names()
        self.assertTrue(names)
        self.assertEqual(
            {n.flow_object_id for n in names},
            {n.flow_object_id for n in _load_overrides().names},
        )


if __name__ == "__main__":
    unittest.main()


class TheMintedChargedIonsAreSpelledTheHouseWayTestCase(unittest.TestCase):
    """The two rows #198 added, asked of the shipped file.

    ecoinvent 3.12's `Rhodium III` and `Palladium II` mint their ions once the
    bare element is refused, and a mint takes the vendor's spelling.  This list
    spells a stated charge one way, the form `merge/species.py` matches under
    and EF's own `Zinc(2+)` publishes, so the shipped file names the two
    objects.  Each is keyed on the object id the mint seeds from the ion's
    registry number, so the row holds whichever list mints first, and goes
    stale rather than wrong if a build mints under another spelling.
    """

    ROWS = {
        "Rhodium III": ("16065-89-7", "fo-fb9b0585c57f953a", "Rhodium(3+)"),
        "Palladium II": ("16065-88-6", "fo-e60ddfdf2e995c72", "Palladium(2+)"),
    }

    def _minted(self, name, cas):
        flow = Flow(
            uuid="7c651713-83f5-56e1-a67f-37b828684f3d",
            source="ecoinvent-3.12",
            unit="kg",
            context=["air", "unspecified"],
            cas_numbers=[cas],
            prefLabel=[{"@value": name, "@language": "en", "source": _BOOTSTRAP}],
        )
        objects, _flows, _stats = resolve_flow_layers(
            [flow],
            source_list=resolve_source_list("ecoinvent-3.12"),
            apply_curated_names=True,
        )
        return _the_object(objects)

    def test_each_mint_is_published_under_the_house_spelling(self):
        for vendor, (cas, object_id, house) in self.ROWS.items():
            with self.subTest(vendor=vendor):
                obj = self._minted(vendor, cas)
                self.assertEqual(obj.flow_object_id, object_id)
                self.assertEqual(_pref_row(obj)["@value"], house)
                self.assertEqual(_alt_row(obj, vendor)["@value"], vendor)

    def test_without_the_pass_the_vendor_spelling_stands(self):
        """The rows are opt in, like every curated name."""
        flow = Flow(
            uuid="7c651713-83f5-56e1-a67f-37b828684f3d", source="ecoinvent-3.12",
            unit="kg", context=["air", "unspecified"], cas_numbers=["16065-89-7"],
            prefLabel=[{"@value": "Rhodium III", "@language": "en", "source": _BOOTSTRAP}],
        )
        objects, _flows, _stats = resolve_flow_layers(
            [flow], source_list=resolve_source_list("ecoinvent-3.12"),
        )
        self.assertEqual(_pref_row(_the_object(objects))["@value"], "Rhodium III")
