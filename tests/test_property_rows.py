"""The `flow_property_statements` table: what each merged list says a unit of a flow is.

One row per statement a source row carried onto a consensus flow, with
whether the mapping converted by it.  Read off the flows' `source_refs`, so a
curated match, an algorithmic match and a flow the merge created are one walk;
written per list so a re-merge replaces; read back by substance so the spread
spans every list merged so far (#407, phase C).
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.property_statements import StatementOrigin, vendor_statement
from brightway_flows.domain.quantities import (
    CALORIFIC_VALUE,
    GROSS_CALORIFIC_VALUE,
    NET_CALORIFIC_VALUE,
    quantity,
)
from brightway_flows.domain.units import CONVERSION_BASIS_KEY, CONVERSION_QUANTITY_KEY
from brightway_flows.domain.vocabulary import QUDT_CONVERSION_MULTIPLIER_CURIE
from brightway_flows.merge.property_rows import (
    COLUMNS,
    TABLE,
    PropertyStatementRow,
    create_table,
    read_rows,
    rows_for_merged_list,
    write_rows,
)
from brightway_flows.merge.store import create_merge_tables


def _statement(slug, value, origin):
    return vendor_statement(
        quantity=slug, value=value, unit="MJ", per_unit="kg", stated_by=origin,
        primary_source=["the export"], derived_from="export.csv",
        generated_by="fetch_test", attributed_to="stepwise-2006-1.09", comment="stated",
    )


class RowsForMergedListTestCase(unittest.TestCase):
    def setUp(self):
        self.coal = Flow(uuid="coal", name="Coal, hard", unit="kg", property_statements=[
            _statement(GROSS_CALORIFIC_VALUE, 19.1, StatementOrigin.VENDOR_FLOW),
            _statement(CALORIFIC_VALUE, 19.1, StatementOrigin.VENDOR_METHOD),
        ])
        self.water = Flow(uuid="water", name="Water", unit="kg")
        self.hard_coal = SimpleNamespace(
            elementary_flow_id="ef-hard-coal", flow_object_id="fo-hard-coal", unit="MJ",
            source_refs=[
                {
                    "list_name": "stepwise", "list_version": "2006-1.09",
                    "source_flow_uuid": "coal", "source_flow_name": "Coal, hard",
                    "source_metadata": {
                        "unit": "kg",
                        CONVERSION_BASIS_KEY: "flow-property",
                        CONVERSION_QUANTITY_KEY: quantity(CALORIFIC_VALUE).iri,
                        QUDT_CONVERSION_MULTIPLIER_CURIE: 19.1,
                    },
                },
                {"list_name": "ecoinvent", "list_version": "3.12", "source_flow_uuid": "coal"},
            ],
        )

    def _rows(self):
        return rows_for_merged_list(
            run_id="run", list_name="stepwise", list_version="2006-1.09",
            source_flows=[self.coal, self.water], merged_elementary=[self.hard_coal],
        )

    def test_one_row_per_statement_of_a_row_that_reached_a_flow(self):
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual((row.list_name, row.list_version), ("stepwise", "2006-1.09"))
            self.assertEqual(row.elementary_flow_uuid, "ef-hard-coal")
            self.assertEqual(row.flow_object_id, "fo-hard-coal")
            self.assertEqual(row.source_flow_name, "Coal, hard")
            self.assertEqual(row.quantity_iri, quantity(row.quantity).iri)

    def test_the_statement_the_mapping_converted_by_is_marked(self):
        """Basis, quantity and multiplier all agree with the method's number
        and not with the block's gross one, which is the same number under
        another quantity."""
        by_origin = {row.stated_by: row for row in self._rows()}
        self.assertTrue(by_origin["vendor-method"].used_for_conversion)
        self.assertFalse(by_origin["vendor-flow"].used_for_conversion)

    def test_another_lists_reference_on_the_same_flow_is_not_this_lists_row(self):
        self.assertEqual({row.list_name for row in self._rows()}, {"stepwise"})

    def test_a_row_with_no_statements_or_no_flow_leaves_nothing(self):
        rows = rows_for_merged_list(
            run_id="run", list_name="stepwise", list_version="2006-1.09",
            source_flows=[self.water], merged_elementary=[self.hard_coal],
        )
        self.assertEqual(rows, [])


class TableTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "consensus.sqlite3"
        connection = sqlite3.connect(self.db)
        create_merge_tables(connection)
        connection.commit()
        connection.close()

    def _row(self, **overrides):
        base = dict(
            run_id="run", list_name="stepwise", list_version="2006-1.09",
            source_flow_uuid="coal", source_flow_name="Coal, hard",
            elementary_flow_uuid="ef-hard-coal", flow_object_id="fo-hard-coal",
            quantity=NET_CALORIFIC_VALUE, quantity_iri=quantity(NET_CALORIFIC_VALUE).iri,
            value=18.2, unit="MJ", per_unit="kg", stated_by="vendor-flow",
            used_for_conversion=True, provenance={"prov:wasDerivedFrom": "export.csv"},
            comment="stated",
        )
        base.update(overrides)
        return PropertyStatementRow(**base)

    def test_the_merge_tables_create_it_with_the_declared_columns(self):
        connection = sqlite3.connect(self.db)
        names = [r[1] for r in connection.execute(f"PRAGMA table_info({TABLE})")]
        connection.close()
        self.assertEqual(tuple(names[1:]), COLUMNS)
        self.assertEqual(names[0], "id")

    def test_write_replaces_a_lists_rows_and_read_groups_by_substance(self):
        self.assertEqual(write_rows([self._row()], list_name="stepwise", list_version="2006-1.09", db_path=self.db), 1)
        self.assertEqual(
            write_rows(
                [self._row(value=19.1), self._row(source_flow_uuid="coal-2", flow_object_id="fo-other")],
                list_name="stepwise", list_version="2006-1.09", db_path=self.db,
            ),
            2,
        )
        write_rows([self._row(list_name="agribalyse", list_version="3.2", value=18.2)],
                   list_name="agribalyse", list_version="3.2", db_path=self.db)
        rows = read_rows(["fo-hard-coal"], db_path=self.db)
        self.assertEqual(set(rows), {"fo-hard-coal"})
        self.assertEqual(
            sorted((row.list_name, row.value) for row in rows["fo-hard-coal"]),
            [("agribalyse", 18.2), ("stepwise", 19.1)],
        )
        (first,) = [row for row in rows["fo-hard-coal"] if row.list_name == "stepwise"]
        self.assertEqual(first.provenance, {"prov:wasDerivedFrom": "export.csv"})
        self.assertTrue(first.used_for_conversion)

    def test_reading_a_database_without_the_table_is_empty(self):
        bare = Path(self.tmp.name) / "bare.sqlite3"
        sqlite3.connect(bare).close()
        self.assertEqual(read_rows(["fo-hard-coal"], db_path=bare), {})
        self.assertEqual(read_rows([], db_path=self.db), {})

    def test_create_table_is_idempotent(self):
        connection = sqlite3.connect(self.db)
        create_table(connection)
        create_table(connection)
        connection.close()


if __name__ == "__main__":
    unittest.main()
