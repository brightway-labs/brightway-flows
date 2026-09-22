"""A vendor can ship a flow where the fetch does not look, and finding it is not
the same as accepting it.

ecoinvent publishes one `ElementaryExchanges.xml` per system model -- `cutoff`,
`apos`, `consequential` and `EN15804` -- and the adapter reads `cutoff`. The 3.8
APOS and consequential releases each carry the same three exchanges cutoff does
not: `venting of argon, crude, liquid`, `venting of nitrogen, liquid` and
`residual wood, dry`, all in `social / unspecified` (#25, #100).

Those rows cannot arrive as `manual_fixes`: a fix names a field on a row the
fetch produced, and these rows do not exist until something puts them there. So
they are a second kind of curated input, and these are the properties that make
it safe to have one -- that it cannot duplicate a uuid, that it cannot assert a
flow without saying why, and that what it adds is indistinguishable from what
the fetch would have produced had it looked in the right file.

And that a record can be *refused*. All three of those ecoinvent rows are, and
#115 is why: each duplicates an intermediate exchange -- a product -- into the
elementary list, under a compartment ecoinvent uses nowhere else, referenced by
no dataset in the release, and gone from 3.9.1 onwards. The tests below hold the
two halves apart: what an exclusion has to carry, and that it is enforced rather
than left to depend on which of the vendor's files the adapter opens.
"""

import tempfile
import unittest
from pathlib import Path

import orjson
from structlog.testing import capture_logs

from brightway_flows.additional_flows import (
    EXCLUDED_REQUIRED_FIELDS,
    REQUIRED_FIELDS,
    apply_additional_flows,
    load_excluded_source_flows,
)
from brightway_flows.context_mapping import context_iri_by_source_context
from brightway_flows.sources import (
    PACKAGE_DATA_DIR,
    excluded_source_flows,
    known_source_lists,
    registered_source_list,
)

#: The three ecoinvent 3.8 exchanges cutoff does not ship, by uuid -- and, since
#: #115, does not map either.  The third element is the intermediate exchange
#: each one duplicates, which is the evidence that they are products.
APOS_ONLY = {
    "22cbd60c-8017-49c4-ae6f-7f0c1c6ebf0b": (
        "venting of argon, crude, liquid", "kg",
        "ccde15d5-179a-4bf2-a323-17fb1e056261",
    ),
    "2d8d9c78-e7da-4b71-8c5e-8d1de08696c0": (
        "venting of nitrogen, liquid", "kg",
        "1adfc43f-187a-4153-996c-aced5301536a",
    ),
    "c7075d71-2cfb-42ac-bd96-4661486e1ff7": (
        "residual wood, dry", "m3",
        "019600be-f3ce-4399-9e31-19cdc087ed5f",
    ),
}

#: The consensus identifier each excluded row was published under before #115,
#: read off the 2026-08-19 artifact.  Recorded because nothing in a build that
#: no longer mints these flows can work them out, and they are what the
#: withdrawal records in `redirects` are built from.
WITHDREW = {
    "22cbd60c-8017-49c4-ae6f-7f0c1c6ebf0b": "3b5f85d9601a67605e692bb34b268dd3e2b6e41c",
    "2d8d9c78-e7da-4b71-8c5e-8d1de08696c0": "e3378e2056920fcd33aaa3650e0c8ae90e47468d",
    "c7075d71-2cfb-42ac-bd96-4661486e1ff7": "a2b1125471a3d31a3094deb35114e6e62d809d73",
}

#: Every ecoinvent list with a manifest, and how many elementary exchanges each
#: of its four system models ships.  Pinned because it is the whole evidence for
#: the claim that reading `cutoff` and adding these files loses nothing: measured
#: release by release on 2026-08-15 by `tools/compare_ecoinvent_system_models.py`
#: (#100).  A version whose releases start to disagree changes these numbers, and
#: a version added without being compared has none.
EXCHANGE_COUNTS = {
    "ecoinvent-3.8": {
        "cutoff": 4421, "apos": 4424, "consequential": 4424, "EN15804": 4421,
    },
    "ecoinvent-3.9.1": {
        "cutoff": 4718, "apos": 4718, "consequential": 4718, "EN15804": 4718,
    },
    "ecoinvent-3.10.1": {
        "cutoff": 4362, "apos": 4362, "consequential": 4362, "EN15804": 4362,
    },
    "ecoinvent-3.11": {
        "cutoff": 9795, "apos": 9795, "consequential": 9795, "EN15804": 9795,
    },
    "ecoinvent-3.12": {
        "cutoff": 9850, "apos": 9850, "consequential": 9850, "EN15804": 9850,
    },
}

SOCIAL_IRI = "https://vocab.brightway.one/flow-contexts/soci"


def _record(uuid="u1", **overrides):
    record = {
        "uuid": uuid,
        "name": "venting of something",
        "context": ["social", "unspecified"],
        "unit": "kg",
        "comment": "Ships in APOS, absent from cutoff.",
    }
    record.update(overrides)
    return record


def _excluded(uuid="u1", **overrides):
    record = {
        "uuid": uuid,
        "name": "venting of something",
        "context": ["social", "unspecified"],
        "unit": "kg",
        "reason": "A product, not an elementary flow.",
        "comment": "Checked against every cached release.",
    }
    record.update(overrides)
    return record


def _write(tmp, records, key="flows", also=None):
    path = Path(tmp) / "additional.json"
    payload = {"schema_version": 1, key: records}
    if also:
        payload.update(also)
    path.write_bytes(orjson.dumps(payload))
    return path


class AddingAFlowTestCase(unittest.TestCase):
    def test_a_record_becomes_a_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = []
            apply_additional_flows(
                rows, _write(tmp, [_record()]), source="ecoinvent-3.8"
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["uuid"], "u1")
        self.assertEqual(rows[0]["context"], ["social", "unspecified"])

    def test_the_source_is_stamped_not_declared(self):
        """Context rules are keyed by it, so a wrong one resolves to no context."""
        with tempfile.TemporaryDirectory() as tmp:
            rows = []
            apply_additional_flows(
                rows,
                _write(tmp, [_record(source="wrong-list")]),
                source="ecoinvent-3.8",
            )
        self.assertEqual(rows[0]["source"], "ecoinvent-3.8")

    def test_the_unit_iri_is_derived_not_copied(self):
        """A hand-written IRI is a second place for `units.json` to go stale."""
        with tempfile.TemporaryDirectory() as tmp:
            rows = []
            apply_additional_flows(
                rows,
                _write(tmp, [_record(unit="kg"), _record(uuid="u2", unit="m3")]),
                source="ecoinvent-3.8",
            )
        self.assertEqual(rows[0]["unit_iri"], "https://vocab.brightway.one/units/unit/KiloGM")
        self.assertEqual(rows[1]["unit_iri"], "https://vocab.brightway.one/units/unit/M3")

    def test_the_comment_does_not_reach_the_row(self):
        """Provenance for the curator, not a field a consumer reads."""
        with tempfile.TemporaryDirectory() as tmp:
            rows = []
            apply_additional_flows(
                rows, _write(tmp, [_record()]), source="ecoinvent-3.8"
            )
        self.assertNotIn("comment", rows[0])

    def test_identifier_defaults_to_the_uuid(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = []
            apply_additional_flows(
                rows, _write(tmp, [_record()]), source="ecoinvent-3.8"
            )
        self.assertEqual(rows[0]["identifier"], "u1")

    def test_a_missing_file_is_not_an_error(self):
        """Having no additional flows is the normal state of every list."""
        rows = [{"uuid": "existing"}]
        apply_additional_flows(rows, Path("/no/such/file.json"), source="x")
        self.assertEqual(len(rows), 1)


class NotDuplicatingAUuidTestCase(unittest.TestCase):
    """The property that lets the file outlive the gap it describes.

    If the adapter ever learns to read APOS, the fetch produces these rows and
    the file becomes redundant. Redundant has to mean *inert*, not "two rows
    under one uuid" -- the merge keys on uuid, so a duplicate is worse than
    the missing flow the file exists to supply.
    """

    def test_a_record_the_fetch_already_carries_is_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{"uuid": "u1", "name": "from the fetch", "unit": "kg"}]
            apply_additional_flows(
                rows, _write(tmp, [_record()]), source="ecoinvent-3.8"
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "from the fetch")

    def test_dropping_one_is_reported(self):
        """A curator's signal that the file has been overtaken upstream."""
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{"uuid": "u1"}]
            with capture_logs() as logs:
                apply_additional_flows(
                    rows, _write(tmp, [_record()]), source="ecoinvent-3.8"
                )
        events = [log for log in logs if log["event"] == "additional_flow_already_fetched"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["uuid"], "u1")

    def test_two_records_sharing_a_uuid_add_one_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = []
            apply_additional_flows(
                rows,
                _write(tmp, [_record(), _record(name="a second spelling")]),
                source="ecoinvent-3.8",
            )
        self.assertEqual(len(rows), 1)


class ExcludingAFlowTestCase(unittest.TestCase):
    """A row the vendor ships and this list refuses.

    The record stays in the file rather than being deleted, for the reason a
    version with nothing to add still gets a file: a row refused on purpose and
    a row nobody looked at must not read alike (#115).
    """

    def test_an_excluded_record_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = load_excluded_source_flows(
                _write(tmp, [_excluded()], key="excluded"), source="ecoinvent-3.8"
            )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].uuid, "u1")
        self.assertEqual(records[0].context, ("social", "unspecified"))
        self.assertEqual(records[0].source, "ecoinvent-3.8")

    def test_a_file_with_no_excluded_key_excludes_nothing(self):
        """The key was added after the files were; its absence is not an error."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                load_excluded_source_flows(
                    _write(tmp, [_record()]), source="ecoinvent-3.8"
                ),
                (),
            )

    def test_a_missing_file_excludes_nothing(self):
        self.assertEqual(
            load_excluded_source_flows(Path("/no/such/file.json"), source="x"), ()
        )

    def test_a_fetched_row_that_is_excluded_is_removed(self):
        """The exclusion is enforced, not inferred from the adapter's choice.

        Today no fetch produces these rows, which is why they needed a curated
        record at all. The day one does -- the adapter learning to read APOS is
        the foreseeable way -- the decision must not silently reverse itself.
        """
        with tempfile.TemporaryDirectory() as tmp:
            rows = [
                {"uuid": "u1", "name": "from the fetch", "unit": "kg"},
                {"uuid": "keep-me", "name": "an ordinary flow", "unit": "kg"},
            ]
            apply_additional_flows(
                rows,
                _write(tmp, [], also={"excluded": [_excluded()]}),
                source="ecoinvent-3.8",
            )
        self.assertEqual([row["uuid"] for row in rows], ["keep-me"])

    def test_removing_a_fetched_row_is_reported_as_a_warning(self):
        """The exclusion still holds, but its stated evidence has gone stale."""
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{"uuid": "u1", "name": "from the fetch", "unit": "kg"}]
            with capture_logs() as logs:
                apply_additional_flows(
                    rows,
                    _write(tmp, [], also={"excluded": [_excluded()]}),
                    source="ecoinvent-3.8",
                )
        events = [
            log for log in logs if log["event"] == "excluded_flow_removed_from_fetch"
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["uuid"], "u1")
        self.assertEqual(events[0]["log_level"], "warning")

    def test_a_list_whose_fetch_carries_the_row_reports_it_as_ordinary(self):
        """Stepwise ships everything it has in the file the adapter reads.

        There the fetch producing a refused row is the refusal being carried out
        rather than news, and a warning on every build would cry wolf. The file
        says which case it is; the removal itself is the same either way.
        """
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{"uuid": "u1", "name": "from the fetch", "unit": "kg"}]
            with capture_logs() as logs:
                apply_additional_flows(
                    rows,
                    _write(tmp, [], also={
                        "excluded": [_excluded()],
                        "excluded_rows_are_in_the_fetch": True,
                    }),
                    source="stepwise-2006-1.09",
                )
        events = [
            log for log in logs if log["event"] == "excluded_flow_removed_from_fetch"
        ]
        self.assertEqual(rows, [])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["log_level"], "info")

    def test_excluding_a_row_the_fetch_does_not_carry_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{"uuid": "other", "name": "an ordinary flow", "unit": "kg"}]
            apply_additional_flows(
                rows,
                _write(tmp, [], also={"excluded": [_excluded()]}),
                source="ecoinvent-3.8",
            )
        self.assertEqual([row["uuid"] for row in rows], ["other"])


class ExclusionAuthoringMistakesFailTestCase(unittest.TestCase):
    """An exclusion that applies to nothing is worse than no exclusion.

    It reads as a decision and behaves as an oversight, which is the exact
    ambiguity the record exists to remove.
    """

    def test_a_record_missing_a_required_field_raises(self):
        for field in EXCLUDED_REQUIRED_FIELDS:
            with self.subTest(field=field):
                record = _excluded()
                del record[field]
                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(ValueError) as caught:
                        load_excluded_source_flows(
                            _write(tmp, [record], key="excluded"),
                            source="ecoinvent-3.8",
                        )
                self.assertIn(field, str(caught.exception))

    def test_both_prose_fields_are_required_and_are_not_the_same_field(self):
        """`reason` is published; `comment` is for the next curator."""
        self.assertIn("reason", EXCLUDED_REQUIRED_FIELDS)
        self.assertIn("comment", EXCLUDED_REQUIRED_FIELDS)

    def test_excluding_one_uuid_twice_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as caught:
                load_excluded_source_flows(
                    _write(tmp, [_excluded(), _excluded()], key="excluded"),
                    source="ecoinvent-3.8",
                )
        self.assertIn("second time", str(caught.exception))

    def test_an_excluded_key_that_is_not_a_list_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "additional.json"
            path.write_bytes(orjson.dumps({"flows": [], "excluded": {"u1": True}}))
            with self.assertRaises(ValueError):
                load_excluded_source_flows(path, source="ecoinvent-3.8")

    def test_adding_and_excluding_one_uuid_raises(self):
        """In one list or the other is a decision; in both it is none."""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as caught:
                apply_additional_flows(
                    [],
                    _write(tmp, [_record()], also={"excluded": [_excluded()]}),
                    source="ecoinvent-3.8",
                )
        self.assertIn("u1", str(caught.exception))


class AuthoringMistakesFailTestCase(unittest.TestCase):
    """Every one of these would otherwise add a row that matches nothing."""

    def test_a_record_missing_a_required_field_raises(self):
        for field in REQUIRED_FIELDS:
            with self.subTest(field=field):
                record = _record()
                del record[field]
                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(ValueError) as caught:
                        apply_additional_flows(
                            [], _write(tmp, [record]), source="ecoinvent-3.8"
                        )
                self.assertIn(field, str(caught.exception))

    def test_an_empty_required_field_raises(self):
        """`""` and `[]` are absence spelled differently."""
        for field, empty in (("name", ""), ("context", []), ("comment", "")):
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(ValueError):
                        apply_additional_flows(
                            [],
                            _write(tmp, [_record(**{field: empty})]),
                            source="ecoinvent-3.8",
                        )

    def test_an_unresolvable_unit_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as caught:
                apply_additional_flows(
                    [],
                    _write(tmp, [_record(unit="furlongs per fortnight")]),
                    source="ecoinvent-3.8",
                )
        self.assertIn("furlongs per fortnight", str(caught.exception))

    def test_a_payload_without_a_flows_list_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                apply_additional_flows(
                    [], _write(tmp, [_record()], key="rows"), source="ecoinvent-3.8"
                )


class EveryEcoinventIsComparedTestCase(unittest.TestCase):
    """Which system models each registered ecoinvent was checked against.

    Before #100 only 3.8 declared this input, and the absence of a file on the
    other four meant two different things at once: that their releases had been
    compared and agreed, and that nobody had looked. The second was true of
    `consequential` and `EN15804`, which had never been compared on any version.
    Every list now carries a file, and a file with an empty `flows` list is the
    finding rather than an oversight.
    """

    def _payload(self, key):
        source = registered_source_list(key)
        return orjson.loads(source.additional_flows_path.read_bytes())

    def test_every_registered_ecoinvent_declares_the_comparison(self):
        declared = {
            key
            for key, source in known_source_lists().items()
            if source.additional_flows_path is not None
        }
        self.assertEqual(
            {key for key in declared if key.startswith("ecoinvent-")},
            set(EXCHANGE_COUNTS),
        )
        # The lists outside ecoinvent that carry a file carry no comparison
        # because there is nothing to compare: each is a single export, so its
        # `flows` list is empty by construction and the file exists for its
        # `excluded` half -- Stepwise's nine rows (#167) and AGRIBALYSE's
        # refused waste compartment (#189).
        self.assertEqual(
            declared - set(EXCHANGE_COUNTS),
            {"stepwise-2006-1.09", "agribalyse-3.2"},
        )

    def test_each_manifest_names_its_own_file_and_it_is_on_disk(self):
        for key in EXCHANGE_COUNTS:
            with self.subTest(key=key):
                source = registered_source_list(key)
                self.assertEqual(
                    source.additional_flows_path,
                    PACKAGE_DATA_DIR / f"{key}-additional-flows.json",
                )
                self.assertEqual(source.missing_curated_inputs(), [])

    def test_each_file_records_what_was_compared_and_what_it_held(self):
        """The evidence, not the conclusion.

        Counts per release are what a later version's comparison is checked
        against, and what shows that all four releases were read rather than
        two.
        """
        for key, counts in EXCHANGE_COUNTS.items():
            with self.subTest(key=key):
                comparison = self._payload(key)["comparison"]
                self.assertEqual(comparison["reference_system_model"], "cutoff")
                self.assertEqual(
                    comparison["system_models"],
                    ["cutoff", "apos", "consequential", "EN15804"],
                )
                self.assertEqual(comparison["exchange_counts"], counts)
                self.assertEqual(comparison["flows_only_in_cutoff"], 0)
                self.assertEqual(comparison["shared_records_differing"], 0)

    def test_three_eight_is_the_only_version_whose_releases_disagree(self):
        """Not an assumption any more: 3.9.1 onwards were measured too.

        ecoinvent dropped the `social` compartment after 3.8 and has shipped
        the same exchanges in all four releases ever since. The comparison
        block, not the `flows` list, is what states this now: since #115 all
        three of 3.8's divergent records are excluded rather than added, so
        `flows` is empty on every version and would say nothing.
        """
        divergent = {
            key: self._payload(key)["comparison"]["flows_only_in_another_system_model"]
            for key in EXCHANGE_COUNTS
            if self._payload(key)["comparison"]["flows_only_in_another_system_model"]
        }
        self.assertEqual(divergent, {"ecoinvent-3.8": 3})

    def test_no_version_adds_a_flow(self):
        """3.8's three were the only ones, and they are refused now (#115)."""
        for key in EXCHANGE_COUNTS:
            with self.subTest(key=key):
                self.assertEqual(self._payload(key)["flows"], [])

    def test_a_version_with_nothing_to_add_loads_unchanged(self):
        """An empty file has to be inert, or four lists pay for one's evidence."""
        source = registered_source_list("ecoinvent-3.12")
        if not source.flows_path.exists():
            self.skipTest("ecoinvent 3.12 flows have not been fetched")
        fetched = orjson.loads(source.flows_path.read_bytes())
        self.assertEqual(len(source.load_flows()), len(fetched))


class EcoinventThreeEightTestCase(unittest.TestCase):
    """The case the mechanism exists for, checked against the real manifest."""

    def setUp(self):
        self.source = registered_source_list("ecoinvent-3.8")
        self.payload = orjson.loads(self.source.additional_flows_path.read_bytes())

    def test_the_file_refuses_exactly_the_three_flows_cutoff_lacks(self):
        by_uuid = {record["uuid"]: record for record in self.payload["excluded"]}
        self.assertEqual(set(by_uuid), set(APOS_ONLY))
        for uuid, (name, unit, _intermediate) in APOS_ONLY.items():
            self.assertEqual(by_uuid[uuid]["name"], name)
            self.assertEqual(by_uuid[uuid]["unit"], unit)
            self.assertEqual(by_uuid[uuid]["context"], ["social", "unspecified"])

    def test_each_reason_names_the_product_the_row_duplicates(self):
        """The evidence a reader can check, not an assertion they must trust.

        Each uuid here appears in exactly one file in any cached release --
        3.8 apos's elementary list -- while the intermediate exchange it
        duplicates carries one uuid from 3.8 through 3.12. That asymmetry is
        the whole argument that these are products, so the reason has to carry
        the identifier that makes it checkable.
        """
        by_uuid = {record["uuid"]: record for record in self.payload["excluded"]}
        for uuid, (_name, _unit, intermediate) in APOS_ONLY.items():
            with self.subTest(uuid=uuid):
                self.assertIn(intermediate, by_uuid[uuid]["reason"])
                self.assertIn(
                    intermediate, by_uuid[uuid]["evidence"]["intermediate_exchange_uuid"]
                )

    def test_each_exclusion_records_the_identifier_it_withdrew(self):
        """No build that stopped minting the flow can work this out again."""
        by_uuid = {record["uuid"]: record for record in self.payload["excluded"]}
        for uuid, identifier in WITHDREW.items():
            with self.subTest(uuid=uuid):
                self.assertEqual(by_uuid[uuid]["withdrew_identifier"], identifier)

    def test_the_comment_names_both_releases_that_ship_them(self):
        """APOS was the only one anyone had looked at, and it is not alone.

        A description crediting APOS alone would say the flows vanish if
        ecoinvent stops publishing that release, which is not what the evidence
        shows.
        """
        self.assertIn("apos and consequential", self.payload["description"])

    def test_the_social_compartment_has_no_context_rule(self):
        """Nothing carries the compartment now, so a rule for it would be dead.

        It had one until #115: `social / unspecified` was mapped to `soci` so
        the three added rows would not fail into the report with no context.
        With the rows refused there is nothing to place, and a mapping for a
        compartment no flow has claims a decision nobody makes.
        """
        rules = context_iri_by_source_context("ecoinvent-3.8")
        self.assertIsNone(rules.get(("social", "unspecified")))

    def test_the_list_loads_the_cutoff_count(self):
        """4,421 in the cutoff export the adapter reads, and none added."""
        if not self.source.flows_path.exists():
            self.skipTest("ecoinvent 3.8 flows have not been fetched")
        flows = self.source.load_flows()
        self.assertEqual(
            [flow.uuid for flow in flows if flow.uuid in APOS_ONLY], []
        )
        fetched = orjson.loads(self.source.flows_path.read_bytes())
        self.assertEqual(len(flows), len(fetched))


class TheRegistryKnowsWhatIsRefusedTestCase(unittest.TestCase):
    """What the export reads: exclusions keyed by concept scheme."""

    def test_what_is_refused_is_keyed_by_the_scheme_slug(self):
        refused = excluded_source_flows()
        self.assertEqual(
            set(refused),
            {"ecoinvent-3.8", "stepwise-2006-1.09", "agribalyse-3.2"},
        )
        self.assertEqual(
            {record.uuid for record in refused["ecoinvent-3.8"]}, set(APOS_ONLY)
        )
        # Stepwise's nine are the six `Chlordane, gamma-` rows of #167 and the
        # three injury counts of #173; what they are and that each names a row
        # the fetch really produces is pinned in
        # tests/test_stepwise_excluded_flows.py.
        self.assertEqual(len(refused["stepwise-2006-1.09"]), 9)

    def test_every_record_carries_a_reason_a_consumer_can_read(self):
        """It is published verbatim, and it is the answer to "where did it go?"."""
        for record in excluded_source_flows()["ecoinvent-3.8"]:
            with self.subTest(uuid=record.uuid):
                self.assertIn("not an elementary flow", record.reason)


if __name__ == "__main__":
    unittest.main()
