"""The consensus elementary flow list: the build, the matcher and the review application."""

from __future__ import annotations

__all__ = ["main"]


def main() -> None:
    """The `brightway-flows` command.

    Imported when the command runs rather than with the package: the command
    line is what fetches and builds, and a program that imports
    `brightway_flows.lookup` to ask where a row goes needs neither it nor the
    packages it needs.
    """
    from brightway_flows.application.cli import main as cli_main

    cli_main()
