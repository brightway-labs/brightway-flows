"""The EF 3.1 archive is read from this project's backup when the JRC fails.

On 22 October 2026 the JRC's site answered every request with a 403 for a
maintenance window, and no build that had to extract EF 3.1 could start.
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import httpx

from brightway_flows.integrations import ef31

ARCHIVE = b"PK\x03\x04 the archive the backup holds"
OTHER = b"PK\x03\x04 a later JRC release"


def server(answers: dict[str, bytes | int]):
    """An `httpx.stream` that answers each URL with bytes or a status code."""
    requested: list[str] = []

    @contextmanager
    def stream(method, url, **kwargs):
        requested.append(url)
        answer = answers[url]
        request = httpx.Request(method, url)
        if isinstance(answer, int):
            response = httpx.Response(answer, request=request)
        else:
            response = httpx.Response(200, content=answer, request=request)
        yield response

    return stream, requested


class DownloadEF31TestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dest = Path(directory.name) / "EF-v3.1.zip"
        for name, value in {
            "EF31_ZIP_FILEPATH": self.dest,
            "EF31_SHA256": hashlib.sha256(ARCHIVE).hexdigest(),
        }.items():
            patcher = mock.patch.object(ef31, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def download(self, answers: dict[str, bytes | int], **kwargs) -> list[str]:
        stream, requested = server(answers)
        with mock.patch.object(ef31.httpx, "stream", stream):
            ef31.download_ef31(url="https://jrc/ef.zip", backup_url="https://backup/ef.zip", **kwargs)
        return requested

    def test_the_jrc_is_asked_first(self):
        requested = self.download({"https://jrc/ef.zip": ARCHIVE})
        self.assertEqual(requested, ["https://jrc/ef.zip"])
        self.assertEqual(self.dest.read_bytes(), ARCHIVE)

    def test_the_backup_answers_when_the_jrc_refuses(self):
        requested = self.download(
            {"https://jrc/ef.zip": 403, "https://backup/ef.zip": ARCHIVE}
        )
        self.assertEqual(requested, ["https://jrc/ef.zip", "https://backup/ef.zip"])
        self.assertEqual(self.dest.read_bytes(), ARCHIVE)

    def test_a_backup_with_other_bytes_is_refused(self):
        with self.assertRaises(ef31.EF31ArchiveError):
            self.download({"https://jrc/ef.zip": 403, "https://backup/ef.zip": OTHER})
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.dest.with_suffix(".zip.part").exists())

    def test_a_new_jrc_release_is_kept(self):
        """The digest is the backup's, not a condition on what the JRC publishes."""
        self.download({"https://jrc/ef.zip": OTHER})
        self.assertEqual(self.dest.read_bytes(), OTHER)

    def test_without_a_backup_the_jrc_error_is_raised(self):
        stream, _ = server({"https://jrc/ef.zip": 403})
        with mock.patch.object(ef31.httpx, "stream", stream):
            with self.assertRaises(httpx.HTTPStatusError):
                ef31.download_ef31(url="https://jrc/ef.zip", backup_url=None)
        self.assertFalse(self.dest.exists())

    def test_an_archive_already_there_is_not_downloaded(self):
        self.dest.write_bytes(OTHER)
        self.assertEqual(self.download({}), [])

    def test_the_backup_is_this_projects_host(self):
        self.assertTrue(ef31.EF31_BACKUP_URL.startswith("https://files.brightway.dev/"))


if __name__ == "__main__":
    unittest.main()
