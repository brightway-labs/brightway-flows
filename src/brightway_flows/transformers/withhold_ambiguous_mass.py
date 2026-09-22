"""Publish a mass only for a flow whose structure is settled.

`molecular_mass` and `monoisotopic_mass` are properties *of a structure*.  A flow
carrying several candidate structures has no single one, so any value written
there is the mass of one candidate presented as the mass of the flow, and
nothing downstream can tell which.

That is not hypothetical.  `7de354b2-88d0-46a4-b0c7-2e6fe0783d5b`,
`10-methoxy-5H-dibenzo[b,f]azepine`, carries six candidate SMILES and published
`232.666` -- the mass of `C13H9ClO2`, a chlorobiphenyl carboxylic acid.  The
flow is `C15H13NO`, 223.275.  The wrong candidate won because RDKit's
`_parse_mol` takes the first *parseable* SMILES from a list held in
`sorted(set(...))` order, and alphabetical order over SMILES strings has nothing
to do with chemistry.  Measured over a full run, the surviving value was the
first list element for 318 flows and the last for 317 -- the signature of
selecting from an unordered set (#217).

So the rule here is: **a mass is published only when the candidate set names one
structure.**  Where it does not, the properties are removed rather than guessed.
Silence is recoverable and a wrong number is not: a consumer can see that a mass
is missing, but cannot see that one is the wrong compound's.

This runs as a late pass rather than as a guard inside the writers because the
value has more than one writer -- `enrich_references.chebi_semantic` supplies it
for 35,038 flows, 502 of them with no RDKit involvement -- and the guarantee
wanted is an invariant over the result, not a behaviour of each contributor.
One place to enforce it, and one place to read it.

The other structural properties are left alone.  `molecular_formula`,
`smiles_string` and `inchi2d_key_string` *accumulate* their candidates, so a
list there states the ambiguity rather than hiding it, which is what a reader
needs in order to resolve it.  Reducing that ambiguity is #6; this transformer
only stops the export asserting a precision the data does not have, and as the
candidate sets narrow the masses come back on their own.
"""

from __future__ import annotations

import copy
from typing import Any

import structlog

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.vocabulary import (
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_MOLECULAR_MASS,
    CHEMROF_MONOISOTOPIC_MASS,
)
from brightway_flows.pipeline import Change, Transformer

logger = structlog.get_logger(__name__)

#: Properties that describe one structure and so cannot describe several.
MASS_PROPERTIES = (CHEMROF_MOLECULAR_MASS, CHEMROF_MONOISOTOPIC_MASS)


def _values(properties: dict[str, Any], iri: str) -> list[str]:
    entry = properties.get(iri)
    if not isinstance(entry, dict):
        return []
    raw = entry.get("@value", [])
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v).strip()]
    return []


def candidate_structure_count(properties: dict[str, Any]) -> int:
    """How many distinct structures the flow's candidates name.

    Judged on the InChIKey *skeleton* -- the first block, before the first
    hyphen -- because the later blocks encode stereochemistry and protonation,
    which two records of the same compound routinely disagree on without being
    different substances.

    Molecular formula is the fallback for flows that carry no InChIKey.  One
    compound has one formula, so two distinct formulas are two compounds.
    """
    skeletons = {value.split("-", 1)[0] for value in _values(properties, CHEMROF_INCHI2D_KEY_STRING)}
    if skeletons:
        return len(skeletons)
    return len({v.strip() for v in _values(properties, CHEMROF_MOLECULAR_FORMULA)})


def structure_is_ambiguous(properties: dict[str, Any]) -> bool:
    """Whether the flow's candidates name more than one structure.

    Judged on the InChIKey *skeleton* -- the first block, before the first
    hyphen -- because the later blocks encode stereochemistry and protonation,
    which two records of the same compound routinely disagree on without being
    different substances.

    Molecular formula is the fallback for flows that carry no InChIKey.  One
    compound has one formula, so two distinct formulas are two compounds.
    """
    return candidate_structure_count(properties) > 1


class WithholdAmbiguousMassTransformer(Transformer):
    """Remove mass properties from flows whose structure is not settled."""

    name = "withhold_ambiguous_mass"
    answers_per_flow = True

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []
        withheld = 0
        for flow in flows:
            properties = flow.properties
            if not isinstance(properties, dict):
                continue
            present = [iri for iri in MASS_PROPERTIES if isinstance(properties.get(iri), dict)]
            if not present:
                continue
            candidates = candidate_structure_count(properties)
            if candidates <= 1:
                continue

            new_properties = copy.deepcopy(properties)
            for iri in present:
                new_properties.pop(iri, None)
            withheld += 1
            removed = ", ".join(iri.rsplit("/", 1)[-1] for iri in present)
            changes.append(Change(
                flow.uuid,
                "properties",
                new_properties,
                comment=(
                    f"withhold_ambiguous_mass: removed {removed}; the flow carries "
                    f"{candidates} candidate structures, so no one mass describes it"
                ),
            ))

        logger.info("withhold_ambiguous_mass_completed", flows_withheld=withheld)
        return changes
