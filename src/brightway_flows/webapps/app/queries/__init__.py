"""Flask-free reads: a connection in, dataclasses out.

No module here imports Flask, so each is unit-testable against a fixture
database. The applications this replaces are reachable only through a Flask
test client, which is why `run_report` is the only one that has tests.
"""
