"""What a flow the merge mints is called, and where its old name went.

#102: a minted identifier used to carry the uuid of whichever source row reached
the compartment first, so a flow was renamed by a vendor adding a row, by a
curated fix letting an existing row through, and by the lists being merged in a
different order -- none of which is a statement about the substance or the
compartment, which is what the flow is.  These are the two halves: the
identifier is a function of the flow, and every identifier the change retired
still resolves.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from brightway_flows.domain.elementary_flow import (
    MINTED_FLOW_ID_BASIS_PREFIX,
    minted_elementary_flow_id,
)
from brightway_flows.domain.vocabulary import (
    DEPRECATION_REASONS,
    deprecation_reason_iri,
)
from brightway_flows.pipeline.redirects import (
    IDENTIFIER_SCHEME_CHANGE,
    RETIREMENTS_SCHEMA_VERSION,
    RetiredIdentifier,
    RetiredIdentifierError,
    build_redirects,
    load_retired_minted_flow_ids,
    retirement_redirects,
)

AIR = "https://vocab.brightway.one/flow-contexts/envi-air"
WATER = "https://vocab.brightway.one/flow-contexts/envi-wate"

#: The flow #102 was written about: water in a river, which 54 source rows
#: reach -- 53 of them ecoinvent's and one BAFU's, and BAFU's is the one that
#: named it, having got there first only because #78 converted it to cubic
#: metres.
RIVER_WATER_SUBSTANCE = "fo-464532a8f956fd39"
RIVER_WATER_CONTEXT = "https://vocab.brightway.one/flow-contexts/envi-wate-rive"


class MintedIdentifierNamesTheFlowTestCase(unittest.TestCase):
    def test_the_same_flow_gets_the_same_name(self):
        self.assertEqual(
            minted_elementary_flow_id("fo-abc", AIR),
            minted_elementary_flow_id("fo-abc", AIR),
        )

    def test_a_different_substance_is_a_different_flow(self):
        self.assertNotEqual(
            minted_elementary_flow_id("fo-abc", AIR),
            minted_elementary_flow_id("fo-xyz", AIR),
        )

    def test_a_different_compartment_is_a_different_flow(self):
        self.assertNotEqual(
            minted_elementary_flow_id("fo-abc", AIR),
            minted_elementary_flow_id("fo-abc", WATER),
        )

    def test_nothing_but_the_substance_and_the_compartment_is_read(self):
        """The point of the issue, stated as a signature.

        A row's uuid, its name, its unit and its vendor cannot reach the
        identifier because the function cannot be told them.  Written as a test
        rather than left to the reader, because the whole defect was an extra
        argument that looked harmless.
        """
        import inspect

        self.assertEqual(
            list(inspect.signature(minted_elementary_flow_id).parameters),
            ["flow_object_id", "context_iri"],
        )

    def test_river_water_is_named_after_the_water_and_the_river(self):
        """The regression anchor for the flow the issue names.

        A literal rather than a recomputation of the same call: this is the
        identifier the published list carries, and a test that recomputed it
        would go on passing through a change of scheme, which is the one thing
        it exists to catch.
        """
        self.assertEqual(
            minted_elementary_flow_id(RIVER_WATER_SUBSTANCE, RIVER_WATER_CONTEXT),
            "f213d8e4abd83830db89e3b9bf1ec0de3b5d00af",
        )

    def test_it_is_a_hex_identifier(self):
        self.assertRegex(minted_elementary_flow_id("fo-abc", AIR), r"^[0-9a-f]{40}$")

    def test_the_basis_is_namespaced(self):
        """So a flow identifier and a flow-object identifier cannot collide.

        `stable_flow_object_id` hashes a bare basis string; this one prefixes
        its own, and the two would otherwise be one hash of one pair of
        arguments under two meanings.
        """
        from hashlib import sha1

        self.assertEqual(
            minted_elementary_flow_id("fo-abc", AIR),
            sha1(f"{MINTED_FLOW_ID_BASIS_PREFIX}:fo-abc:{AIR}".encode()).hexdigest(),
        )


def _retirement(**overrides: object) -> dict[str, object]:
    row = {
        "identifier": "0" * 40,
        "replaced_by": minted_elementary_flow_id("fo-abc", AIR),
        "flow_object_id": "fo-abc",
        "context_iri": AIR,
        "name": "Ammonia",
    }
    row.update(overrides)
    return row


class LoadingTheRetirementsTestCase(unittest.TestCase):
    """A retirement that cannot be read is refused, never skipped.

    A skipped retirement is an identifier that quietly stops resolving, which is
    the failure the file exists to prevent -- so every one of these is a raise.
    """

    def _write(self, payload: object) -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / "retired-minted-flow-ids.json"
        path.write_text(json.dumps(payload))
        return path

    def test_a_well_formed_file_loads(self):
        path = self._write({
            "schema_version": RETIREMENTS_SCHEMA_VERSION,
            "retirements": [_retirement()],
        })
        (record,) = load_retired_minted_flow_ids(path)
        self.assertEqual(record.identifier, "0" * 40)
        self.assertEqual(record.flow_object_id, "fo-abc")

    def test_a_missing_file_retires_nothing(self):
        self.assertEqual(
            load_retired_minted_flow_ids(Path("/nonexistent/retirements.json")), ()
        )

    def test_another_schema_version_is_refused(self):
        path = self._write({"schema_version": 99, "retirements": []})
        with self.assertRaises(RetiredIdentifierError):
            load_retired_minted_flow_ids(path)

    def test_a_replacement_that_is_not_what_the_flow_mints_is_refused(self):
        """The check that keeps the file and the naming rule from drifting apart."""
        path = self._write({
            "schema_version": RETIREMENTS_SCHEMA_VERSION,
            "retirements": [_retirement(replaced_by="f" * 40)],
        })
        with self.assertRaises(RetiredIdentifierError) as caught:
            load_retired_minted_flow_ids(path)
        self.assertIn("is minted as", str(caught.exception))

    def test_a_retirement_that_names_no_flow_is_refused(self):
        path = self._write({
            "schema_version": RETIREMENTS_SCHEMA_VERSION,
            "retirements": [_retirement(flow_object_id="")],
        })
        with self.assertRaises(RetiredIdentifierError):
            load_retired_minted_flow_ids(path)

    def test_retiring_one_identifier_twice_is_refused(self):
        path = self._write({
            "schema_version": RETIREMENTS_SCHEMA_VERSION,
            "retirements": [_retirement(), _retirement()],
        })
        with self.assertRaises(RetiredIdentifierError):
            load_retired_minted_flow_ids(path)

    def test_retiring_an_identifier_onto_itself_is_refused(self):
        replaced_by = minted_elementary_flow_id("fo-abc", AIR)
        path = self._write({
            "schema_version": RETIREMENTS_SCHEMA_VERSION,
            "retirements": [_retirement(identifier=replaced_by)],
        })
        with self.assertRaises(RetiredIdentifierError):
            load_retired_minted_flow_ids(path)


class TheBundledRetirementsTestCase(unittest.TestCase):
    def test_every_recorded_retirement_still_points_where_it_says(self):
        """The shipped file, read by the same rule the merge names flows with.

        Nothing else compares the two: the file was generated from a build made
        before the rename, and if the naming rule moved again every entry in it
        would point at a flow that is no longer there.
        """
        records = load_retired_minted_flow_ids()
        self.assertGreater(len(records), 2000)
        for record in records:
            with self.subTest(record.identifier):
                self.assertEqual(
                    record.replaced_by,
                    minted_elementary_flow_id(
                        record.flow_object_id, record.context_iri
                    ),
                )

    def test_the_river_water_flow_the_issue_names_is_in_it(self):
        by_identifier = {
            record.identifier: record
            for record in load_retired_minted_flow_ids()
        }
        record = by_identifier["656bc4922facb93bd3c2a62794de1cd9c0cdde0b"]
        self.assertEqual(record.name, "Water")
        self.assertEqual(record.context_iri, RIVER_WATER_CONTEXT)
        self.assertEqual(
            record.replaced_by, "f213d8e4abd83830db89e3b9bf1ec0de3b5d00af"
        )


class PublishingTheRetirementsTestCase(unittest.TestCase):
    RECORD = RetiredIdentifier(
        identifier="0" * 40,
        replaced_by=minted_elementary_flow_id("fo-abc", AIR),
        flow_object_id="fo-abc",
        context_iri=AIR,
        name="Ammonia",
    )

    def test_a_retirement_this_build_can_resolve_is_published(self):
        records, counts = retirement_redirects(
            {self.RECORD.replaced_by}, (self.RECORD,)
        )
        self.assertEqual(counts["redirects_published"], 1)
        (redirect,) = records
        self.assertEqual(redirect.identifier, "0" * 40)
        self.assertEqual(redirect.replaced_by_identifier, self.RECORD.replaced_by)
        self.assertEqual(
            redirect.deprecation_reason["@id"],
            deprecation_reason_iri(IDENTIFIER_SCHEME_CHANGE),
        )

    def test_a_retirement_this_build_does_not_mint_is_left_out(self):
        """Not a defect. A build merging fewer lists mints fewer flows, and a
        redirect into a flow that is not there is the miss #39 closed."""
        records, counts = retirement_redirects(set(), (self.RECORD,))
        self.assertEqual(records, [])
        self.assertEqual(counts["not_in_this_build"], 1)
        self.assertEqual(counts["redirects_published"], 0)

    def test_a_retired_identifier_that_is_live_again_is_refused(self):
        records, counts = retirement_redirects(
            {self.RECORD.replaced_by, self.RECORD.identifier}, (self.RECORD,)
        )
        self.assertEqual(records, [])
        self.assertEqual(counts["still_published"], 1)

    def test_the_reason_is_a_declared_one(self):
        self.assertIn(IDENTIFIER_SCHEME_CHANGE, DEPRECATION_REASONS)

    def test_retirements_are_published_beside_the_deprecations(self):
        """One document, three kinds, and the deprecations still first.

        `build_redirects` reads two recorded files by default -- the retirements
        and the withdrawals -- so a caller that wants only the deprecations
        passes `()` for both, which is what every existing test of this function
        relies on staying true.
        """
        flows = [
            {"identifier": self.RECORD.replaced_by},
            {"identifier": "dead", "owl:deprecated": True,
             "is_replaced_by_uuid": self.RECORD.replaced_by},
        ]
        records, counts = build_redirects(
            flows, None, (self.RECORD,), withdrawals=()
        )
        self.assertEqual([r.identifier for r in records], ["dead", "0" * 40])
        self.assertEqual(counts["redirects"], 2)

        without, _counts = build_redirects(flows, None, (), withdrawals=())
        self.assertEqual([r.identifier for r in without], ["dead"])
