"""Each file a build reads is downloaded from one version of it, and checked.

AGRIBALYSE's export and BAFU's archive were placed by hand, the GLAD workbook
came from the tip of a GitHub branch, and ChEBI from whatever release the EBI
served that day (#429 to #432).  Each now has an address naming one version and
a digest the bytes must match.
"""

from __future__ import annotations

import gzip
import hashlib
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import httpx

from brightway_flows import downloads
from brightway_flows.downloads import DownloadDigestError, PinnedFile, download_pinned
from brightway_flows.sources import SourceList, known_source_lists

FILE = b"the file as the builds read it"
OTHER = b"a later release under the same name"


def server(answers: dict[str, bytes | int]):
    """An `httpx.stream` that answers each URL with bytes or a status code."""
    requested: list[str] = []

    @contextmanager
    def stream(method, url, **kwargs):
        requested.append(url)
        answer = answers[url]
        request = httpx.Request(method, url)
        if isinstance(answer, int):
            yield httpx.Response(answer, request=request)
        else:
            yield httpx.Response(200, content=answer, request=request)

    return stream, requested


class DownloadPinnedTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dest = Path(directory.name) / "file.csv"
        self.digest = hashlib.sha256(FILE).hexdigest()

    def download(self, answers, urls, **kwargs) -> list[str]:
        stream, requested = server(answers)
        with mock.patch.object(downloads.httpx, "stream", stream):
            download_pinned(self.dest, urls, self.digest, **kwargs)
        return requested

    def assertNoPartFiles(self):
        self.assertEqual(
            [path.name for path in self.dest.parent.iterdir() if path.suffix == ".part"],
            [],
        )

    def test_the_first_address_is_asked_first(self):
        requested = self.download({"https://a/f": FILE}, ["https://a/f", "https://b/f"])
        self.assertEqual(requested, ["https://a/f"])
        self.assertEqual(self.dest.read_bytes(), FILE)

    def test_the_next_address_answers_when_one_does_not(self):
        requested = self.download(
            {"https://a/f": 403, "https://b/f": FILE}, ["https://a/f", "https://b/f"]
        )
        self.assertEqual(requested, ["https://a/f", "https://b/f"])
        self.assertEqual(self.dest.read_bytes(), FILE)

    def test_other_bytes_are_refused_and_not_routed_around(self):
        """Wrong bytes from a pin is a defect in the pin, not an outage."""
        with self.assertRaises(DownloadDigestError):
            self.download(
                {"https://a/f": OTHER, "https://b/f": FILE}, ["https://a/f", "https://b/f"]
            )
        self.assertFalse(self.dest.exists())
        self.assertNoPartFiles()

    def test_no_address_answering_raises_and_leaves_nothing(self):
        with self.assertRaises(httpx.HTTPStatusError):
            self.download({"https://a/f": 503}, ["https://a/f"])
        self.assertFalse(self.dest.exists())
        self.assertNoPartFiles()

    def test_a_gzipped_copy_is_unpacked_and_checked_unpacked(self):
        """The digest is the file's, so a hand-placed copy has the same one."""
        self.download({"https://a/f.gz": gzip.compress(FILE)}, ["https://a/f.gz"], gzipped=True)
        self.assertEqual(self.dest.read_bytes(), FILE)
        self.assertNoPartFiles()

    def test_a_file_already_here_is_read_as_it_is(self):
        """A hand-placed newer release is a new artifact, not a failure."""
        self.dest.write_bytes(OTHER)
        self.assertEqual(self.download({}, ["https://a/f"]), [])
        self.assertEqual(self.dest.read_bytes(), OTHER)


class PinnedSourcesTestCase(unittest.TestCase):
    def test_every_registered_handed_over_list_has_a_copy(self):
        """A list whose vendor publishes no download must name this project's."""
        from brightway_flows.integrations.agribalyse import AGRIBALYSE_DOWNLOADS
        from brightway_flows.integrations.bafu import BAFU_DOWNLOADS
        from brightway_flows.integrations.stepwise import STEPWISE_DOWNLOADS

        pinned = {
            "agribalyse": AGRIBALYSE_DOWNLOADS,
            "bafu": BAFU_DOWNLOADS,
            "stepwise": STEPWISE_DOWNLOADS,
        }
        for source in known_source_lists().values():
            if source.list_name in pinned:
                with self.subTest(key=source.key):
                    self.assertIn(source.list_version, pinned[source.list_name])

    def test_every_address_names_one_version(self):
        from brightway_flows.integrations.agribalyse import AGRIBALYSE_DOWNLOADS
        from brightway_flows.integrations.bafu import BAFU_DOWNLOADS
        from brightway_flows.integrations.chebi import CHEBI_JSON_GZ_URL, CHEBI_RELEASE
        from brightway_flows.integrations.glad_mapping import (
            GLAD_COMMIT,
            GLAD_ILCD_TO_SIMAPRO_URL,
        )
        from brightway_flows.integrations.stepwise import STEPWISE_DOWNLOADS

        self.assertIn(f"/archive/rel{CHEBI_RELEASE}/", CHEBI_JSON_GZ_URL)
        self.assertRegex(GLAD_COMMIT, r"^[0-9a-f]{40}$")
        self.assertIn(f"/raw/{GLAD_COMMIT}/", GLAD_ILCD_TO_SIMAPRO_URL)
        for pinned in (
            *AGRIBALYSE_DOWNLOADS.values(),
            *BAFU_DOWNLOADS.values(),
            *STEPWISE_DOWNLOADS.values(),
        ):
            for url in pinned.urls:
                with self.subTest(url=url):
                    self.assertTrue(url.startswith(downloads.FILES_BRIGHTWAY_DEV))
            self.assertRegex(pinned.sha256, r"^[0-9a-f]{64}$")

    def test_a_missing_vendor_file_is_downloaded_where_the_adapter_wanted_it(self):
        from brightway_flows.integrations import agribalyse, bafu, stepwise

        class Asked(Exception):
            pass

        cases = (
            (agribalyse, "AGRIBALYSE_DOWNLOADS", "agribalyse_csv_path", "agribalyse", "3.2"),
            (bafu, "BAFU_DOWNLOADS", "bafu_ecospold_zip_path", "bafu", "2026-v1"),
            (stepwise, "STEPWISE_DOWNLOADS", "stepwise_csv_path", "stepwise", "2006-1.09"),
        )
        for module, table, path_function, name, version in cases:
            with self.subTest(list=name), tempfile.TemporaryDirectory() as tmp:
                missing = Path(tmp) / "vendor-file"
                pinned = mock.Mock(spec=PinnedFile)
                pinned.download.side_effect = Asked
                source = SourceList(
                    list_name=name, list_version=version, flows_path=Path(tmp) / "f.json"
                )
                with mock.patch.object(module, table, {version: pinned}), mock.patch(
                    f"brightway_flows.filesystem.{path_function}", return_value=missing
                ), self.assertRaises(Asked):
                    module.fetch(source)
                pinned.download.assert_called_once()
                self.assertEqual(pinned.download.call_args.args, (missing,))


if __name__ == "__main__":
    unittest.main()
