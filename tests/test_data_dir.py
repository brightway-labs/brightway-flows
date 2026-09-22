"""The data directory: the machine's, and the variable that overrides it."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from brightway_flows import data_dir


class MachineDataDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        patcher = mock.patch.object(
            data_dir, "user_data_dir",
            lambda appname, appauthor: str(self.root / appname),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_directory_under_the_project_name(self):
        self.assertEqual(data_dir.machine_data_dir(), self.root / "brightway-flows")

    def test_the_same_directory_once_it_exists(self):
        (self.root / "brightway-flows").mkdir()
        self.assertEqual(data_dir.machine_data_dir(), self.root / "brightway-flows")


class EnvDataDirTestCase(unittest.TestCase):
    def test_no_variable(self):
        with mock.patch.dict(os.environ, clear=True):
            self.assertIsNone(data_dir.env_data_dir())

    def test_the_variable_overrides_the_machine(self):
        env = {"BRIGHTWAY_FLOWS_DATA_DIR": "/new"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(data_dir.env_data_dir(), Path("/new"))
            self.assertEqual(data_dir.data_dir(), Path("/new"))


if __name__ == "__main__":
    unittest.main()
