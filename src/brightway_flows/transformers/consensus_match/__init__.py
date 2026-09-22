"""Consensus-based identifier/name matching across ChEBI, EC inventory, and PubChem.

Split into focused modules; this package re-exports the transformer and the
review records other packages read, so
`from brightway_flows.transformers.consensus_match import
ConsensusMatchTransformer` keeps working.

| Module | Responsibility |
|---|---|
| `transformer` | `ConsensusMatchTransformer`: lifecycle, wiring, the loop over flow objects |
| `rules` | turning evidence into a `Change` or a review row |
| `grouping` | flow objects, the groups they fall into, and the evidence a group carries |
| `voting` | the multi-source ballot: a CAS from a name, a name from a CAS |
| `relationships` | how a name and a CAS, or two CAS numbers, relate |
| `profiles` | one merged view of a CAS, from PubChem and Common Chemistry |
| `indexes` | the ChEBI, EC-inventory and PubChem tables, loaded once per run |
| `lookups` | every network call, its throttling, and its on-disk caches |
| `rename_gate` | this run's rulings, and the renames still waiting for one |
| `naming` | what a name looks like, decided from the name alone |
| `records` | the rows written to the review queues |

The dependency order runs down that table: `rules` reads everything below it,
`naming` and `records` read nothing.  A new rule belongs in `rules`; a new
source belongs in `indexes` and `voting`.
"""

from brightway_flows.transformers.consensus_match.naming import normalize_stereo
from brightway_flows.transformers.consensus_match.records import (
    CasVoteConflict,
    ConsensusDecision,
    ConsensusMatchReviewItem,
)
from brightway_flows.transformers.consensus_match.transformer import (
    ConsensusMatchTransformer,
)

__all__ = [
    "CasVoteConflict",
    "ConsensusDecision",
    "ConsensusMatchReviewItem",
    "ConsensusMatchTransformer",
    "normalize_stereo",
]
