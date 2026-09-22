"""Transformer-based ETL pipeline for producing harmonised flow data.

Split into focused modules; this package re-exports the surface that transformers
and callers use, so `from brightway_flows.pipeline import Change, Transformer`
keeps working.

| Module | Responsibility |
|---|---|
| `engine` | `Change`, `Transformer`, `run_pipeline` |
| `loading` | reading input files into validated `Flow` records |
| `provenance` | the PROV-O graph for a run |
| `exporting` | projection onto the simplified published export |
| `deduplication` | duplicate elementary flows and their deprecation |
| `concept_associations` | links back to source-list flows |
| `sqlite` | the denormalised database backing the review application |
| `text` | name and unit predicates used by transformers |
"""

from brightway_flows.pipeline.engine import (
    Change,
    Transformer,
    apply_transformers,
    run_pipeline,
    writable_flows,
)
from brightway_flows.pipeline.exporting import (
    _strip_lcia_from_flows,
    strip_lcia_from_flows,
)
from brightway_flows.pipeline.text import (
    has_stereo_descriptor,
    is_becquerel_unit,
    normalize,
)

__all__ = [
    "Change",
    "Transformer",
    "_strip_lcia_from_flows",
    "apply_transformers",
    "has_stereo_descriptor",
    "is_becquerel_unit",
    "normalize",
    "run_pipeline",
    "strip_lcia_from_flows",
    "writable_flows",
]
