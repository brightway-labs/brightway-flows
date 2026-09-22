"""Add RDKit-computed structural properties to flows before consensus matching.

Values are added to the existing ``@value`` list when not already present --
where "present" means the structure is, however the source spelled it, which is
what ``_already_present`` decides.  Existing data from ChEBI/PubChem is never
replaced or removed.
"""

from __future__ import annotations

import copy
from typing import Any

import orjson

from brightway_flows.domain.flow import Flow
from brightway_flows.chem import (
    StructureValues,
    canonical_smiles_key,
    capture_rdkit_logs,
    configure_rdkit_logging,
    structure_values_from_inchi,
    structure_values_from_smiles,
)
from brightway_flows.domain.attestation import attest
from brightway_flows.domain.common import Provenance
from brightway_flows.domain.inchikey import without_redundant_flat_keys
from brightway_flows.domain.vocabulary import (
    CHEMROF_ATOMIC_NUMBER,
    PROV_WAS_GENERATED_BY_CURIE,
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_INCHI2D_STRING,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_MOLECULAR_MASS,
    CHEMROF_MONOISOTOPIC_MASS,
    CHEMROF_SMILES_STRING,
    QUDT_HAS_UNIT,
    RDFS_LABEL_CURIE,
    UNIT_IRI_GM_PER_MOL,
)
from brightway_flows.filesystem import RDKIT_LOG_FILEPATH
from brightway_flows.pipeline import Change, Transformer


def _get_values(properties: dict[str, Any], iri: str) -> list[str]:
    entry = properties.get(iri)
    if not isinstance(entry, dict):
        return []
    raw = entry.get("@value", [])
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v).strip()]
    return []


def _already_present(iri: str, value: str, existing_values: list[str]) -> bool:
    """Does the record already carry *value*, however that structure is spelled?

    Exact string comparison answers this for every property computed here
    except SMILES.  InChI, InChIKey, the formula and the masses are canonical
    across toolkits, so RDKit's output for a molecule PubChem already described
    *is* PubChem's string.  A canonical SMILES is canonical only per toolkit:
    RDKit writes camphor `CC12CCC(CC1=O)C2(C)C` where PubChem's OEChem writes
    `CC1(C2CCC1(C(=O)C2)C)C`, and comparing those as strings said "new value"
    and appended a second spelling of a structure the record already had, on
    5,270 flow objects (#22).

    A stored string RDKit cannot parse never matches: it has no canonical form,
    and no canonical form is not the same as being the structure at hand.
    """
    if value in existing_values:
        return True
    if iri != CHEMROF_SMILES_STRING:
        return False
    key = canonical_smiles_key(value)
    if key is None:
        return False
    return any(canonical_smiles_key(other) == key for other in existing_values)


def _merged_values(iri: str, value: str, existing_values: list[str]) -> list[str]:
    """The ``@value`` list for *iri* once *value* joins *existing_values*.

    A plain sorted union for every property but the InChIKey, where the union
    is not what the record should publish.  A key with no stereochemistry beside
    one that has it is the same substance stated twice, and the flat string is
    also some *other* substance's real key -- L-tryptophan carrying
    `QIVBCDIJIAJPQS-UHFFFAOYSA-N` beside its own key is carrying DL-tryptophan's
    (#50).

    Applied to the merged list rather than to the incoming value, so it holds
    whichever order the two arrive in: the flat key is refused when the record
    already has the specific one -- *value* is then absent from the result and
    the caller records nothing -- and withdrawn when the specific one arrives
    later.  On the 2026-08-12 build the first case is 426 of 427 and the second
    none, and depending on that would make this correct only for as long as
    `DEFAULT_TRANSFORMERS` keeps its current order.
    """
    merged = sorted(set(existing_values) | {value})
    if iri == CHEMROF_INCHI2D_KEY_STRING:
        return without_redundant_flat_keys(merged)
    return merged


def _parse_structure(properties: dict[str, Any]) -> tuple[StructureValues | None, str]:
    """Try SMILES then InChI; return (values, source) or (None, '').

    The values come back already derived rather than as a molecule, because the
    derivation is cached on the source string and the molecule is not: the same
    SMILES is read by every flow that carries it and by each of the three RDKit
    transformers in turn, and reading it is the expensive part.
    """
    for smi in _get_values(properties, CHEMROF_SMILES_STRING):
        values = structure_values_from_smiles(smi)
        if values is not None:
            return values, smi
    for inchi_str in _get_values(properties, CHEMROF_INCHI2D_STRING):
        values = structure_values_from_inchi(inchi_str)
        if values is not None:
            return values, inchi_str
    return None, ""


def _computed_rows(
    values: StructureValues,
) -> list[tuple[str, str, str, str | None]]:
    """The (property, label, value, unit) rows the RDKit transformers write.

    Shared by the pre- and post-consensus transformers, which wrote the same
    six rows out separately.
    """
    return [
        (CHEMROF_SMILES_STRING, "SMILES", values.smiles, None),
        (CHEMROF_INCHI2D_STRING, "InChI", values.inchi, None),
        (CHEMROF_INCHI2D_KEY_STRING, "InChIKey", values.inchikey, None),
        (CHEMROF_MOLECULAR_FORMULA, "Molecular formula", values.formula, None),
        (CHEMROF_MOLECULAR_MASS, "Molecular mass", values.molecular_mass, UNIT_IRI_GM_PER_MOL),
        (CHEMROF_MONOISOTOPIC_MASS, "Monoisotopic mass", values.monoisotopic_mass, UNIT_IRI_GM_PER_MOL),
    ]


def _should_skip(flow: dict[str, Any], properties: dict[str, Any]) -> bool:
    # Qualified flows (biogenic/fossil) should be skipped here, but the
    # qualifier lives on the flow object, not on the flow: the guard that used to
    # sit here read a field Flow does not have and so never fired.  Restoring it
    # would change which flows RDKit enriches, so it is left out deliberately.
    if properties.get(CHEMROF_ATOMIC_NUMBER) and not _get_values(properties, CHEMROF_SMILES_STRING):
        return True
    return False


def _merge_provenance(entry: dict[str, Any], new_prov: dict[str, Any]) -> None:
    """Add new_prov to entry's provenance list if not already present."""
    marker = orjson.dumps(new_prov, option=orjson.OPT_SORT_KEYS).decode()
    existing = entry.get("provenance")
    if isinstance(existing, list):
        seen = {orjson.dumps(p, option=orjson.OPT_SORT_KEYS).decode() for p in existing if isinstance(p, dict)}
        if marker not in seen:
            entry["provenance"] = existing + [new_prov]
    elif isinstance(existing, dict):
        if orjson.dumps(existing, option=orjson.OPT_SORT_KEYS).decode() != marker:
            entry["provenance"] = [existing, new_prov]
    else:
        entry["provenance"] = new_prov


def _set_definitive(
    properties: dict[str, Any],
    iri: str,
    label: str,
    value: str,
    unit_iri: str | None,
    prov: dict[str, Any],
) -> None:
    """Replace @value with a single authoritative value, overwriting all prior entries."""
    if not value:
        return
    entry: dict[str, Any] = {
        "@id": iri,
        RDFS_LABEL_CURIE: label,
        "@value": [value],
        "provenance": prov,
    }
    # A definitive write replaces the slot, so the attribution starts over with
    # it: whoever attested the value being overwritten no longer stands behind
    # anything the record publishes here.
    attest(entry, [value], str(prov.get(PROV_WAS_GENERATED_BY_CURIE) or ""))
    if unit_iri:
        entry[QUDT_HAS_UNIT] = unit_iri
    properties[iri] = entry


class RDKitPreConsensusTransformer(Transformer):
    """Add RDKit-computed structural values to properties before consensus matching.

    Values are appended to each property's ``@value`` list only when not already
    present.  Nothing is removed or replaced — ChEBI/PubChem data is preserved.
    """

    name = "rdkit_pre_consensus"
    answers_per_flow = True

    def setup(self) -> None:
        configure_rdkit_logging(RDKIT_LOG_FILEPATH)

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []
        for flow in flows:
            change = self._process_flow(flow)
            if change is not None:
                changes.append(change)
        return changes

    def _process_flow(self, flow: dict[str, Any]) -> Change | None:
        flow_label = f"{flow.uuid} {flow.name or ''}"
        with capture_rdkit_logs(flow_label):
            return self._process_flow_inner(flow)

    def _process_flow_inner(self, flow: dict[str, Any]) -> Change | None:
        properties = flow.properties
        if not isinstance(properties, dict):
            return None
        if _should_skip(flow, properties):
            return None

        values, source = _parse_structure(properties)
        if values is None:
            return None

        new_properties = copy.deepcopy(properties)
        added: list[str] = []

        computed = _computed_rows(values)
        prov = Provenance(
            was_generated_by="rdkit_pre_consensus",
            was_attributed_to="brightway-flows",
            had_primary_source=[source],
        ).to_dict()

        for iri, label, value, unit_iri in computed:
            if not value:
                continue
            existing = new_properties.get(iri)
            if isinstance(existing, dict):
                existing_values = _get_values(new_properties, iri)
                if _already_present(iri, value, existing_values):
                    continue
                merged = _merged_values(iri, value, existing_values)
                if value not in merged:
                    continue
                entry = dict(existing)
                entry["@value"] = merged
                _merge_provenance(entry, prov)
                attest(entry, [value], "rdkit_pre_consensus")
                new_properties[iri] = entry
            else:
                entry: dict[str, Any] = {"@id": iri, RDFS_LABEL_CURIE: label, "@value": [value], "provenance": prov}
                attest(entry, [value], "rdkit_pre_consensus")
                if unit_iri:
                    entry[QUDT_HAS_UNIT] = unit_iri
                new_properties[iri] = entry
            added.append(iri.rsplit("/", 1)[-1])

        if not added:
            return None

        return Change(
            flow.uuid,
            "properties",
            new_properties,
            comment=f"rdkit_pre_consensus from {source!r}; added: {', '.join(added)}",
        )
