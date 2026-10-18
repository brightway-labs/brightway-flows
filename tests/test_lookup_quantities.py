"""Amounts sent to lookup must be expressed in the unit of its answer (#382)."""

from pathlib import Path
import sqlite3

import orjson
import pytest

from brightway_flows.lookup import FlowMatcher, FlowQuery
from brightway_flows.merge.store import create_merge_tables
from brightway_flows.pipeline.sqlite import _write_consensus_sqlite
from test_lookup_index import (
    AIR,
    MERGE_RUN_ID,
    _elementary,
    _flow,
    _flow_object,
    _write_run_tables,
)


def quantity_build(
    tmp_path: Path,
    *,
    name="Quantity fixture",
    source="Bq",
    target="kBq",
    factor=None,
    basis=None,
):
    db = tmp_path / "consensus-flows.sqlite3"
    obj = _flow_object("quantity-object", name)
    elementary = _elementary(
        "quantity-flow", obj.flow_object_id, context_iri=AIR, unit=target
    )
    metadata = {"unit": source, "original_context": ["Environmental", "Air", "Unknown"]}
    if factor is not None:
        metadata["qudt:conversionMultiplier"] = factor
    if basis is not None:
        metadata["conversion_basis"] = basis
    elementary.source_refs = [
        {
            "list_name": "quantity-fixture",
            "list_version": "1",
            "source_flow_uuid": "source-row",
            "source_flow_name": name,
            "source_metadata": metadata,
        }
    ]
    flow = _flow(
        "quantity-flow",
        name,
        flow_object_id=obj.flow_object_id,
        context_iri=AIR,
        unit=target,
    )
    _write_consensus_sqlite([flow], [], [obj], [elementary], db_path=db)
    _write_run_tables(db)
    with sqlite3.connect(db) as conn:
        create_merge_tables(conn)
        conn.execute(
            "INSERT INTO merge_outcomes (run_id,list_name,list_version,source_uuid,"
            "source_name,source_unit,source_context_json,outcome,target_elementary_flow_id,detail_json) "
            "VALUES ('merge-1','quantity-fixture','1','source-row',?,?,'[]','algorithm','quantity-flow',?)",
            (name, source, orjson.dumps({"source_context_iri": AIR}).decode()),
        )
        conn.execute("UPDATE merge_outcomes SET run_id = ?", (MERGE_RUN_ID,))
    return db


@pytest.mark.parametrize("tier", ["recorded", "recorded-by-name", "algorithm"])
@pytest.mark.parametrize(
    "source,target,factor",
    [
        ("Bq", "kBq", 0.001),
        ("kBq", "Bq", 1000),
        ("km", "m", 1000),
        ("kWh", "MJ", 3.6),
        ("m2a", "m2.a", 1),
        ("personkm", "p.km", 1),
        ("tkm", "t.km", 1),
        ("m3y", "m3.a", 1),
        ("kg", "kg", 1),
    ],
)
def test_total_quantity_factor_in_every_lookup_tier(
    tmp_path, tier, source, target, factor
):
    db = quantity_build(tmp_path, source=source, target=target)
    matcher = FlowMatcher.from_results(db, recorded_by_name=tier == "recorded-by-name")
    exact = (
        {"list_key": "quantity-fixture-1", "identifier": "source-row"}
        if tier == "recorded"
        else {}
    )
    result = matcher.match(
        FlowQuery(name="Quantity fixture", unit=source, context_iri=AIR, **exact)
    )
    assert result.matched and result.tier == tier
    assert result.unit_conversion_factor == pytest.approx(factor)
    # A synthetic amount and a CF stated per target unit give the same score.
    assert 7 * result.unit_conversion_factor * 11 == pytest.approx(7 * factor * 11)


@pytest.mark.parametrize("source", ["", "unknown-unit", "m3"])
def test_unknown_conversion_is_never_reported_as_identity(tmp_path, source):
    db = quantity_build(tmp_path, source=source, target="kg")
    result = FlowMatcher.from_results(db).match(
        FlowQuery(
            name="Quantity fixture",
            unit=source,
            list_key="quantity-fixture-1",
            identifier="source-row",
        )
    )
    assert result.matched
    assert result.unit_conversion_factor is None


def test_quantity_table_preserves_all_published_unit_notations():
    from brightway_flows.domain.units import UNITS_FILEPATH, unit_table_factor

    for row in orjson.loads(UNITS_FILEPATH.read_bytes()):
        unit = row["notation"]
        assert unit_table_factor(unit, unit) == 1, unit


def test_unmatched_query_has_no_quantity_factor(tmp_path):
    db = quantity_build(tmp_path)
    result = FlowMatcher.from_results(db).match(
        FlowQuery(name="Not present", unit="Bq", context_iri=AIR)
    )
    assert not result.matched
    assert result.unit_conversion_factor is None


@pytest.mark.parametrize(
    "source,target,factor", [("kg", "m3", 0.001), ("kg", "kg", 0.599)]
)
def test_exact_recorded_source_factor_is_retained(tmp_path, source, target, factor):
    db = quantity_build(tmp_path, source=source, target=target, factor=factor)
    result = FlowMatcher.from_results(db).match(
        FlowQuery(
            name="Quantity fixture",
            unit=source,
            list_key="quantity-fixture-1",
            identifier="source-row",
        )
    )
    assert result.matched
    assert result.unit_conversion_factor == pytest.approx(factor)


def test_recorded_factor_can_rebase_a_callers_scaled_unit(tmp_path):
    db = quantity_build(tmp_path, source="kg", target="MJ", factor=9.76)
    result = FlowMatcher.from_results(db).match(
        FlowQuery(
            name="Quantity fixture",
            unit="g",
            list_key="quantity-fixture-1",
            identifier="source-row",
        )
    )
    assert result.unit_conversion_factor == pytest.approx(0.00976)


def test_lineage_preparation_is_composed_with_final_unit_scale(tmp_path):
    db = quantity_build(tmp_path, name="Uranium", source="kg", target="kWh")
    result = FlowMatcher.from_results(db).match(
        FlowQuery(
            name="Uranium, 451 GJ per kg",
            unit="kg",
            simapro_origin=True,
            list_key="quantity-fixture-1",
            identifier="source-row",
        )
    )
    assert result.matched
    assert result.prepared_unit == "MJ"
    assert result.unit_conversion_factor == pytest.approx(451000 / 3.6)


def test_recorded_factor_and_lineage_preparation_are_not_applied_twice(tmp_path):
    db = quantity_build(
        tmp_path, name="Uranium", source="kg", target="MJ", factor=451000
    )
    result = FlowMatcher.from_results(db).match(
        FlowQuery(
            name="Uranium, 451 GJ per kg",
            unit="kg",
            simapro_origin=True,
            list_key="quantity-fixture-1",
            identifier="source-row",
        )
    )
    assert result.unit_conversion_factor == pytest.approx(451000)


def test_source_specific_composition_requires_an_exact_row(tmp_path):
    db = quantity_build(tmp_path, source="kg", target="kg", factor=0.599)
    result = FlowMatcher.from_results(db, recorded_by_name=True).match(
        FlowQuery(
            name="Quantity fixture",
            unit="kg",
            context_iri=AIR,
        )
    )
    assert result.matched and result.tier == "recorded-by-name"
    assert result.unit_conversion_factor is None
    assert (
        result.selector_details["quantity_conversion"]["basis"]
        == "source-identifier-required"
    )


def test_a_multiplier_for_another_quantity_kind_does_not_withhold_the_unit_table(
    tmp_path,
):
    # BAFU's `Water` in kg carries kg -> m3 at 0.001; the same name sent in m3
    # lands on the same m3 flow and is 1:1, which the multiplier cannot touch.
    db = quantity_build(tmp_path, source="kg", target="m3", factor=0.001)
    matcher = FlowMatcher.from_results(db, recorded_by_name=True)
    in_volume = matcher.match(
        FlowQuery(name="Quantity fixture", unit="m3", context_iri=AIR)
    )
    assert in_volume.matched and in_volume.tier == "recorded-by-name"
    assert in_volume.unit_conversion_factor == pytest.approx(1.0)
    assert in_volume.selector_details["quantity_conversion"]["basis"] == "unit-table"
    in_mass = matcher.match(
        FlowQuery(name="Quantity fixture", unit="kg", context_iri=AIR)
    )
    assert in_mass.unit_conversion_factor is None
    assert (
        in_mass.selector_details["quantity_conversion"]["basis"]
        == "source-identifier-required"
    )


def test_name_index_does_not_lose_a_composition_factor_behind_same_target(tmp_path):
    db = quantity_build(tmp_path, source="kg", target="kg", factor=0.599)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO elementary_flow_sources "
            "(elementary_flow_uuid,list_name,list_version,source_flow_uuid,source_flow_name,source_metadata_json) "
            "VALUES ('quantity-flow','quantity-fixture','1','source-row-2','Quantity fixture','{\"unit\":\"kg\"}')"
        )
        conn.execute(
            "INSERT INTO merge_outcomes (run_id,list_name,list_version,source_uuid,source_name,"
            "source_unit,source_context_json,outcome,target_elementary_flow_id,detail_json) "
            "SELECT run_id,list_name,list_version,'source-row-2',source_name,source_unit,"
            "source_context_json,outcome,target_elementary_flow_id,detail_json FROM merge_outcomes"
        )
    result = FlowMatcher.from_results(db, recorded_by_name=True).match(
        FlowQuery(
            name="Quantity fixture",
            unit="kg",
            context_iri=AIR,
        )
    )
    assert result.matched and result.tier == "recorded-by-name"
    assert result.unit_conversion_factor is None


@pytest.mark.parametrize("factor", [0, -1, True, "0.5"])
def test_invalid_recorded_conversion_is_refused(tmp_path, factor):
    db = quantity_build(tmp_path, factor=factor)
    with pytest.raises(ValueError, match="Invalid recorded quantity conversion"):
        FlowMatcher.from_results(db).match(
            FlowQuery(
                name="Quantity fixture",
                unit="Bq",
                list_key="quantity-fixture-1",
                identifier="source-row",
            )
        )


def test_a_unit_table_multiplier_is_not_a_reason_to_ask_for_the_identifier(tmp_path):
    """A build publishes `units.json`'s 0.001 on a Bq row mapped onto a kBq
    flow, saying so with `conversion_basis` (#393).  It is true of any flow
    measured in those units, so a caller sending the name gets it too."""
    db = quantity_build(
        tmp_path, source="Bq", target="kBq", factor=0.001, basis="unit-table"
    )
    result = FlowMatcher.from_results(db, recorded_by_name=True).match(
        FlowQuery(name="Quantity fixture", unit="Bq", context_iri=AIR)
    )
    assert result.matched and result.tier == "recorded-by-name"
    assert result.unit_conversion_factor == pytest.approx(0.001)
    assert result.selector_details["quantity_conversion"]["basis"] == "unit-table"


def test_a_stated_multiplier_still_asks_for_the_identifier(tmp_path):
    db = quantity_build(
        tmp_path, source="kg", target="kg", factor=0.599, basis="correspondence-table"
    )
    result = FlowMatcher.from_results(db, recorded_by_name=True).match(
        FlowQuery(name="Quantity fixture", unit="kg", context_iri=AIR)
    )
    assert result.unit_conversion_factor is None
    assert (
        result.selector_details["quantity_conversion"]["basis"]
        == "source-identifier-required"
    )
