"""A row named exactly what a substance is called beats one that lists the name.

A source row is looked up under every name it is known by, and a hit is a hit:
nothing in matching asks *which kind* of name it landed on.  For most rows that
costs nothing, because one substance answers and the row is placed.  Where
several answer, it is the whole question.

BAFU ships a row called simply `Water`.  Twelve substances in this list carry
water's registry number, because every kind of water is H2O, and eleven of the
twelve also list "water" among their alternative names -- correctly, since they
are all water.  So the row hits twelve on the number and eleven on a name, and
the selector reports `multiple-flow-object-candidates`.  One of the twelve is
*called* `Water` (#86).

The same shape, without water: `Thorium` reaches both the element and
thorium-232, because the isotope carries the element's number and lists the
element's name; `1,1,1-Trichloroethane` reaches nine substances, because the row
carries two dozen trade names and each of them is some other compound's
alternative label.  In each case one candidate's own name is what the row is
called, and that is a better answer than the rest.

What the rule must not do is collapse the distinctions the list holds
deliberately.  Sea water is not lake water, and a process drawing from a river
does not draw from a well.  Two things keep it honest, and both are asserted
below: only the row's **own** name is asked, never the synonyms it was enriched
with, and it must equal a candidate's **preferred** name rather than any label
that candidate answers to.
"""

from __future__ import annotations

import dataclasses
import unittest

from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.matching import resolve_flow_object
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes, SourceRow
from brightway_flows.sources import resolve_source_list

WATER_CAS = "7732-18-5"

#: The twelve substances sharing water's registry number, as the list spells
#: them.  The real set: this is the tie the issue is about, and a fix that only
#: works against a sample of it is not a fix.
WATERS = {
    "Water": "fo-water",
    "Lake water": "fo-lake",
    "Sea water": "fo-sea",
    "Groundwater": "fo-ground",
    "Rainwater": "fo-rain",
    "Cooling water": "fo-cooling",
    "River water": "fo-river",
    "Fresh water": "fo-fresh",
    "Turbine water": "fo-turbine",
    "Fossil groundwater": "fo-fossil",
    "Water vapour": "fo-vapour",
    "Green water": "fo-green",
}

#: What the row carries besides its own name: water's synonyms, which
#: enrichment attaches to every water row alike.  `Water, river` and `Water`
#: arrive with the identical list, which is why matching on any of them would
#: send both to the same substance.
WATER_SYNONYMS = ["H2O", "aqua", "eau", "Wasser", "oxidane", "Water"]


def _source(*, simapro: bool):
    """A registered list with `simapro_origin` set either way.

    Which list it is does not matter and should not: the flag is what gates a
    derived spelling, not the identity of the vendor.
    """
    return dataclasses.replace(
        resolve_source_list("ecoinvent-3.12"), simapro_origin=simapro
    )


class WaterTestCase(unittest.TestCase):
    """The twelve-way tie, and what does and does not break it."""

    def _indexes(self, *, simapro=True):
        pref = {name.casefold(): {oid} for name, oid in WATERS.items()}
        labels = {key: set(value) for key, value in pref.items()}
        # Eleven of the twelve list "water" among their alternative names.
        labels["water"] = set(WATERS.values()) - {"fo-green"}
        return MergeIndexes(
            flow_objects_by_id={oid: {} for oid in WATERS.values()},
            flow_object_label_by_id={oid: name for name, oid in WATERS.items()},
            cas_index={WATER_CAS: set(WATERS.values())},
            ec_index={},
            label_index=labels,
            pref_label_index=pref,
            qualifier_index={},
            flow_objects_with_cas=set(WATERS.values()),
            context_expectations=ContextExpectations(
                _by_source_context={}, _source_label="test"
            ),
            consensus_context_strings={},
            prepared_context_decisions={},
            mapping_file=None,
            source=_source(simapro=simapro),
        )

    def _row(self, name, *, labels=None, cas=WATER_CAS):
        return SourceRow(
            uuid="s-1", name=name, synonyms=[],
            labels=[name, *(labels if labels is not None else WATER_SYNONYMS)],
            context=["resources", "in water"], context_iri="",
            context_normalized=(), unit="m3", unit_iri="", cas=cas, ec="",
        )

    def _resolve(self, row, indexes):
        return resolve_flow_object(
            row=row, indexes=indexes, accumulator=MergeAccumulator()
        )

    def test_the_row_called_water_is_the_substance_called_water(self):
        resolution = self._resolve(self._row("Water"), self._indexes())
        self.assertEqual(resolution.flow_object_id, "fo-water")
        # `cas+label` is where it got to before this: twelve candidates on
        # the number, narrowed to the eleven that also answer to "water".
        self.assertEqual(resolution.basis, "cas+label+preferred-name")

    def test_the_name_that_decided_it_is_recorded(self):
        """`basis_value` carried the registry number alone, which is the one
        thing that did *not* decide this row."""
        resolution = self._resolve(self._row("Water"), self._indexes())
        self.assertEqual(resolution.basis_value, f"{WATER_CAS}; Water")

    def test_a_row_naming_a_kind_of_water_does_not_land_on_plain_water(self):
        """The collapse the rule must not cause. `Water, river` carries the
        same 23 names as `Water` -- enrichment gave every water row water's
        synonyms -- so a rule reading any of the row's names would send it to
        the substance called `Water`. Only its own name is asked, and it is
        reached through the spelling the list uses for it instead."""
        resolution = self._resolve(self._row("Water, river"), self._indexes())
        self.assertEqual(resolution.flow_object_id, "fo-river")

    def test_a_kind_of_water_the_list_does_not_hold_stays_a_tie(self):
        """`Water, fossil` de-inverts to `fossil water`, and the list's
        substance is called `Fossil groundwater`. Close is not equal, and the
        row is reported rather than assigned by resemblance."""
        self.assertIsNone(self._resolve(self._row("Water, fossil"), self._indexes()))

    def test_a_list_simapro_did_not_shape_gets_no_derived_spelling(self):
        """The same gate every other derived name has. Read anywhere else a
        comma is not a habit, and swapping across it is a guess."""
        self.assertIsNone(
            self._resolve(self._row("Water, river"), self._indexes(simapro=False))
        )

    def test_the_row_named_water_still_resolves_without_the_derived_spelling(self):
        """The plain name needs no habit read out of it, so it is placed on a
        list of any lineage."""
        resolution = self._resolve(self._row("Water"), self._indexes(simapro=False))
        self.assertEqual(resolution.flow_object_id, "fo-water")

    def test_an_alternative_name_hit_is_not_enough(self):
        """Every candidate keeps its alternative names and loses its preferred
        one: the row is still called `Water` and eleven substances still list
        `water`, and now nothing is *called* it. The tie stands."""
        indexes = self._indexes()
        indexes.pref_label_index.clear()
        self.assertIsNone(self._resolve(self._row("Water"), indexes))

    def test_a_row_one_substance_answers_never_reaches_the_rule(self):
        """`basis` says `cas`: there was no tie, so nothing was narrowed and
        the rule cannot have moved it."""
        indexes = self._indexes()
        indexes.cas_index[WATER_CAS] = {"fo-sea"}
        resolution = self._resolve(self._row("Water"), indexes)
        self.assertEqual(resolution.flow_object_id, "fo-sea")
        self.assertEqual(resolution.basis, "cas")


class SpeciesSpellingTestCase(unittest.TestCase):
    """The house spelling of the row's own name counts as the row's name.

    BAFU ships two rows named `Copper Ion` with no registry number; the list's
    substance is called `Copper, Ion` since the minted ions were renamed onto
    the one spelling (#141's harmonisation), and the vendor's comma-less form
    is an alternative label -- which this rule rightly refuses to count.  The
    row's own name folded through `merge/species.py` is still the row's own
    name, so the tie the rename created breaks the same way it did before.

    Since #198 the tie never forms: the element is the bare form of the row's
    own ion name, and the label narrowing refuses it before this rule is
    asked, so the row reaches the ion on its label alone.  The fold is still
    what the second test below exercises, for a name outside the family.
    """

    def _indexes(self):
        objects = {"Copper": "fo-copper", "Copper, Ion": "fo-copper-ion"}
        pref = {name.casefold(): {oid} for name, oid in objects.items()}
        labels = {key: set(value) for key, value in pref.items()}
        # The vendor spelling stays searchable on the renamed object, and an
        # enrichment synonym reaches the element -- the two-way tie the build
        # of 2026-08-23 reported for both rows.
        labels["copper ion"] = {"fo-copper-ion"}
        labels["a trade name"] = {"fo-copper"}
        return MergeIndexes(
            flow_objects_by_id={oid: {} for oid in objects.values()},
            flow_object_label_by_id={oid: n for n, oid in objects.items()},
            cas_index={},
            ec_index={},
            label_index=labels,
            pref_label_index=pref,
            qualifier_index={},
            flow_objects_with_cas=set(),
            context_expectations=ContextExpectations(
                _by_source_context={}, _source_label="test"
            ),
            consensus_context_strings={},
            prepared_context_decisions={},
            mapping_file=None,
            source=_source(simapro=True),
        )

    def _row(self, name):
        # The enrichment labels reach both objects, which is the tie itself:
        # one synonym is the element's trade name, one is the ion's spelling.
        return SourceRow(
            uuid="s-1", name=name, synonyms=[],
            labels=[name, "a trade name", "Copper Ion"],
            context=["emissions to water", "unspecified"], context_iri="",
            context_normalized=(), unit="kg", unit_iri="", cas="", ec="",
        )

    def test_the_vendor_spelling_reaches_the_house_spelling(self):
        resolution = resolve_flow_object(
            row=self._row("Copper Ion"),
            indexes=self._indexes(),
            accumulator=MergeAccumulator(),
        )
        self.assertIsNotNone(resolution)
        self.assertEqual(resolution.flow_object_id, "fo-copper-ion")
        # Used to read `preferred-name`: the element was a candidate and this
        # rule chose between the two.  The element is refused on the row's own
        # name now (#198), so there is one candidate and no tie to break.
        self.assertEqual(resolution.basis, "label")

    def test_a_name_that_is_no_species_still_stands_its_tie(self):
        # The other half: the fold reaches nothing for a name outside the
        # species family, and the tie is reported rather than guessed at.
        accumulator = MergeAccumulator()
        resolution = resolve_flow_object(
            row=self._row("Kupferwasser"),
            indexes=self._indexes(),
            accumulator=accumulator,
        )
        self.assertIsNone(resolution)


class ElementAndIsotopeTestCase(unittest.TestCase):
    """The same shape without water, which is what makes it a rule.

    Thorium-232 carries the element's registry number -- a number names a
    substance, and the lists do not agree that an isotope is one -- and lists
    the element's name among its own. So `Thorium` reaches both, and one of
    them is called `Thorium`.
    """

    def _indexes(self):
        return MergeIndexes(
            flow_objects_by_id={"fo-th": {}, "fo-th232": {}},
            flow_object_label_by_id={"fo-th": "Thorium", "fo-th232": "Thorium-232"},
            cas_index={"7440-29-1": {"fo-th", "fo-th232"}},
            ec_index={},
            label_index={
                "thorium": {"fo-th", "fo-th232"},
                "thorium-232": {"fo-th232"},
            },
            pref_label_index={"thorium": {"fo-th"}, "thorium-232": {"fo-th232"}},
            qualifier_index={},
            flow_objects_with_cas={"fo-th", "fo-th232"},
            context_expectations=ContextExpectations(
                _by_source_context={}, _source_label="test"
            ),
            consensus_context_strings={},
            prepared_context_decisions={},
            mapping_file=None,
            source=_source(simapro=True),
        )

    def _row(self, name):
        return SourceRow(
            uuid="s-2", name=name, synonyms=[],
            labels=[name, "232Th", "Thorium-232", "torio"],
            context=["emissions to air", "low. pop."], context_iri="",
            context_normalized=(), unit="kBq", unit_iri="",
            cas="7440-29-1", ec="",
        )

    def test_the_element_wins_over_its_isotope(self):
        resolution = resolve_flow_object(
            row=self._row("Thorium"),
            indexes=self._indexes(),
            accumulator=MergeAccumulator(),
        )
        self.assertEqual(resolution.flow_object_id, "fo-th")

    def test_the_isotope_wins_when_the_row_names_the_isotope(self):
        """Not a preference for the shorter name or the parent substance: the
        rule reads what the row is called, and reversing the row reverses it."""
        resolution = resolve_flow_object(
            row=self._row("Thorium-232"),
            indexes=self._indexes(),
            accumulator=MergeAccumulator(),
        )
        self.assertEqual(resolution.flow_object_id, "fo-th232")


if __name__ == "__main__":
    unittest.main()
