"""Application-layer entry points and orchestration modules.

`cli` is the command-line application itself, not a re-export of one. It lived
at `brightway_flows.cli` with a five-line shim here that
`tests/test_architecture_structure.py` then asserted was importable -- the same
thing that made `merge_ecoinvent` look maintained (#92). A `pipeline` shim sat
beside it re-exporting `run_pipeline`, with no importer anywhere; it is gone.
"""

from brightway_flows.application.cli import app, main

__all__ = ["app", "main"]
