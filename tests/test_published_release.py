"""The release file, the download it describes, and which data the application reads.

Zenodo is played by a replacement for `urllib.request.urlopen` that serves
three-line files and honours a ``Range`` header, so an interrupted download
can be carried on the way a real one is.  Nothing here touches the network.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import orjson
from release_fixture import RELEASE_1_1_0, write_release_file
from test_webapp_controls import _write_fixture
from typer.testing import CliRunner

from brightway_flows import published_release
from brightway_flows.application.cli import app as cli
from brightway_flows.published_release import (
    ARTIFACT_KEYS,
    RELEASE_FILE_ENV,
    PublishedRelease,
    ReleaseDownloadError,
    ReleaseFile,
    ReleaseFileError,
    fetch_release,
    fetched_files,
    load_published_release,
    local_path,
    missing_files,
    read_published_release,
    release_directory,
)
from brightway_flows.webapps import app as webapp
from brightway_flows.webapps.app import LOCAL_ENV, create_app

BODIES = {
    "release-snapshot.json.gz": b"the snapshot",
    "harmonised-flows-simple.json.gz": b"the flows",
    "lcia-factors.json.gz": b"the factors",
    "lcia-differences.json": b"the differences",
    "1.1.0__1.2.0.zip": b"the migration",
    "consensus-flows.sqlite3": b"the database, which is the long one",
}
KEYS = dict(zip(ARTIFACT_KEYS, BODIES, strict=True))

RELEASE = PublishedRelease(
    version="1.2.0",
    previous_version="1.1.0",
    release_date="2026-12-01",
    doi="10.5281/zenodo.24000001",
    record_url="https://zenodo.test/records/24000001",
    files=tuple(
        ReleaseFile(key, name, len(BODIES[name]), hashlib.sha256(BODIES[name]).hexdigest())
        for key, name in KEYS.items()
    ),
)


class FakeZenodoFiles:
    """`urlopen`, answering for the record's files."""

    def __init__(self, *, bodies=None, resumes=True, down=False, failing=0, gone=False):
        self.bodies = dict(bodies or BODIES)
        self.resumes = resumes
        self.down = down
        #: How many requests are answered with a 500 before one is served.
        self.failing = failing
        self.gone = gone
        self.requests: list[tuple[str, str | None]] = []

    def __call__(self, request, timeout=None):
        name = request.full_url.split("/files/")[1].split("?")[0]
        byte_range = request.get_header("Range")
        self.requests.append((name, byte_range))
        if self.down:
            raise urllib.error.URLError("no route to host")
        if self.gone:
            raise urllib.error.HTTPError(request.full_url, 404, "NOT FOUND", {}, None)
        if self.failing:
            self.failing -= 1
            raise urllib.error.HTTPError(
                request.full_url, 500, "INTERNAL SERVER ERROR", {}, None
            )
        body = self.bodies[name]
        response = io.BytesIO(body)
        response.status = 200
        if byte_range and self.resumes:
            response = io.BytesIO(body[int(byte_range.removeprefix("bytes=").rstrip("-")):])
            response.status = 206
        return response

    def patch(self):
        return mock.patch.object(published_release.urllib.request, "urlopen", self)


class _TmpTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        # No test here reads whatever release file the machine names.
        patched = mock.patch.dict(os.environ)
        patched.start()
        self.addCleanup(patched.stop)
        os.environ.pop(RELEASE_FILE_ENV, None)
        os.environ.pop(LOCAL_ENV, None)
        # A retry does not wait in a test.
        waiting = mock.patch.object(published_release, "_WAIT_SECONDS", 0)
        waiting.start()
        self.addCleanup(waiting.stop)


class TheReleaseFileTestCase(_TmpTestCase):
    def test_what_is_written_is_what_is_read(self):
        path = write_release_file(self.tmp, RELEASE)
        self.assertEqual(read_published_release(path), RELEASE)
        self.assertEqual(
            list(orjson.loads(path.read_bytes())),
            ["version", "previous_version", "release_date", "doi", "record_url", "files"],
        )

    def test_the_checksums_are_keyed_as_the_download_page_asks(self):
        self.assertEqual(set(RELEASE.checksums), set(ARTIFACT_KEYS))
        self.assertEqual(
            RELEASE.download_url(RELEASE.file("database")),
            "https://zenodo.test/records/24000001/files/consensus-flows.sqlite3?download=1",
        )

    def test_the_data_directory_s_file_is_read_and_its_absence_is_an_answer(self):
        self.assertIsNone(load_published_release(data_dir=self.tmp))
        write_release_file(self.tmp, RELEASE)
        self.assertEqual(load_published_release(data_dir=self.tmp), RELEASE)

    def test_the_variable_names_another_file_which_has_to_be_there(self):
        elsewhere = self.tmp / "elsewhere"
        named = write_release_file(elsewhere, RELEASE_1_1_0)
        write_release_file(self.tmp, RELEASE)
        os.environ[RELEASE_FILE_ENV] = str(named)
        self.assertEqual(load_published_release(data_dir=self.tmp), RELEASE_1_1_0)
        os.environ[RELEASE_FILE_ENV] = str(self.tmp / "nowhere.json")
        with self.assertRaisesRegex(ReleaseFileError, "nowhere.json"):
            load_published_release(data_dir=self.tmp)

    def test_a_malformed_file_raises(self):
        """Never read in part: five files would be served as a release with
        one missing."""
        good = RELEASE.to_dict()
        cases = {
            "not json": b"{",
            "a file missing": orjson.dumps(
                {**good, "files": {k: v for k, v in good["files"].items() if k != "database"}}
            ),
            "a short checksum": orjson.dumps(
                {**good, "files": {**good["files"], "flows": {
                    "name": "f", "size": 1, "sha256": "abc"}}}
            ),
            "a path for a name": orjson.dumps(
                {**good, "files": {**good["files"], "flows": {
                    "name": "../f", "size": 1, "sha256": "0" * 64}}}
            ),
            "an unknown field": orjson.dumps({**good, "licence": "x"}),
            "no doi": orjson.dumps({k: v for k, v in good.items() if k != "doi"}),
        }
        for name, content in cases.items():
            with self.subTest(name):
                path = self.tmp / "release.json"
                path.write_bytes(content)
                with self.assertRaises(ReleaseFileError):
                    read_published_release(path)


class TheDownloadTestCase(_TmpTestCase):
    def setUp(self):
        super().setUp()
        self.directory = release_directory(RELEASE, self.tmp)

    def test_only_the_database_is_fetched(self):
        """The one file the application reads.  The other five are files a
        reader downloads, and a reader gets them from Zenodo."""
        self.assertEqual(self.directory, self.tmp / "published" / "1.2.0")
        self.assertEqual([file.key for file in fetched_files(RELEASE)], ["database"])
        zenodo = FakeZenodoFiles()
        with zenodo.patch():
            fetch_release(RELEASE, self.directory)
        self.assertEqual(zenodo.requests, [("consensus-flows.sqlite3", None)])
        self.assertEqual(
            sorted(
                str(path.relative_to(self.directory))
                for path in self.directory.rglob("*")
                if path.is_file() and not path.name.startswith(".")
            ),
            ["consensus-flows.sqlite3"],
        )
        database = RELEASE.file("database")
        self.assertEqual(
            local_path(database, self.directory).read_bytes(), BODIES[database.name]
        )
        self.assertEqual(missing_files(RELEASE, self.directory), [])

    def test_a_release_already_there_asks_nothing_of_the_network(self):
        with FakeZenodoFiles().patch():
            fetch_release(RELEASE, self.directory)
        zenodo = FakeZenodoFiles(down=True)
        with zenodo.patch():
            fetch_release(RELEASE, self.directory)
        self.assertEqual(zenodo.requests, [])

    def test_a_database_of_another_size_is_downloaded_again(self):
        with FakeZenodoFiles().patch():
            fetch_release(RELEASE, self.directory)
        (self.directory / "consensus-flows.sqlite3").write_bytes(b"cut short")
        zenodo = FakeZenodoFiles()
        lines: list[str] = []
        with zenodo.patch():
            fetch_release(RELEASE, self.directory, report=lines.append)
        self.assertEqual(zenodo.requests, [("consensus-flows.sqlite3", None)])
        self.assertEqual(len(lines), 1)
        self.assertIn("consensus-flows.sqlite3 of 1.2.0", lines[0])
        self.assertEqual(missing_files(RELEASE, self.directory), [])

    def test_an_interrupted_download_carries_on_where_it_stopped(self):
        body = BODIES["consensus-flows.sqlite3"]
        self.directory.mkdir(parents=True)
        (self.directory / "consensus-flows.sqlite3.part").write_bytes(body[:10])
        zenodo = FakeZenodoFiles()
        with zenodo.patch():
            fetch_release(RELEASE, self.directory)
        self.assertIn(("consensus-flows.sqlite3", "bytes=10-"), zenodo.requests)
        self.assertEqual((self.directory / "consensus-flows.sqlite3").read_bytes(), body)
        self.assertFalse((self.directory / "consensus-flows.sqlite3.part").exists())

    def test_a_server_that_will_not_resume_is_read_from_the_start(self):
        body = BODIES["consensus-flows.sqlite3"]
        self.directory.mkdir(parents=True)
        (self.directory / "consensus-flows.sqlite3.part").write_bytes(b"x" * 10)
        with FakeZenodoFiles(resumes=False).patch():
            fetch_release(RELEASE, self.directory)
        self.assertEqual((self.directory / "consensus-flows.sqlite3").read_bytes(), body)

    def test_other_bytes_than_the_release_s_are_refused_and_removed(self):
        zenodo = FakeZenodoFiles(
            bodies={**BODIES, "consensus-flows.sqlite3": b"not the database"}
        )
        with zenodo.patch(), self.assertRaisesRegex(
            ReleaseDownloadError, "consensus-flows.sqlite3 of 1.2.0 arrived with SHA-256"
        ):
            fetch_release(RELEASE, self.directory)
        self.assertFalse((self.directory / "consensus-flows.sqlite3").exists())
        self.assertFalse((self.directory / "consensus-flows.sqlite3.part").exists())
        self.assertIn(RELEASE.file("database"), missing_files(RELEASE, self.directory))

    def test_zenodo_not_answering_is_a_download_error(self):
        zenodo = FakeZenodoFiles(down=True)
        with zenodo.patch(), self.assertRaises(ReleaseDownloadError):
            fetch_release(RELEASE, self.directory)
        self.assertEqual(len(zenodo.requests), published_release._ATTEMPTS)

    def test_a_server_error_is_asked_again(self):
        """Zenodo answered the first real download with a 500, and the same
        request a moment later with the file."""
        zenodo = FakeZenodoFiles(failing=2)
        with zenodo.patch():
            fetch_release(RELEASE, self.directory)
        self.assertEqual(missing_files(RELEASE, self.directory), [])
        self.assertEqual(len(zenodo.requests), 3)

    def test_a_file_that_is_not_there_is_not_asked_for_again(self):
        """An unpublished draft, or a release file naming the wrong record."""
        zenodo = FakeZenodoFiles(gone=True)
        with zenodo.patch(), self.assertRaisesRegex(ReleaseDownloadError, "404"):
            fetch_release(RELEASE, self.directory)
        self.assertEqual(len(zenodo.requests), 1)


class WhichDataTheApplicationReadsTestCase(_TmpTestCase):
    """The published release by default; the local build where it is asked for."""

    def setUp(self):
        super().setUp()
        self.zenodo = FakeZenodoFiles()
        for patcher in (
            self.zenodo.patch(),
            mock.patch.object(webapp, "DATA_DIR", self.tmp),
            mock.patch.object(
                webapp, "CONSENSUS_DB_FILEPATH", self.tmp / "consensus-flows.sqlite3"
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_release_is_downloaded_on_the_first_launch_and_read_from_there(self):
        write_release_file(self.tmp, RELEASE)
        app = create_app()
        directory = self.tmp / "published" / "1.2.0"
        self.assertEqual(app.config["CONSENSUS_DB_PATH"], directory / "consensus-flows.sqlite3")
        self.assertEqual(app.config["CONSENSUS_DATA_DIR"], directory)
        self.assertEqual(app.config["SERVED_RELEASE"], RELEASE)
        self.assertEqual(self.zenodo.requests, [("consensus-flows.sqlite3", None)])
        self.assertEqual(
            app.config["CONSENSUS_DB_PATH"].read_bytes(), BODIES["consensus-flows.sqlite3"]
        )

    def test_the_second_launch_downloads_nothing(self):
        write_release_file(self.tmp, RELEASE)
        create_app()
        self.zenodo.requests.clear()
        create_app()
        self.assertEqual(self.zenodo.requests, [])

    def test_the_download_page_sizes_every_file_from_the_release_file(self):
        """Five of the six are not on this machine, and each still has a row,
        a size and its checksum."""
        release = dataclasses.replace(
            RELEASE,
            files=tuple(
                dataclasses.replace(file, size=size)
                for file, size in zip(
                    RELEASE.files,
                    (59_500_000, 45_900_000, 16_400_000, 29_500_000, 6_400_000,
                     len(BODIES["consensus-flows.sqlite3"])),
                    strict=True,
                )
            ),
        )
        write_release_file(self.tmp, release)
        app = create_app()
        app.config["TESTING"] = True
        body = app.test_client().get("/download/").get_data(as_text=True)
        self.assertIn("Latest release · 1.2.0 · Released 2026-12-01", body)
        self.assertIn("Migration from 1.1.0", body)
        self.assertIn("1.1.0__1.2.0.zip", body)
        for size in ("59.5 MB", "45.9 MB", "16.4 MB", "29.5 MB", "6.4 MB"):
            with self.subTest(size):
                self.assertIn(f"<span>{size}</span>", body)
        for key in ARTIFACT_KEYS:
            self.assertIn(release.checksums[key], body)
        self.assertNotIn("Not in this build", body)

    def test_the_build_page_links_the_files_it_does_not_hold_to_zenodo(self):
        """The database is served from here; the other five are rows with the
        release's size and Zenodo's address, not absences."""
        fixture = self.tmp / "fixture.sqlite3"
        _write_fixture(fixture)
        body = fixture.read_bytes()
        release = dataclasses.replace(
            RELEASE,
            files=tuple(
                ReleaseFile(
                    file.key, file.name, len(body), hashlib.sha256(body).hexdigest()
                )
                if file.key == "database"
                else file
                for file in RELEASE.files
            ),
        )
        self.zenodo.bodies["consensus-flows.sqlite3"] = body
        write_release_file(self.tmp, release)
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        response = client.get("/run/")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("6 of\n      6 published", page)
        self.assertIn('href="/run/download/database"', page)
        for key in ("snapshot", "flows", "factors", "differences", "migration"):
            with self.subTest(key):
                file = release.file(key)
                self.assertIn(
                    f'href="{release.record_url}/files/{file.name}?download=1"', page
                )
                self.assertNotIn(f"/run/download/{key}", page)
                self.assertEqual(client.get(f"/run/download/{key}").status_code, 404)
        self.assertNotIn("this run did not write it", page)
        served = client.get("/run/download/database")
        self.addCleanup(served.close)
        self.assertEqual(served.status_code, 200)

    def test_over_a_local_build_the_download_page_still_sizes_the_release(self):
        """The page is about the release wherever one is named."""
        write_release_file(self.tmp, RELEASE)
        (self.tmp / "lcia-factors.json.gz").write_bytes(b"x" * 5000)
        app = create_app(local=True)
        app.config["TESTING"] = True
        body = app.test_client().get("/download/").get_data(as_text=True)
        self.assertIn(f"<span>{len(BODIES['lcia-factors.json.gz'])} bytes</span>", body)
        self.assertNotIn("5.0 kB", body)

    def test_the_flag_reads_the_local_build_and_still_names_the_release(self):
        write_release_file(self.tmp, RELEASE)
        app = create_app(local=True)
        self.assertEqual(
            app.config["CONSENSUS_DB_PATH"], self.tmp / "consensus-flows.sqlite3"
        )
        self.assertIsNone(app.config["SERVED_RELEASE"])
        self.assertEqual(app.config["PUBLISHED_RELEASE"], RELEASE)
        self.assertEqual(self.zenodo.requests, [])

    def test_the_variable_says_the_same_as_the_flag(self):
        write_release_file(self.tmp, RELEASE)
        os.environ[LOCAL_ENV] = "1"
        app = create_app()
        self.assertIsNone(app.config["SERVED_RELEASE"])
        self.assertEqual(self.zenodo.requests, [])

    def test_a_named_database_is_read_as_it_is(self):
        """A fixture, or a deployment pointed at one build."""
        write_release_file(self.tmp, RELEASE)
        app = create_app(self.tmp / "consensus-flows.sqlite3")
        self.assertIsNone(app.config["SERVED_RELEASE"])
        self.assertEqual(self.zenodo.requests, [])

    def test_no_release_file_is_the_local_build_and_a_placeholder(self):
        app = create_app()
        self.assertEqual(
            app.config["CONSENSUS_DB_PATH"], self.tmp / "consensus-flows.sqlite3"
        )
        self.assertIsNone(app.config["PUBLISHED_RELEASE"])
        self.assertEqual(self.zenodo.requests, [])
        app.config["TESTING"] = True
        body = app.test_client().get("/download/").get_data(as_text=True)
        self.assertIn("[v1.0.0]", body)
        self.assertIn("Migration from the previous release", body)

    def test_a_release_that_cannot_be_downloaded_is_a_page_saying_so(self):
        """Not a start-up failure: the documentation still has to be served."""
        write_release_file(self.tmp, RELEASE)
        self.zenodo.down = True
        app = create_app()
        app.config["TESTING"] = True
        response = app.test_client().get("/run/")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("This application serves release 1.2.0", body)
        self.assertIn("brightway-flows release-download", body)
        self.assertNotIn("brightway-flows build", body)

    def test_a_local_application_with_no_build_still_says_to_build(self):
        body = create_app(local=True).test_client().get("/run/").get_data(as_text=True)
        self.assertIn("brightway-flows build", body)
        self.assertNotIn("release-download", body)

    def test_a_named_release_file_that_cannot_be_read_stops_the_start(self):
        with self.assertRaises(ReleaseFileError):
            create_app(release_path=self.tmp / "nowhere.json")


class TheDownloadCommandTestCase(_TmpTestCase):
    def invoke(self, *arguments: str):
        with mock.patch.object(published_release, "resolve_data_dir", lambda: self.tmp):
            return CliRunner().invoke(cli, ["release-download", *arguments])

    def test_it_downloads_into_the_data_directory_and_says_where(self):
        write_release_file(self.tmp, RELEASE)
        with FakeZenodoFiles().patch():
            result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("database downloaded", result.output)
        self.assertIn(str(self.tmp / "published" / "1.2.0"), result.output.replace("\n", ""))
        with FakeZenodoFiles(down=True).patch():
            again = self.invoke()
        self.assertEqual(again.exit_code, 0, again.output)
        self.assertIn("nothing to download", again.output)

    def test_no_release_file_is_refused(self):
        result = self.invoke()
        self.assertEqual(result.exit_code, 2)
        self.assertIn("no release file", result.output)

    def test_a_failed_download_exits_with_one(self):
        write_release_file(self.tmp, RELEASE)
        with FakeZenodoFiles(down=True).patch():
            result = self.invoke()
        self.assertEqual(result.exit_code, 1)


if __name__ == "__main__":
    unittest.main()
