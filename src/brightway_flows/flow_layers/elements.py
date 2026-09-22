"""Writing element and isotope facts onto the flow objects a run produced.

The pass matches PubChem elements to existing **base list** flow objects by
label and enriches those in place -- it adds no objects of its own -- and
matches the kBq flow objects against the isotope tables, which is how a
consensus flow comes to carry a nuclide, a half-life and a specific activity.
It then hands the same objects to the ion enrichment, which depends on the
element typing done here.

Seeded from the base list only, deliberately.  A substance that arrives only
through a merged list gets no element or isotope enrichment: the periodic table
is matched against the one list whose labels are curated for that purpose, and a
merged list's row reaches this pass only once it has been matched onto a
consensus flow the base list already named.  That was an undeclared consequence
of `row.source == "EF 3.1"` before #14; it is now stated at the guard.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

import httpx

from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow_object import FlowObject, stable_flow_object_id
from brightway_flows.domain.nuclides import (
    ELEMENTS,
    Nuclide,
    half_life_days,
    parse_nuclide,
    parse_nuclide_label,
)
from brightway_flows.domain.vocabulary import (
    CHEMROF_ATOMIC_NUMBER,
    CHEMROF_MOLECULAR_FORMULA,
    CHEMROF_CHEMICAL_ELEMENT,
    CHEMROF_SYMBOL,
    QUDT_HAS_UNIT,
    RDFS_LABEL_CURIE,
    UNIT_IRI_NUM,
)
from brightway_flows.flow_layers.element_cache import (
    _load_chemlin_cache,
    _load_or_fetch_pubchem_element_cache,
    _parse_relative_abundance,
    _resolve_chemlin_isotope_data,
    _save_chemlin_cache,
)
from brightway_flows.flow_layers.ions import enrich_monoatomic_ions
from brightway_flows.flow_layers.labels import (
    _canonical_name,
    _label_entry,
    _object_alt_label_values,
    _object_pref_label_value,
    _reference_key,
)
from brightway_flows.flow_layers.provenance import _element_property_provenance
from brightway_flows.sources import base_source_label

#: Property key recording which base-list flows an element object was matched
#: to.  Published in `flow_objects.properties` and read by the element-coverage
#: review table, so it names the base list of the day it was minted rather than
#: the base list: renaming it is a data migration, not a refactor (#14).
BASE_REFERENCES_PROPERTY = "ef31_references"

#: How far the two half-lives may differ before the record is refused.  They
#: come from independent sources for the same nuclide, so agreement is the
#: normal case and a factor of two is generous -- the disagreements this exists
#: to catch are one source answering for a different nuclide, which puts them
#: orders of magnitude apart rather than percentages.
HALF_LIFE_AGREEMENT_FACTOR = 2.0

#: The element name for a nuclide, for reporting which elements a run could not
#: link its isotopes to.
_ELEMENT_NAME_BY_SYMBOL = {symbol: name for _, symbol, name in ELEMENTS}


def _element_name_for(nuclide: Nuclide) -> str:
    return _ELEMENT_NAME_BY_SYMBOL.get(nuclide.symbol, nuclide.symbol)


#: What `created_from.resolver` says on an element this pass minted, so the
#: object names the pass that made it rather than a source flow it came from.
MINTED_ELEMENT_RESOLVER = "element_enrichment_minted_element_v1"


def _could_be_the_element(obj: FlowObject | None, *, symbol: str) -> bool:
    """Whether *obj* could be the element itself, rather than something of it.

    The bound on the synonym fallback in :func:`enrich_elements`, and it exists
    because that fallback found two things wearing an element's name that were
    not the element (#327).

    **A nuclide is not its element.**  EF 3.1's `Neptunium-237` carries the
    synonym `NEPTUNIUM`, and EF ships no flow called `Neptunium` at all, so the
    fallback found the isotope and gave it neptunium's atomic number, symbol and
    isotope list -- and the element object the nuclides point at stopped being
    minted, so `Neptunium` vanished from the published list.

    **An allotrope is not its element either.**  `Dinitrogen` carries `nitrogen`
    among its synonyms and EF ships no flow called `Nitrogen`, so the same
    fallback typed N2 as `ChemicalElement`.  It is an allotrope: two atoms of
    nitrogen, not the element.

    The formula settles both, and settles them the same way a chemist would: the
    element is the substance whose formula is the bare symbol.  `Al` is
    aluminium; `N2` is not nitrogen; `Np` on a nuclide is caught by the nuclide
    test before the formula is asked.

    An object stating no formula is allowed through, because a great many base
    list objects state none and refusing them would turn this fallback off for
    every element whose published name simply differs in spelling -- which is
    the case it exists for.  What stops that being a hole is the caller's other
    condition: exactly one object may answer for an element, so a nameless
    candidate has to be the only one.
    """
    if obj is None:
        return False
    if parse_nuclide_label(_object_pref_label_value(obj)) is not None:
        return False
    properties = obj.properties
    if not isinstance(properties, dict):
        return True
    entry = properties.get(CHEMROF_MOLECULAR_FORMULA)
    if not isinstance(entry, dict):
        return True
    formulas = entry.get("@value")
    if not isinstance(formulas, list):
        formulas = [formulas]
    stated = {str(value).strip() for value in formulas if str(value or "").strip()}
    if not stated:
        return True
    return symbol.strip() in stated


def _mint_missing_element_objects(
    by_id: dict[str, FlowObject],
    *,
    elements: list[Any],
    kbq_flow_object_ids: set[str],
    target_element_object_id_by_atomic_number: dict[int, str],
) -> dict[int, str]:
    """Give an element with isotopes in the list, but no flow of its own, an object.

    `chemrof:has_element` has range `ChemicalElement`, so the target has to
    exist as an object for the triple to say anything.  Four elements appear in
    both source lists **only as nuclides** -- there is no `Americium` flow, no
    `Neptunium`, no `Promethium`, no `Technetium` -- so five isotope objects had
    nothing to point at and published the link empty.

    This pass had added no objects since #14, and the docstring above says so.
    The policy it states is about *enrichment*: the periodic table is matched
    against the base list's curated labels rather than being poured into the
    list wholesale, and that still holds -- an element is minted here only when
    the list already carries its isotopes, so the run is completing a substance
    it is already publishing rather than importing one it is not.

    The minted objects are the **first flow objects with no elementary flows**.
    That is what they are: a flow object is a substance and an elementary flow
    is an occurrence, and this list has americium as a substance without having
    an occurrence of americium.  Both layers publish as `skos:Concept`, so a
    concept with no occurrences is a vocabulary entry rather than a broken row;
    the review app counts a substance's flows with a subquery and shows nought.

    The guard is exactly the condition that prevents a duplicate: if a source
    list ever does carry an `Americium` flow, the match above succeeds, nothing
    is minted, and the element is that flow's object.  The identifier changes on
    that day -- `element:Am` is not the CAS a source flow would bring -- which
    is the same trade every grouping key here makes.

    Returns the atomic numbers minted, mapped to their new object ids.
    """
    wanted: dict[int, dict[str, Any]] = {}
    by_atomic_number = {
        int(element["atomic_number"]): element
        for element in elements
        if isinstance(element, dict) and isinstance(element.get("atomic_number"), int)
    }
    for foid in sorted(kbq_flow_object_ids):
        obj = by_id.get(foid)
        if obj is None:
            continue
        nuclide = parse_nuclide_label(_object_pref_label_value(obj))
        if nuclide is None:
            continue
        if nuclide.atomic_number in target_element_object_id_by_atomic_number:
            continue
        element = by_atomic_number.get(nuclide.atomic_number)
        if element is not None:
            wanted[nuclide.atomic_number] = element

    minted: dict[int, str] = {}
    for atomic_number, element in sorted(wanted.items()):
        symbol = str(element.get("symbol") or "").strip()
        name = str(element.get("name") or "").strip()
        if not symbol or not name:
            continue
        object_id = stable_flow_object_id("fo", f"element:{symbol}")
        if object_id in by_id:
            continue
        by_id[object_id] = FlowObject(
            flow_object_id=object_id,
            prefLabel=[
                _label_entry(
                    value=name,
                    language="en",
                    resolver_name=MINTED_ELEMENT_RESOLVER,
                    seed_source=str(element.get("page_url") or ""),
                    was_derived_from="pubchem.element.name",
                )
            ],
            altLabel=[],
            properties={},
            references=sorted(
                {
                    url
                    for url in (
                        str(element.get("page_url") or "").strip(),
                        str(element.get("api_url") or "").strip(),
                    )
                    if url
                }
            ),
            created_from={
                "resolver": MINTED_ELEMENT_RESOLVER,
                "reason": "isotopes_in_the_list_with_no_flow_object_for_the_element",
                "atomic_number": atomic_number,
                "symbol": symbol,
            },
        )
        # The enrichment loop below reads this map, so the minted object picks
        # up its symbol, atomic number, periodic-table bag, `ChemicalElement`
        # type and isotope summary by the same path every other element does.
        target_element_object_id_by_atomic_number[atomic_number] = object_id
        minted[atomic_number] = object_id
    return minted


def _resolve_metastable_state(
    claimed: Nuclide,
    *,
    isomers_by_symbol_mass: dict[tuple[str, int], list[tuple[Nuclide, str]]],
) -> tuple[Nuclide, dict[str, Any]]:
    """Which excited state a label's bare ``m`` names.

    An inventory writes one letter.  The nuclear data uses several: PubChem
    orders the excited states ``m``, ``n``, ``p``, ``q`` by excitation energy,
    and ChemLIN calls the same ones ``m``, ``m1``, ``m2``, ``m3``.  Energy
    order is not lifetime order, so the state a source *means* -- the one it
    can inventory, which is the one that lives long enough to be measured -- is
    not reliably the first one listed.

    ``Silver-110m`` is the case that matters, and the whole of the class this
    list carries: of its 74 mass numbers, silver-110 is the only one whose
    ground state is outlived by an excited state.  PubChem files that state as
    ``110Agn`` at 249.863 days and gives ``110Agm`` to a 660-nanosecond state no
    inventory reports.  Taking the letter literally binds the label to the 660 ns
    row, which is a worse record than the ground state it replaced and one no
    check here can see: an isomer decaying by isomeric transition is exactly what
    an isomer does (#24).

    So a bare ``m`` resolves to the longest-lived excited state rather than to
    the state spelled ``m``.  This is the convention ``element_cache`` already
    states for the ChemLIN slugs -- "the longest-lived candidate is the one an
    inventory means when it writes a bare `m`" -- applied on the PubChem side,
    where it was missing.  It changes nothing for the seven isomers the list
    carries today: ``Kr-85m``, ``Xe-133m``, ``Tc-99m``, ``Te-123m``, ``Xe-131m``,
    ``Xe-135m`` and ``Pa-234m`` all have ``m`` as their longest-lived state, and
    a test pins that.

    Only a bare ``m`` is resolved.  ``Ag-110n`` names a state rather than
    invoking a convention, and is looked up as written.

    Returns the nuclide to look up and a record of how it was chosen, which is
    published on the object whether the choice moved it or not.
    """
    resolution: dict[str, Any] = {
        "claimed_state": claimed.state,
        "selected_state": claimed.state,
        "strategy": "state_taken_as_written",
        "candidates": [],
    }
    if claimed.state != "m":
        return claimed, resolution
    candidates = isomers_by_symbol_mass.get((claimed.symbol, claimed.mass_number), [])
    if len(candidates) < 2:
        # One excited state, or none at all: the convention has nothing to
        # choose between, and the letter is read as written.
        return claimed, resolution

    def rank(item: tuple[Nuclide, str]) -> tuple[float, str]:
        nuclide, half_life = item
        days = half_life_days(half_life)
        # A state PubChem gives no readable half-life for cannot be ranked and
        # must not win by default.  It sorts last, and the state letter breaks
        # a tie so the choice does not depend on the order of the rows.
        return (days if isinstance(days, float) else -1.0, nuclide.state)

    selected = max(candidates, key=rank)[0]
    resolution.update({
        "selected_state": selected.state,
        "strategy": (
            "longest_lived_metastable_state"
            if selected != claimed
            else "state_taken_as_written"
        ),
        "candidates": [
            {"nuclide": nuclide.key, "half_life_and_uncertainty": half_life}
            for nuclide, half_life in sorted(candidates, key=lambda item: item[0].state)
        ],
    })
    return selected, resolution


def _nuclide_record_checks(
    *, nuclide: Nuclide, record: dict[str, Any]
) -> list[dict[str, Any]]:
    """What has to hold before a nuclide record is published.

    Each check is recorded with its outcome whether it passes or not, so the
    reason a record was withheld is on the object rather than in a log, and so
    the checks that did run are visible on the ones that were published.

    None of these could fire on well-formed data.  They exist because all three
    have fired: a ground state was published decaying by isomeric transition 31
    times over, and the two half-life sources disagreed by up to eight orders of
    magnitude while both were reported as matched.
    """
    checks: list[dict[str, Any]] = []

    # A ground state has no higher state to fall from, so isomeric transition
    # is not available to it.  This is the cheapest statement of "the record
    # and the label are about different nuclides", and it needs no second
    # source to make it.
    decay_modes = str(record.get("decay_modes") or "")
    checks.append({
        "check": "ground_state_does_not_decay_by_isomeric_transition",
        "passed": not (nuclide.is_ground_state and "IT" in decay_modes),
        "detail": decay_modes,
    })

    # PubChem and ChemLIN answered separately for the same nuclide.  Where both
    # have a number they have to be the same number.
    #
    # A *stable* nuclide has no number: `half_life_days` returns infinity for
    # it, which is what the ranking in `element_cache` needs and what the
    # comparison below must not see.  Argon-40 and Xenon-131 are stable, both
    # sources say so, and dividing one infinity by the other is a NaN that
    # fails every comparison it is put through -- so agreeing perfectly read as
    # disagreeing and the record was withheld.  Two sources that both decline
    # to give a half-life have not contradicted each other.
    pubchem_days = half_life_days(str(record.get("half_life_and_uncertainty") or ""))
    chemlin_days = half_life_days(str(record.get("half_life_chemlin") or ""))
    comparable = [
        value
        for value in (pubchem_days, chemlin_days)
        if isinstance(value, float) and math.isfinite(value) and value > 0
    ]
    if len(comparable) == 2:
        ratio = max(pubchem_days / chemlin_days, chemlin_days / pubchem_days)
        checks.append({
            "check": "half_life_sources_agree",
            "passed": ratio <= HALF_LIFE_AGREEMENT_FACTOR,
            "detail": {
                "pubchem_days": pubchem_days,
                "chemlin_days": chemlin_days,
                "ratio": ratio,
            },
        })

    return checks


def _augment_with_element_and_isotope_flow_objects(
    flow_objects: list[FlowObject],
    elementary_flows: list[ElementaryFlow],
) -> tuple[list[FlowObject], dict[str, int]]:
    """Enrich the element flow objects a run has, and its kBq isotope flows.

    Adds objects again, in one bounded case: an element with isotopes in the
    list and no flow object of its own.  `element_flow_object_count_added` was
    a hardcoded zero and is a real count again.  See
    `_mint_missing_element_objects` for why that is not a reversal of the
    base-list-only policy in the module docstring.

    Every other element still reaches a flow object only by matching one that is
    already there.
    """
    payload = _load_or_fetch_pubchem_element_cache()
    elements = payload.get("elements", [])
    if not isinstance(elements, list):
        return flow_objects, {
            "element_flow_object_count_added": 0,
            "isotope_flow_object_count_added": 0,
            "isotope_kbq_candidate_flow_object_count": 0,
            "isotope_kbq_matched_flow_object_count": 0,
            "isotope_kbq_unmatched_flow_object_count": 0,
            "short_lived_isotopes_not_in_consensus_count": 0,
        }

    by_id: dict[str, FlowObject] = {
        row.flow_object_id: row for row in flow_objects if row.flow_object_id
    }

    # Seeded from the base list only, deliberately: a row that arrived through
    # a merged list is not a candidate for element enrichment.  See the module
    # docstring -- this is a decision about the data, not an accident of the
    # comparison.
    base_label = base_source_label()
    ef_object_ids = {
        row.flow_object_id
        for row in elementary_flows
        if row.source == base_label and row.flow_object_id
    }
    ef_by_canon_pref: dict[str, set[str]] = {}
    #: The same index over *alternative* labels, and it is the fallback rather
    #: than a second opinion: an element is matched on its published name and on
    #: its symbol, and only where neither finds anything is a synonym consulted.
    #:
    #: One element needs it, and the reason is a single letter.  PubChem calls
    #: element 13 `Aluminum`; this list publishes IUPAC's `Aluminium`; the symbol
    #: `Al` is nobody's published name.  So aluminium matched nothing, was never
    #: typed `ChemicalElement`, and carried none of the atomic number, symbol,
    #: element link or isotope list that the other 92 elements carry -- and
    #: because the ion layer finds an ion by resolving its base name against an
    #: object typed `ChemicalElement`, EF's `aluminium (iii)` was never
    #: recognised as an ion of it either (#327).
    #:
    #: `aluminum` is already on the object as a synonym, so the spelling this
    #: needs is in the data rather than in a list somebody has to keep.
    ef_by_canon_alt: dict[str, set[str]] = {}
    for foid in ef_object_ids:
        obj = by_id.get(foid)
        if obj is None:
            continue
        pref_label = _object_pref_label_value(obj)
        if isinstance(pref_label, str) and pref_label.strip():
            ef_by_canon_pref.setdefault(_canonical_name(pref_label), set()).add(foid)
        for alt in _object_alt_label_values(obj):
            if isinstance(alt, str) and alt.strip():
                ef_by_canon_alt.setdefault(_canonical_name(alt), set()).add(foid)

    ef_elem_ids_by_object: dict[str, list[str]] = {}
    for row in elementary_flows:
        if row.source == base_label and row.flow_object_id and row.elementary_flow_id:
            ef_elem_ids_by_object.setdefault(row.flow_object_id, []).append(
                row.elementary_flow_id
            )

    # Identify candidate isotope flow objects from existing consensus flows by unit.
    kbq_flow_object_ids: set[str] = {
        row.flow_object_id
        for row in elementary_flows
        if row.flow_object_id and str(row.unit or "").strip().lower() == "kbq"
    }
    kbq_flow_object_ids = {x for x in kbq_flow_object_ids if x in by_id}

    # Index the nuclide rows by *identity*.
    #
    # This was a dictionary keyed by every name a row might go by -- `238U`,
    # `U238`, `U-238`, `Uranium-238`, `Uranium 238` and eight more.  An isomer
    # and its ground state differ in exactly one of those spellings and share
    # the rest, so `238Um` claimed `Uranium-238` as well, the assignment
    # overwrote, and whichever row PubChem happened to list last won the ground
    # state's name.  37 of the 79 published nuclides ended up carrying an
    # isomer's half-life, decay mode and specific activity under a ground
    # state's label: Potassium-40 shipped at 336 nanoseconds against 1.25
    # billion years, Uranium-238 at 280 nanoseconds against 4.5 billion
    # (#18).  Nothing recorded that a choice had been made.
    #
    # `Nuclide` is the triple those rows actually differ in, so keying by it
    # makes the collision impossible rather than unlikely, and drops the
    # dependency on PubChem's row order.
    isotope_by_nuclide: dict[Nuclide, tuple[dict[str, Any], dict[str, Any]]] = {}
    #: Every mass number the nuclear data holds for an element, in any state.
    #: A label naming one the tables have never heard of is a defect in the
    #: label rather than a gap in the data -- `Palladium-234m` is
    #: protactinium-234m, and palladium stops at about mass 128 (#20) -- and
    #: this is what lets the run say which of the two it is.
    known_mass_numbers: dict[str, set[int]] = {}
    #: The excited states each mass number has, with the half-life PubChem gives
    #: each -- what `_resolve_metastable_state` needs to say which one a bare
    #: `m` in a label means (#24).
    isomers_by_symbol_mass: dict[tuple[str, int], list[tuple[Nuclide, str]]] = {}
    isotope_rows_by_element_atomic_number: dict[int, list[dict[str, Any]]] = {}
    stable_abundance_by_symbol_mass: dict[tuple[str, int], float] = {}
    element_short_lived_counts: dict[int, int] = {}
    unparsed_nuclide_rows = 0
    for element in elements:
        try:
            atomic_number = int(element.get("atomic_number"))
        except Exception:
            continue
        symbol = str(element.get("symbol") or "").strip()
        isotope_rows = element.get("isotope_decay", [])
        if not isinstance(isotope_rows, list):
            continue
        isotope_rows_by_element_atomic_number[atomic_number] = isotope_rows
        stable_rows = element.get("stable_isotopes", [])
        if isinstance(stable_rows, list):
            for stable in stable_rows:
                if not isinstance(stable, dict):
                    continue
                stable_nuclide = parse_nuclide(
                    str(stable.get("nuclide") or ""), symbol=symbol
                )
                if stable_nuclide is None:
                    continue
                known_mass_numbers.setdefault(symbol, set()).add(
                    stable_nuclide.mass_number
                )
                abundance = _parse_relative_abundance(str(stable.get("abundance_uncertainty") or ""))
                if abundance is not None:
                    stable_abundance_by_symbol_mass[
                        (stable_nuclide.symbol, stable_nuclide.mass_number)
                    ] = abundance
        short_lived = 0
        for iso in isotope_rows:
            if not isinstance(iso, dict):
                continue
            half_life_text = str(iso.get("half_life_and_uncertainty") or "").strip()
            days = half_life_days(half_life_text)
            if days is not None and days < 1.0:
                short_lived += 1
            nuclide = parse_nuclide(str(iso.get("nuclide") or ""), symbol=symbol)
            if nuclide is None:
                # A state letter outside the set the tables use, or a row whose
                # nuclide does not belong to the element it is filed under.
                # Counted rather than guessed at: every one of the 5,829 rows
                # in the cache parses today, so a non-zero count here is the
                # cache having changed shape.
                unparsed_nuclide_rows += 1
                continue
            known_mass_numbers.setdefault(symbol, set()).add(nuclide.mass_number)
            if not nuclide.is_ground_state:
                isomers_by_symbol_mass.setdefault(
                    (nuclide.symbol, nuclide.mass_number), []
                ).append((nuclide, half_life_text))
            # First row wins, and no row can displace another: within one
            # element PubChem lists each nuclide once, so this only guards
            # against a duplicated row rather than resolving a real conflict.
            isotope_by_nuclide.setdefault(nuclide, (element, iso))
        element_short_lived_counts[atomic_number] = short_lived

    chemlin_cache = _load_chemlin_cache()
    chemlin_records = chemlin_cache.get("records", {})
    if not isinstance(chemlin_records, dict):
        chemlin_records = {}
        chemlin_cache["records"] = chemlin_records
    chemlin_dirty = False
    chemlin_client = httpx.Client(
        timeout=20.0,
        headers={"User-Agent": "brightway-flows/1.0.0 (+https://example.org)"},
    )
    # Prefer enriching existing EF-linked flow objects for elements, keyed by atomic number.
    target_element_object_id_by_atomic_number: dict[int, str] = {}
    matched_ef_obj_ids_by_atomic_number: dict[int, set[str]] = {}
    matched_ef_elem_ids_by_atomic_number: dict[int, list[str]] = {}
    #: Elements reached only through a synonym.  Counted rather than left silent:
    #: this is the fallback, and a build where it starts answering for several
    #: elements is a build where the published names have drifted from the
    #: periodic table rather than one where the fallback is doing its job.
    matched_on_a_synonym = 0
    for element in elements:
        if not isinstance(element, dict):
            continue
        try:
            atomic_number = int(element.get("atomic_number"))
        except Exception:
            continue
        symbol = str(element.get("symbol") or "").strip()
        name = str(element.get("name") or "").strip()
        if not symbol or not name:
            continue
        canon_candidates = {_canonical_name(name), _canonical_name(symbol)}
        matched_ef_obj_ids: set[str] = set()
        for canon in canon_candidates:
            matched_ef_obj_ids.update(ef_by_canon_pref.get(canon, set()))
        if not matched_ef_obj_ids:
            # Only the element's own name, never its symbol: `Al`, `As` and `In`
            # are ordinary words and two-letter fragments, and a symbol matched
            # against 444 synonyms of one substance would find something for
            # reasons having nothing to do with chemistry.
            #
            # And only where exactly one object answers.  A name that two
            # substances both carry as a synonym is not evidence about which of
            # them is the element -- it is the ambiguity this fallback exists
            # below the pref-label match to avoid (#327).
            # And never onto a nuclide.  An isotope carries its element's bare
            # name among its synonyms, so `Neptunium-237` answers to `neptunium`
            # -- and a build that let it took neptunium's atomic number, symbol
            # and isotope list onto the isotope, and stopped minting the element
            # object the nuclides point at.  Caught by a build, which is the only
            # thing that could have caught it: the substance disappeared from the
            # published list and nothing else moved.
            #
            # `parse_nuclide_label` is the module's own test for that, so this
            # asks the question the same way the isotope machinery does.
            by_alt = {
                object_id
                for object_id in ef_by_canon_alt.get(_canonical_name(name), set())
                if _could_be_the_element(by_id.get(object_id), symbol=symbol)
            }
            if len(by_alt) == 1:
                matched_ef_obj_ids = set(by_alt)
                matched_on_a_synonym += 1
        if not matched_ef_obj_ids:
            continue
        matched_ef_elem_ids = sorted({
            eid
            for foid in matched_ef_obj_ids
            for eid in ef_elem_ids_by_object.get(foid, [])
        })
        # Pick a stable target to avoid creating duplicate element flow objects.
        target_id = sorted(matched_ef_obj_ids)[0]
        target_element_object_id_by_atomic_number[atomic_number] = target_id
        matched_ef_obj_ids_by_atomic_number[atomic_number] = matched_ef_obj_ids
        matched_ef_elem_ids_by_atomic_number[atomic_number] = matched_ef_elem_ids

    minted_element_objects = _mint_missing_element_objects(
        by_id,
        elements=elements,
        kbq_flow_object_ids=kbq_flow_object_ids,
        target_element_object_id_by_atomic_number=target_element_object_id_by_atomic_number,
    )

    # Match existing kBq flow objects to isotope rows.
    matched_by_kbq_object: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    matched_count_by_element_atomic_number: dict[int, int] = {}
    unmatched_kbq_objects: set[str] = set()
    unmatched_reasons: Counter = Counter()
    #: Objects that matched a nuclide row and then failed a check on it.  Kept
    #: apart from the unmatched: nothing was wrong with the *lookup*, and the
    #: fix for one of these is a correction to a source rather than to a label.
    withheld_kbq_objects: set[str] = set()
    withheld_reasons: Counter = Counter()
    #: Elements whose isotopes could not be linked, by name.  Named rather than
    #: counted, because the fix is per element and the list is short.
    unlinked_elements: Counter = Counter()
    for foid in kbq_flow_object_ids:
        obj = by_id.get(foid)
        if obj is None:
            continue
        # The **preferred label only**, and never a synonym.
        #
        # The alternative labels used to be searched as well, and the first one
        # that hit anything won.  `Praseodym-147` is a truncated name that no
        # nuclide parser will read, and the object carries `Praseodymium-141`
        # as a synonym -- inherited from the element, along with the element's
        # CAS -- so the fallback answered with the *stable* praseodymium
        # nuclide for a flow measured in becquerels.  A synonym can name
        # something broader than the flow, which the preferred-label rules
        # already say in as many words; it is not a claim about identity and
        # cannot settle one.
        #
        # It also keeps this pass and `layering._nuclide_object_basis` reading
        # the same string: they have to agree about which flows are nuclides,
        # or an object would be split by one and enriched by the other.
        pref = _object_pref_label_value(obj)
        label = pref.strip() if isinstance(pref, str) else ""
        match: tuple[dict[str, Any], dict[str, Any]] | None = None
        match_key = ""
        claimed = parse_nuclide_label(label)
        unmatched_reason = "label_is_not_a_nuclide_name"
        # What the label claims and what it is looked up as are the same
        # nuclide everywhere but one: a bare `m` names a convention rather than
        # a state letter, and `_resolve_metastable_state` says which state that
        # convention picks out.  Both are kept -- the claim is what a review
        # table reads back to a curator, the resolution is what the record is.
        sought = claimed
        state_resolution: dict[str, Any] = {}
        if claimed is not None:
            match_key = label
            sought, state_resolution = _resolve_metastable_state(
                claimed, isomers_by_symbol_mass=isomers_by_symbol_mass
            )
            match = isotope_by_nuclide.get(sought)
            if match is None:
                # The label parses but the tables have no such nuclide.  Which
                # of the two it is matters: a mass number that exists for the
                # element in some other state is a state this project cannot
                # resolve, and one that exists for no state at all says the
                # element name is wrong.  Neither is publishable, and only the
                # second is a data correction.
                unmatched_reason = (
                    "no_row_for_isomeric_state"
                    if claimed.mass_number in known_mass_numbers.get(claimed.symbol, set())
                    else "no_nuclide_at_that_mass_number"
                )
        if not match:
            unmatched_reasons[unmatched_reason] += 1
            unmatched_kbq_objects.add(foid)
            props = obj.properties
            if not isinstance(props, dict):
                props = {}
            # Handle grouped isotope names (e.g. "Curium Alpha") with candidate isotope lists.
            # This one *does* read the synonyms: it is looking for which
            # element a mixture belongs to, not for which nuclide a flow is,
            # and it assigns no identity -- the result is a list of candidates.
            grouped_candidates: list[dict[str, Any]] = []
            joined_label = " ".join(
                [label, *_object_alt_label_values(obj)]
            ).lower()
            inferred_element: dict[str, Any] | None = None
            for element in elements:
                element_name = str(element.get("name") or "").strip().lower()
                symbol = str(element.get("symbol") or "").strip().lower()
                if (element_name and element_name in joined_label) or (
                    symbol and re.search(rf"\b{re.escape(symbol)}\b", joined_label)
                ):
                    inferred_element = element
                    break
            if inferred_element and any(token in joined_label for token in ("alpha", "beta", "gamma")):
                try:
                    inferred_atomic_number = int(inferred_element.get("atomic_number"))
                except Exception:
                    inferred_atomic_number = 0
                inferred_symbol = str(inferred_element.get("symbol") or "").strip()
                for iso in isotope_rows_by_element_atomic_number.get(inferred_atomic_number, []):
                    if not isinstance(iso, dict):
                        continue
                    candidate_nuclide = parse_nuclide(
                        str(iso.get("nuclide") or ""), symbol=inferred_symbol
                    )
                    if candidate_nuclide is None:
                        continue
                    abundance = stable_abundance_by_symbol_mass.get(
                        (candidate_nuclide.symbol, candidate_nuclide.mass_number)
                    )
                    grouped_candidates.append(
                        {
                            "nuclide": str(iso.get("nuclide") or "").strip(),
                            "mass_number": candidate_nuclide.mass_number,
                            "half_life_and_uncertainty": iso.get("half_life_and_uncertainty") or "",
                            "decay_modes": iso.get("decay_modes_intensities_and_uncertainties_%") or "",
                            "relative_abundance": abundance,
                            "relative_abundance_source": "pubchem_stable_isotope_abundance" if abundance is not None else "",
                        }
                    )
                if grouped_candidates:
                    total_abundance = sum(
                        float(c.get("relative_abundance"))
                        for c in grouped_candidates
                        if isinstance(c.get("relative_abundance"), (int, float))
                    )
                    for candidate in grouped_candidates:
                        ab = candidate.get("relative_abundance")
                        if total_abundance > 0 and isinstance(ab, (int, float)):
                            candidate["relative_abundance_fraction"] = float(ab) / total_abundance
                        else:
                            candidate["relative_abundance_fraction"] = None
                    props["isotope_mix_candidates"] = {
                        "element": str(inferred_element.get("name") or ""),
                        "source": "pubchem_element_isotope_lists",
                        "candidates": grouped_candidates,
                    }
            lookup = dict((props.get("isotope_lookup") or {}) if isinstance(props.get("isotope_lookup"), dict) else {})
            lookup.update({
                "is_kbq_candidate": True,
                "matched": False,
                # Which nuclide the label claimed, and why the tables could not
                # answer for it.  `matched: false` was the whole record before,
                # and nothing read it: `Palladium-234m` carried it for months
                # while the object stayed untyped for an unrelated-sounding
                # reason (#20).  A named reason is what a review table can
                # group by and a correction can be written against.
                "matched_on": match_key,
                "claimed_nuclide": claimed.key if claimed is not None else "",
                "resolved_nuclide": sought.key if sought is not None else "",
                "state_resolution": state_resolution,
                "reason": unmatched_reason,
                "source": "pubchem_pug_view_annotation_heading",
                "sources": ["pubchem_pug_view_annotation_heading"],
            })
            props["isotope_lookup"] = lookup
            obj.properties = props
            by_id[foid] = obj
            continue

        element, iso = match
        # `sought` is the identity the index answered for, so it *is* the row's
        # identity -- that is what looking up by identity buys.  Everything
        # below reads it rather than re-parsing the row's string.  It differs
        # from what the label claimed only where a bare `m` was resolved to the
        # state PubChem spells otherwise, and then the row's own spelling is the
        # one to publish: a record saying `110Agn` at 249.863 days describes the
        # nuclide it holds, where `110Agm` would name a different one (#24).
        nuclide_id: Nuclide = sought  # type: ignore[assignment]
        nuclide = str(iso.get("nuclide") or "").strip()
        atomic_number = nuclide_id.atomic_number
        element_id = target_element_object_id_by_atomic_number.get(atomic_number, "")
        # Keyed by the nuclide alone.  It used to be prefixed with the element's
        # flow object id, which is a build artifact: the day an element gained
        # a flow object -- which is the day this change gives uranium one --
        # every cache entry for its isotopes was orphaned and refetched, and
        # the entries left behind were keyed by an id that no longer meant
        # anything.  What ChemLIN was asked about is the nuclide.
        cache_key = nuclide_id.key
        chemlin_data = chemlin_records.get(cache_key)
        if not isinstance(chemlin_data, dict):
            chemlin_data = {}
        needs_refresh = not chemlin_data or (
            bool(chemlin_data.get("found"))
            and not chemlin_data.get("half_life")
            and not chemlin_data.get("specific_activity_bq_per_g")
        )
        if not chemlin_data.get("found"):
            needs_refresh = True
        # A cache entry written before the resolution knew about the ground
        # state ranked one candidate and called it the longest-lived.  It has
        # to be refetched rather than trusted.
        resolution = chemlin_data.get("isomer_resolution")
        if not isinstance(resolution, dict) or not resolution.get("attempted_slugs"):
            needs_refresh = True
        pubchem_half_life = str(iso.get("half_life_and_uncertainty") or "")
        if needs_refresh:
            fetched = _resolve_chemlin_isotope_data(
                chemlin_client,
                element_name=str(element.get("name") or ""),
                nuclide=nuclide_id,
                expected_half_life_days=half_life_days(pubchem_half_life),
            )
            chemlin_data = fetched if isinstance(fetched, dict) else {}
            chemlin_records[cache_key] = chemlin_data
            chemlin_dirty = True
        references_by_key: dict[str, Any] = {}
        for ref in obj.references if isinstance(obj.references, list) else []:
            key = _reference_key(ref)
            if key:
                references_by_key[key] = ref
        for url in (
            str(element.get("page_url") or "").strip(),
            str(element.get("api_url") or "").strip(),
        ):
            if url:
                references_by_key[url] = references_by_key.get(url) or url
        chemlin_url = (
            str((chemlin_data or {}).get("url") or "").strip()
            if bool((chemlin_data or {}).get("found"))
            else ""
        )
        isomer_resolution = (
            (chemlin_data or {}).get("isomer_resolution")
            if isinstance((chemlin_data or {}).get("isomer_resolution"), dict)
            else {}
        )
        if chemlin_url:
            references_by_key[chemlin_url] = references_by_key.get(chemlin_url) or chemlin_url
            references_by_key["https://www.chemlin.org"] = references_by_key.get("https://www.chemlin.org") or "https://www.chemlin.org"
        for alt in isomer_resolution.get("alternates", []) if isinstance(isomer_resolution, dict) else []:
            if isinstance(alt, dict):
                alt_url = str(alt.get("url") or "").strip()
                if alt_url:
                    references_by_key[alt_url] = references_by_key.get(alt_url) or alt_url
        props = obj.properties
        if not isinstance(props, dict):
            props = {}

        record = {
            "nuclide": nuclide,
            "mass_number": nuclide_id.mass_number,
            "atomic_mass_and_uncertainty_u": iso.get("atomic_mass_and_uncertainty_u") or "",
            "half_life_and_uncertainty": pubchem_half_life,
            "decay_modes": iso.get("decay_modes_intensities_and_uncertainties_%") or "",
            "discovery_year": iso.get("discovery_year") or "",
            "specific_activity_bq_per_g": (chemlin_data or {}).get("specific_activity_bq_per_g") or "",
            "specific_activity_bq_per_g_value": (
                (chemlin_data or {}).get("specific_activity_bq_per_g_value")
                if (chemlin_data or {}).get("specific_activity_bq_per_g_value") is not None
                else (
                    float(str((chemlin_data or {}).get("specific_activity_bq_per_g")))
                    if str((chemlin_data or {}).get("specific_activity_bq_per_g") or "")
                    and re.match(r"^[0-9]+(?:\.[0-9]+)?(?:e[+\-]?[0-9]+)?$", str((chemlin_data or {}).get("specific_activity_bq_per_g")), flags=re.IGNORECASE)
                    else None
                )
            ),
            "half_life_chemlin": (chemlin_data or {}).get("half_life") or "",
            "chemlin_url": chemlin_url,
            "isomer_resolution": isomer_resolution,
            # From the element the row is filed under, never from the row's own
            # string.  Reading it off `238Um` is what published a symbol of `U`
            # for uranium but `P` for promethium and `M` for manganese (#18).
            "symbol": nuclide_id.symbol,
            "isomeric_state": nuclide_id.state,
            "metastable": not nuclide_id.is_ground_state,
        }
        checks = _nuclide_record_checks(nuclide=nuclide_id, record=record)
        failed = [check["check"] for check in checks if not check["passed"]]
        for name in failed:
            withheld_reasons[name] += 1

        lookup = dict((props.get("isotope_lookup") or {}) if isinstance(props.get("isotope_lookup"), dict) else {})
        lookup.update({
            "is_kbq_candidate": True,
            # A record that fails a check is *not* published.  Rule 1 of the
            # semantic typing fires on the presence of `isotope` alone, so
            # writing one that contradicts itself would type the object
            # `Isotope` and hang a wrong half-life, decay mode and specific
            # activity off it -- which is how Potassium-40 came to be published
            # at 336 nanoseconds.  Untyped with a named reason is worse for a
            # consumer than a right answer and much better than a wrong one.
            "matched": not failed,
            "matched_on": match_key,
            "claimed_nuclide": claimed.key if claimed is not None else "",
            "resolved_nuclide": nuclide_id.key,
            "state_resolution": state_resolution,
            "checks": checks,
            "reason": failed[0] if failed else "",
            "source": "pubchem_pug_view_annotation_heading",
            "sources": (
                ["pubchem_pug_view_annotation_heading", "https://www.chemlin.org"]
                if chemlin_url
                else ["pubchem_pug_view_annotation_heading"]
            ),
            "isomer_resolution": isomer_resolution,
        })
        props["isotope_lookup"] = lookup
        if failed:
            withheld_kbq_objects.add(foid)
            props.pop("isotope", None)
            obj.properties = props
            by_id[foid] = obj
            continue

        matched_by_kbq_object[foid] = match
        matched_count_by_element_atomic_number[atomic_number] = (
            matched_count_by_element_atomic_number.get(atomic_number, 0) + 1
        )
        # The link to the element, which `semantic_typing` publishes as
        # `chemrof:has_element`.  Resolved through the nuclide's atomic number,
        # so it does not depend on the row's own spelling of anything.
        #
        # It can still come up empty, and when it does the reason is recorded
        # rather than left as an absent key: the target has to be an object
        # this pass has typed `ChemicalElement`, and an element neither source
        # list carries a flow for has none.  Americium, Neptunium, Promethium
        # and Technetium appear in the list only as nuclides -- there is no
        # `Americium` flow to be the element -- so their isotopes have nothing
        # to point at.  That is a gap in the lists rather than in the link, and
        # minting an object to close it is a decision this pass does not make:
        # it enriches objects a run produced and adds none.
        rel = dict((props.get("relationships") or {}) if isinstance(props.get("relationships"), dict) else {})
        if element_id:
            rel.update({
                "parent_element_flow_object_id": element_id,
                "relationship_type": "isotope_of",
            })
        else:
            unlinked_elements[_element_name_for(nuclide_id)] += 1
            rel.update({
                "parent_element_flow_object_id": "",
                "relationship_type": "isotope_of",
                "unresolved_reason": "no_flow_object_for_the_element",
            })
        props["relationships"] = rel
        props["isotope"] = record
        obj.properties = props
        obj.references = [references_by_key[key] for key in sorted(references_by_key)]
        by_id[foid] = obj

    enriched_elements = 0
    ignored_unlinked_elements = 0
    added_isotopes = 0
    for element in elements:
        try:
            atomic_number = int(element.get("atomic_number"))
        except Exception:
            continue
        symbol = str(element.get("symbol") or "").strip()
        name = str(element.get("name") or "").strip()
        if not symbol or not name:
            continue
        element_title_name = name.title()
        element_source_urls = sorted({
            str(element.get("page_url") or "").strip(),
            str(element.get("api_url") or "").strip(),
        } - {""})
        target_id = target_element_object_id_by_atomic_number.get(atomic_number, "")
        if not target_id:
            ignored_unlinked_elements += 1
            continue
        matched_ef_obj_ids = matched_ef_obj_ids_by_atomic_number.get(atomic_number, set())
        matched_ef_elem_ids = matched_ef_elem_ids_by_atomic_number.get(atomic_number, [])
        # The matched EF 3.1 objects keep the labels they arrived with.  The
        # PubChem element name reaches them through `props["element"]["name"]`
        # below, so there is nothing to gain from rewriting `prefLabel`, and
        # doing so here would overrule labels the preferred-label rules
        # approved -- this enrichment is not gated by them.
        # Approximate neutron number from the most abundant stable isotope.
        neutron_number: int | None = None
        best_abundance = -1.0
        stable_rows = element.get("stable_isotopes", [])
        if isinstance(stable_rows, list):
            for stable in stable_rows:
                if not isinstance(stable, dict):
                    continue
                stable_nuclide = parse_nuclide(
                    str(stable.get("nuclide") or ""), symbol=symbol
                )
                if stable_nuclide is None:
                    continue
                abundance = _parse_relative_abundance(str(stable.get("abundance_uncertainty") or ""))
                if abundance is None:
                    abundance = 0.0
                if abundance >= best_abundance:
                    best_abundance = abundance
                    neutron_number = max(0, stable_nuclide.mass_number - atomic_number)
        if neutron_number is None:
            decay_rows = element.get("isotope_decay", [])
            if isinstance(decay_rows, list):
                for iso in decay_rows:
                    if not isinstance(iso, dict):
                        continue
                    decay_nuclide = parse_nuclide(
                        str(iso.get("nuclide") or ""), symbol=symbol
                    )
                    if decay_nuclide is None:
                        continue
                    neutron_number = max(0, decay_nuclide.mass_number - atomic_number)
                    break
        element_obj = by_id.get(target_id)
        if element_obj is None:
            continue
        existing_types = element_obj.types
        if isinstance(existing_types, list):
            merged_types = [str(x) for x in existing_types if isinstance(x, str) and x.strip()]
        elif isinstance(existing_types, str) and existing_types.strip():
            merged_types = [existing_types.strip()]
        else:
            merged_types = []
        if CHEMROF_CHEMICAL_ELEMENT not in merged_types:
            merged_types.append(CHEMROF_CHEMICAL_ELEMENT)
        element_obj.types = merged_types
        props = element_obj.properties
        if not isinstance(props, dict):
            props = {}
        props[CHEMROF_SYMBOL] = {
            RDFS_LABEL_CURIE: "symbol",
            "@value": [symbol],
            "provenance": _element_property_provenance(
                source_urls=element_source_urls,
                derived_from="pubchem.element.symbol",
            ),
        }
        props[CHEMROF_ATOMIC_NUMBER] = {
            RDFS_LABEL_CURIE: "atomic number",
            "@value": [atomic_number],
            QUDT_HAS_UNIT: UNIT_IRI_NUM,
            "provenance": _element_property_provenance(
                source_urls=element_source_urls,
                derived_from="pubchem.element.atomic_number",
            ),
        }
        # `neutron_number` and the neutral charge live here rather than on
        # `chemrof:neutron_number` and `chemrof:elemental_charge`.
        # `ChemicalElement` is "generic form of an atom, with unspecified
        # neutron or charge"; stating either would contradict the class, and the
        # neutron number is an approximation from the most abundant isotope
        # rather than a specification.  Nothing is lost -- this bag is the
        # periodic-table row, and it is where the approximation belongs.
        props["element"] = {
            "atomic_number": atomic_number,
            "symbol": symbol,
            "name": element_title_name,
            "most_abundant_neutron_number": neutron_number,
            "charge": 0,
            "provenance": _element_property_provenance(
                source_urls=element_source_urls,
                derived_from="pubchem.periodic_table_record",
            ),
        }
        if not isinstance(props.get("isotopes"), dict):
            props["isotopes"] = {}
        props[BASE_REFERENCES_PROPERTY] = {
            "flow_object_ids": sorted(matched_ef_obj_ids),
            "elementary_flow_ids": matched_ef_elem_ids,
            "provenance": _element_property_provenance(
                source_urls=[base_source_label()],
                derived_from="ef31.pref_label_element_name_symbol_matches",
            ),
        } if (matched_ef_obj_ids or matched_ef_elem_ids) else {}
        element_obj.properties = props
        references_by_key: dict[str, Any] = {}
        for ref in element_obj.references if isinstance(element_obj.references, list) else []:
            key = _reference_key(ref)
            if key:
                references_by_key[key] = ref
        for url in element_source_urls:
            if url:
                references_by_key[url] = references_by_key.get(url) or url
        element_obj.references = [references_by_key[key] for key in sorted(references_by_key)]
        by_id[target_id] = element_obj
        enriched_elements += 1

        # Populate element isotope summaries only from matched consensus isotope objects.
        element_obj = by_id.get(target_id)
        if element_obj is not None:
            matched_for_element = []
            for foid, (matched_element, matched_iso) in matched_by_kbq_object.items():
                # `matched_element` and `matched_iso` are PubChem and ChemLIN
                # payloads, so they stay dicts; `matched_obj` is a flow object.
                try:
                    if int(matched_element.get("atomic_number")) != atomic_number:
                        continue
                except Exception:
                    continue
                matched_obj = by_id.get(foid)
                matched_properties = (
                    matched_obj.properties if matched_obj is not None else {}
                )
                matched_isotope = (
                    matched_properties.get("isotope")
                    if isinstance(matched_properties, dict)
                    else {}
                )
                matched_for_element.append(
                    {
                        "flow_object_id": foid,
                        "pref_label_value": _object_pref_label_value(matched_obj),
                        "nuclide": matched_iso.get("nuclide") or "",
                        "half_life_and_uncertainty": matched_iso.get("half_life_and_uncertainty") or "",
                        "specific_activity_bq_per_g": (
                            matched_isotope.get("specific_activity_bq_per_g")
                            if isinstance(matched_isotope, dict)
                            else ""
                        ) or "",
                        "chemlin_url": (
                            matched_isotope.get("chemlin_url")
                            if isinstance(matched_isotope, dict)
                            else ""
                        ) or "",
                    }
                )
            short_lived_total = element_short_lived_counts.get(atomic_number, 0)
            short_lived_not_listed = max(0, short_lived_total - matched_count_by_element_atomic_number.get(atomic_number, 0))
            props = element_obj.properties
            if not isinstance(props, dict):
                props = {}
            isotopes_summary = dict((props.get("isotopes") or {}) if isinstance(props.get("isotopes"), dict) else {})
            isotopes_summary.update(
                {
                    "consensus_matched": sorted(
                        matched_for_element,
                        key=lambda x: (str(x.get("nuclide") or ""), str(x.get("flow_object_id") or "")),
                    ),
                    "short_lived_not_in_consensus_count": short_lived_not_listed,
                    "provenance": _element_property_provenance(
                        source_urls=element_source_urls,
                        derived_from="pubchem.element.isotope_decay_and_consensus_kbq_flow_objects",
                    ),
                }
            )
            props["isotopes"] = isotopes_summary
            element_obj.properties = props
            by_id[target_id] = element_obj

    ion_stats = enrich_monoatomic_ions(by_id)

    chemlin_client.close()
    if chemlin_dirty:
        _save_chemlin_cache(chemlin_cache)

    out = sorted(by_id.values(), key=lambda row: _object_pref_label_value(row).lower())
    short_lived_not_in_consensus_total = 0
    for element in elements:
        try:
            atomic_number = int(element.get("atomic_number"))
        except Exception:
            continue
        short_lived_total = element_short_lived_counts.get(atomic_number, 0)
        short_lived_not_listed = max(0, short_lived_total - matched_count_by_element_atomic_number.get(atomic_number, 0))
        short_lived_not_in_consensus_total += short_lived_not_listed
    return out, {
        "element_flow_object_count_added": len(minted_element_objects),
        "element_flow_object_names_added": sorted(
            _object_pref_label_value(by_id[oid])
            for oid in minted_element_objects.values()
        ),
        "element_flow_object_count_enriched": enriched_elements,
        "element_flow_object_count_ignored_unlinked": ignored_unlinked_elements,
        "element_matched_on_a_synonym": matched_on_a_synonym,
        "isotope_flow_object_count_added": added_isotopes,
        "isotope_kbq_candidate_flow_object_count": len(kbq_flow_object_ids),
        "isotope_kbq_matched_flow_object_count": len(matched_by_kbq_object),
        "isotope_kbq_unmatched_flow_object_count": len(unmatched_kbq_objects),
        # Split out from the unmatched, and reported per reason.  A single
        # "unmatched" count is what let 37 wrong records and one unresolvable
        # label sit behind the same number for as long as they did: a label
        # that is not a nuclide name is the expected outcome for an aggregate,
        # a nuclide the tables have never heard of is a correction waiting to
        # be written, and a record that failed its own checks is neither.
        "isotope_kbq_unmatched_reasons": dict(unmatched_reasons),
        "isotope_kbq_withheld_flow_object_count": len(withheld_kbq_objects),
        "isotope_kbq_withheld_reasons": dict(withheld_reasons),
        "isotope_unlinked_element_count": sum(unlinked_elements.values()),
        "isotope_unlinked_elements": dict(unlinked_elements),
        "isotope_rows_unparsed_count": unparsed_nuclide_rows,
        "short_lived_isotopes_not_in_consensus_count": short_lived_not_in_consensus_total,
        **ion_stats,
    }
