"""How a name and a CAS, or two CAS numbers, relate to one another.

Four answers, and only the first licenses a change: an exact match, a component
of a mixture, a broader or narrower class, or unresolved.  Anything but exact
means the two are not the same substance, so the rules stop and file a review
row instead of writing.

Evidence is taken in tiers, cheapest first: the compound profiles (InChIKey,
formula, locants), then the names themselves, then Wikidata, then a Wikipedia
summary.  The fallback tiers only run when the local evidence leaves the
question open, which is why they are inside the classifier rather than fetched
by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from brightway_flows.pipeline import normalize
from brightway_flows.transformers.consensus_match.indexes import SourceIndexes
from brightway_flows.transformers.consensus_match.lookups import LookupClient
from brightway_flows.transformers.consensus_match.naming import (
    CLASS_KEYWORDS,
    MIXTURE_KEYWORDS,
    contains_isomer_locants,
    is_class_like,
    is_mixture_like,
    locant_signature,
)
from brightway_flows.transformers.consensus_match.profiles import CompoundProfiles

RELATIONSHIP_EXACT = "exact_match"
RELATIONSHIP_MIXTURE = "component_of_mixture"
RELATIONSHIP_CLASS = "broader_or_narrower_class"
RELATIONSHIP_UNRESOLVED = "unresolved"


def classify_cas_pair(
    *,
    candidate_profile: dict[str, Any],
    other_profile: dict[str, Any],
) -> tuple[str, str]:
    """Classify relationship between two CAS profiles on the same flow."""
    c_inchi = candidate_profile.get("inchi_key")
    o_inchi = other_profile.get("inchi_key")
    if c_inchi and o_inchi:
        if c_inchi == o_inchi:
            return RELATIONSHIP_EXACT, "same InChIKey for both CAS entries"
        c_main = c_inchi.split("-", 1)[0]
        o_main = o_inchi.split("-", 1)[0]
        if c_main == o_main:
            return (
                RELATIONSHIP_CLASS,
                "same core InChIKey block, different form/salt/stereo",
            )

    c_name = (candidate_profile.get("preferred_name") or "").lower()
    o_name = (other_profile.get("preferred_name") or "").lower()
    if is_mixture_like(c_name) or is_mixture_like(o_name):
        return RELATIONSHIP_MIXTURE, "mixture/salt keyword in CAS-pair names"

    if contains_isomer_locants(c_name) and contains_isomer_locants(o_name):
        if locant_signature(c_name) != locant_signature(o_name):
            return RELATIONSHIP_CLASS, "different locant signature (positional isomer)"

    c_formula = candidate_profile.get("formula")
    o_formula = other_profile.get("formula")
    if c_formula and o_formula and c_formula != o_formula:
        return RELATIONSHIP_CLASS, "different molecular formula between CAS entries"

    return RELATIONSHIP_UNRESOLVED, "CAS pair relationship unresolved"


@dataclass
class RelationshipClassifier:
    """Tiered classification, from local profiles out to the web fallback."""

    indexes: SourceIndexes
    lookups: LookupClient
    profiles: CompoundProfiles

    def classify_name_cas(
        self,
        *,
        flow_name: str,
        candidate_name: str,
        candidate_cas: str,
        existing_cas_numbers: list[str],
    ) -> tuple[str, str, list[str]]:
        """Classify CAS/name relationship and return supporting refs."""
        supporting_refs: list[str] = []
        candidate_profile = self.profiles.get(candidate_cas)
        if candidate_profile.get("pubchem_url"):
            supporting_refs.append(candidate_profile["pubchem_url"])
        if candidate_profile.get("commonchemistry_url"):
            supporting_refs.append(candidate_profile["commonchemistry_url"])
        supporting_refs.extend(candidate_profile.get("chebi_urls", []))

        # If multiple CAS are present on one flow, compare pairwise first.
        if existing_cas_numbers and len(existing_cas_numbers) > 1:
            for other_cas in existing_cas_numbers:
                if other_cas == candidate_cas:
                    continue
                other_profile = self.profiles.get(other_cas)
                if other_profile.get("pubchem_url"):
                    supporting_refs.append(other_profile["pubchem_url"])
                if other_profile.get("commonchemistry_url"):
                    supporting_refs.append(other_profile["commonchemistry_url"])
                supporting_refs.extend(other_profile.get("chebi_urls", []))
                rel_class, rel_reason = classify_cas_pair(
                    candidate_profile=candidate_profile,
                    other_profile=other_profile,
                )
                if rel_class != RELATIONSHIP_EXACT:
                    return rel_class, rel_reason, sorted(set(supporting_refs))

        flow_norm = normalize(flow_name)
        cand_norm = normalize(candidate_name)

        if flow_norm == cand_norm:
            base_class = RELATIONSHIP_EXACT
            base_reason = "normalized names match"
        elif is_mixture_like(flow_name) or is_mixture_like(candidate_name):
            base_class = RELATIONSHIP_MIXTURE
            base_reason = "mixture keyword in flow/candidate name"
        elif is_class_like(flow_name) or is_class_like(candidate_name):
            base_class = RELATIONSHIP_CLASS
            base_reason = "class-level keyword in flow/candidate name"
        elif flow_norm in cand_norm or cand_norm in flow_norm:
            base_class = RELATIONSHIP_CLASS
            base_reason = "name containment suggests broader/narrower class"
        else:
            base_class = RELATIONSHIP_UNRESOLVED
            base_reason = "local evidence insufficient"

        # Add ChEBI refs for provenance when available.
        for chebi_id in self.indexes.chebi_by_cas.get(candidate_cas, []):
            rec = self.indexes.chebi_records.get(chebi_id, {})
            supporting_refs.extend(rec.get("xrefs_urls", []))

        if base_class != RELATIONSHIP_UNRESOLVED:
            return base_class, base_reason, sorted(set(supporting_refs))

        # Tier 2 + 3 fallback (cached)
        wiki = self.lookups.wikidata(candidate_cas, flow_name)
        if wiki.get("url"):
            supporting_refs.append(wiki["url"])
        wiki_text = ((wiki.get("label") or "") + " " + (wiki.get("description") or "")).lower()
        if any(k in wiki_text for k in MIXTURE_KEYWORDS):
            return (
                RELATIONSHIP_MIXTURE,
                "mixture keyword found in Wikidata text",
                sorted(set(supporting_refs)),
            )
        if any(k in wiki_text for k in CLASS_KEYWORDS):
            return (
                RELATIONSHIP_CLASS,
                "class-level keyword found in Wikidata text",
                sorted(set(supporting_refs)),
            )

        web = self.lookups.wikipedia(candidate_cas, flow_name)
        if web.get("url"):
            supporting_refs.append(web["url"])
        web_text = ((web.get("heading") or "") + " " + (web.get("abstract") or "")).lower()
        if any(k in web_text for k in MIXTURE_KEYWORDS):
            return (
                RELATIONSHIP_MIXTURE,
                "mixture keyword found in web fallback",
                sorted(set(supporting_refs)),
            )
        if any(k in web_text for k in CLASS_KEYWORDS):
            return (
                RELATIONSHIP_CLASS,
                "class-level keyword found in web fallback",
                sorted(set(supporting_refs)),
            )

        return (
            RELATIONSHIP_UNRESOLVED,
            "still unresolved after Wikidata/web fallback",
            sorted(set(supporting_refs)),
        )

    def classify_cas_pair_with_fallback(
        self,
        left_cas: str,
        right_cas: str,
    ) -> tuple[str, str, list[str]]:
        """Classify relationship between two CAS entries using local + fallback evidence."""
        left = self.profiles.get(left_cas)
        right = self.profiles.get(right_cas)
        refs: list[str] = []
        if left.get("pubchem_url"):
            refs.append(left["pubchem_url"])
        if right.get("pubchem_url"):
            refs.append(right["pubchem_url"])
        if left.get("commonchemistry_url"):
            refs.append(left["commonchemistry_url"])
        if right.get("commonchemistry_url"):
            refs.append(right["commonchemistry_url"])
        refs.extend(left.get("chebi_urls", []))
        refs.extend(right.get("chebi_urls", []))

        rel, reason = classify_cas_pair(candidate_profile=left, other_profile=right)
        if rel != RELATIONSHIP_UNRESOLVED:
            return rel, reason, sorted(set(refs))

        left_name = left.get("preferred_name") or ""
        right_name = right.get("preferred_name") or ""
        wiki_left = self.lookups.wikidata(left_cas, left_name)
        wiki_right = self.lookups.wikidata(right_cas, right_name)
        if wiki_left.get("url"):
            refs.append(wiki_left["url"])
        if wiki_right.get("url"):
            refs.append(wiki_right["url"])

        # If both resolve to same Wikidata entity, treat as exact.
        if wiki_left.get("id") and wiki_left.get("id") == wiki_right.get("id"):
            return (
                RELATIONSHIP_EXACT,
                "both CAS resolve to same Wikidata entity",
                sorted(set(refs)),
            )

        wiki_text = (
            (wiki_left.get("label") or "")
            + " "
            + (wiki_left.get("description") or "")
            + " "
            + (wiki_right.get("label") or "")
            + " "
            + (wiki_right.get("description") or "")
        ).lower()
        if any(k in wiki_text for k in MIXTURE_KEYWORDS):
            return (
                RELATIONSHIP_MIXTURE,
                "mixture/salt keyword found in Wikidata pair evidence",
                sorted(set(refs)),
            )
        if any(k in wiki_text for k in CLASS_KEYWORDS):
            return (
                RELATIONSHIP_CLASS,
                "class-level keyword found in Wikidata pair evidence",
                sorted(set(refs)),
            )

        web_left = self.lookups.wikipedia(left_cas, left_name)
        web_right = self.lookups.wikipedia(right_cas, right_name)
        if web_left.get("url"):
            refs.append(web_left["url"])
        if web_right.get("url"):
            refs.append(web_right["url"])
        web_text = (
            (web_left.get("heading") or "")
            + " "
            + (web_left.get("abstract") or "")
            + " "
            + (web_right.get("heading") or "")
            + " "
            + (web_right.get("abstract") or "")
        ).lower()
        if any(k in web_text for k in MIXTURE_KEYWORDS):
            return (
                RELATIONSHIP_MIXTURE,
                "mixture/salt keyword found in web pair evidence",
                sorted(set(refs)),
            )
        if any(k in web_text for k in CLASS_KEYWORDS):
            return (
                RELATIONSHIP_CLASS,
                "class-level keyword found in web pair evidence",
                sorted(set(refs)),
            )

        return RELATIONSHIP_UNRESOLVED, "CAS pair unresolved after fallback", sorted(set(refs))
