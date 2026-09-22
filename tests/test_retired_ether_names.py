"""The retired ecoinvent 2 ether names, and the rule that places each one.

ecoinvent 2 named twelve fluorinated ethers by a structural prose name with the
industry designation appended -- `Ether, 1,1,2,2-Tetrafluoroethyl
2,2,2-trifluoroethyl-, HFE-347mcc3` -- and gave every member of a family one
CAS number. Stepwise 2006 still ships those rows verbatim, each characterised
with its own designation's factors. EF 3.1 carries the same shared numbers, so
a row stating the retired name and the family CAS reaches every member of the
family and narrows to none: `multiple-flow-object-candidates`, on all twelve.

The fix is a synonym per flow in `ef-3.1-manual-fixes.json`: the retired name
is written onto the flow whose designation the name *ends in*, which is the one
piece of the name that identifies a single substance. The `cas+label` narrowing
then settles the family. This file is about that table as data -- the property
every entry has to have is that the trailing designation and the flow the name
is written on agree, because an entry that broke it would silently publish one
substance under another's history. What the fixes do to a row is
`test_manual_fixes.py`'s job.
"""

from __future__ import annotations

import unittest

import orjson

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.matching import resolve_flow_object
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes, SourceRow
from brightway_flows.sources import resolve_source_list

FIXES = PACKAGE_DATA_DIR / "ef-3.1-manual-fixes.json"

#: The twelve designations the retired names end in.
CODES = {
    "HFE-236ea2", "HFE-236fa",
    "HFE-245cb2", "HFE-245fa1", "HFE-245fa2",
    "HFE-347mcc3", "HFE-347mcf2", "HFE-347pcf2",
    "HFE-356mec3", "HFE-356pcc3", "HFE-356pcf2", "HFE-356pcf3",
}


def _retired_name_entries():
    """Every synonyms fix that appends a `..., <designation>` retired name."""
    fixes = orjson.loads(FIXES.read_bytes())["fixes"]
    out = []
    for fix in fixes:
        if fix.get("field") != "synonyms" or "new_value" not in fix:
            continue
        added = [
            value
            for value in fix["new_value"]
            if value not in (fix.get("original_value") or [])
        ]
        for value in added:
            code = value.rsplit(", ", 1)[-1]
            if code in CODES:
                out.append((fix, value, code))
    return out


class TheNameEndsInTheFlowItIsWrittenOnTestCase(unittest.TestCase):
    def test_every_code_has_exactly_one_retired_name(self):
        by_code = {}
        for _fix, value, code in _retired_name_entries():
            by_code.setdefault(code, []).append(value)
        self.assertEqual(set(by_code), CODES)
        for code, values in by_code.items():
            with self.subTest(code=code):
                self.assertEqual(len(values), 1, values)

    def test_the_trailing_designation_is_the_matched_flow(self):
        """The one property that makes the table safe: the designation the
        retired name ends in is the flow the synonym is written on. An entry
        that broke it would publish one substance under another's history."""
        for fix, value, code in _retired_name_entries():
            with self.subTest(name=value):
                self.assertEqual(fix["match"], {"name": code})

    def test_each_entry_adds_the_one_name_and_removes_nothing(self):
        """The fix extends EF's own synonyms; it never rewrites them. A missing
        shipped synonym here means EF's data moved and `original_value` no
        longer guards what it claims to."""
        seen = set()
        for fix, value, code in _retired_name_entries():
            with self.subTest(code=code):
                original = fix.get("original_value") or []
                self.assertEqual(fix["new_value"], original + [value])
                self.assertNotIn(value, seen)
                seen.add(value)

    def test_the_retired_name_is_no_other_flow_s_spelling(self):
        """Across every fix in the file, each retired name appears exactly once
        -- written onto its own designation's flow and nowhere else. A second
        carrier would be cross-object-stripped and the narrowing would go back
        to reading nothing."""
        fixes = orjson.loads(FIXES.read_bytes())["fixes"]
        retired = {value for _fix, value, _code in _retired_name_entries()}
        for name in retired:
            carriers = [
                fix
                for fix in fixes
                if fix.get("field") == "synonyms"
                and name in (fix.get("new_value") or [])
            ]
            with self.subTest(name=name):
                self.assertEqual(len(carriers), 1)


#: The three HFE-347 ethers as EF ships them: one CAS for the family, each
#: substance's published label its designation.
FAMILY_CAS = "406-78-0"
FAMILY = {
    "fo-347mcc3": "HFE-347mcc3",
    "fo-347mcf2": "HFE-347mcf2",
    "fo-347pcf2": "HFE-347pcf2",
}


class TheTrailingDesignationSettlesASharedCasTestCase(unittest.TestCase):
    """`cas+designation`: the last comma-segment of a SimaPro-lineage name,
    read against the candidates the registry number already found.

    Both halves of the rule, per the repo's own discipline for a rule that
    refines something: the narrowing it performs, and the three places it must
    do nothing -- a list without the lineage, a segment naming no candidate,
    and a row whose stated evidence already answered.
    """

    def _indexes(self, *, simapro: bool) -> MergeIndexes:
        return MergeIndexes(
            flow_objects_by_id=dict.fromkeys(FAMILY),
            flow_object_label_by_id=dict(FAMILY),
            cas_index={FAMILY_CAS: set(FAMILY)},
            ec_index={},
            label_index={label.lower(): {obj} for obj, label in FAMILY.items()},
            pref_label_index={},
            qualifier_index={},
            flow_objects_with_cas=set(FAMILY),
            context_expectations=ContextExpectations(
                _by_source_context={}, _source_label="bafu-2026-v1"
            ),
            consensus_context_strings={},
            prepared_context_decisions={},
            mapping_file=None,
            source=resolve_source_list(
                "bafu-2026-v1" if simapro else "ecoinvent-3.12"
            ),
        )

    def _resolve(self, name: str, *, simapro: bool = True):
        return resolve_flow_object(
            row=SourceRow(
                uuid="row-under-test", name=name, synonyms=[], labels=[name],
                context=["air", "(unspecified)"], context_iri="",
                context_normalized=(), unit="kg", unit_iri="",
                cas=FAMILY_CAS, ec="",
            ),
            indexes=self._indexes(simapro=simapro),
            accumulator=MergeAccumulator(),
        )

    def test_the_designation_the_name_ends_in_is_the_substance(self):
        for obj, code in FAMILY.items():
            name = f"Ether, 1,1,2,2-Tetrafluoroethyl 2,2,2-trifluoroethyl-, {code}"
            with self.subTest(code=code):
                resolution = self._resolve(name)
                self.assertIsNotNone(resolution)
                self.assertEqual(resolution.flow_object_id, obj)
                self.assertEqual(resolution.basis, "cas+designation")

    def test_without_the_simapro_lineage_the_tie_stands(self):
        """The habit belongs to a naming lineage, like every other rule about
        that lineage's spellings."""
        name = "Ether, 1,1,2,2-Tetrafluoroethyl 2,2,2-trifluoroethyl-, HFE-347mcc3"
        self.assertIsNone(self._resolve(name, simapro=False))

    def test_a_segment_naming_no_candidate_leaves_the_tie(self):
        """`Water, well, in ground` ends in a place, not a substance: the rule
        declines rather than guesses, and the row is reported as it was."""
        self.assertIsNone(
            self._resolve("Ether, 1,1,2,2-Tetrafluoroethyl-, in ground")
        )

    def test_a_name_that_is_itself_a_label_is_settled_before_this_rule(self):
        """The full-label narrowing answers first, so a row whose own name is a
        candidate's label keeps `cas+label` -- stated evidence is never
        re-derived."""
        resolution = self._resolve("HFE-347mcf2")
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.flow_object_id, "fo-347mcf2")
        self.assertEqual(resolution.basis, "cas+label")


if __name__ == "__main__":
    unittest.main()
