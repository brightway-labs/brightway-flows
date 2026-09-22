"""Remove element-symbol altLabel values from non-element flow objects.

Element symbols such as "Rn" and "[Rn]" are exclusive identifiers of the
corresponding FullySpecifiedAtom (the pure element).  When they appear as
altLabels on isotopes, compounds, or other flows, they create false synonymy
and confuse identity matching.

Detection strategy
------------------
A flow is identified as the canonical element for symbol S if its
CHEMROF ``molecular_formula`` property contains exactly one value and that
value is the bare element symbol (e.g. ``["Rn"]``).  Isotope flows carry
additional formula entries (e.g. ``["Rn", "[222Rn]"]``) and are therefore
not recognised as the element.

Protected forms
---------------
For each element symbol S the protected alt-label forms are:

* the bare symbol itself: ``"Rn"``
* the SMILES/InChI bracket notation: ``"[Rn]"``

Any other flow object (different ``flow_object_id``) that carries one of
these forms in its ``altLabel`` list has it removed.
"""

from __future__ import annotations


import orjson

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.vocabulary import CHEMROF_MOLECULAR_FORMULA
from brightway_flows.filesystem import PUBCHEM_ELEMENTS_CACHE_FILEPATH
from brightway_flows.domain.labels import (
    coerce_alt_labels,
    coerce_pref_label,
    dedupe_alt_labels_against_pref,
)
from brightway_flows.pipeline import Change, Transformer, writable_flows


class StripElementSymbolAltLabelsTransformer(Transformer):
    """Remove element-symbol altLabels from flows that are not the element itself."""

    name = "strip_element_symbol_altlabels"
    # Its first pass decides which flow object *is* the element for each symbol,
    # across the whole build, before any label is judged against that.  The
    # element is normally a consensus flow, so hiding those would leave every
    # symbol unclaimed and the rule inert.
    answers_per_flow = False

    def __init__(self) -> None:
        # Set of all valid element symbols (e.g. {"H", "He", ..., "Rn", ...}).
        self._element_symbols: frozenset[str] = frozenset()
        # Maps each protected form (bare or bracketed) to the canonical symbol.
        # e.g. {"Rn": "Rn", "[Rn]": "Rn"}.
        self._form_to_symbol: dict[str, str] = {}

    def setup(self) -> None:
        if not PUBCHEM_ELEMENTS_CACHE_FILEPATH.exists():
            return
        try:
            payload = orjson.loads(PUBCHEM_ELEMENTS_CACHE_FILEPATH.read_bytes())
        except Exception:
            return
        symbols: set[str] = set()
        form_to_symbol: dict[str, str] = {}
        for element in payload.get("elements", []):
            if not isinstance(element, dict):
                continue
            symbol = str(element.get("symbol") or "").strip()
            if not symbol:
                continue
            symbols.add(symbol)
            for form in (symbol, f"[{symbol}]"):
                form_to_symbol[form] = symbol
        self._element_symbols = frozenset(symbols)
        self._form_to_symbol = form_to_symbol

    def transform(self, flows: list[Flow]) -> list[Change]:
        if not self._form_to_symbol:
            return []

        # Pass 1: find which flow_object_id is the canonical element for each
        # symbol.  A flow is the element for symbol S when its molecular formula
        # list contains exactly one entry and that entry is S itself.
        element_foid_by_symbol: dict[str, str] = {}
        for flow in flows:
            props = flow.properties or {}
            mf_entry = props.get(CHEMROF_MOLECULAR_FORMULA)
            if not isinstance(mf_entry, dict):
                continue
            formulas = mf_entry.get("@value", [])
            if not isinstance(formulas, list) or len(formulas) != 1:
                continue
            formula = str(formulas[0]).strip()
            if formula not in self._element_symbols:
                continue
            foid = flow.flow_object_id or ""
            if foid:
                element_foid_by_symbol[formula] = foid

        if not element_foid_by_symbol:
            return []

        # Pass 2: strip element-symbol alt labels from flows that are not the
        # canonical element for that symbol.  Only the flows this call can still
        # write to: pass 1 above needs every flow, because the element for a
        # symbol is normally a consensus flow, but a proposal for a finished
        # flow is dropped on arrival and deriving it is the waste #88 is about.
        changes: list[Change] = []
        for flow in writable_flows(flows):
            uuid = flow.uuid or ""
            if not uuid:
                continue
            foid = flow.flow_object_id or ""

            existing_pref = coerce_pref_label(flow.prefLabel)
            existing_alt = coerce_alt_labels(flow.altLabel)

            kept = []
            removed: list[str] = []
            for label in existing_alt:
                symbol = self._form_to_symbol.get(label.value)
                if (
                    symbol
                    and symbol in element_foid_by_symbol
                    and foid != element_foid_by_symbol[symbol]
                ):
                    removed.append(label.value)
                else:
                    kept.append(label)

            if not removed:
                continue

            new_alt = dedupe_alt_labels_against_pref(
                alt_labels=kept, pref_label=existing_pref
            )
            changes.append(
                Change(
                    uuid,
                    "altLabel",
                    [x.to_dict() for x in new_alt],
                    comment=(
                        f"Removed {len(removed)} element-symbol altLabel value(s) "
                        f"reserved for the FullySpecifiedAtom flow object: "
                        f"{', '.join(repr(v) for v in sorted(removed))}"
                    ),
                )
            )

        return changes
