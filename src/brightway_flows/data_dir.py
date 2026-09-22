"""Where the data directory is.

A module of its own, importing nothing from the project and doing nothing on
import, because the tools ask it too: `tools/seed_data_dir.py` and the others
want the machine-wide directory without `filesystem`'s `mkdir`, and without the
variable, which by the time they run points somewhere else.
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "brightway-flows"
APP_AUTHOR = "brightway-labs"

#: The variable that overrides the directory.
ENV_VAR = "BRIGHTWAY_FLOWS_DATA_DIR"


def machine_data_dir() -> Path:
    """The machine-wide data directory, ignoring the variable."""
    return Path(user_data_dir(appname=APP_NAME, appauthor=APP_AUTHOR))


def env_data_dir() -> Path | None:
    """The directory the variable names, or `None` where it is unset."""
    if value := os.environ.get(ENV_VAR):
        return Path(value)
    return None


def data_dir() -> Path:
    """The data directory this process uses: the variable's, else the machine's."""
    return env_data_dir() or machine_data_dir()
