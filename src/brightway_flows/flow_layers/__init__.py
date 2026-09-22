"""Layered flow model: shared flow objects + context-specific elementary flows.

Split into focused modules; this package re-exports the two names callers use,
so `from brightway_flows.flow_layers import resolve_flow_layers` keeps
working.

| Module | Responsibility |
|---|---|
| `layering` | `resolve_flow_layers`: grouping flows into flow objects |
| `classifications` | CAS and EC classification blocks |
| `labels` | label and definition rows, and the keys they are indexed by |
| `element_cache` | retrieving and caching PubChem elements and ChemLin isotopes |
| `elements` | writing element and isotope facts onto flow objects |
| `ions` | ion name parsing, and monoatomic-ion enrichment |
| `provenance` | the activity name the enrichments are attributed to |

`ElementaryFlow` is not defined here: it is a record type and lives with its two
siblings in `brightway_flows.domain.elementary_flow`.
"""

from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.flow_layers.layering import resolve_flow_layers

__all__ = [
    "ElementaryFlow",
    "resolve_flow_layers",
]
