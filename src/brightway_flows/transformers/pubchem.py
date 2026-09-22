"""Propose flow name updates based on PubChem compound data."""

from __future__ import annotations

import orjson

from brightway_flows.domain.flow import Flow
from brightway_flows.filesystem import PUBCHEM_DATA_FILEPATH
from brightway_flows.domain.labels import Label, flow_label_value
from brightway_flows.pipeline import (
    Change,
    Transformer,
    has_stereo_descriptor,
    normalize,
)


class PubChemTransformer(Transformer):
    """Propose flow name updates based on PubChem data (CAS -> CID -> name)."""

    name = "pubchem"

    def __init__(self) -> None:
        self._cas_to_name: dict[str, str] = {}

    def setup(self) -> None:
        if not PUBCHEM_DATA_FILEPATH.exists():
            raise FileNotFoundError(
                f"PubChem data not found at {PUBCHEM_DATA_FILEPATH}. "
                "Run 'brightway-flows pubchem' first."
            )

        pubchem = orjson.loads(PUBCHEM_DATA_FILEPATH.read_bytes())

        cid_to_name: dict[int, str] = {}
        for pname, compounds in pubchem.get("by_name", {}).items():
            for compound in compounds:
                cid_to_name.setdefault(compound["cid"], pname)

        for cas, compounds in pubchem.get("by_cas", {}).items():
            for compound in compounds:
                cid = compound["cid"]
                if cid in cid_to_name:
                    self._cas_to_name[cas] = cid_to_name[cid]
                    break

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []

        for flow in flows:
            cas_list = flow.cas_numbers
            ef_name = flow_label_value(flow)
            if not cas_list or not ef_name:
                continue

            matched_cas: str | None = None
            pubchem_name: str | None = None
            for cas in cas_list:
                pubchem_name = self._cas_to_name.get(cas)
                if pubchem_name is not None:
                    matched_cas = cas
                    break

            if pubchem_name is None:
                continue

            if normalize(ef_name) == normalize(pubchem_name):
                continue

            # Don't strip stereochemical information: if the current name
            # contains a stereo descriptor (alpha-, beta-, γ, δ, cis-,
            # trans-, …) and the PubChem name does not, the PubChem entry
            # refers to the parent compound class, not this specific isomer.
            if has_stereo_descriptor(ef_name) and not has_stereo_descriptor(pubchem_name):
                continue

            changes.append(Change(
                flow.uuid,
                "prefLabel",
                [Label(
                    value=pubchem_name,
                    source=f"provider=pubchem; via=legacy-pubchem-transformer; cas={matched_cas}",
                ).to_dict()],
                comment=f"PubChem preferred name for CAS {matched_cas}",
            ))

        return changes
