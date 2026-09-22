"""Merge-domain orchestration exports.

`merge_ecoinvent` was exported here until #243.  It took a version string,
resolved it against the registry, and called `merge_source_list` -- a second
entry point that could only name one list, kept for a CLI that had stopped
calling it.  `merge_source_list` takes the `SourceList`, which is the identity
the rest of the merge uses; import it from `brightway_flows.merge.pipeline`.
"""

from brightway_flows.merge.pipeline import merge_source_list

__all__ = ["merge_source_list"]
