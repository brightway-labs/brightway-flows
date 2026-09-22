"""Set definitive RDKit structural properties for unambiguous flow objects.

A flow qualifies when all three conditions hold:

1. It has no ``origin_qualifier`` (qualifier variants are intentionally excluded
   from uniqueness checks, consistent with the rest of the RDKit pipeline).
2. Its ``properties[CHEMROF_IUPAC_NAME]`` contains exactly one value — either
   set by :class:`OPSINTransformer` in this pipeline run, or seeded from
   PubChem by :class:`EnrichReferencesTransformer` in a prior run.
3. Its InChI resolves to a standard-layer InChIKey that is globally unique
   among all non-qualifier flows.

When all conditions are met every structural property (SMILES, InChI,
InChIKey, formula, masses) is replaced with a single RDKit-computed value and
the replacement is logged.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from typing import Any

import structlog

from brightway_flows.domain.flow import Flow
from brightway_flows.chem import (
    StructureValues,
    capture_rdkit_logs,
    configure_rdkit_logging,
    structure_values_from_inchi,
)
from brightway_flows.domain.common import Provenance
from brightway_flows.domain.vocabulary import (
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_INCHI2D_STRING,
    CHEMROF_IUPAC_NAME,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_MOLECULAR_MASS,
    CHEMROF_MONOISOTOPIC_MASS,
    CHEMROF_SMILES_STRING,
    UNIT_IRI_GM_PER_MOL,
)
from brightway_flows.filesystem import RDKIT_LOG_FILEPATH
from brightway_flows.pipeline import Change, Transformer, writable_flows
from brightway_flows.transformers.rdkit_enrichment import (
    _get_values,
    _set_definitive,
    _should_skip,
)

logger = structlog.get_logger(__name__)


def _std_inchikey(key: str) -> str:
    """Return the standard (connectivity) layer of an InChIKey."""
    return key.split("-")[0]


class RDKitAuthoritativeTransformer(Transformer):
    """Replace structural properties with definitive RDKit values for unambiguous flows.

    Requires a globally unique InChI (standard layer) and a single IUPAC name.
    Flows with origin qualifiers are excluded from both the uniqueness index and
    the candidate set.
    """

    name = "rdkit_authoritative"
    # "Is this structure unique in the build?" is a question about the whole
    # list.  Shown only the flows it can write to, it would find a structure
    # unique among those and overwrite a flow's data on the strength of it,
    # while the substance it collides with sat in the consensus list unseen.
    answers_per_flow = False

    def setup(self) -> None:
        configure_rdkit_logging(RDKIT_LOG_FILEPATH)

    def transform(self, flows: list[Flow]) -> list[Change]:
        # Index standard InChIKey → list[uuid] across all non-qualifier flows.
        # Every flow, deliberately: "is this structure unique in the build?" is
        # the question this transformer exists to ask, and a structure it could
        # not see is a collision it would not find.
        std_key_to_uuids: dict[str, list[str]] = defaultdict(list)

        for flow in flows:
            # See the note in rdkit_enrichment._should_skip: the qualifier is a
            # flow-object field, so the guard that used to sit here never fired.
            properties = flow.properties or {}
            for inchi_str in _get_values(properties, CHEMROF_INCHI2D_STRING):
                values = structure_values_from_inchi(inchi_str)
                if values is None:
                    continue
                if values.inchikey:
                    std_key_to_uuids[_std_inchikey(values.inchikey)].append(flow.uuid)

        # The decision, over the flows this call can still write to.  The index
        # above answers for the whole build; a proposal for a finished flow is
        # dropped on arrival, so re-reading its structure to make one is work
        # done to be discarded.  This loop used to run over an `eligible` list
        # the loop above appended every flow to unconditionally, which is what
        # made the name misleading.
        changes: list[Change] = []
        for flow in writable_flows(flows):
            properties = flow.properties or {}
            if _should_skip(flow, properties):
                continue

            iupac_values = _get_values(properties, CHEMROF_IUPAC_NAME)
            if len(iupac_values) != 1:
                continue

            inchi_values = _get_values(properties, CHEMROF_INCHI2D_STRING)
            if len(inchi_values) != 1:
                continue

            values = structure_values_from_inchi(inchi_values[0])
            if values is None:
                continue

            if not values.inchikey:
                continue
            if len(std_key_to_uuids.get(_std_inchikey(values.inchikey), [])) != 1:
                continue

            flow_label = f"{flow.uuid} {flow.name or ''}"
            with capture_rdkit_logs(flow_label):
                change = self._make_change(flow, values, inchi_values[0])
            if change is not None:
                changes.append(change)

        return changes

    def _make_change(
        self, flow: dict[str, Any], values: StructureValues, source_inchi: str
    ) -> Change | None:
        new_properties = copy.deepcopy(flow.properties)

        prov = Provenance(
            was_generated_by="rdkit_authoritative",
            was_attributed_to="brightway-flows",
            had_primary_source=[source_inchi],
        ).to_dict()

        _set_definitive(new_properties, CHEMROF_SMILES_STRING, "SMILES", values.smiles, None, prov)
        _set_definitive(new_properties, CHEMROF_INCHI2D_STRING, "InChI", values.inchi, None, prov)
        _set_definitive(new_properties, CHEMROF_INCHI2D_KEY_STRING, "InChIKey", values.inchikey, None, prov)
        if values.formula:
            _set_definitive(new_properties, CHEMROF_MOLECULAR_FORMULA, "Molecular formula", values.formula, None, prov)
        if values.molecular_mass:
            _set_definitive(new_properties, CHEMROF_MOLECULAR_MASS, "Molecular mass", values.molecular_mass, UNIT_IRI_GM_PER_MOL, prov)
        if values.monoisotopic_mass:
            _set_definitive(new_properties, CHEMROF_MONOISOTOPIC_MASS, "Monoisotopic mass", values.monoisotopic_mass, UNIT_IRI_GM_PER_MOL, prov)

        logger.info(
            "rdkit_authoritative_set",
            uuid=flow.uuid,
            inchikey=values.inchikey,
        )

        return Change(
            flow.uuid,
            "properties",
            new_properties,
            comment="rdkit_authoritative: set definitive structural data from unique InChI",
        )
