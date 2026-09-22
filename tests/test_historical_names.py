"""The retired-name aliases: what the file may contain, and when it decides.

`data/ecoinvent-historical-names.json` says that a name ecoinvent retired --
`Sulfate, ion`, `Laterite, in ground` -- is the newest release's name for the
same flow.  Two things keep it honest, and each half is tested here: the loader
refuses every family the derivation promises to exclude, so a hand edit cannot
smuggle one back in; and the matcher consults the file only after every
registry number and every name the row itself shipped has failed, so an entry
that is wrong can only touch a row that was going to be reported unmatched
anyway.  See #338.
"""

import json
import tempfile
import unittest
from pathlib import Path

from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.historical_names import (
    HISTORICAL_NAMES_SCHEMA_VERSION,
    HistoricalName,
    HistoricalNameError,
    load_historical_names,
)
from brightway_flows.merge.matching import resolve_flow_object
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes, SourceRow
from brightway_flows.sources import resolve_source_list

SULFATE = "fo-sulfate"
TALC = "fo-talc"


def _payload(*rows):
    return {
        "schema_version": HISTORICAL_NAMES_SCHEMA_VERSION,
        "names": [
            {
                "historical_name": historical,
                "canonical_name": canonical,
                "decided_by": "ecoinvent-3.9.1-biosphere",
            }
            for historical, canonical in rows
        ],
    }


def _write(tmp, payload):
    path = Path(tmp) / "names.json"
    path.write_text(json.dumps(payload))
    return path


class LoaderTestCase(unittest.TestCase):
    def test_the_shipped_file_loads_and_keys_are_normalised(self):
        index = load_historical_names()
        self.assertGreater(len(index), 300)
        entry = index["sulfate, ion"]
        self.assertEqual(entry.canonical_name, "Sulfate")
        self.assertNotIn("Sulfate, ion", index, "keys are the normalised spelling")

    def test_a_missing_file_is_an_empty_index(self):
        self.assertEqual(
            load_historical_names(Path("/nonexistent/names.json")), {}
        )

    def _refuses(self, payload, fragment):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(HistoricalNameError) as caught:
                load_historical_names(_write(tmp, payload))
        self.assertIn(fragment, str(caught.exception))

    def test_a_wrong_schema_version_raises(self):
        payload = _payload(("Old name", "New name"))
        payload["schema_version"] = 99
        self._refuses(payload, "schema version")

    def test_a_second_entry_for_one_name_raises(self):
        self._refuses(
            _payload(("Old name", "New name"), ("OLD  name", "Other name")),
            "second",
        )

    def test_a_name_mapped_to_its_own_spelling_raises(self):
        self._refuses(_payload(("Old Name", "old name")), "own")

    def test_a_land_name_raises(self):
        self._refuses(
            _payload(("Occupation, arable", "Occupation, annual crop")), "land"
        )

    def test_a_bare_element_name_raises(self):
        """2.2's `Cadmium` in water became `Cadmium II` and in air stayed the
        element; which is meant depends on the compartment, which an alias
        cannot see."""
        self._refuses(_payload(("Cadmium", "Cadmium II")), "bare element")

    def test_an_alias_that_assigns_a_charge_raises(self):
        """`Calcium, ion` deliberately does not say how the calcium is charged;
        `Calcium II` does. Writing the charge in is a chemistry decision, and
        it belongs to merge/species.py."""
        self._refuses(_payload(("Calcium, ion", "Calcium II")), "species")

    def test_a_generic_ion_respelt_is_allowed(self):
        """`Copper, ion` -> `Copper ion` states nothing new about the copper,
        so the alias may carry it -- the half of the rule that stops the
        species guard growing into a ban on the family's spellings."""
        with tempfile.TemporaryDirectory() as tmp:
            index = load_historical_names(
                _write(tmp, _payload(("Copper, ion", "Copper ion")))
            )
        self.assertEqual(index["copper, ion"].canonical_name, "Copper ion")


def _row(name, *, cas=""):
    return SourceRow(
        uuid="s-1", name=name, synonyms=[], labels=[name],
        context=["water"], context_iri="", context_normalized=(),
        unit="kg", unit_iri="", cas=cas, ec="",
    )


def _indexes(*, label_index, pref_label_index, with_cas, cas_index=None,
             historical=None):
    return MergeIndexes(
        flow_objects_by_id={}, flow_object_label_by_id={},
        cas_index=cas_index or {},
        ec_index={}, label_index=label_index, pref_label_index=pref_label_index,
        qualifier_index={}, flow_objects_with_cas=with_cas,
        context_expectations=ContextExpectations(
            _by_source_context={}, _source_label="test"
        ), consensus_context_strings={},
        prepared_context_decisions={}, mapping_file=None,
        source=resolve_source_list("ecoinvent-3.8"),
        historical_names=historical or {},
    )


SULFATE_ALIAS = {
    "sulfate, ion": HistoricalName(
        historical_name="Sulfate, ion",
        canonical_name="Sulfate",
        decided_by="ecoinvent-3.9.1-biosphere",
    )
}


def _resolve(row, indexes):
    return resolve_flow_object(
        row=row, indexes=indexes, accumulator=MergeAccumulator()
    )


class MatchingTestCase(unittest.TestCase):
    def test_a_retired_name_reaches_the_newest_names_object(self):
        """The Sulfate case: no usable CAS, a name every release has retired,
        and the vendor's crosswalk says what it became."""
        resolution = _resolve(
            _row("Sulfate, ion", cas="14996-02-2"),
            _indexes(
                label_index={"sulfate": {SULFATE}},
                pref_label_index={"sulfate": {SULFATE}},
                with_cas={SULFATE},
                historical=SULFATE_ALIAS,
            ),
        )
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.flow_object_id, SULFATE)
        self.assertEqual(resolution.basis, "historical-name")
        self.assertEqual(resolution.basis_value, "Sulfate")

    def test_a_row_whose_own_name_matches_never_sees_the_alias(self):
        """The other half: the alias is evidence of last resort, so a shipped
        name that answers wins even where an alias entry would point somewhere
        else entirely."""
        resolution = _resolve(
            _row("Sulfate, ion"),
            _indexes(
                label_index={"sulfate, ion": {TALC}, "sulfate": {SULFATE}},
                pref_label_index={"sulfate, ion": {TALC}},
                with_cas=set(),
                historical=SULFATE_ALIAS,
            ),
        )
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.flow_object_id, TALC)
        self.assertEqual(resolution.basis, "label")

    def test_a_row_whose_cas_matches_never_sees_the_alias(self):
        resolution = _resolve(
            _row("Sulfate, ion", cas="14808-79-8"),
            _indexes(
                label_index={"sulfate": {SULFATE}},
                pref_label_index={"sulfate": {SULFATE}},
                with_cas={SULFATE},
                cas_index={"14808-79-8": {SULFATE}},
                historical=SULFATE_ALIAS,
            ),
        )
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.basis, "cas")

    def test_a_canonical_name_that_is_only_an_alt_label_is_still_refused(self):
        """The trade-name rule does not soften for an alias: a rewritten name
        that lands on something a CAS-bearing substance is merely also called
        stays out, exactly as a shipped one would."""
        resolution = _resolve(
            _row("Sulfate, ion"),
            _indexes(
                label_index={"sulfate": {TALC}},
                pref_label_index={"talc": {TALC}},
                with_cas={TALC},
                historical=SULFATE_ALIAS,
            ),
        )
        self.assertIsNone(resolution)

    def test_no_aliases_loaded_means_no_change_in_behaviour(self):
        resolution = _resolve(
            _row("Sulfate, ion"),
            _indexes(
                label_index={"sulfate": {SULFATE}},
                pref_label_index={"sulfate": {SULFATE}},
                with_cas={SULFATE},
            ),
        )
        self.assertIsNone(resolution)


if __name__ == "__main__":
    unittest.main()
