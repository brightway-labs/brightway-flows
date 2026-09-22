"""#241: a curated context ruling belongs to one list, and reaches only that one.

Decisions were stored and looked up under a bare ``source_uuid``.  Source lists
do not agree to keep out of each other's UUID space, so two lists whose UUIDs
collided applied each other's rulings -- and a decision that resolves looks
exactly like one that was meant for the row, so nothing showed it.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import orjson

from brightway_flows.merge.prepared_context_decisions import (
    DECISIONS_FILEPATH,
    DECISIONS_SCHEMA_VERSION,
    load_prepared_context_decision_index,
    save_prepared_context_decision,
)
from brightway_flows.sources import SourceList

UUID = "f06815cb-65ca-4446-8ea9-329ae0252c29"
TARGET = "23ec75d2-71c5-4d61-ab7c-cdc3a153c662"


def _list(name: str, version: str) -> SourceList:
    return SourceList(
        list_name=name,
        list_version=version,
        flows_path=Path("/nonexistent/flows.json"),
    )


def _payload(*rows: dict) -> dict:
    return {"schema_version": DECISIONS_SCHEMA_VERSION, "decisions": list(rows)}


def _row(list_name: str, *, uuid: str = UUID, decision: str = "mapped", **extra) -> dict:
    return {
        "list_name": list_name,
        "list_version": "",
        "source_uuid": uuid,
        "prepared_target_elementary_flow_id": TARGET,
        "decision": decision,
        **extra,
    }


class DecisionsAreScopedToOneListTestCase(unittest.TestCase):
    def _index_for(self, payload: dict, source: SourceList):
        with mock.patch(
            "brightway_flows.merge.prepared_context_decisions._read_payload",
            return_value=payload,
        ):
            return load_prepared_context_decision_index(source)

    def test_a_list_sees_its_own_decision(self):
        index = self._index_for(_payload(_row("ecoinvent")), _list("ecoinvent", "3.12"))
        self.assertIn((UUID, TARGET), index)

    def test_a_colliding_uuid_in_another_list_is_not_given_the_decision(self):
        """The defect. Same UUID, different list: BAFU must see nothing."""
        index = self._index_for(_payload(_row("ecoinvent")), _list("bafu", "2025"))
        self.assertEqual(index, {})

    def test_a_decision_applies_across_releases_of_its_own_list(self):
        """`list_name` selects, not `(list_name, list_version)`.

        Within one list a UUID names the same flow across releases -- this one
        is in ecoinvent 3.8 and 3.12 with identical name and context -- so
        version-scoping would make a curator re-decide the same row every
        release without closing the cross-list hole.
        """
        payload = _payload(_row("ecoinvent"))
        for version in ("3.8", "3.11", "3.12"):
            with self.subTest(version=version):
                index = self._index_for(payload, _list("ecoinvent", version))
                self.assertIn((UUID, TARGET), index)

    def test_an_unstamped_row_reaches_no_list(self):
        """A decision naming no list used to belong to all of them."""
        row = _row("ecoinvent")
        row["list_name"] = ""
        for source in (_list("ecoinvent", "3.12"), _list("bafu", "2025")):
            with self.subTest(source=source.key):
                self.assertEqual(self._index_for(_payload(row), source), {})

    def test_rows_with_an_invalid_decision_are_still_dropped(self):
        index = self._index_for(
            _payload(_row("ecoinvent", decision="maybe")), _list("ecoinvent", "3.12")
        )
        self.assertEqual(index, {})

    def test_two_lists_keep_separate_decisions_for_the_same_uuid(self):
        payload = _payload(
            _row("ecoinvent", decision="mapped"),
            _row("bafu", decision="reject"),
        )
        ecoinvent = self._index_for(payload, _list("ecoinvent", "3.12"))
        bafu = self._index_for(payload, _list("bafu", "2025"))
        self.assertEqual(ecoinvent[(UUID, TARGET)].decision, "mapped")
        self.assertEqual(bafu[(UUID, TARGET)].decision, "reject")


class SaveStampsTheListTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        self.path = self.tmp / "prepared-context-decisions.json"
        patcher = mock.patch(
            "brightway_flows.merge.prepared_context_decisions.DECISIONS_FILEPATH",
            self.path,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _saved(self) -> dict:
        return orjson.loads(self.path.read_bytes())

    def test_a_saved_decision_names_its_list(self):
        save_prepared_context_decision(
            source=_list("bafu", "2025"),
            source_uuid=UUID,
            prepared_target_elementary_flow_id=TARGET,
            decision="mapped",
        )
        row = self._saved()["decisions"][0]
        self.assertEqual(row["list_name"], "bafu")
        self.assertEqual(row["list_version"], "2025")

    def test_the_same_uuid_in_two_lists_is_two_rows_not_a_replacement(self):
        for source in (_list("ecoinvent", "3.12"), _list("bafu", "2025")):
            save_prepared_context_decision(
                source=source,
                source_uuid=UUID,
                prepared_target_elementary_flow_id=TARGET,
                decision="mapped",
            )
        rows = self._saved()["decisions"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            sorted(row["list_name"] for row in rows), ["bafu", "ecoinvent"]
        )

    def test_re_deciding_within_one_list_replaces(self):
        source = _list("ecoinvent", "3.12")
        for decision in ("mapped", "reject"):
            save_prepared_context_decision(
                source=source,
                source_uuid=UUID,
                prepared_target_elementary_flow_id=TARGET,
                decision=decision,
            )
        rows = self._saved()["decisions"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decision"], "reject")

    def test_saving_writes_the_current_schema_version(self):
        save_prepared_context_decision(
            source=_list("ecoinvent", "3.12"),
            source_uuid=UUID,
            prepared_target_elementary_flow_id=TARGET,
            decision="mapped",
        )
        self.assertEqual(self._saved()["schema_version"], DECISIONS_SCHEMA_VERSION)


class BundledDecisionsFileTestCase(unittest.TestCase):
    """The checked-in file is migrated, not half-migrated."""

    def test_every_bundled_decision_names_a_list(self):
        payload = orjson.loads(DECISIONS_FILEPATH.read_bytes())
        self.assertEqual(payload["schema_version"], DECISIONS_SCHEMA_VERSION)
        for row in payload["decisions"]:
            with self.subTest(source_uuid=row.get("source_uuid")):
                self.assertTrue(str(row.get("list_name") or "").strip())

    def test_the_migrated_decisions_still_reach_ecoinvent(self):
        index = load_prepared_context_decision_index(_list("ecoinvent", "3.12"))
        payload = orjson.loads(DECISIONS_FILEPATH.read_bytes())
        self.assertEqual(len(index), len(payload["decisions"]))


if __name__ == "__main__":
    unittest.main()
