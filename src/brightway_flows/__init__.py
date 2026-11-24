"""The consensus elementary flow list: the build, the matcher and the review application."""

from __future__ import annotations

__all__ = ["main"]


def main() -> None:
    """The `brightway-flows` command.

    Imported when the command runs rather than with the package: the command
    line is what fetches and builds, and a program that imports
    `brightway_flows.lookup` to ask where a row goes needs neither it nor the
    packages it needs.

    A plain install is the matcher alone, so the command, and each of its
    subcommands, can reach for a package only an extra brings. That is said as
    which extra to install, rather than as a traceback ending in an import.
    """
    try:
        from brightway_flows.application.cli import main as cli_main

        cli_main()
    except ModuleNotFoundError as error:
        extras = _extras_bringing(error.name or "")
        if not extras:
            raise
        import sys

        wanted = " or ".join(f"`brightway-flows[{extra}]`" for extra in extras)
        sys.exit(
            f"This command needs `{error.name}`, which is not installed. "
            f"It comes with {wanted}."
        )


def _extras_bringing(module: str) -> list[str]:
    """The extras of this package that declare the distribution *module* is in.

    Read from the installed package's own metadata, so it answers from
    `pyproject.toml` as it was installed and there is no second list to keep.
    Empty for a module no extra declares, which is then a real error and is
    raised as one. A module named unlike its distribution -- `yaml` for
    `pyyaml` -- is not installed, so nothing says which it is in, and it too
    is raised as it came.
    """
    import re
    from importlib.metadata import PackageNotFoundError, requires

    def normal(name: str) -> str:
        return re.sub(r"[-_.]+", "-", name).lower()

    wanted = normal(module.partition(".")[0])
    try:
        declared = requires("brightway-flows") or []
    except PackageNotFoundError:
        return []
    extras = set()
    for line in declared:
        name = re.match(r"[A-Za-z0-9._-]+", line)
        extra = re.search(r"""extra\s*==\s*["']([^"']+)["']""", line)
        if name and extra and normal(name.group()) == wanted:
            extras.add(extra.group(1))
    return sorted(extras)
