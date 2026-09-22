"""Is the replacement a name the cited CAS actually has?

The one question the sources can answer about a proposed preferred-label rename,
asked of Common Chemistry and ChEBI: do they hold the current name for this CAS,
the replacement, both, or neither?

    synonym_swap                          both names known -- supported
    systematic_to_common                  replacement known, current not -- usually
                                          a systematic name giving way to a common one
    replacement_not_a_name_for_this_cas   flagged
    neither_name_known_for_this_cas       flagged
    cas_unknown_to_sources                flagged

A flagged pair asserts an identity neither source supports.  That is where a
wrong preferred label comes from -- `'Sodium Chloride' -> 'sea water'` scores
`replacement_not_a_name_for_this_cas`, and the `entropy` rule proposed it
anyway; the audit this module automates found 79 of that rule's 117 pairs
flagged, and #222 removed it.

**The verdict is about identity, not specificity**, and that limit is the whole
of #224.  It cannot see a replacement that names something *broader* than the
flow is: `'Xylene (all isomers)' -> 'Xylene'` scores `systematic_to_common`,
because `xylene` is a name CAS 1330-20-7 holds and `xylene (all isomers)` is
not.  `curation.qualifier_loss` is what shortlists those for a reader; the two
are separate because they answer different questions and only one of them is
answered from the sources.

It lives here rather than in `tools/` because two tools now ask it -- the
worklist over the *queued* renames and the shortlist over the *applied* ones --
and a second copy of a verdict table is a second definition of what the project
means by "supported".
"""

from __future__ import annotations

from typing import Any

import orjson

from brightway_flows.domain.labels import canonical_label_value
from brightway_flows.filesystem import COMMONCHEMISTRY_CACHE_FILEPATH
from brightway_flows.integrations.chebi import load_chebi_index

#: The verdicts under which the pair's identity is supported by the sources.
#: Everything else is flagged.
SUPPORTED_VERDICTS = frozenset({"synonym_swap", "systematic_to_common"})


class SourceNames:
    """Names Common Chemistry and ChEBI hold, keyed by CAS."""

    def __init__(self) -> None:
        cache = orjson.loads(COMMONCHEMISTRY_CACHE_FILEPATH.read_bytes())
        self._detail_by_cas: dict[str, Any] = cache.get("detail_by_cas") or {}
        chebi = load_chebi_index()
        self._records = chebi["records"]
        self._by_cas = chebi["by_cas"]

    def evidence(self, cas: str) -> dict[str, Any]:
        cc_name, cc_synonyms = "", []
        detail = self._detail_by_cas.get(cas)
        if isinstance(detail, dict):
            cc_name = str(detail.get("name") or "")
            cc_synonyms = [s for s in (detail.get("synonyms") or []) if isinstance(s, str)]

        chebi_labels, chebi_synonyms = [], []
        for chebi_id in self._by_cas.get(cas, []):
            record = self._records.get(chebi_id) or {}
            label = record.get("label")
            if isinstance(label, str) and label.strip():
                chebi_labels.append(label.strip())
            chebi_synonyms.extend(
                s for s in (record.get("synonyms") or []) if isinstance(s, str)
            )

        known = {
            canonical_label_value(name)
            for name in [cc_name, *cc_synonyms, *chebi_labels, *chebi_synonyms]
        }
        known.discard("")
        return {
            "common_chemistry_name": cc_name,
            "common_chemistry_synonyms": cc_synonyms[:10],
            "chebi_labels": chebi_labels,
            "_known": known,
        }


def verdict_for(current: str, replacement: str, known: set[str]) -> str:
    if not known:
        return "cas_unknown_to_sources"
    current_known = canonical_label_value(current) in known
    replacement_known = canonical_label_value(replacement) in known
    return {
        (True, True): "synonym_swap",
        (False, True): "systematic_to_common",
        (True, False): "replacement_not_a_name_for_this_cas",
        (False, False): "neither_name_known_for_this_cas",
    }[(current_known, replacement_known)]


def verdict_over_cas(
    current: str, replacement: str, evidence: list[dict[str, Any]]
) -> str:
    """The verdict for a pair whose replacement was keyed on several CAS.

    One row can span several CAS, and a ruling binds all of them, so a row is
    flagged when *any* of its CAS fails to support the replacement.
    """
    per_cas = [verdict_for(current, replacement, item["_known"]) for item in evidence]
    if not per_cas:
        return "cas_unknown_to_sources"
    return next((v for v in per_cas if v not in SUPPORTED_VERDICTS), per_cas[0])


def public_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """The evidence block as it is published: the private `_known` set dropped."""
    return {key: value for key, value in evidence.items() if not key.startswith("_")}
