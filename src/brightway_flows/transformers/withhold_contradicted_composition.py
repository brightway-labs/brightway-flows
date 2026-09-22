"""Withdraw a structure whose composition the registry contradicts.

A substance can end up publishing two molecular formulas and two InChIKeys that
describe different things.  Nickel (ii) acetate is the example (#310)::

    molecular_formula   C2H4NiO2                      C4H6NiO4
    InChIKey            XMOKRCSXICGIDD-UHFFFAOYSA-N   AIYYMMQIMJOTBM-UHFFFAOYSA-L

One of those is the salt and one is not, and a consumer reading either field
gets two answers with nothing to choose between them.

**How the registry settles it.**  CAS registers 373-02-4 as `C2H4O2 . 1/2 Ni`
with a mass of 178.80 -- two acetic acids to one nickel, which is the salt.  The
composition is right and the ratio is the part that matters, because neither
SMILES nor InChI can hold half an atom: converting that formula to a structure
drops the fraction and yields `C2H4NiO2`, one acetic acid to one nickel.  So the
registry's *formula* is the field to ask, and its *structure* is the field that
lost the answer.  See `domain.formula` for the reading, and 274 registry records
carry such a ratio.

The same question, asked of a name-derived structure, points the other way.
`1,4-diazabicyclooctane` is not a complete name -- von Baeyer nomenclature needs
the bridge lengths, `[2.2.2]` -- and the name reader does not refuse it; it
returns `C14H28N2`, where DABCO is `C6H12N2`.  CAS registers 280-57-9 as
`C6H12N2`.  So the same test keeps the name-derived answer for the salt and
withdraws it for DABCO, which is the point: **nothing here is decided on which
stage produced a value.**

## How a value is judged

1. The flow's registry numbers give a registered composition, heavy atoms only,
   ratio multiplied out.  Where more than one number answers, every answer
   counts and a value matching any of them is kept -- two numbers on one flow
   is a disagreement of its own and not one to settle by withdrawing data.
2. Each published molecular formula is read the same way and compared.
3. **Only where the registry backs at least one published formula** is anything
   withdrawn.  Where it contradicts them all, the disagreement is real and
   belongs to a curator; where it backs them all, there is nothing to do.
4. The contradicted formulas go, and so does every structural value attested by
   *only* the stages that attested a contradicted formula and no surviving one.

Step 4 is what `domain.attestation` exists for.  Withdrawing a formula is easy;
withdrawing the InChIKey that came with it needs to know which key came from the
same place, and the `provenance` list is kept per property rather than per value
so it cannot be asked.

## What is deliberately not done

- **A value no stage attested is never withdrawn.**  Silence in `attested_by`
  means unknown -- a record written before that key existed, or by a stage that
  does not attest -- and unknown is not the same as unsupported.
- **The last surviving value of a property is never withdrawn**, even when the
  registry contradicts it.  A substance with no formula at all is worse than one
  whose formula is disputed, and the dispute is already reported.
- **Hydrogen is ignored** in every comparison, because a salt is its acid with
  the acidic hydrogens gone and the registry names the acid.  That makes ethane
  and ethene indistinguishable here, which is acceptable only because this asks
  whether a *second* value on a record contradicts the registry, never whether
  two substances are the same.
"""

from __future__ import annotations

import copy
from collections import Counter
from typing import Any

import structlog

from brightway_flows.domain.attestation import attested_by, prune
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.formula import Composition, published_heavy_atoms
from brightway_flows.domain.vocabulary import (
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_INCHI2D_STRING,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_MOLECULAR_MASS,
    CHEMROF_MONOISOTOPIC_MASS,
    CHEMROF_SMILES_STRING,
)
from brightway_flows.integrations.commonchemistry import (
    load_commonchemistry_index,
)
from brightway_flows.pipeline import Change, Transformer

logger = structlog.get_logger(__name__)

#: The properties a withdrawal reaches.  The formula is what is judged; the rest
#: are the values that describe the same structure and would otherwise be left
#: behind, still contradicting the formula that survived.  The masses are here
#: because they are derived from the composition -- a mass belonging to the
#: withdrawn formula is the same wrong answer stated as a number.
_STRUCTURAL_PROPERTIES = (
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_INCHI2D_STRING,
    CHEMROF_SMILES_STRING,
    CHEMROF_MOLECULAR_MASS,
    CHEMROF_MONOISOTOPIC_MASS,
)


def _values(entry: Any) -> list[str]:
    if not isinstance(entry, dict):
        return []
    raw = entry.get("@value")
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if not isinstance(raw, list):
        return []
    return [str(v).strip() for v in raw if str(v).strip()]


class WithholdContradictedCompositionTransformer(Transformer):
    """Withdraw structural values the registry's own composition contradicts.

    See the module docstring for how a value is judged and what is deliberately
    left alone.
    """

    name = "withhold_contradicted_composition"
    # Reads one flow's registry numbers and one flow's properties, against the
    # registry index `setup()` loaded.  Nothing about the other flows.
    answers_per_flow = True

    def setup(self) -> None:
        self._registry = load_commonchemistry_index()

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []
        settled = 0
        contradicted_everything = 0
        for flow in flows:
            change, outcome = self._process_flow(flow)
            if change is not None:
                changes.append(change)
            if outcome == "settled":
                settled += 1
            elif outcome == "contradicted_everything":
                contradicted_everything += 1
        logger.info(
            "withhold_contradicted_composition",
            flows_settled=settled,
            # Left alone on purpose: where the registry agrees with nothing the
            # substance publishes, the disagreement is a curator's.  Watch it
            # between runs -- it going up means a source has started supplying
            # compositions the registry does not recognise.
            flows_where_registry_agreed_with_nothing=contradicted_everything,
        )
        return changes

    def _registered_compositions(self, flow: Flow) -> set[Composition]:
        """What the registry says this flow's numbers are made of."""
        found: set[Composition] = set()
        for cas in flow.cas_numbers or []:
            if not isinstance(cas, str) or not cas.strip():
                continue
            composition = self._registry.registered_composition_for(cas)
            if composition is not None:
                found.add(composition)
        return found

    def _process_flow(self, flow: Flow) -> tuple[Change | None, str]:
        properties = flow.properties
        if not isinstance(properties, dict):
            return None, ""
        formula_entry = properties.get(CHEMROF_MOLECULAR_FORMULA)
        formulas = _values(formula_entry)
        if len(formulas) < 2:
            # One formula is not a contradiction, whatever the registry says.
            # Withdrawing it would leave the substance with none, and #310 is
            # about a record that answers twice, not about correcting a record
            # that answers once.
            return None, ""
        registered = self._registered_compositions(flow)
        if not registered:
            return None, ""

        backed: list[str] = []
        contradicted: list[str] = []
        for value in formulas:
            composition = published_heavy_atoms(value)
            if composition is None:
                continue  # unreadable says nothing; leave it alone
            (backed if composition in registered else contradicted).append(value)
        if not backed or not contradicted:
            return None, "contradicted_everything" if contradicted else ""

        # A stage that attested a surviving formula is not a stage to withdraw
        # anything from, even if it also attested a contradicted one: it agreed
        # with the registry somewhere, and the disagreement is then about which
        # of its own values is right, which this rule cannot answer.
        keep_sources = {
            source for value in backed for source in attested_by(formula_entry, value)
        }
        drop_sources = {
            source
            for value in contradicted
            for source in attested_by(formula_entry, value)
        } - keep_sources
        if not drop_sources:
            return None, ""

        new_properties = copy.deepcopy(properties)
        withdrawn: Counter[str] = Counter()
        for iri in _STRUCTURAL_PROPERTIES:
            entry = new_properties.get(iri)
            if not isinstance(entry, dict):
                continue
            values = _values(entry)
            if len(values) < 2:
                # Never the last one: a substance with no formula at all is
                # worse than one whose formula is disputed.
                continue
            kept = [
                value
                for value in values
                if not self._is_withdrawable(entry, value, drop_sources)
            ]
            if len(kept) == len(values) or not kept:
                continue
            entry["@value"] = kept
            prune(entry)
            new_properties[iri] = entry
            withdrawn[iri.rsplit("/", 1)[-1]] = len(values) - len(kept)

        if not withdrawn:
            return None, ""
        summary = ", ".join(f"{name} x{count}" for name, count in sorted(withdrawn.items()))
        return (
            Change(
                flow.uuid,
                "properties",
                new_properties,
                comment=(
                    "withhold_contradicted_composition: the registry registers "
                    f"{sorted(registered)!r}, contradicting {sorted(contradicted)!r} "
                    f"from {sorted(drop_sources)!r}; withdrew {summary}"
                ),
            ),
            "settled",
        )

    @staticmethod
    def _is_withdrawable(entry: dict[str, Any], value: str, drop_sources: set[str]) -> bool:
        """Whether *value* was attested only by stages the registry contradicted.

        Unattested is never withdrawable.  A record carrying values from before
        `attested_by` existed says nothing about where they came from, and
        silence read as "no support" would withdraw the whole record.
        """
        sources = set(attested_by(entry, value))
        return bool(sources) and sources <= drop_sources


__all__ = ["WithholdContradictedCompositionTransformer"]
