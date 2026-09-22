"""Add ChEBI synonyms as SKOS altLabels using linked identifiers."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import orjson

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.common import Provenance
from brightway_flows.domain.vocabulary import CHEMROF_MOLECULAR_FORMULA
from brightway_flows.filesystem import PUBCHEM_DATA_FILEPATH
from brightway_flows.integrations.chebi import load_chebi_index
from brightway_flows.domain.labels import (
    Label,
    canonical_label_value,
    coerce_alt_labels,
    coerce_pref_label,
    dedupe_alt_labels_against_pref,
    flow_label_value,
)
from brightway_flows.pipeline import Change, Transformer
from brightway_flows.transformers.enrich_references import (
    _CHEBI_DIRECT_FORMULA_THRESHOLD,
    formula_similarity_score,
)


class ChebiAltLabelsTransformer(Transformer):
    """Propose altLabel additions from ChEBI synonyms."""

    name = "chebi_altlabels"
    answers_per_flow = True

    def __init__(self) -> None:
        self._chebi_records: dict[str, dict[str, Any]] = {}
        self._chebi_by_cas: dict[str, list[str]] = {}
        self._pubchem_chebi_ids_by_cas: dict[str, set[str]] = defaultdict(set)
        self._chebi_key_aliases: dict[str, str] = {}

    def setup(self) -> None:
        chebi = load_chebi_index()
        self._chebi_records = chebi["records"]
        self._chebi_by_cas = chebi["by_cas"]
        self._pubchem_chebi_ids_by_cas = defaultdict(set)
        self._chebi_key_aliases = {}
        for key in self._chebi_records:
            if not isinstance(key, str):
                continue
            canonical = self._to_chebi_record_key(key)
            if canonical:
                self._chebi_key_aliases[canonical] = key

        if not PUBCHEM_DATA_FILEPATH.exists():
            return

        pubchem = orjson.loads(PUBCHEM_DATA_FILEPATH.read_bytes())
        identifiers = pubchem.get("identifiers", {})
        by_cas = pubchem.get("by_cas", {})

        cid_to_chebi_ids: dict[int, set[str]] = defaultdict(set)
        for cid_key, id_map in identifiers.items():
            if not isinstance(id_map, dict):
                continue
            try:
                cid = int(cid_key)
            except (TypeError, ValueError):
                continue
            for item in id_map.get("ChEBI ID", []):
                value = item.get("value") if isinstance(item, dict) else None
                if isinstance(value, str) and value.strip():
                    normalized = self._to_chebi_record_key(value)
                    if normalized:
                        cid_to_chebi_ids[cid].add(normalized)

        for cas, compounds in by_cas.items():
            if not isinstance(cas, str):
                continue
            if not isinstance(compounds, list):
                continue
            for compound in compounds:
                if not isinstance(compound, dict):
                    continue
                cid = compound.get("cid")
                if isinstance(cid, int):
                    self._pubchem_chebi_ids_by_cas[cas].update(cid_to_chebi_ids.get(cid, set()))

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []

        for flow in flows:
            flow_name = flow_label_value(flow)
            if not flow_name:
                continue

            matched_chebi_ids = self._matched_chebi_ids(flow)
            if not matched_chebi_ids:
                continue

            candidate_synonym_sources: dict[str, set[str]] = defaultdict(set)
            for chebi_id in matched_chebi_ids:
                rec = self._chebi_records.get(chebi_id, {})
                for syn in rec.get("synonyms", []):
                    if isinstance(syn, str) and syn.strip():
                        text = syn.strip()
                        candidate_synonym_sources[text].add(chebi_id)

            if not candidate_synonym_sources:
                continue

            existing_alt = coerce_alt_labels(flow.altLabel)
            existing_pref = coerce_pref_label(flow.prefLabel)
            existing_canon = {canonical_label_value(flow_name)}
            if existing_pref is not None:
                existing_canon.add(canonical_label_value(existing_pref.value))
            existing_canon.update(canonical_label_value(x.value) for x in existing_alt if x.value.strip())

            additions: list[Label] = []
            for syn in sorted(candidate_synonym_sources):
                key = canonical_label_value(syn)
                if not key or key in existing_canon:
                    continue
                source_chebi_ids = sorted(candidate_synonym_sources[syn])
                additions.append(
                    Label(
                        value=syn,
                        source=self._chebi_label_source(
                            chebi_ids=source_chebi_ids,
                            flow=flow,
                        ),
                    )
                )
            if not additions:
                continue

            new_alt = dedupe_alt_labels_against_pref(
                alt_labels=existing_alt + additions,
                pref_label=existing_pref,
            )
            if [x.to_dict() for x in new_alt] == [x.to_dict() for x in existing_alt]:
                continue
            changes.append(Change(
                flow.uuid,
                "altLabel",
                [x.to_dict() for x in new_alt],
                comment=(
                    f"Added {len(additions)} ChEBI synonym(s) as altLabel "
                    f"from {len(matched_chebi_ids)} linked ChEBI record(s)"
                ),
            ))

        return changes

    def _matched_chebi_ids(self, flow: dict[str, Any]) -> list[str]:
        queried_cas = {
            cas.strip()
            for cas in flow.cas_numbers
            if isinstance(cas, str) and cas.strip()
        }
        matched: set[str] = set()
        for cas in queried_cas:
            for chebi_id in self._chebi_by_cas.get(cas, []):
                normalized = self._to_chebi_record_key(chebi_id)
                if normalized:
                    matched.add(normalized)
            for chebi_id in self._pubchem_chebi_ids_by_cas.get(cas, set()):
                normalized = self._to_chebi_record_key(chebi_id)
                if not normalized:
                    continue
                # Only accept a PubChem-derived ChEBI ID if the ChEBI record
                # itself confirms the CAS. PubChem's cross-reference table can
                # map a CAS to unrelated ChEBI entries (e.g. several menthol
                # stereoisomers), causing synonyms from the wrong stereoisomer
                # to spread across all related flow objects.
                record = self._chebi_records.get(normalized, {})
                if set(record.get("cas_numbers", [])) & queried_cas:
                    matched.add(normalized)

        # Secondary guard: ChEBI data errors can cause a compound record to
        # claim a CAS number that belongs to a different substance.  When
        # multiple ChEBI-direct IDs match the same CAS and the flow has a known
        # molecular formula, filter out records whose formula is clearly
        # incompatible (same logic as EnrichReferencesTransformer).
        if len(matched) > 1:
            props = flow.properties or {}
            mf_entry = props.get(CHEMROF_MOLECULAR_FORMULA)
            expected_formulas: list[str] = []
            if isinstance(mf_entry, dict):
                for v in mf_entry.get("@value", []):
                    if isinstance(v, str) and v.strip():
                        expected_formulas.append(v.strip())
            if expected_formulas:
                formula_filtered: set[str] = set()
                for chebi_id in matched:
                    record = self._chebi_records.get(chebi_id, {})
                    record_formula = record.get("formula")
                    if isinstance(record_formula, str) and record_formula.strip():
                        best = max(
                            formula_similarity_score(record_formula, ef)
                            for ef in expected_formulas
                        )
                        if best >= _CHEBI_DIRECT_FORMULA_THRESHOLD:
                            formula_filtered.add(chebi_id)
                    else:
                        formula_filtered.add(chebi_id)
                if formula_filtered:
                    matched = formula_filtered

        return sorted(matched)

    def _to_chebi_record_key(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if text in self._chebi_records:
            return text
        aliased = self._chebi_key_aliases.get(text)
        if aliased:
            return aliased
        match = re.search(r"CHEBI[_:](\d+)", text, flags=re.IGNORECASE)
        if match:
            suffix = match.group(1)
            uri = f"http://purl.obolibrary.org/obo/CHEBI_{suffix}"
            if uri in self._chebi_records:
                self._chebi_key_aliases[text] = uri
                return uri
            compact = f"CHEBI:{suffix}"
            aliased = self._chebi_key_aliases.get(compact)
            if aliased:
                self._chebi_key_aliases[text] = aliased
                return aliased
        if text.isdigit():
            uri = f"http://purl.obolibrary.org/obo/CHEBI_{text}"
            if uri in self._chebi_records:
                self._chebi_key_aliases[text] = uri
                return uri
        return ""

    def _chebi_label_source(
        self,
        *,
        chebi_ids: list[str],
        flow: Flow,
    ) -> dict[str, Any]:
        """Where a ChEBI synonym came from: the records, and the flow's list.

        The list used to open with `label:<the synonym itself>` (#250).  That
        is not a source -- it names the string the row is attached to, and
        `@value` already says it -- and it was published on 258,206 of the
        2,012,182 elementary-flow alternative labels, every row this
        transformer writes.  It was also captured before `strip_markup` ran,
        so for `N-D-Glucosyl-(2)-N'-nitrosomethylharnstoff` it was the one
        place a raw `&#39;` still reached a published artifact.
        """
        primary_sources = [x for x in chebi_ids if isinstance(x, str) and x.strip()]
        flow_source = str(flow.source or "").strip()
        if flow_source:
            primary_sources.append(flow_source)
        return Provenance(
            was_generated_by="chebi_altlabels",
            was_attributed_to="brightway-flows",
            had_primary_source=primary_sources,
            was_derived_from="chebi synonym match",
        ).to_dict()

