"""Which releases the score comparison assesses is a setting, not a constant.

Three things a setting has to do that a constant does not: come with a default
that is the two releases this was built for, be overridable from the
environment for a machine that has other brightway projects, and be readable
by the exporter under a Python that cannot import this package -- which is
what `score-comparison-config` prints.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import typer.main
from typer.testing import CliRunner

from brightway_flows.application.cli import app
from brightway_flows.settings import (
    AppSettings,
    AssessedRelease,
    ScoreComparisonSettings,
)


class DefaultsTestCase(unittest.TestCase):
    def test_the_two_releases_this_was_built_for(self):
        settings = ScoreComparisonSettings()
        self.assertEqual(
            [r.key for r in settings.releases],
            ["ecoinvent-3.8-apos", "ecoinvent-3.12-cutoff"],
        )
        self.assertEqual(settings.releases[0].method_family, "EF v3.0")
        self.assertEqual(settings.releases[1].method_family, "EF v3.1")
        self.assertEqual(settings.sample_size, 500)
        self.assertEqual(
            settings.releases[0].reference_activities, ["b09e51ef9d976bc64905c74fd99842fc"]
        )
        self.assertEqual(settings.releases[1].reference_activities, [])

    def test_the_identity_is_the_merge_s(self):
        """`list_name` and `list_version` are what `elementary_flow_sources` holds."""
        for release in ScoreComparisonSettings().releases:
            self.assertEqual(release.list_name, "ecoinvent")
            self.assertIn(release.list_version, {"3.8", "3.12"})

    def test_an_artifact_path_is_under_the_directory(self):
        settings = ScoreComparisonSettings(artifact_dir=Path("/x"))
        self.assertEqual(
            settings.artifact_path(settings.releases[0]),
            Path("/x/unit-process-scores-ecoinvent-3.8-apos.json"),
        )

    def test_an_unknown_release_names_the_known_ones(self):
        with self.assertRaises(KeyError) as caught:
            ScoreComparisonSettings().release("ecoinvent-3.9.1-cutoff")
        self.assertIn("ecoinvent-3.8-apos", str(caught.exception))

    def test_a_sample_of_nothing_is_refused(self):
        with self.assertRaises(ValueError):
            ScoreComparisonSettings(sample_size=0)


class SourcesTestCase(unittest.TestCase):
    """Environment over file over default, nested with a double underscore."""

    def test_the_environment_overrides(self):
        env = {"SCORE_COMPARISON__SAMPLE_SIZE": "25", "SCORE_COMPARISON__SAMPLE_SEED": "3"}
        with mock.patch.dict(os.environ, env):
            settings = AppSettings()
        self.assertEqual(settings.score_comparison.sample_size, 25)
        self.assertEqual(settings.score_comparison.sample_seed, 3)

    def test_the_file_overrides_the_default_and_keeps_the_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({
                "commonchemistry_api_key": "secret",
                "score_comparison": {
                    "artifact_dir": tmp,
                    "releases": [{
                        "list_name": "ecoinvent", "list_version": "3.11",
                        "system_model": "cutoff",
                        "brightway_project": "ecoinvent-3.11-cutoff",
                        "brightway_database": "ecoinvent-3.11-cutoff",
                        "method_family": "EF v3.1",
                        "artifact": "scores.json",
                    }],
                },
            }))
            # The environment is cleared because the shell running this may
            # carry the real key; the file is patched in because the JSON
            # source reads the class's configured path, not an init kwarg.
            with (
                mock.patch.dict(os.environ, {}, clear=True),
                mock.patch.dict(AppSettings.model_config, {"json_file": str(path)}),
            ):
                settings = AppSettings()
        self.assertEqual(settings.commonchemistry_api_key.get_secret_value(), "secret")
        self.assertEqual(settings.score_comparison.artifact_dir, Path(tmp))
        self.assertEqual(
            [r.key for r in settings.score_comparison.releases], ["ecoinvent-3.11-cutoff"]
        )

    def test_a_release_needs_every_field(self):
        with self.assertRaises(ValueError):
            AssessedRelease(list_name="ecoinvent", list_version="3.8")  # type: ignore[call-arg]


class ConfigCommandTestCase(unittest.TestCase):
    def test_the_command_exists(self):
        self.assertIn("score-comparison-config", typer.main.get_command(app).commands)

    def test_it_prints_the_settings_as_json(self):
        env = {"SCORE_COMPARISON__SAMPLE_SIZE": "7"}
        with mock.patch.dict(os.environ, env):
            from brightway_flows.settings import get_settings

            get_settings.cache_clear()
            try:
                result = CliRunner().invoke(app, ["score-comparison-config"])
            finally:
                get_settings.cache_clear()
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["sample_size"], 7)
        self.assertEqual(payload["releases"][0]["brightway_project"], "ecoinvent-3.8-apos")
