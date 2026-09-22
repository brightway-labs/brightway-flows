"""AGRIBALYSE 3.2's curated targets, and what each one is about (#190).

AGRIBALYSE ships no flow identifiers, so its uuids are derived from the four
fields the vendor writes -- name, compartment, sub-compartment, unit -- and a
row of `agribalyse-3.2-match-overrides.json` can be checked without the
vendor's file: recomputing the identifier from the fields the row carries for
the reader's sake says whether it names the flow it claims to.  That is the
check the file exists to survive, because an override naming a uuid the list
does not ship overrides nothing, raises nothing, and reads in review exactly
like one that does its job.
"""

from __future__ import annotations

import unittest

import orjson

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.integrations.agribalyse import _flow_uuid
from brightway_flows.match_overrides import load_match_overrides
from brightway_flows.sources import (
    known_source_lists,
    load_prepared_match_table,
    resolve_source_list,
)

KEY = "agribalyse-3.2"
OVERRIDES_PATH = PACKAGE_DATA_DIR / "agribalyse-3.2-match-overrides.json"

#: Each row, and the EF 3.1 flow it is sent to: the flow ecoinvent's row of the
#: same ecoinvent 2 name reaches by a curated target of its own.
TARGETS = {
    "Gangue, bauxite": "fe0acd60-3ddc-11dd-a6ff-0050c2490048",
    "Kaolin ore": "fe0acd60-3ddc-11dd-aab8-0050c2490048",
    "Mineral oil": "12b74f48-d8ba-4361-8fee-0740c4475136",
}


class TheFileTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.source = known_source_lists()[KEY]
        self.overrides = load_match_overrides(OVERRIDES_PATH)

    def test_the_manifest_declares_it(self) -> None:
        self.assertEqual(self.source.match_overrides_path, OVERRIDES_PATH)
        self.assertEqual(self.source.missing_curated_inputs(), [])

    def test_every_row_names_a_flow_agribalyse_ships(self) -> None:
        for override in self.overrides:
            if override.source_name not in TARGETS:
                # #353's Water/m3 row states no context; its own test reads
                # it against the vendor file.
                continue
            with self.subTest(override.source_name):
                self.assertTrue(override.source_context)
                compartment, subcompartment = override.source_context
                self.assertEqual(
                    _flow_uuid(
                        override.source_name, compartment, subcompartment,
                        override.source_unit or "kg",
                    ),
                    override.source_uuid,
                )

    def test_every_row_states_its_reason_and_no_conversion(self) -> None:
        """Three rows, kilograms onto kilograms of the same thing: a factor on
        any of them would be a claim the comment does not make.  The file also
        carries #353's `Water/m3` row, which is that PR's to check."""
        by_name = {override.source_name: override for override in self.overrides}
        self.assertTrue(set(TARGETS) <= set(by_name))
        for name, target in sorted(TARGETS.items()):
            with self.subTest(name):
                override = by_name[name]
                self.assertTrue(override.comment.strip())
                self.assertEqual(override.target_uuid, target)
                self.assertIsNone(override.conversion_factor)

    def test_the_rows_reach_the_prepared_table(self) -> None:
        rows = {
            row["source"]["uuid"]: row["target"]["uuid"]
            for row in load_prepared_match_table(resolve_source_list(KEY))
        }
        for override in self.overrides:
            with self.subTest(override.source_name):
                self.assertEqual(rows.get(override.source_uuid), override.target_uuid)

    def test_the_vendor_ships_every_row_this_is_about(self) -> None:
        """The identifier check above is the one that runs without the file;
        this one reads the extraction where it exists."""
        if not self.source.flows_path.exists():
            raise unittest.SkipTest("AGRIBALYSE 3.2 is not extracted here")
        shipped = {
            row["uuid"]: row["name"]
            for row in orjson.loads(self.source.flows_path.read_bytes())
        }
        for override in self.overrides:
            with self.subTest(override.source_name):
                self.assertEqual(shipped.get(override.source_uuid), override.source_name)


class EnergyAndPeatTestCase(unittest.TestCase):
    """#354's rows: the peat ruling, the energy duplicates, and two rebases.

    The peat rows are the decision the user made on #354 -- an agricultural
    database's kilogram of peat in the biotic compartment is the growing
    medium, `Peat, Horticulture`, never the megajoule fuel (#160 drew the same
    line from the factor side).  The energy rows go where their sibling lists'
    identical names already go, and the two rows whose names state their own
    energy content are rebased at the vendor's numbers, accepted as crossings
    in `unit-change-allowlist.json`.
    """

    #: uuid -> (vendor name, compartment, subcompartment, unit, target uuid,
    #:          conversion factor or None)
    ROWS = {
        "fc379dc0-4b59-5cc3-b454-3538dd8f9f60": (
            "Peat", "Resources", "", "kg",
            "126514fa-415f-454a-8425-aa5d54a1402b", None,
        ),
        "d1e2ddc8-c24d-55ca-ae4a-78b5d99d8813": (
            "Peat", "Resources", "biotic", "kg",
            "126514fa-415f-454a-8425-aa5d54a1402b", None,
        ),
        "68c994ed-f3ce-5be2-8478-0422ab6b679f": (
            "Energy, from biomass", "Resources", "biotic", "MJ",
            "fe0acd60-3ddc-11dd-a6fd-0050c2490048", None,
        ),
        "3300104d-2e3f-5715-bf1b-43a64ecc5601": (
            "Energy, from wood", "Resources", "biotic", "MJ",
            "3e4d9eab-6556-11dd-ad8b-0800200c9a66", None,
        ),
        "4e658766-68ab-567e-ba85-3d01c0a0ca45": (
            "Energy, from wood", "Resources", "", "MJ",
            "3e4d9eab-6556-11dd-ad8b-0800200c9a66", None,
        ),
        "c4898890-5cdc-59a8-8632-4055832784ab": (
            "Energy, gross calorific value, in biomass", "Resources", "biotic",
            "MJ", "fe0acd60-3ddc-11dd-a6fd-0050c2490048", None,
        ),
        "de4b6754-0d2e-587e-8b5b-5ee5a039698f": (
            "Energy, gross calorific value, in biomass", "Resources", "", "MJ",
            "fe0acd60-3ddc-11dd-a6fd-0050c2490048", None,
        ),
        "f65c0b45-7781-5ae0-aeb1-d329b21796dd": (
            "Wood and wood waste, 9.5 MJ per kg", "Resources", "biotic", "kg",
            "3e4d9eab-6556-11dd-ad8b-0800200c9a66", 9.5,
        ),
        "e6f6fcbd-c5ce-53c1-b5aa-d2fc52c10d98": (
            "Uranium oxide, 332 GJ per kg, in ore", "Resources", "in ground",
            "kg", "3e4d2966-6556-11dd-ad8b-0800200c9a66", 332000.0,
        ),
    }

    def setUp(self) -> None:
        self.by_uuid = {
            override.source_uuid: override
            for override in load_match_overrides(OVERRIDES_PATH)
        }

    def test_every_row_names_the_flow_its_vendor_fields_derive(self) -> None:
        for uuid, (name, compartment, sub, unit, _, _) in self.ROWS.items():
            with self.subTest(name=name, sub=sub or "(bare)"):
                self.assertIn(uuid, self.by_uuid)
                self.assertEqual(_flow_uuid(name, compartment, sub, unit), uuid)

    def test_every_row_states_its_target_and_factor(self) -> None:
        for uuid, (name, _, _, _, target, factor) in self.ROWS.items():
            with self.subTest(name=name):
                override = self.by_uuid[uuid]
                self.assertEqual(override.target_uuid, target)
                self.assertTrue(override.comment.strip())
                if factor is None:
                    self.assertIsNone(override.conversion_factor)
                else:
                    self.assertEqual(override.conversion_factor, factor)
                    self.assertEqual(override.source_unit, "kg")
                    self.assertEqual(override.target_unit, "MJ")

    def test_the_two_crossings_are_accepted_with_their_rows(self) -> None:
        """A quantity-kind crossing needs a written reason in the allowlist;
        the two rebases carry the factor their own names state."""
        accepted = {
            (row["source_uuid"], row["target_elementary_flow_id"])
            for row in orjson.loads(
                (PACKAGE_DATA_DIR / "unit-change-allowlist.json").read_bytes()
            )["accepted"]
        }
        for uuid, (name, _, _, _, target, factor) in self.ROWS.items():
            with self.subTest(name=name):
                if factor is None:
                    self.assertNotIn((uuid, target), accepted)
                else:
                    self.assertIn((uuid, target), accepted)

    def test_the_re_filed_rows_state_their_true_compartments(self) -> None:
        """Four rows move compartments in `agribalyse-3.2-manual-fixes.json`:
        the bare-heading peat, wood-energy and biomass-energy rows join their
        biotic twins, and the biotic `Energy, from peat` joins its ground
        siblings -- fuel peat is a ground resource, the growing medium is not
        fuel."""
        fixes = {
            fix["uuid"]: fix["new_value"]
            for fix in orjson.loads(
                (PACKAGE_DATA_DIR / "agribalyse-3.2-manual-fixes.json").read_bytes()
            )["fixes"]
            if fix.get("field") == "context" and "uuid" in fix
        }
        self.assertEqual(
            fixes.get("fc379dc0-4b59-5cc3-b454-3538dd8f9f60"),
            ["Resources", "biotic"],
        )
        self.assertEqual(
            fixes.get("4e658766-68ab-567e-ba85-3d01c0a0ca45"),
            ["Resources", "biotic"],
        )
        self.assertEqual(
            fixes.get("de4b6754-0d2e-587e-8b5b-5ee5a039698f"),
            ["Resources", "biotic"],
        )
        self.assertEqual(
            fixes.get("9fabfb2e-de94-5532-bf2f-6024b445a9ad"),
            ["Resources", "in ground"],
        )

    def test_the_rows_this_family_leaves_alone_stay_alone(self) -> None:
        """The negative half.  `Energy, from coal` and its carrier siblings
        match by label and need no curation; `Energy, from peat` is fixed by a
        compartment re-file alone and takes no target; `Wood, dry matter` has
        no stated energy content and no recorded heating value, so it stays a
        faithful mint until somebody sources a number (#354 records why); and
        oil-field off-gas keeps its own flow (#80's reasoning at an oil
        well), so none of them may appear here."""
        for name, compartment, sub, unit in (
            ("Energy, from coal", "Resources", "", "MJ"),
            ("Energy, from peat", "Resources", "biotic", "MJ"),
            ("Wood, dry matter", "Resources", "biotic", "kg"),
            ("Gas, off-gas, oil production", "Resources", "in ground", "m3"),
        ):
            with self.subTest(name):
                self.assertNotIn(
                    _flow_uuid(name, compartment, sub, unit), self.by_uuid
                )


class PlainCarbonDioxideTestCase(unittest.TestCase):
    """#194's two rows: one name, two compartments, two different origins.

    AGRIBALYSE ships `Carbon dioxide` with no origin in the name and 124-38-9
    and nothing else, twice: once in unspecified air and once in non-urban air.
    Both reached carbon dioxide of unstated origin, which no method here
    characterises.  They are decided separately, on their own datasets --
    industrial carbon dioxide in the first, composting and straw retting in the
    second -- which is what these cases exist to hold apart, because the two
    rows differ by nothing a rule reading names could see.

    `Carbon dioxide, peat oxidation` is not here, deliberately: it states an
    origin, and it is answered by the `land_use_change` qualifier in
    `qualifiers.py`, whose cases are in `tests/test_land_carbon_qualifiers.py`.
    Its nitrous oxide sibling *is* here, and that is not an inconsistency: the
    rule reads the phrase on that name too, and EF ships no nitrous oxide of
    land-use-change origin for it to reach, so the row has to be told where it
    goes.
    """

    NAME = "Carbon dioxide"
    #: uuid -> (sub-compartment, target uuid, the word the comment must argue)
    ROWS = {
        "9f281494-cb58-5f23-a894-ba8b7839e534": (
            "", "08a91e70-3ddc-11dd-923d-0050c2490048", "Glutamate",
        ),
        "5dab3ab7-6821-58ec-b4dd-f1e0366ff916": (
            "low. pop.", "08a91e70-3ddc-11dd-9241-0050c2490048", "Compost",
        ),
    }

    def setUp(self) -> None:
        self.by_uuid = {
            override.source_uuid: override
            for override in load_match_overrides(OVERRIDES_PATH)
        }

    def test_every_row_names_the_flow_its_vendor_fields_derive(self) -> None:
        for uuid, (sub, _, _) in self.ROWS.items():
            with self.subTest(sub=sub or "(bare)"):
                self.assertIn(uuid, self.by_uuid)
                self.assertEqual(
                    _flow_uuid(self.NAME, "Emissions to air", sub, "kg"), uuid
                )

    def test_every_row_reaches_its_target_without_a_conversion(self) -> None:
        for uuid, (sub, target, _) in self.ROWS.items():
            with self.subTest(sub=sub or "(bare)"):
                override = self.by_uuid[uuid]
                self.assertEqual(override.target_uuid, target)
                self.assertIsNone(override.conversion_factor)
                self.assertIn("#194", override.comment)

    def test_the_two_rows_are_sent_to_different_substances(self) -> None:
        """The claim the file is here to make.  One vendor name, one registry
        number, and a fossil answer for one compartment and a biogenic answer
        for the other: an entry copied from its neighbour would publish
        composting carbon dioxide as fossil and never fail a test that only
        checked each row against itself."""
        targets = {self.by_uuid[uuid].target_uuid for uuid in self.ROWS}
        self.assertEqual(len(targets), len(self.ROWS))

    def test_each_row_argues_from_its_own_datasets(self) -> None:
        for uuid, (sub, _, evidence) in self.ROWS.items():
            with self.subTest(sub=sub or "(bare)"):
                self.assertIn(evidence, self.by_uuid[uuid].comment)

    def test_the_two_peat_rows_ef_can_answer_take_no_curated_target(self) -> None:
        """They are answered by a rule that reads what their names say, which
        is what lets one line answer both."""
        for name in ("Carbon dioxide, peat oxidation", "Methane, peat oxidation"):
            with self.subTest(name):
                self.assertNotIn(
                    _flow_uuid(name, "Emissions to air", "", "kg"), self.by_uuid
                )

    def test_the_peat_nitrous_oxide_row_is_told_where_it_goes(self) -> None:
        """The one the rule cannot finish.  EF ships no nitrous oxide of
        land-use-change origin, and once the row's name carries a qualifier it
        stops reaching the plain `Nitrous Oxide` it was already on: 10024-97-2
        finds the substance and its delayed-emission correction flow, and what
        had separated them was this row's own name, carried onto the substance
        as an altLabel.  A full build turned it from `algorithm` into
        `unmatched`, which is what the override prevents."""
        override = self.by_uuid[
            _flow_uuid("Dinitrogen monoxide, peat oxidation", "Emissions to air", "", "kg")
        ]
        self.assertEqual(override.target_uuid, "08a91e70-3ddc-11dd-94c3-0050c2490048")
        self.assertIsNone(override.conversion_factor)
        self.assertIn("multiple-flow-object-candidates", override.comment)


if __name__ == "__main__":
    unittest.main()


class SoilCarbonStockTestCase(unittest.TestCase):
    """#195's three rows: AGRIBALYSE's soil carbon stock on EF's stock flow.

    The rows carry the element's number, 7440-44-0, as ecoinvent's and BAFU's
    rows of the same name do, and #116 ruled that number groups nothing.  With
    it withdrawn the rows fell through to the tail of their name and minted a
    `Carbon` resource under elemental carbon: 2,278 datasets digging the
    element out of the ground.  The override says what ecoinvent's Increase
    entry says (#116): an occurrence of EF's stock flow.
    """

    STOCK = "26f9293f-8c18-4f3b-a334-e57a8ecda895"
    NAME = "Carbon, organic, in soil or biomass stock"
    #: uuid -> the compartment and sub-compartment the vendor writes.
    ROWS = {
        "f2590e38-fbee-53d4-b8a2-f27c391bf73f": ("Resources", ""),
        "02ec599f-c6a1-50ac-86bc-ab213d8a9f83": ("Resources", "in ground"),
        "0a68e3c1-dc59-515a-af32-c6ecb00b864a": ("Resources", "land"),
    }

    def setUp(self) -> None:
        self.by_uuid = {
            override.source_uuid: override
            for override in load_match_overrides(OVERRIDES_PATH)
        }

    def test_every_row_names_the_flow_its_vendor_fields_derive(self) -> None:
        for uuid, (compartment, sub) in self.ROWS.items():
            with self.subTest(sub=sub or "(bare)"):
                self.assertIn(uuid, self.by_uuid)
                self.assertEqual(_flow_uuid(self.NAME, compartment, sub, "kg"), uuid)

    def test_every_row_reaches_the_stock_flow_without_a_conversion(self) -> None:
        for uuid in self.ROWS:
            with self.subTest(uuid=uuid[:8]):
                override = self.by_uuid[uuid]
                self.assertEqual(override.target_uuid, self.STOCK)
                self.assertIsNone(override.conversion_factor)
                self.assertIn("#195", override.comment)

    def test_each_row_is_given_its_own_reason(self) -> None:
        """Three rows reach the stock flow by three different routes -- the
        `in ground` one because it is ecoinvent's row carried through, the bare
        one because AGRIBALYSE's own ledger puts both directions on it, the
        `land` one because its single dataset already emits the carbon beside
        it -- so a reader who opens one row must not be handed the argument for
        another.  A comment repeated across the three would read as an
        explanation and give none."""
        comments = [self.by_uuid[uuid].comment for uuid in self.ROWS]
        self.assertEqual(len(set(comments)), len(self.ROWS))
        for comment, phrase in zip(
            comments,
            ("twelve datasets", "2,307 datasets", "occurs exactly\nonce"),
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(" ".join(phrase.split()), " ".join(comment.split()))

    def test_the_land_row_states_the_compartment_the_vendor_wrote(self) -> None:
        """#351 re-files the `Resources / land` row to `in ground`; the
        override names the flow by the fields the vendor shipped, because
        that is what its identifier is derived from."""
        self.assertEqual(
            list(self.by_uuid["0a68e3c1-dc59-515a-af32-c6ecb00b864a"].source_context),
            ["Resources", "land"],
        )
