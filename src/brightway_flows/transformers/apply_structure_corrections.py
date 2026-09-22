"""Write the structure a curator states, for the substances that need one.

`data/structure-corrections.json` holds them and says what belongs there; this
step puts them on the flow.  One substance today: antimony trisulfide, whose
structure no route in this pipeline can reach.

## Why it runs last among the structural steps

It overrules everything.  A curated structure is the strongest claim this
project lets a file make -- it is not evidence from a source list, it cannot be
traced to a vendor's record, and it is asserted on a curator's authority -- so
it is written after every step that derives one, and nothing may overwrite it
afterwards.

That is the opposite of the two steps before it, and deliberately so.
`supply_registered_composition` fills a hole and defers to anything already
there; `withhold_contradicted_composition` judges what is published against the
registry.  Both are rules about evidence.  This is a decision, and a decision
that could be quietly reversed by a later derivation would not be one.

## What it writes

The whole structural record: SMILES, InChI, InChIKey, molecular formula and
both masses, all derived from the one SMILES the curator wrote, so they cannot
disagree with each other.  Replacing rather than adding, because the values it
replaces are the ones judged wrong -- leaving them beside the correction would
publish two answers and settle nothing.

The published ChemROF class is not written here.  It is stated in the same
curated entry and applied by `pipeline.semantic_typing`, which is the one place
that decides what a substance is; a transformer writing a type directly would
be a second such place.
"""

from __future__ import annotations

import copy

import structlog

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.structure_corrections import (
    StructureCorrection,
    correction_for,
)
from brightway_flows.domain.vocabulary import (
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_INCHI2D_STRING,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_MOLECULAR_MASS,
    CHEMROF_MONOISOTOPIC_MASS,
    CHEMROF_SMILES_STRING,
    UNIT_IRI_GM_PER_MOL,
)
from brightway_flows.pipeline import Change, Transformer
from brightway_flows.transformers.rdkit_enrichment import _set_definitive

logger = structlog.get_logger(__name__)

ACTIVITY = "structure_corrections"


class ApplyStructureCorrectionsTransformer(Transformer):
    """Replace a flow's structure with the curated one for its registry number.

    See the module docstring for why this runs after every step that derives a
    structure, and the curated file for what may be corrected.
    """

    name = "structure_corrections"
    # One flow's registry numbers against the curated file `setup()` read.
    # Nothing about the other flows.
    answers_per_flow = True

    def setup(self) -> None:
        # Read here rather than per flow, and read at all rather than lazily,
        # so a malformed file fails the run at its start instead of partway
        # through a merge.  The loader checks each entry against its own SMILES
        # and raises on a disagreement.
        self._corrections = correction_for

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []
        for flow in flows:
            correction = self._corrections(flow.cas_numbers)
            if correction is None:
                continue
            properties = flow.properties
            if not isinstance(properties, dict):
                properties = {}
            changes.append(self._change(flow, properties, correction))
        logger.info(
            "structure_corrections",
            flows_corrected=len(changes),
            # A curated structure that reaches nothing is a curation error --
            # the number was corrected, renumbered or never present -- and it
            # is silent unless counted, because there is no row to notice.
            corrections_that_reached_nothing=self._unreached(flows),
        )
        return changes

    def _unreached(self, flows: list[Flow]) -> int:
        from brightway_flows.domain.structure_corrections import (
            structure_corrections,
        )

        reached = {
            cas
            for flow in flows
            for cas in flow.cas_numbers or []
            if isinstance(cas, str)
        }
        return sum(
            1
            for correction in structure_corrections()
            if correction.cas_number not in reached
        )

    def _change(
        self,
        flow: Flow,
        properties: dict,
        correction: StructureCorrection,
    ) -> Change:
        prov = Provenance(
            was_generated_by=ACTIVITY,
            was_attributed_to="brightway-flows",
            had_primary_source=[correction.cas_number],
            was_derived_from="curated structure correction",
        ).to_dict()
        new_properties = copy.deepcopy(properties)
        for iri, label, value, unit in (
            (CHEMROF_SMILES_STRING, "SMILES", correction.smiles, None),
            (CHEMROF_INCHI2D_STRING, "InChI", correction.inchi, None),
            (CHEMROF_INCHI2D_KEY_STRING, "InChIKey", correction.inchikey, None),
            (
                CHEMROF_MOLECULAR_FORMULA,
                "molecular formula",
                correction.molecular_formula,
                None,
            ),
            (
                CHEMROF_MOLECULAR_MASS,
                "Molecular mass",
                correction.molecular_mass,
                UNIT_IRI_GM_PER_MOL,
            ),
            (
                CHEMROF_MONOISOTOPIC_MASS,
                "Monoisotopic mass",
                correction.monoisotopic_mass,
                UNIT_IRI_GM_PER_MOL,
            ),
        ):
            _set_definitive(new_properties, iri, label, value, unit, prov)
        return Change(
            flow.uuid,
            "properties",
            new_properties,
            comment=(
                f"structure_corrections: {correction.molecular_formula} "
                f"({correction.smiles}) for {correction.cas_number}, which no "
                "derivation in this pipeline reaches"
            ),
        )
