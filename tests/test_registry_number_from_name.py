"""A row takes the registry number its own list gives that name (#26, #71).

BAFU ships four rows called `Silver-110`. Two carry 14391-76-5 and reach the
silver-110 the list already holds; two carry nothing, so the matcher had only a
name, and they became a second substance also called `Silver-110`. One vendor
name, one build, two substances, and only one of them characterised.

Both halves of the rule are pinned here, because the half that refuses is the
one that stops it growing into a rule that overrules the source:

- what it fills in -- a name its own list gives exactly one number;
- what it leaves alone -- a flow that already has a number, a name the list
  gives two numbers, a name that appears only on another list's rows, and a
  synonym rather than the name the source shipped.
"""

from __future__ import annotations

import unittest

from brightway_flows.domain.flow import Flow
from brightway_flows.transformers.registry_number_from_name import (
    RegistryNumberFromNameTransformer,
)

BAFU = "bafu-2026-v1"
ECOINVENT = "ecoinvent-3.12"


def _flow(uuid: str, name: str, *, source: str = BAFU, cas: str = "") -> Flow:
    return Flow.from_dict({
        "uuid": uuid,
        "identifier": uuid,
        "source": source,
        "unit": "kg",
        "cas_numbers": [cas] if cas else [],
        "prefLabel": [{"@value": name, "@language": "en"}],
        "altLabel": [],
    })


class RegistryNumberFromNameTestCase(unittest.TestCase):
    def run_transformer(self, flows):
        return RegistryNumberFromNameTransformer().transform(flows)

    def number_written(self, changes, uuid):
        for change in changes:
            if change.uuid == uuid and change.field == "cas_numbers":
                return change.new_value
        return None

    # --- what it fills in -------------------------------------------------

    def test_a_row_takes_the_number_its_own_list_gives_the_name(self):
        """The `Silver-110` case, which is #26."""
        flows = [
            _flow("has-1", "Silver-110", cas="14391-76-5"),
            _flow("has-2", "Silver-110", cas="14391-76-5"),
            _flow("bare-1", "Silver-110"),
            _flow("bare-2", "Silver-110"),
        ]
        changes = self.run_transformer(flows)

        self.assertEqual(self.number_written(changes, "bare-1"), ["14391-76-5"])
        self.assertEqual(self.number_written(changes, "bare-2"), ["14391-76-5"])

    def test_the_name_is_matched_without_regard_to_case(self):
        flows = [
            _flow("has-1", "Ethane, Pentafluoro-, HFC-125", cas="354-33-6"),
            _flow("bare-1", "ethane, pentafluoro-, hfc-125"),
        ]
        changes = self.run_transformer(flows)

        self.assertEqual(self.number_written(changes, "bare-1"), ["354-33-6"])

    def test_the_provenance_names_the_list_that_answered(self):
        flows = [
            _flow("has-1", "Silver-110", cas="14391-76-5"),
            _flow("bare-1", "Silver-110"),
        ]
        changes = self.run_transformer(flows)

        sources = {
            change.uuid: change.new_value
            for change in changes
            if change.field == "cas_number_sources"
        }
        self.assertEqual(
            sources["bare-1"]["14391-76-5"]["prov:hadPrimarySource"], [BAFU]
        )

    def test_a_nuclide_is_answered_like_anything_else(self):
        """The vendor's own number is not in doubt, whatever the substance is.

        Reference data cannot be used for these -- ChEBI and PubChem index
        `krypton-85m` under krypton-85's number and `uranium-238` under
        uranium's -- and that is why this rule reads the source list instead of
        a reference database. What BAFU says about BAFU's rows is not subject to
        that failure.
        """
        flows = [
            _flow("has-1", "Hydrogen-3, Tritium", cas="10028-17-8"),
            _flow("bare-1", "Hydrogen-3, Tritium"),
        ]
        changes = self.run_transformer(flows)

        self.assertEqual(self.number_written(changes, "bare-1"), ["10028-17-8"])

    # --- what it leaves alone ---------------------------------------------

    def test_a_flow_that_has_a_number_keeps_it(self):
        """A name is weaker evidence than a number and never overrules one."""
        flows = [
            _flow("has-1", "Barite", cas="13462-86-7"),
            _flow("has-2", "Barite", cas="7727-43-7"),
        ]
        changes = self.run_transformer(flows)

        self.assertEqual(changes, [])

    def test_a_list_that_gives_one_name_two_numbers_answers_nothing(self):
        flows = [
            _flow("has-1", "Sulfur Chloride", cas="10545-99-0"),
            _flow("has-2", "Sulfur Chloride", cas="10025-67-9"),
            _flow("bare-1", "Sulfur Chloride"),
        ]
        changes = self.run_transformer(flows)

        self.assertIsNone(self.number_written(changes, "bare-1"))

    def test_a_number_the_list_gives_two_names_answers_nothing(self):
        """The `Uranium-238` case, and the mirror of the rule above.

        BAFU gives 7440-61-1 -- uranium the element -- to fourteen of its
        fifteen `Uranium-238` rows, and to its `Uranium` rows as well. The
        fifteenth carries nothing and was matching the uranium-238 isotope on
        its name, correctly. Taking BAFU's number would have made it consistent
        with its siblings and moved it off the isotope onto the element, which
        is a worse answer than the one it had.

        A number one list gives to two names is not identifying a substance in
        that list, exactly as a name given two numbers is not. Both halves have
        to refuse, or the rule turns one vendor's data defect into fifteen rows
        instead of fourteen.
        """
        flows = [
            _flow("has-1", "Uranium-238", cas="7440-61-1"),
            _flow("has-2", "Uranium", cas="7440-61-1"),
            _flow("bare-1", "Uranium-238"),
        ]
        changes = self.run_transformer(flows)

        self.assertIsNone(self.number_written(changes, "bare-1"))

    def test_a_number_another_list_gives_two_names_still_answers(self):
        """The guard is about *this* list's usage, like everything else here.

        ecoinvent gives 14391-76-5 to `Silver-110m` and BAFU to `Silver-110`.
        That is two lists spelling one substance two ways, which is the merge's
        ordinary work; it is not BAFU using one number for two substances.
        """
        flows = [
            _flow("other-1", "Silver-110m", source=ECOINVENT, cas="14391-76-5"),
            _flow("has-1", "Silver-110", cas="14391-76-5"),
            _flow("bare-1", "Silver-110"),
        ]
        changes = self.run_transformer(flows)

        self.assertEqual(self.number_written(changes, "bare-1"), ["14391-76-5"])

    def test_a_name_no_row_of_this_list_numbers_answers_nothing(self):
        changes = self.run_transformer([_flow("u-1", "Occupation, Annual Crop")])

        self.assertEqual(changes, [])

    def test_another_list_using_the_same_word_does_not_answer(self):
        """Two lists using one word for different substances is the ordinary case.

        The evidence is that *this* vendor said what the substance is on another
        of its own rows. A different vendor's row is a different claim, and
        acting on it would be matching two lists by name -- which the merge does
        downstream, carefully, with the whole list in view.
        """
        flows = [
            _flow("other-1", "Barite", source=ECOINVENT, cas="7727-43-7"),
            _flow("bare-1", "Barite", source=BAFU),
        ]
        changes = self.run_transformer(flows)

        self.assertEqual(changes, [])

    def test_an_alternative_label_is_not_looked_up(self):
        """Only the name the source shipped, never the synonyms enrichment found.

        By the time this runs, every synonym ChEBI and Common Chemistry could
        supply is on the flow. Reading those would ask whether some name the
        substance is *also* known by means a number, which is how "Granite"
        reaches Penoxsulam.
        """
        flows = [
            _flow("has-1", "Silver-110", cas="14391-76-5"),
            Flow.from_dict({
                "uuid": "u-1",
                "identifier": "u-1",
                "source": BAFU,
                "unit": "kg",
                "cas_numbers": [],
                "prefLabel": [{"@value": "Some Trade Mixture", "@language": "en"}],
                "altLabel": [{"@value": "Silver-110", "@language": "en"}],
            }),
        ]
        changes = self.run_transformer(flows)

        self.assertIsNone(self.number_written(changes, "u-1"))

    def test_a_finished_flow_is_not_written_to(self):
        """The consensus side of a merge is shown, and is not a candidate."""
        flows = [
            _flow("has-1", "Silver-110", cas="14391-76-5"),
            _flow("bare-1", "Silver-110"),
        ]
        flows[1].transformed = True
        changes = self.run_transformer(flows)

        self.assertEqual(changes, [])


if __name__ == "__main__":
    unittest.main()
