"""WSGI entry point for the consolidated review application (default port 5000).

One process, one port, one nginx block. The four entries beside this one are
still here because the four applications they serve are still here; they go as
their pages are ported.
"""
from brightway_flows.webapps.app import create_app

application = create_app()
