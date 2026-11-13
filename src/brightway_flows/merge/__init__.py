"""Merge-domain orchestration exports.

`merge_ecoinvent` was exported here until #243.  It took a version string,
resolved it against the registry, and called `merge_source_list` -- a second
entry point that could only name one list, kept for a CLI that had stopped
calling it.  `merge_source_list` takes the `SourceList`, which is the identity
the rest of the merge uses; import it from `brightway_flows.merge.pipeline`.
"""

from brightway_flows._lazy import lazy_exports

#: Imported when first used: `merge.matching` and `merge.store` are read by the
#: lookup and by the review application, neither of which runs a merge.
_EXPORTS = {"merge_source_list": "pipeline"}

__getattr__, __dir__ = lazy_exports(__name__, _EXPORTS)

__all__ = sorted(_EXPORTS)
