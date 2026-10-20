"""The one download path: through a `.part` file, checked where a digest is
given, and cleaned up where it is not the file named."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import httpx

from brightway_flows.download import DigestMismatchError, download, sha256_of

BODY = b"not much of an archive"


@contextmanager
def _stream(body: bytes = BODY, *, status: int = 200):
    response = mock.MagicMock()
    response.headers = {"content-length": str(len(body))}
    response.iter_bytes.return_value = [body[:5], body[5:]]
    if status != 200:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom", request=mock.MagicMock(), response=mock.MagicMock()
        )
    yield response


class DownloadTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.destination = self.root / "archive.zip"

    def test_the_file_arrives_whole_under_its_own_name(self):
        with mock.patch("httpx.stream", return_value=_stream()) as stream:
            path = download("https://example.org/a.zip", self.destination)
        self.assertEqual(path, self.destination)
        self.assertEqual(self.destination.read_bytes(), BODY)
        self.assertEqual(list(self.root.iterdir()), [self.destination])
        self.assertEqual(stream.call_args.kwargs["timeout"], 300)

    def test_a_digest_that_matches_is_accepted(self):
        with mock.patch("httpx.stream", return_value=_stream()):
            download(
                "https://example.org/a.zip",
                self.destination,
                sha256=hashlib.sha256(BODY).hexdigest(),
            )
        self.assertTrue(self.destination.exists())

    def test_a_digest_that_does_not_match_leaves_nothing_behind(self):
        with mock.patch("httpx.stream", return_value=_stream()):
            with self.assertRaises(DigestMismatchError):
                download("https://example.org/a.zip", self.destination, sha256="0" * 64)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_an_http_error_leaves_nothing_behind(self):
        with mock.patch("httpx.stream", return_value=_stream(status=500)):
            with self.assertRaises(httpx.HTTPError):
                download("https://example.org/a.zip", self.destination)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_headers_and_timeout_reach_the_request(self):
        with mock.patch("httpx.stream", return_value=_stream()) as stream:
            download(
                "https://example.org/a.zip",
                self.destination,
                timeout=12,
                headers={"User-Agent": "x"},
            )
        self.assertEqual(stream.call_args.kwargs["timeout"], 12)
        self.assertEqual(stream.call_args.kwargs["headers"], {"User-Agent": "x"})

    def test_sha256_of_is_the_file_s_digest(self):
        self.destination.write_bytes(BODY)
        self.assertEqual(sha256_of(self.destination), hashlib.sha256(BODY).hexdigest())


if __name__ == "__main__":
    unittest.main()
