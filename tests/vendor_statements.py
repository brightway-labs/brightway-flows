"""What the vendors' own files state about the rows that cross a unit, for the tests.

Since phase B of #407 most of the numbers a mapping converts by are read off
the vendor's file -- SimaPro's substance block, Stepwise's method, ecoinvent's
exchange properties, a flow's name -- rather than out of `data/`.  A test that
pins one of those numbers cannot read the vendor's file, which is not in the
repository, so the lines are copied here, field for field, from
`Stepwise2006_v1.09.csv`, `AGB32_final.CSV` and ecoinvent 3.12's
`ElementaryExchanges.xml`, and :func:`resolved_statements` runs them through
the same readers the load does: the adapters' substance-block and method
readers, the name reader, and the list's own statements file on attach.  What
comes back is what the merge sees for the row, and the tests ask of it what the
merge asks: which statement converts onto the target, and at what number.

The two SimaPro exports share one substance library, so a name has one comment
here and both lists read it.
"""

from __future__ import annotations

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.property_statements import (
    PropertyStatement,
    choose_statement,
    factor_between,
)
from brightway_flows.integrations.stepwise import (
    _method_statement,
    statements_from_substance_comment,
)
from brightway_flows.pipeline.loading import _normalize_input_flow_record
from brightway_flows.property_statements import (
    add_statements_from_names,
    attach_property_statements,
)
from brightway_flows.sources import SourceList

#: The export each list's statements are read out of, by `list_name`.
EXPORTS = {"stepwise": "Stepwise2006_v1.09.csv", "agribalyse": "AGB32_final.CSV"}

#: SimaPro's substance-block comment for each name that states a property,
#: as `bw_simapro_csv` hands it over (one line per property).  Copied from the
#: `Raw materials` block; `Coal, hard`'s lower heating value is misspelt
#: `MH/kg` in the vendor's file and is left as the vendor wrote it.
SUBSTANCE_COMMENTS = {
    "Coal, hard": (
        "Synonyms: Anthracite; Hard coal\n"
        "Higher heating value (HHV): 19.1 MJ/kg\n"
        "Lower heating value (LHV): 18.2 MH/kg"
    ),
    "Coal, brown": (
        "Synonyms: Lignite; Brown coal\n"
        "Higher heating value (HHV): 9.90 MJ/kg\n"
        "Lower heating value (LHV): 8.75 MJ/kg"
    ),
    "Oil, crude": (
        "Synonyms: Crude oil\n"
        "Higher heating value (HHV): 45.8 MJ/kg\n"
        "Lower heating value (LHV): 43.2 MJ/kg"
    ),
    "Gas, natural/m3": (
        "Synonyms: Natural gas\n"
        "Higher heating value (HHV): 38.3 MJ/m3\n"
        "Lower heating value (LHV): 34.5 MJ/m3"
    ),
    "Gas, natural/kg": (
        "Synonyms: Natural gas\n"
        "Higher heating value (HHV): 47.9 MJ/kg\n"
        "Lower heating value (LHV): 43.1 MJ/kg"
    ),
    "Gas, natural, 30.3 MJ per kg": (
        "Higher heating value (HHV): 33.6 MJ/kg\nLower heating value (LHV): 30.3 MJ/kg"
    ),
    "Gas, natural, 46.8 MJ per kg": (
        "Higher heating value (HHV): 52.0 MJ/kg\nLower heating value (LHV): 46.8 MJ/kg"
    ),
    "Gas, natural, feedstock, 46.8 MJ per kg": (
        "Higher heating value (HHV): 52.0 MJ/kg\nLower heating value (LHV): 46.8 MJ/kg"
    ),
    "Gas, natural, 35 MJ per m3": (
        "Higher heating value (HHV): 38.9 MJ/m3\nLower heating value (LHV): 35.0 MJ/m3"
    ),
    "Gas, natural, feedstock, 35 MJ per m3": (
        "Higher heating value (HHV): 38.9 MJ/m3\nLower heating value (LHV): 35.0 MJ/m3"
    ),
    "Gas, natural, 36.6 MJ per m3": (
        "Higher heating value (HHV): 40.6 MJ/m3\nLower heating value (LHV): 36.6 MJ/m3"
    ),
    "Peat": "",
    "Uranium": "Formula: U",
    "Wood and wood waste, 9.5 MJ per kg": "",
    "Uranium oxide, 332 GJ per kg, in ore": "",
}

#: Stepwise's energy carriers: uuid -> (name, unit, the `Non-renewable energy`
#: factor the method gives one unit of the row).  Copied from the export's
#: `Impact category` block; every one is per the unit the substance block
#: inventories the row in, so nothing is rescaled.
STEPWISE_CARRIERS = {
    "7d86a5b7-c5d1-549b-aad3-29286a5e5346": ("Coal, hard", "kg", 19.1),
    "cede79a3-3e82-562b-ac7c-8f0483604f8b": ("Coal, brown", "kg", 9.9),
    "146c61d4-321a-53ef-b58e-35d53bc57de6": ("Oil, crude", "kg", 45.8),
    "b28ffb76-dac7-5bdc-9aa9-f3a00f1ce266": ("Peat", "kg", 9.9),
    "2a7ddb41-4644-5f68-a2ac-81cf18772938": ("Uranium", "kg", 560000.0),
    "177b2fed-48df-5222-b7a7-be3b71a0e73c": ("Gas, natural/m3", "m3", 40.3),
    "bbc7d9ed-0d3a-541b-8ea4-9b80d7c93b66": ("Gas, natural, 30.3 MJ per kg", "kg", 30.3),
    "1da85908-9de5-5f8c-ad12-c5c2031a675d": ("Gas, natural, 46.8 MJ per kg", "kg", 46.8),
    "00e5682e-99d0-53ca-9142-8ddb8c14325a": ("Gas, natural, feedstock, 46.8 MJ per kg", "kg", 46.8),
    "3e88af6a-0f31-5fb7-a035-7a4577e02c9b": ("Gas, natural, 35 MJ per m3", "m3", 35.0),
    "01aa0043-f4ce-5461-9eab-6f7725cecbf2": ("Gas, natural, feedstock, 35 MJ per m3", "m3", 35.0),
    "26eeeb1c-17c9-539c-a654-3a995495c235": ("Gas, natural, 36.6 MJ per m3", "m3", 36.6),
}

#: AGRIBALYSE's rows whose number the vendor states, by substance block or by
#: name: uuid -> (name, unit).  The rows the curated file still states -- the
#: water densities, the radionuclides, hard coal's misspelt net value, the
#: `Uranium` rows whose name says nothing -- are not here; their numbers are
#: read off the file.
AGRIBALYSE_VENDOR_STATED = {
    "c93d8b25-7b26-526d-96c4-417ab385f38a": ("Coal, brown", "kg"),
    "b958fc8c-ff3d-5499-af0d-897d4cc569e9": ("Coal, brown", "kg"),
    "966368b2-34db-55ba-a84a-beb4533aaeb9": ("Oil, crude", "kg"),
    "92052d5f-40db-5440-b75f-6d86ea1ccfd5": ("Oil, crude", "kg"),
    "4e0fae84-bad2-5378-9a09-0d5b6ff09550": ("Gas, natural/m3", "m3"),
    "b71f49da-94c5-5015-a636-f03630a348af": ("Gas, natural/kg", "kg"),
    "e87519c1-c32b-5d7b-9595-d29db06904e7": ("Gas, natural, 30.3 MJ per kg", "kg"),
    "9fdd888b-ae2b-54a1-a659-f6b1c5e5a2ac": ("Gas, natural, 46.8 MJ per kg", "kg"),
    "06156935-5f89-5754-968c-a068a2265517": ("Gas, natural, 35 MJ per m3", "m3"),
    "bf468574-1d70-522c-9077-637beb24f28f": ("Gas, natural, 36.6 MJ per m3", "m3"),
    "f65c0b45-7781-5ae0-aeb1-d329b21796dd": ("Wood and wood waste, 9.5 MJ per kg", "kg"),
    "e6f6fcbd-c5ce-53c1-b5aa-d2fc52c10d98": ("Uranium oxide, 332 GJ per kg, in ore", "kg"),
}

#: ecoinvent's crude oil and natural gas exchanges as `xmltodict` hands them
#: over, the `<property>` children and all, copied from 3.12's
#: `ElementaryExchanges.xml`; and the three property definitions they name,
#: from `Properties.xml`.  3.9.1, 3.10.1 and 3.11 carry the same two.
ECOINVENT_PROPERTY_DEFINITIONS = {
    "48c987bb-3144-4872-b5c7-b1389c40be25": ("heating value, net", "MJ"),
    "d61b8768-8ef6-4a99-ae16-9e51f24ad5b5": ("heating value, gross", "MJ"),
    "67f102e2-9cb6-4d20-aa16-bf74d8a03326": ("wet mass", "kg"),
}
ECOINVENT_CRUDE_OIL = {
    "@id": "88d06db9-59a1-4719-9174-afeb1fa4026a",
    "name": {"@xml:lang": "en", "#text": "Oil, crude"},
    "unitName": {"@xml:lang": "en", "#text": "kg"},
    "property": [
        {
            "@propertyId": "48c987bb-3144-4872-b5c7-b1389c40be25",
            "@amount": "43.4",
            "@isDefiningValue": "false",
            "comment": {"@xml:lang": "en", "#text": "Based on Meili et al. (2022) section 5.1"},
        },
        {
            "@propertyId": "d61b8768-8ef6-4a99-ae16-9e51f24ad5b5",
            "@amount": "46",
            "@isDefiningValue": "false",
            "comment": {"@xml:lang": "en", "#text": "Based on Meili et al. (2022) section 5.1"},
        },
        {"@propertyId": "67f102e2-9cb6-4d20-aa16-bf74d8a03326", "@amount": "1"},
    ],
}
ECOINVENT_NATURAL_GAS = {
    "@id": "7c337428-fb1b-45c7-bbb2-2ee4d29e17ba",
    "name": {"@xml:lang": "en", "#text": "Gas, natural"},
    "unitName": {"@xml:lang": "en", "#text": "Sm3"},
    "property": [
        {
            "@propertyId": "d61b8768-8ef6-4a99-ae16-9e51f24ad5b5",
            "@amount": "40",
            "@isDefiningValue": "false",
            "comment": {"@xml:lang": "en", "#text": "At standard conditions; based on Meili et al. (2022) section 5.1"},
        },
        {
            "@propertyId": "48c987bb-3144-4872-b5c7-b1389c40be25",
            "@amount": "36",
            "@isDefiningValue": "false",
            "comment": {"@xml:lang": "en", "#text": "At standard conditions; based on Meili et al. (2022) section 5.1"},
        },
    ],
}


def resolved_statements(
    source: SourceList, *, uuid: str, name: str, unit: str,
) -> list[PropertyStatement]:
    """Every statement the load leaves on this row, vendor's and curator's.

    The row is built as the vendor shipped it, read with the adapters'
    readers (the substance block's comment for the name, and for Stepwise the
    method's factor), the name reader, and the list's statements file on
    attach -- the same chain `SourceList.load_flows` runs, on one row.
    """
    comment = SUBSTANCE_COMMENTS.get(name, "")
    statements, _refused = statements_from_substance_comment(
        comment, flow_unit=unit, row_name=name, block="Raw materials",
        export=EXPORTS.get(source.list_name, ""), source=source.source_label,
    )
    if source.list_name == "stepwise":
        for carrier_uuid, (carrier, carrier_unit, factor) in STEPWISE_CARRIERS.items():
            if carrier_uuid == uuid:
                method = _method_statement(
                    name=carrier, compartment="Raw", subcompartment="(unspecified)",
                    amount=factor, per_unit=carrier_unit,
                    export=EXPORTS["stepwise"], source=source.source_label,
                )
                if method is not None:
                    statements.append(method)
    row = {
        "uuid": uuid, "name": name, "unit": unit, "context": ["Raw", "in ground"],
        "property_statements": [s.to_dict() for s in statements],
    }
    if source.simapro_origin:
        add_statements_from_names([row], label=source.key)
    flow = Flow.from_dict(_normalize_input_flow_record(row, source_hint=source.key))
    attach_property_statements([flow], source.load_property_statements())
    return list(flow.property_statements or [])


def converting_statement(
    source: SourceList, *, uuid: str, name: str, unit: str, target_quantity: str,
) -> PropertyStatement | None:
    """The statement the merge converts this row by onto a target of *target_quantity*."""
    return choose_statement(
        resolved_statements(source, uuid=uuid, name=name, unit=unit),
        target_quantity=target_quantity,
        rules=source.load_property_statements().rules,
    )


def published_factor(
    source: SourceList, *, uuid: str, name: str, unit: str, target_unit: str,
    target_quantity: str,
) -> float | None:
    """The multiplier the mapping publishes for this row onto *target_unit*."""
    statement = converting_statement(
        source, uuid=uuid, name=name, unit=unit, target_quantity=target_quantity
    )
    return None if statement is None else factor_between(statement, unit, target_unit)
