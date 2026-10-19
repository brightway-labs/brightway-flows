"""The element/ion rule, end to end through the matcher it rides on.

`merge/species.py` deliberately adds no branch to `resolve_flow_object`: it
rewrites a row's matching evidence -- the vendor's newest identity, charge
normalised to this list's spelling -- and the ordinary CAS and label branches
do the rest.  These cases prove the ride works, on the fixtures the simulation
in `plans/retire-prepared-correspondence.md` §3a measured at scale:

* a charged name lands on the ion object through its number;
* a stale ion row follows its canonical identity to the newest release's ion
  -- and, without the identity, provably does not;
* a row its release called the bare element stays the element, though a later
  release reused its uuid for the ion (#398);
* a generic-ion name is its own substance: it lands on a generic-ion object
  where one exists and matches *nothing* where none does, so the creation path
  mints one rather than a charge being guessed;
* bare stays bare, end to end.
"""

from __future__ import annotations

import dataclasses
import unittest

from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.matching import _normalize_text, resolve_flow_object
from brightway_flows.merge.species import (
    CanonicalIdentity,
    canonicalized_for_matching,
)
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes, SourceRow
from brightway_flows.sources import resolve_source_list

#: label -> (flow object id, CAS or None).  The shape the real list has: the
#: element and its ion side by side, and one generic-ion object with no number
#: of its own -- the `Arsenic, Ion` precedent.
OBJECTS = {
    "Nickel": ("fo-nickel", "7440-02-0"),
    "Nickel(2+)": ("fo-nickel-ion", "14701-22-5"),
    "Zinc": ("fo-zinc", "7440-66-6"),
    "Zinc(2+)": ("fo-zinc-ion", "23713-49-7"),
    "Copper": ("fo-copper", "7440-50-8"),
    "Copper, Ion": ("fo-copper-ion", None),
    "Antimony": ("fo-antimony", "7440-36-0"),
    "Vanadium": ("fo-vanadium", "7440-62-2"),
    "Vanadium(3+)": ("fo-vanadium-3", "22541-77-1"),
    "Vanadium(5+)": ("fo-vanadium-5", "22537-31-1"),
}

IDENTITIES = {
    "s-zinc-38": CanonicalIdentity(
        uuid="s-zinc-38", name="Zinc II", cas_number="23713-49-7",
        decided_by="3.12", replaces=(("3.8", "Zinc, ion", "23713-49-7"),),
    ),
    # ecoinvent 3.8's `Vanadium, ion` under the trivalent ion's number, which
    # 3.12 calls `Vanadium V` under the pentavalent one's.
    "s-vanadium-38": CanonicalIdentity(
        uuid="s-vanadium-38", name="Vanadium V", cas_number="22537-31-1",
        decided_by="3.12", replaces=(("3.8", "Vanadium, ion", "22541-77-1"),),
    ),
}


def _indexes() -> MergeIndexes:
    cas_index: dict[str, set[str]] = {}
    label_index: dict[str, set[str]] = {}
    for label, (oid, cas) in OBJECTS.items():
        label_index.setdefault(_normalize_text(label), set()).add(oid)
        if cas:
            cas_index.setdefault(cas, set()).add(oid)
    return MergeIndexes(
        flow_objects_by_id={oid: {} for oid, _ in OBJECTS.values()},
        flow_object_label_by_id={oid: label for label, (oid, _) in OBJECTS.items()},
        cas_index=cas_index,
        ec_index={},
        label_index=label_index,
        pref_label_index={
            _normalize_text(label): {oid} for label, (oid, _) in OBJECTS.items()
        },
        qualifier_index={},
        flow_objects_with_cas={oid for oid, cas in OBJECTS.values() if cas},
        context_expectations=ContextExpectations(
            _by_source_context={}, _source_label="test"
        ),
        consensus_context_strings={},
        prepared_context_decisions={},
        mapping_file=None,
        source=dataclasses.replace(
            resolve_source_list("ecoinvent-3.12"), prepared_match_table=None
        ),
        canonical_identities=IDENTITIES,
    )


def _row(name: str, *, uuid: str = "s-1", cas: str = "") -> SourceRow:
    return SourceRow(
        uuid=uuid, name=name, synonyms=[], labels=[name],
        context=["water", "surface water"], context_iri="",
        context_normalized=(), unit="kg", unit_iri="", cas=cas, ec="",
    )


class SpeciesMatchingTestCase(unittest.TestCase):
    def _resolve(self, row: SourceRow):
        indexes = _indexes()
        prepared = canonicalized_for_matching(row, indexes.canonical_identities)
        return resolve_flow_object(
            row=prepared, indexes=indexes, accumulator=MergeAccumulator()
        )

    def test_a_charged_name_lands_on_the_ion_by_its_number(self):
        resolution = self._resolve(_row("Nickel II", cas="14701-22-5"))
        self.assertEqual(resolution.flow_object_id, "fo-nickel-ion")

    def test_a_charged_name_with_no_number_lands_on_the_ion_by_its_label(self):
        resolution = self._resolve(_row("Nickel(2+)"))
        self.assertEqual(resolution.flow_object_id, "fo-nickel-ion")

    def test_a_stale_ion_row_follows_its_canonical_identity(self):
        resolution = self._resolve(
            _row("Vanadium, ion", uuid="s-vanadium-38", cas="22541-77-1")
        )
        self.assertEqual(resolution.flow_object_id, "fo-vanadium-5")
        self.assertEqual(resolution.basis, "cas")

    def test_without_the_identity_the_same_row_keeps_its_own_number(self):
        """The counterfactual that sizes the rule: same words, no entry."""
        resolution = self._resolve(
            _row("Vanadium, ion", uuid="s-unknown", cas="22541-77-1")
        )
        self.assertEqual(resolution.flow_object_id, "fo-vanadium-3")

    def test_a_bare_element_on_a_reused_uuid_stays_the_element(self):
        """#398: 3.8's `Zinc` (7440-66-6) on a uuid whose newest name is
        `Zinc II` lands on the metal, where BAFU's and EF's `Zinc` are."""
        resolution = self._resolve(_row("Zinc", uuid="s-zinc-38", cas="7440-66-6"))
        self.assertEqual(resolution.flow_object_id, "fo-zinc")
        self.assertEqual(resolution.basis, "cas")

    def test_a_generic_ion_name_lands_on_the_generic_ion_object(self):
        resolution = self._resolve(_row("Copper ion"))
        self.assertEqual(resolution.flow_object_id, "fo-copper-ion")
        self.assertEqual(resolution.basis, "label")

    def test_a_generic_ion_with_no_object_matches_nothing_rather_than_a_charge(self):
        """`Antimony ion` where only elemental `Antimony` exists: guessing a
        charge is the reinterpretation the rule refuses, and an unmatched row
        is what lets the creation path mint `Antimony, Ion` instead."""
        self.assertIsNone(self._resolve(_row("Antimony ion")))

    def test_bare_stays_bare_end_to_end(self):
        resolution = self._resolve(_row("Copper", cas="7440-50-8"))
        self.assertEqual(resolution.flow_object_id, "fo-copper")


if __name__ == "__main__":
    unittest.main()
