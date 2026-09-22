"""The unit-process score comparison: a vendor's scores against ours, flow by flow.

| Module | Responsibility |
|---|---|
| `pipeline` | `compare_scores`: the order the steps run in |
| `compare` | the comparison itself, over records, and the closed list of reasons a contribution can differ |
| `store` | the `score_*` tables, written into the file `build` and `characterise` wrote |

The artifact it reads is `domain.lcia.unit_process_scores`; the settings that
say which releases and where are `settings.ScoreComparisonSettings`; the design
is `plans/unit-process-scores.md`.
"""

from brightway_flows.lcia.scores.pipeline import compare_scores

__all__ = ["compare_scores"]
