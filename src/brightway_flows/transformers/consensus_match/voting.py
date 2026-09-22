"""What the sources say a substance is called, and which CAS it holds.

A vote is taken in both directions -- a CAS from a name, a name from a CAS --
over ChEBI, the EC inventory, PubChem and Common Chemistry.  A candidate wins
only with at least two sources behind it and no tie, so a single source can
never rename anything on its own; `unique_winner` is where that rule lives.

`cc_chebi_agreed_name` is the one exception, and deliberately narrow: two
curated sources stating the same primary name for a CAS is stronger evidence
than a tally, so it is answered here rather than folded into the vote.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from brightway_flows.pipeline import normalize
from brightway_flows.transformers.consensus_match.indexes import SourceIndexes
from brightway_flows.transformers.consensus_match.lookups import LookupClient
from brightway_flows.transformers.consensus_match.naming import normalize_stereo
from brightway_flows.transformers.consensus_match.records import CasVoteConflict


def unique_winner(votes: dict[str, set[str]]) -> str | None:
    """The candidate at least two sources back, when nothing ties it."""
    if not votes:
        return None
    counts = Counter({k: len(v) for k, v in votes.items()})
    top = counts.most_common(2)
    if not top:
        return None
    best_key, best_votes = top[0]
    if best_votes < 2:
        return None
    if len(top) > 1 and top[1][1] == best_votes:
        return None
    return best_key


def build_conflicts(
    votes: dict[str, set[str]], chosen_key: str | None
) -> list[CasVoteConflict]:
    """The candidates that lost the vote, and who voted for each.

    Order follows `votes`, which is keyed off set iteration upstream and so
    is not stable between processes.  `ConsensusMatchReviewItem.to_dict()`
    settles it on the way to the table.
    """
    return [
        CasVoteConflict(candidate=key, sources=sorted(srcs))
        for key, srcs in votes.items()
        if key != chosen_key
    ]


@dataclass
class ConsensusVotes:
    """The multi-source ballot, over the loaded indexes and Common Chemistry."""

    indexes: SourceIndexes
    lookups: LookupClient

    def cas_from_name(self, flow_name: str) -> tuple[str | None, dict[str, set[str]]]:
        nname = normalize(flow_name)
        votes: dict[str, set[str]] = defaultdict(set)

        for chebi_id in self.indexes.chebi_by_name.get(nname, []):
            for cas in self.indexes.chebi_records.get(chebi_id, {}).get("cas_numbers", []):
                votes[cas].add("chebi")
        for cas in self.indexes.ec_cas_by_name.get(nname, set()):
            votes[cas].add("ec_inventory")
        for cas in self.indexes.pubchem_cas_by_name.get(nname, set()):
            votes[cas].add("pubchem")
        for cas in self.lookups.cas_from_name(flow_name):
            votes[cas].add("common_chemistry")

        return unique_winner(votes), votes

    def name_from_cas(self, cas: str) -> tuple[str | None, dict[str, set[str]]]:
        votes: dict[str, set[str]] = defaultdict(set)
        representative: dict[str, str] = {}

        for chebi_id in self.indexes.chebi_by_cas.get(cas, []):
            rec = self.indexes.chebi_records.get(chebi_id, {})
            if rec.get("label"):
                key = normalize(rec["label"])
                votes[key].add("chebi")
                representative.setdefault(key, rec["label"])
        for name in self.indexes.ec_names_by_cas.get(cas, set()):
            key = normalize(name)
            votes[key].add("ec_inventory")
            representative.setdefault(key, name)
        for name in self.indexes.pubchem_names_by_cas.get(cas, set()):
            key = normalize(name)
            votes[key].add("pubchem")
            representative.setdefault(key, name)
        for name in self.lookups.names_for_cas(cas):
            key = normalize(name)
            votes[key].add("common_chemistry")
            representative.setdefault(key, name)

        winner_norm = unique_winner(votes)
        if winner_norm is None:
            return None, votes
        return representative[winner_norm], votes

    def cc_chebi_agreed_name(self, cas: str) -> str | None:
        """Return the agreed primary name when Common Chemistry and ChEBI concur.

        Compares the CC primary name and the ChEBI primary label using a
        stereo-aware normalizer that treats β/beta, α/alpha etc. as equivalent.
        When the two sources agree, the CC name is preferred (CC tends to use
        Unicode stereo characters such as β which are more readable).

        Returns None when:
        - either source has no data for this CAS, or
        - both have data but the names do not agree after stereo-normalisation.
        """
        # Common Chemistry primary name
        detail = self.lookups.commonchem_detail(cas)
        cc_primary = str(detail.get("name") or "").strip() if isinstance(detail, dict) else ""

        # ChEBI primary label — require all matching records to share the same label
        chebi_ids = self.indexes.chebi_by_cas.get(cas, [])
        chebi_labels: set[str] = set()
        for cid in chebi_ids:
            label = str(self.indexes.chebi_records.get(cid, {}).get("label") or "").strip()
            if label:
                chebi_labels.add(label)
        chebi_primary = next(iter(chebi_labels)) if len(chebi_labels) == 1 else ""

        if not cc_primary or not chebi_primary:
            return None

        if normalize_stereo(cc_primary) == normalize_stereo(chebi_primary):
            return cc_primary  # prefer CC (Unicode stereo characters)

        return None
