"""A unit spelled with its SI prefix in the other case is not that unit (#388).

Lookup folds case because source lists capitalise at random; only a prefix
letter whose two cases are two prefixes -- milli and mega above all -- is held.
"""

import pytest

from brightway_flows.domain.units import unit_iri_for, unit_row_for
from brightway_flows.merge.conversions import _same_unit


@pytest.mark.parametrize("spelling", ["mJ", "mj", "mJ primary", "mJ/kg"])
def test_a_milli_spelling_does_not_reach_mega(spelling):
    assert unit_iri_for(spelling) == ""
    assert unit_row_for(spelling) is None


@pytest.mark.parametrize(
    ("spelling", "notation"),
    [
        ("MJ", "MJ"),
        ("Mj", "MJ"),
        ("MJ primary", "MJ primary"),
        ("MJprimary", "MJ primary"),
        ("Megajoule", "MJ"),
        ("KG", "kg"),
        ("Kilograms", "kg"),
        ("kbq", "kBq"),
        ("mol", "mole"),
        ("Mole", "mole"),
        ("kwh", "kwh"),
        ("M3", "m3"),
    ],
)
def test_other_spellings_resolve_as_before(spelling, notation):
    row = unit_row_for(spelling)
    assert row is not None and row["notation"] == notation


def test_a_conversion_stated_for_mj_does_not_bind_mj_spelled_milli():
    assert not _same_unit("mJ", "MJ")
    assert _same_unit("Mj", "MJ")


def test_the_ef_reader_holds_the_same_rule():
    from brightway_flows.integrations.ef31 import _load_units_index, _resolve_unit

    index = _load_units_index()
    assert _resolve_unit("mJ", index)[0] is None
    assert _resolve_unit("MJ", index)[0]["notation"] == "MJ"
