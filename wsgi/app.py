"""WSGI entry point for the consolidated review application (default port 5000).

One process, one port, one nginx block. The four entries beside this one are
still here because the four applications they serve are still here; they go as
their pages are ported.

`create_app()` with nothing named serves the published release: the one
`release.json` in the data directory names, downloaded from Zenodo if it is
not there yet.  `BRIGHTWAY_FLOWS_WEBAPP_LOCAL=1` in the environment serves the
build in the data directory instead.  `docs/operating/deployment.md`.
"""
from brightway_flows.webapps.app import create_app

application = create_app()
