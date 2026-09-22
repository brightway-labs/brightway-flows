"""The structure a curator states, where the pipeline cannot work one out.

See `data/structure-corrections.json` for what belongs here and what does not.
This module reads it, checks it against itself, and indexes it by registry
number.

**The file is checked at load time rather than trusted.**  A curator writes the
SMILES and also writes the InChI, the InChIKey and the molecular formula; those
three are derived from the SMILES here and compared, and a disagreement raises.
The point is not that RDKit needs help -- it is that a reviewer reading the file
can see the InChIKey without running anything, and that what they read cannot
quietly stop being what the structure says.  The same reasoning as
`aggregate_measurements`, where a name claimed twice raises where the file is
read rather than letting the last entry win.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import orjson

from brightway_flows.chem import structure_values_from_smiles
from brightway_flows.domain.vocabulary import IRIS, Term
from brightway_flows.filesystem import PACKAGE_DATA_DIR

STRUCTURE_CORRECTIONS_FILEPATH = (
    PACKAGE_DATA_DIR / "structure-corrections.json"
)


@dataclass(frozen=True)
class StructureCorrection:
    """One substance's structure, as a curator states it."""

    cas_number: str
    label: str
    smiles: str
    inchi: str
    inchikey: str
    molecular_formula: str
    #: Derived from the SMILES like everything above, and not stated in the
    #: file: a mass is arithmetic on a structure, so writing it down would be
    #: noise a curator could get wrong rather than a fact they can check.
    molecular_mass: str
    monoisotopic_mass: str
    #: The published ChemROF class, as an IRI.  Stated rather than inferred:
    #: see the file's description for why a correction that depends on the
    #: typing rules agreeing is not a correction.
    flow_type: str
    comment: str


def _check(field: str, cas: str, stated: str, derived: str) -> None:
    if stated != derived:
        raise ValueError(
            f"structure-corrections.json: {cas} states {field} {stated!r}, but "
            f"its SMILES derives {derived!r}.  One of the two is wrong, and a "
            "curated structure may not disagree with itself."
        )


@lru_cache(maxsize=None)
def structure_corrections() -> tuple[StructureCorrection, ...]:
    """The curated structures, in file order.

    :raises FileNotFoundError: if the file is absent.  Not optional, for the
        reason `aggregate_measurements` gives: an empty mapping would look like
        a clean run while every substance here fell back to being wrong.
    :raises ValueError: if an entry disagrees with its own SMILES, names a
        class ChemROF does not have, or claims a registry number twice.
    """
    if not STRUCTURE_CORRECTIONS_FILEPATH.exists():
        raise FileNotFoundError(
            "Structure corrections not found at "
            f"{STRUCTURE_CORRECTIONS_FILEPATH}."
        )
    payload = orjson.loads(STRUCTURE_CORRECTIONS_FILEPATH.read_bytes())
    corrections: list[StructureCorrection] = []
    claimed: set[str] = set()
    for entry in payload["corrections"]:
        cas = str(entry["cas_number"]).strip()
        if cas in claimed:
            raise ValueError(
                f"structure-corrections.json: {cas} is corrected twice.  One "
                "substance cannot have two structures."
            )
        claimed.add(cas)
        smiles = str(entry["smiles"]).strip()
        values = structure_values_from_smiles(smiles)
        if values is None:
            raise ValueError(
                f"structure-corrections.json: {cas} states a SMILES that "
                f"cannot be read: {smiles!r}."
            )
        _check("an InChI", cas, str(entry["inchi"]).strip(), values.inchi)
        _check("an InChIKey", cas, str(entry["inchikey"]).strip(), values.inchikey)
        _check(
            "a molecular formula",
            cas,
            str(entry["molecular_formula"]).strip(),
            values.formula,
        )
        corrections.append(
            StructureCorrection(
                cas_number=cas,
                label=str(entry.get("label") or ""),
                # The canonical form rather than the curator's spelling, so
                # what is published is what every other structural value on the
                # record was derived from.
                smiles=values.smiles,
                inchi=values.inchi,
                inchikey=values.inchikey,
                molecular_formula=values.formula,
                molecular_mass=values.molecular_mass,
                monoisotopic_mass=values.monoisotopic_mass,
                flow_type=_flow_type_iri(cas, entry["flow_type"]),
                comment=str(entry.get("comment") or ""),
            )
        )
    return tuple(corrections)


def _flow_type_iri(cas: str, stated: Any) -> str:
    """The IRI for a stated ChemROF class name, or a refusal naming it."""
    try:
        return IRIS[Term(str(stated).strip())]
    except (KeyError, ValueError):
        raise ValueError(
            f"structure-corrections.json: {cas} states the class "
            f"{stated!r}, which is not a term this project publishes."
        ) from None


@lru_cache(maxsize=None)
def _by_cas() -> dict[str, StructureCorrection]:
    return {correction.cas_number: correction for correction in structure_corrections()}


def correction_for(cas_numbers: Any) -> StructureCorrection | None:
    """The correction one of *cas_numbers* claims, or ``None``.

    ``None`` where two of the flow's numbers are corrected differently: a flow
    carrying two numbers that are made of different things is two substances
    wearing one flow, and picking one of them would hide that rather than
    settle it.
    """
    if isinstance(cas_numbers, str):
        cas_numbers = [cas_numbers]
    found = {
        correction
        for cas in cas_numbers or []
        if isinstance(cas, str)
        and (correction := _by_cas().get(cas.strip())) is not None
    }
    return found.pop() if len(found) == 1 else None
