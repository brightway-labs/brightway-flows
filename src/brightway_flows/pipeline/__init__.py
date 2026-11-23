"""Transformer-based ETL pipeline for producing harmonised flow data.

Split into focused modules; this package re-exports the surface that transformers
and callers use, so `from brightway_flows.pipeline import Change, Transformer`
keeps working.

| Module | Responsibility |
|---|---|
| `transforming` | `Change`, `Transformer`, `apply_transformers` |
| `engine` | `run_pipeline`, the whole build |
| `loading` | reading input files into validated `Flow` records |
| `provenance` | the PROV-O graph for a run |
| `exporting` | projection onto the simplified published export |
| `deduplication` | duplicate elementary flows and their deprecation |
| `concept_associations` | links back to source-list flows |
| `sqlite` | the denormalised database backing the review application |
| `text` | name and unit predicates used by transformers |
"""

from brightway_flows._lazy import lazy_exports

#: Each name and the module it lives in, imported when the name is first used.
#: `Change` and `Transformer` are what every transformer imports from here, and
#: they come from `transforming` rather than `engine` so that importing one
#: transformer does not import a whole build.
_EXPORTS = {
    "Change": "transforming",
    "Transformer": "transforming",
    "apply_transformers": "transforming",
    "writable_flows": "transforming",
    "run_pipeline": "engine",
    "_strip_lcia_from_flows": "exporting",
    "strip_lcia_from_flows": "exporting",
    "has_stereo_descriptor": "text",
    "is_becquerel_unit": "text",
    "normalize": "text",
}

__getattr__, __dir__ = lazy_exports(__name__, _EXPORTS)

__all__ = sorted(_EXPORTS)
