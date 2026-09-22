"""Publish the registry's composition where the pipeline worked out none.

#129 left `Antimony Trisulfide` with no molecular formula at all.  Its only one
had been `SSb+`, derived by reading the synonym `antimonous sulfide` -- a name
that does not say how many sulfur atoms there are -- and withdrawn because it
describes antimony *mono*sulfide, which the substance is not.

Withdrawing it was right and stopping there was not.  This project's own rule,
written in `withhold_contradicted_composition`, is that **a substance with no
formula at all is worse than one whose formula is disputed**; that module
therefore never withdraws the last surviving value.  #129 reached the same
substance from the other end and emptied the property anyway.

**The answer was already on hand.**  Common Chemistry registers 1345-04-6 as
`S3Sb2` -- Sb2S3, the composition the substance's own name states -- and has
done throughout.  Nothing asked it, because the question "what is this made of"
was only ever used to *judge* a derived formula, never to supply one.

## What may be published from such a number, and what may not

These numbers are the ambiguous third state `CommonChemistryIndex` keeps
separate: a formula on file and no structure.  The distinction is not a defect
in the registry, it is a fact about the substance -- CAS knows what Sb2S3 is
made of and does not publish a connection table for it.

So the composition is published and nothing else is.  No SMILES, no InChI, no
InChIKey, no mass: those are statements about *connectivity*, the registry
makes none, and inventing one from a composition would be exactly the mistake
#129 is about -- a confident structure standing in for an absent one.

## The registry alone is not enough, and that is the load-bearing part

A registry number is evidence about the number, not about the flow that carries
it, and this list has flows whose number is not quite what they are.  Requiring
only "no formula, and CAS knows one" fills **24** substances, and measuring them
is what showed the rule had to be narrower:

    Rhenium(2+)       would take `Re` -- the neutral element's composition,
                      from the element's registry number, published as the
                      formula of its 2+ cation
    Uranium Alpha     would take `U`.  It is the alpha-emitting isotopes of
                      uranium reported together as activity: not one substance
                      at all (#68), and certainly not uranium metal
    Correction Flow…  six accounting constructs would take `CO2`, `CH4`, `N2O`

So the substance's **own name must corroborate** the registry: it has to state
a count, and the count has to agree.  `Antimony Trisulfide` says three sulfurs
and CAS registers `S3Sb2`; two sources reached one answer independently, and
nothing is published on the strength of a registry number alone.

That leaves **one** substance today, which is the one #129 emptied.  A rule
that fires once is the right size here -- it is publishing a composition
nobody reviewed that would be the wrong size.

## Where it does not fire

- **Where the flow already publishes a formula.**  This fills a hole; it does
  not adjudicate between a derived answer and the registry's.  That comparison
  is `withhold_contradicted_composition`'s, it runs next, and it is better at
  it.
- **Where the flow's numbers disagree**, or where more than one distinct
  composition answers.  Two numbers on one flow is a disagreement of its own,
  and settling it by picking one would hide it.
- **Where CAS states no definite composition** -- `Unspecified`, an unreadable
  formula, or a multi-component string.  A UVCB has no formula to publish and
  saying so by silence is correct.
"""

from __future__ import annotations

import copy
from typing import Any

import structlog

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.composition import corroborates_name
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import coerce_pref_labels
from brightway_flows.domain.vocabulary import CHEMROF_MOLECULAR_FORMULA
from brightway_flows.integrations.commonchemistry import (
    load_commonchemistry_index,
)
from brightway_flows.pipeline import Change, Transformer
from brightway_flows.transformers.rdkit_enrichment import (
    _get_values,
    _set_definitive,
)

logger = structlog.get_logger(__name__)


def _pref_label_value(flow: Flow) -> str:
    """The flow's own name, which is what has to corroborate the registry."""
    labels = coerce_pref_labels(flow.prefLabel)
    return labels[0].value if labels else ""

#: What the published value is attributed to.  Named for the registry rather
#: than for this step, because the fact is CAS's and this step only carries it.
ACTIVITY = "commonchemistry_registered_composition"


class SupplyRegisteredCompositionTransformer(Transformer):
    """Write CAS's composition as the molecular formula, where there is none.

    See the module docstring for what is deliberately not written.
    """

    name = "supply_registered_composition"
    # One flow's registry numbers against the index `setup()` loaded.  Nothing
    # about the other flows.
    answers_per_flow = True

    def setup(self) -> None:
        self._registry = load_commonchemistry_index()

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []
        already_published = 0
        registry_had_none = 0
        numbers_disagreed = 0
        uncorroborated = 0
        for flow in flows:
            properties = flow.properties
            if not isinstance(properties, dict):
                continue
            if _get_values(properties, CHEMROF_MOLECULAR_FORMULA):
                already_published += 1
                continue
            formulas = self._registered_formulas(flow)
            if not formulas:
                registry_had_none += 1
                continue
            if len(formulas) > 1:
                numbers_disagreed += 1
                continue
            formula = formulas.pop()
            if not corroborates_name(formula, _pref_label_value(flow)):
                uncorroborated += 1
                continue
            changes.append(self._change(flow, properties, formula))
        logger.info(
            "supply_registered_composition",
            formulas_supplied=len(changes),
            flows_already_publishing_one=already_published,
            flows_the_registry_could_not_answer_for=registry_had_none,
            # The gate, and the number that says how much this rule is being
            # asked to take on trust.  Every one of these is a flow whose
            # registry number knows a composition its own name does not
            # confirm -- see the module docstring for the three shapes that
            # turned out to be, and why none of them may be published.
            flows_whose_name_did_not_corroborate=uncorroborated,
            # Watch this between runs.  A flow carrying two numbers that are
            # made of different things is two substances wearing one flow, and
            # that is worth being told about rather than resolved quietly.
            flows_whose_numbers_disagreed=numbers_disagreed,
        )
        return changes

    def _registered_formulas(self, flow: Flow) -> set[str]:
        """The distinct compositions this flow's registry numbers state."""
        found: set[str] = set()
        for cas in flow.cas_numbers or []:
            if not isinstance(cas, str) or not cas.strip():
                continue
            formula = self._registry.registered_formula_for(cas)
            if formula is not None:
                found.add(formula)
        return found

    def _change(
        self, flow: Flow, properties: dict[str, Any], formula: str
    ) -> Change:
        prov = Provenance(
            was_generated_by=ACTIVITY,
            was_attributed_to="CAS Common Chemistry",
            had_primary_source=sorted(
                cas
                for cas in flow.cas_numbers or []
                if isinstance(cas, str)
                and self._registry.registered_formula_for(cas) == formula
            ),
            was_derived_from="registered composition, no structure on file",
        ).to_dict()
        new_properties = copy.deepcopy(properties)
        _set_definitive(
            new_properties,
            CHEMROF_MOLECULAR_FORMULA,
            "molecular formula",
            formula,
            None,
            prov,
        )
        return Change(
            flow.uuid,
            "properties",
            new_properties,
            comment=(
                f"supply_registered_composition: {formula} from the registry, "
                "which publishes no structure for this number"
            ),
        )
