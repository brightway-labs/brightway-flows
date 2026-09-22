"""An ion is named for the charge it carries, once the charge is known.

#128. `flow_layers.ions` names an ion from its label, and where the label holds
no numeral it falls back to `X, ion` -- meaning "I could not work out the
charge".  The charge then arrives from PubChem in a *transformer*, which runs
after the flow layers, so the fallback name is written before the answer exists
and nothing revisits it.  `Tin(2+)` and `Tin, ion` are published side by side and
are stannous and stannic tin.

The half that matters is the second class: the pass must leave `Iron, ion` and
`Arsenic, Ion` alone, because those state no charge and iron II and iron III are
different substances.  A rule that renamed them would be guessing, which is the
thing #127 established this project should not do.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.preferred_label_decisions import (
    APPROVE,
    REJECT,
    LabelDecision,
    decision_key,
)
from brightway_flows.domain.vocabulary import CHEMROF_ELEMENTAL_CHARGE
from brightway_flows.pipeline.element_labels import IonPrefLabelPass

RULE = IonPrefLabelPass.name


def _object(label, charge=None, object_id="fo-1"):
    properties = {}
    if charge is not None:
        values = charge if isinstance(charge, list) else [charge]
        properties[CHEMROF_ELEMENTAL_CHARGE] = {"@value": values}
    return FlowObject(
        flow_object_id=object_id,
        prefLabel=[{"@value": label, "@language": "en"}],
        altLabel=[],
        properties=properties,
        references=[],
        created_from={},
    )


def _ruling(current, replacement, verdict=APPROVE):
    """A curated ruling on this pair, keyed the way the decisions file is."""
    return {
        decision_key(current, replacement): LabelDecision(
            current=current, replacement=replacement, decision=verdict
        )
    }


def _label(obj):
    entry = obj.prefLabel[0] if obj.prefLabel else {}
    return entry.get("@value", "") if isinstance(entry, dict) else str(entry)


class TheChargeIsInTheName(unittest.TestCase):
    """The half #128 is about."""

    def _run(self, obj, decisions=None):
        current = _label(obj)
        charge = obj.properties.get(CHEMROF_ELEMENTAL_CHARGE, {}).get("@value")
        replacement = ""
        if charge:
            value = charge[0]
            replacement = f"{current[: -len(', ion')].strip()}({abs(value)}+)"
        pass_ = IonPrefLabelPass(
            decisions=decisions if decisions is not None
            else _ruling(current, replacement)
        )
        return pass_, pass_.apply([obj])

    def test_a_stannic_tin_is_named_for_its_charge(self):
        obj = _object("Tin, ion", charge=4)
        pass_, stats = self._run(obj)
        self.assertEqual(stats["renamed"], 1)
        self.assertEqual(len(pass_.renames), 1)
        self.assertEqual(_label(obj), "Tin(4+)")

    def test_a_singly_charged_cation_too(self):
        obj = _object("Sodium, ion", charge=1)
        pass_, stats = self._run(obj)
        self.assertEqual(stats["renamed"], 1)
        self.assertEqual(_label(obj), "Sodium(1+)")

    def test_the_write_says_why(self):
        # The comment is what a reader of the changelog sees, and the reason is
        # the whole argument: the object states this charge and its name did not.
        obj = _object("Tin, ion", charge=4)
        pass_, _ = self._run(obj)
        self.assertEqual(pass_.renames[0], ("fo-1", "Tin, ion", "Tin(4+)"))

    def test_a_negative_charge_keeps_its_sign(self):
        obj = _object("Thiocyanate, ion", charge=-1)
        pass_ = IonPrefLabelPass(
            decisions=_ruling("Thiocyanate, ion", "Thiocyanate(1-)")
        )
        stats = pass_.apply([obj])
        self.assertEqual(stats["renamed"], 1)
        self.assertEqual(
            _label(obj), "Thiocyanate(1-)"
        )


class TheChargeIsNotKnown(unittest.TestCase):
    """The half that stops this guessing, which is the point of #127."""

    def test_an_ion_with_no_stated_charge_keeps_the_fallback_name(self):
        # BAFU's `Iron, ion`: iron II and iron III are different substances with
        # different registry numbers and different factors, and the row does not
        # say which is meant.  `X, ion` is the right name for that.
        obj = _object("Iron, Ion")
        pass_ = IonPrefLabelPass(decisions={})
        stats = pass_.apply([obj])
        self.assertEqual(stats["no_stated_charge"], 1)
        self.assertEqual(stats["renamed"], 0)
        self.assertEqual(pass_.renames, [])

    def test_it_is_counted_rather_than_skipped_silently(self):
        # This number going to nought would mean the ambiguity had been settled
        # somewhere, which is worth seeing rather than inferring.
        pass_ = IonPrefLabelPass(decisions={})
        stats = pass_.apply([_object("Iron, Ion"), _object("Arsenic, Ion", object_id="fo-2")])
        self.assertEqual(stats["unspecified_charge_names"], 2)
        self.assertEqual(stats["no_stated_charge"], 2)

    def test_a_charge_of_zero_is_not_a_charge(self):
        obj = _object("Something, ion", charge=0)
        pass_ = IonPrefLabelPass(decisions={})
        stats = pass_.apply([obj])
        self.assertEqual(stats["no_stated_charge"], 1)

    def test_two_charges_are_not_a_charge(self):
        # A salt states formulas at more than one charge, and `+1` and `-1` on
        # one object is two readings of a substance rather than a charge it has.
        obj = _object("Something, ion", charge=[1, -1])
        pass_ = IonPrefLabelPass(decisions={})
        stats = pass_.apply([obj])
        self.assertEqual(stats["no_stated_charge"], 1)

    def test_an_object_not_named_the_fallback_way_is_untouched(self):
        obj = _object("Tin(2+)", charge=2)
        pass_ = IonPrefLabelPass(decisions={})
        stats = pass_.apply([obj])
        self.assertEqual(stats["unspecified_charge_names"], 0)
        self.assertEqual(pass_.renames, [])


class TheRenameIsRuledOn(unittest.TestCase):
    """#16's lesson: a published rename is proposed, not asserted."""

    def test_an_unruled_rename_does_not_happen_and_asks(self):
        obj = _object("Tin, ion", charge=4)
        pass_ = IonPrefLabelPass(decisions={})
        stats = pass_.apply([obj])
        self.assertEqual(stats["undecided"], 1)
        self.assertEqual(stats["renamed"], 0)
        self.assertEqual(pass_.renames, [])
        items = pass_.review_queue_items()
        self.assertEqual(len(items), 1)
        self.assertIn("Tin(4+)", items[0].title)

    def test_a_rejected_rename_does_not_happen_and_does_not_ask(self):
        obj = _object("Tin, ion", charge=4)
        pass_ = IonPrefLabelPass(
            decisions=_ruling("Tin, ion", "Tin(4+)", REJECT)
        )
        stats = pass_.apply([obj])
        self.assertEqual(stats["rejected"], 1)
        self.assertEqual(pass_.renames, [])
        self.assertEqual(pass_.review_queue_items(), [])

    def test_it_rules_under_its_own_rule_name(self):
        # So that approving an ion rename does not approve the element renames
        # `ElementPrefLabelPass` proposes, and the other way round.
        self.assertEqual(IonPrefLabelPass.name, "ion_pref_label_from_stated_charge")


if __name__ == "__main__":
    unittest.main()
