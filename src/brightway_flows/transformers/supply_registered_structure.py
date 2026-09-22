"""Publish the registry's structure where the pipeline derived none.

#129 taught the pipeline to publish the *composition* CAS registers for a
number, and `supply_registered_composition` does it.  The structure was left
alone deliberately, on a premise that module states plainly: these numbers are
"the ambiguous third state -- a formula on file and no structure", the registry
"makes no [connectivity statement]", and inventing one from a composition would
be the mistake #129 is about.

For a formula-only number all of that is exactly right.  It is not right for a
number CAS holds a **full InChI** for, and nothing ever asked.  `Disodium
Phosphonate` is the shape of it: CAS 13708-85-5, registered as `Disodium
hydrogen phosphite` with `Disodium phosphonate` among its synonyms, with
``InChI=1S/2Na.H3O3P/c;;1-4(2)3/h;;4H,(H2,1,2,3)`` and
``InChIKey=NOMFAOXRBCOULH-UHFFFAOYSA-N`` on file throughout, published by this
list as a label and a number and nothing else.

It arrives there through `registered_formula_for`, which refuses a
multi-component formula because ``C15H24O6.C4H11N`` is CAS stating two
substances in one string.  That refusal is right for a UVCB and wrong for a
salt, and **a full InChI on file is CAS's own statement of which one this is.**

## Detection strategy

A flow is eligible when it publishes no structure at all -- no InChI, no
InChIKey, no SMILES.  This step fills a hole; it never adjudicates between a
derived structure and the registry's.  That comparison belongs to
`withhold_contradicted_composition`, it runs next, and it is better at it.

Its registry numbers must reach exactly one structure.  Two numbers stating two
structures is a disagreement of its own, and settling it by picking one would
hide it -- the same rule, for the same reason, as the composition step.

## The corroboration, which is the load-bearing part

A registry number is evidence about the number, not about the flow that carries
it.  #129 solved that by requiring the substance's own name to **state a count**
the formula agrees with: `Antimony Trisulfide` says three sulfurs, CAS registers
`S3Sb2`, two sources reach one answer.

That test cannot be reused here, and measuring is what showed it: of the 35
substances that publish no structure while carrying a number CAS has one for,
`corroborates_name` accepts **none**.  Their names state no counts, because a
structure is not the kind of thing a name usually counts.

What these names *can* meet is the same two-source test in another form --
**the registry knows the substance under the name this list gives it.**
`Disodium Phosphonate` is a synonym CAS records for 13708-85-5.  See
:meth:`~brightway_flows.integrations.commonchemistry.CommonChemistryIndex.registers_name`.

That gate refuses every case #129's docstring warns about, and refuses each for
the right reason rather than by naming it:

    Correction Flow For Delayed Emission Of Fossil Carbon Dioxide (×6)
                      carries 124-38-9; CAS registers `Carbon dioxide` and
                      nothing calls it a correction flow
    Uranium Alpha     carries 7440-61-1; CAS registers `Uranium`.  Not a
                      substance at all (#68), and certainly not uranium metal
    Rhenium(2+)       carries 7440-15-5, the *neutral element's* number
    Curium Alpha, Plutonium-alpha
                      the same shape as `Uranium Alpha`

## Where it does not fire, beyond that

Three groups pass the name gate and must still be refused.  Each was found by
running the rule over a full build, not reasoned about in advance.

- **A nuclide.**  CAS registers 24678-82-8 as `Uranium` with ``InChI=1S/U`` --
  the elemental key -- so publishing it would collide `Uranium-238` with
  uranium metal under InChIKey.  That is #35, and the isotope machinery in
  `flow_layers.elements` is where an isotope's identity is settled.  Refused as
  a class rather than case by case, because 378784-45-3 carries a correct
  ``InChI=1S/Tc/i1+1`` and the registry is not consistent about which it gives.
- **A UVCB**, which CAS names in its own terms -- `reaction products with`,
  `reaction mass of`, `derivs.`, `compds. with`.  These do carry a full InChI,
  composed from the components the name lists, and it is a recipe rather than a
  structure: 101357-15-7 is aniline twice with nitrobenzene and hydrogen
  chloride.  See `registers_a_class_not_a_substance`.
- **An indefinite stoichiometry**, where the registered formula states a
  fraction or an unknown multiplier and so does not describe the same thing the
  registered InChI does: `Talc` at ``H2O3Si.3/4Mg`` against an InChI holding one
  magnesium, `Ulexite`, `Asbestos (white)`, and an octasodium dye at ``.xNa``.

Finally, **where the flow already publishes a formula it has to agree** --
compared as compositions rather than as strings, so that `C22H24N2O8.HCl` and
CAS's `C22H24N2O8.ClH` are the one substance they are.  `Hematite` publishes
`Fe2O3` and CAS registers `Fe.O`; the registry's answer is the vaguer of the
two and this step does not get to install it.

## What is published, and what is not

The InChI, the InChIKey and the composition, all attributed to the registry.

No SMILES and no mass.  Those would have to be *computed* from the InChI, and
the steps that compute them have already run by the time this one does -- see
its position in `DEFAULT_TRANSFORMERS`, which is where it has to be so that it
only ever fills a hole.  A record that gains an identity here and no mass is
saying exactly what is known about it, which is the same discipline
`supply_registered_composition` keeps when it publishes a composition and
refuses to derive a structure from it.

The composition **is** published, including the multi-component formulas
`registered_formula_for` refuses.  That refusal is a guard against reading a
UVCB's component list as a molecule, and every flow reaching this point has
already been shown not to be one: CAS holds a single structure for the number,
names the substance the way this list does, and does not call it a class.

Measured on the build of b03c940 (ecoinvent-3.12, ecoinvent-3.8, bafu-2026-v1):
9 substances publish a structure that published none, and 26 are refused.
"""

from __future__ import annotations

import copy
from typing import Any

import structlog

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.formula import registered_composition
from brightway_flows.domain.labels import coerce_pref_labels
from brightway_flows.domain.nuclides import parse_nuclide_label
from brightway_flows.domain.vocabulary import (
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_INCHI2D_STRING,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_SMILES_STRING,
)
from brightway_flows.integrations.commonchemistry import (
    load_commonchemistry_index,
)
from brightway_flows.pipeline import Change, Transformer
from brightway_flows.transformers.rdkit_enrichment import (
    _get_values,
    _set_definitive,
    _should_skip,
)

logger = structlog.get_logger(__name__)

#: What the published values are attributed to.  Named for the registry rather
#: than for this step, because the facts are CAS's and this step only carries
#: them -- the same naming as `supply_registered_composition`'s `ACTIVITY`.
ACTIVITY = "commonchemistry_registered_structure"

#: The properties whose presence means this flow already has an identity, and
#: so that there is no hole to fill.
_STRUCTURE_PROPERTIES = (
    CHEMROF_INCHI2D_STRING,
    CHEMROF_INCHI2D_KEY_STRING,
    CHEMROF_SMILES_STRING,
)


def _pref_label_value(flow: Flow) -> str:
    """The flow's own name, which is what the registry has to know it by."""
    labels = coerce_pref_labels(flow.prefLabel)
    return labels[0].value if labels else ""


class SupplyRegisteredStructureTransformer(Transformer):
    """Write CAS's structure where the pipeline derived none.

    See the module docstring for the corroboration this requires and for the
    four groups it deliberately refuses.
    """

    name = "supply_registered_structure"
    # One flow's registry numbers and its own name, against the index `setup()`
    # loaded.  Nothing about the other flows.
    answers_per_flow = True

    def setup(self) -> None:
        self._registry = load_commonchemistry_index()

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []
        counts: dict[str, int] = {
            "already_published": 0,
            "registry_had_none": 0,
            "numbers_disagreed": 0,
            "name_not_registered": 0,
            "nuclide": 0,
            "registers_a_class": 0,
            "indefinite_stoichiometry": 0,
            "own_formula_disagreed": 0,
        }
        for flow in flows:
            properties = flow.properties
            if not isinstance(properties, dict):
                continue
            # The same guard the RDKit steps use, for the same reason: an
            # element flow's identity is settled by the element layer, not from
            # a registry number that names the metal.
            if _should_skip(flow, properties):
                continue
            if any(_get_values(properties, iri) for iri in _STRUCTURE_PROPERTIES):
                counts["already_published"] += 1
                continue
            refusal, cas = self._structure_number_for(flow)
            if refusal is not None:
                counts[refusal] += 1
                continue
            changes.append(self._change(flow, properties, cas))
        logger.info(
            "supply_registered_structure",
            structures_supplied=len(changes),
            flows_already_publishing_one=counts["already_published"],
            flows_the_registry_could_not_answer_for=counts["registry_had_none"],
            # The gate, and the number that says how much this rule is *not*
            # taking on trust: a flow whose number CAS holds a structure for
            # while CAS does not know the substance by this list's name for it.
            # Every case #129 warns about is counted here.
            flows_whose_name_the_registry_does_not_register=counts["name_not_registered"],
            # Watch this between runs, for the same reason the composition step
            # watches its own: a flow carrying two numbers that reach two
            # structures is two substances wearing one flow.
            flows_whose_numbers_disagreed=counts["numbers_disagreed"],
            flows_refused_as_a_nuclide=counts["nuclide"],
            flows_refused_as_a_registered_class=counts["registers_a_class"],
            flows_refused_for_indefinite_stoichiometry=counts["indefinite_stoichiometry"],
            flows_whose_own_composition_disagreed=counts["own_formula_disagreed"],
        )
        return changes

    def _structure_number_for(self, flow: Flow) -> tuple[str | None, str]:
        """The number whose structure *flow* may publish, or why it may not.

        Returns `(None, cas)` when one may be published and `(reason, "")`
        otherwise, where *reason* is a key of the counter in `transform`.  The
        order of the checks is the order of the module docstring, and it is the
        order the counters read in: a flow refused for two reasons is counted
        under the first, so `flows_whose_name_the_registry_does_not_register`
        means what it says rather than "and was not also a nuclide".
        """
        numbers = [
            cas.strip()
            for cas in flow.cas_numbers or []
            if isinstance(cas, str) and cas.strip()
        ]
        with_structure = sorted(
            {cas for cas in numbers if self._registry.has_structure(cas)}
        )
        if not with_structure:
            return "registry_had_none", ""
        if len({self._registry.inchikey_for(cas) for cas in with_structure}) > 1:
            return "numbers_disagreed", ""
        label = _pref_label_value(flow)
        named = [
            cas for cas in with_structure if self._registry.registers_name(cas, label)
        ]
        if not named:
            return "name_not_registered", ""
        cas = named[0]
        if parse_nuclide_label(label) is not None:
            return "nuclide", ""
        if self._registry.registers_a_class_not_a_substance(cas):
            return "registers_a_class", ""
        if self._registry.registers_indefinite_stoichiometry(cas):
            return "indefinite_stoichiometry", ""
        if self._contradicts_own_composition(flow, cas):
            return "own_formula_disagreed", ""
        return None, cas

    def _contradicts_own_composition(self, flow: Flow, cas: str) -> bool:
        """Whether the flow's own formula says something else than the registry.

        Compared as compositions, not as strings: CAS writes tetracycline
        hydrochloride's salt as ``C22H24N2O8.ClH`` and this list derived
        ``C22H24N2O8.HCl``, which is one substance written two ways, and a
        string comparison would refuse it.

        False where either side cannot be read.  That is the same reading
        `contradicts_name` takes -- a composition nobody can parse is a
        question this cannot answer rather than one it answers no to.
        """
        properties = flow.properties if isinstance(flow.properties, dict) else {}
        own = _get_values(properties, CHEMROF_MOLECULAR_FORMULA)
        if not own:
            return False
        theirs = registered_composition(self._registry.formula_for(cas) or "")
        if theirs is None:
            return False
        ours = [registered_composition(value) for value in own]
        readable = [value for value in ours if value is not None]
        if not readable:
            return False
        return all(value != theirs for value in readable)

    def _change(self, flow: Flow, properties: dict[str, Any], cas: str) -> Change:
        inchi = self._registry.inchi_for(cas) or ""
        inchikey = self._registry.inchikey_for(cas) or ""
        formula = self._registry.formula_for(cas) or ""
        prov = Provenance(
            was_generated_by=ACTIVITY,
            was_attributed_to="CAS Common Chemistry",
            had_primary_source=[cas],
            was_derived_from="registered structure, corroborated by a registered name",
        ).to_dict()
        new_properties = copy.deepcopy(properties)
        # The key is written bare, as every other writer here holds it: the
        # cache ships it prefixed `InChIKey=`, and that prefix is a display
        # convention rather than part of the value a consumer joins on.
        _set_definitive(
            new_properties,
            CHEMROF_INCHI2D_KEY_STRING,
            "InChIKey",
            inchikey.split("=", 1)[-1].strip(),
            None,
            prov,
        )
        _set_definitive(
            new_properties, CHEMROF_INCHI2D_STRING, "InChI", inchi, None, prov
        )
        # Only where there is none.  A flow whose own composition agrees reached
        # here past `_contradicts_own_composition`, and its value was derived by
        # a step that also said how -- overwriting it with the same answer would
        # replace that attribution with this one for no gain.
        if formula and not _get_values(properties, CHEMROF_MOLECULAR_FORMULA):
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
                f"supply_registered_structure: {inchikey or inchi} from the "
                f"registry, which registers {cas} under this substance's name"
            ),
        )
