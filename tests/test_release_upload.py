"""`release-upload`: a release goes to Zenodo as a new version, or is refused.

Zenodo is played by a transport that keeps a record with one published
version, 1.1.0, and answers the deposit API's requests the way the service
does: a new version starts with the last one's files and metadata, a file put
into the bucket is answered with its MD5, and nothing has a DOI of its own
until it is published.  Every request is kept, so a test can say what was
sent and, where an upload is refused, that nothing was.
"""

from __future__ import annotations

import gzip
import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

import httpx
import orjson
from typer.testing import CliRunner

from brightway_flows.application.cli import app
from brightway_flows.published_release import ARTIFACT_KEYS, read_published_release
from brightway_flows.releases import zenodo
from brightway_flows.releases.zenodo import (
    ZenodoError,
    check_release_files,
    describe,
    read_release_notes,
    release_files,
    upload_release,
    version_metadata,
)
from brightway_flows.settings import get_settings

RUN = "20261201T1000000000000000"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
CONCEPT = "22857949"
LATEST = "23554066"
DRAFT = "24000001"

NOTES = """# What changed in each release

Intro.

## 1.2.0 — 2026-12-01

Published on [Zenodo](https://doi.org/10.5281/zenodo.0).

Built from six lists: ecoinvent 3.13 joins the five of 1.1.0, and
`Trifluoromethane` is [named](outputs.md) as other lists name it.

### A subsection

More.

## 1.1.0 — 2026-10-21

Built from the same five lists as 1.0.0.
"""


class FakeZenodo:
    """One record, its latest version 1.1.0, and at most one draft."""

    def __init__(self, *, held: str = "1.1.0", corrupt: str | None = None):
        self.held = held
        self.corrupt = corrupt
        self.requests: list[tuple[str, str]] = []
        self.draft_files: dict[str, bytes] = {}
        self.metadata: dict | None = None
        self.published = False
        self.draft_open = False

    @property
    def changes(self) -> list[tuple[str, str]]:
        return [(method, path) for method, path in self.requests if method != "GET"]

    def client(self) -> httpx.Client:
        return httpx.Client(
            base_url="https://zenodo.test",
            transport=httpx.MockTransport(self.handle),
            follow_redirects=True,
        )

    def _draft(self) -> dict:
        return {
            "id": int(DRAFT),
            "links": {
                "bucket": "https://zenodo.test/api/files/bucket-1",
                "html": f"https://zenodo.test/uploads/{DRAFT}",
            },
            "files": [
                {"id": f"id-{name}", "filename": name} for name in self.draft_files
            ],
            "metadata": self.metadata,
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.requests.append((method, path))
        deposition = f"/api/deposit/depositions/{DRAFT}"
        if (method, path) == ("GET", f"/api/records/{CONCEPT}/versions/latest"):
            return httpx.Response(
                301, headers={"Location": f"https://zenodo.test/api/records/{LATEST}"}
            )
        if (method, path) == ("GET", f"/api/records/{LATEST}"):
            return httpx.Response(200, json={
                "id": int(LATEST),
                "doi": f"10.5281/zenodo.{LATEST}",
                "metadata": {"version": self.held},
            })
        if (method, path) == (
            "POST", f"/api/deposit/depositions/{LATEST}/actions/newversion"
        ):
            if not self.draft_open:
                self.draft_open = True
                self.draft_files = {"consensus-flows.sqlite3": b"the 1.1.0 database"}
                self.metadata = {
                    "title": "Brightway Flows v1.1.0",
                    "version": "1.1.0",
                    "publication_date": "2026-10-21",
                    "description": "<p>old</p>",
                    "doi": f"10.5281/zenodo.{LATEST}",
                    "creators": [{"name": "Mutel, Christopher"}],
                    "license": "odc-odbl",
                    "prereserve_doi": {"doi": f"10.5281/zenodo.{DRAFT}"},
                }
            return httpx.Response(201, json={
                "links": {"latest_draft": f"https://zenodo.test{deposition}"}
            })
        if (method, path) == ("GET", deposition):
            return httpx.Response(200, json=self._draft())
        if method == "DELETE" and path.startswith(f"{deposition}/files/id-"):
            del self.draft_files[path.rsplit("/id-", 1)[1]]
            return httpx.Response(204)
        if method == "PUT" and path.startswith("/api/files/bucket-1/"):
            name = path.rsplit("/", 1)[1]
            body = request.read()
            assert request.headers["Content-Length"] == str(len(body))
            self.draft_files[name] = body
            received = b"damaged" if name == self.corrupt else body
            return httpx.Response(201, json={
                "key": name,
                "checksum": "md5:" + hashlib.md5(received).hexdigest(),  # noqa: S324
            })
        if (method, path) == ("PUT", deposition):
            self.metadata = orjson.loads(request.read())["metadata"]
            return httpx.Response(200, json=self._draft())
        if (method, path) == ("POST", f"{deposition}/actions/publish"):
            self.published = True
            return httpx.Response(202, json={
                "links": {"record_html": f"https://zenodo.test/records/{DRAFT}"}
            })
        return httpx.Response(404, text=f"no such route: {method} {path}")


class ReleaseOnDiskTestCase(unittest.TestCase):
    """A data directory holding release 1.2.0, every file from one build."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = Path(self._tmp.name)
        self.releases = self.data / "releases"
        (self.releases / "migrations").mkdir(parents=True)
        self.database = self.data / "consensus-flows.sqlite3"
        self.notes = self.data / "releases.md"
        self.notes.write_text(NOTES, encoding="utf-8")
        self.write_database()
        self.write_snapshot()
        self.write_flows()
        self.write_factor_file("lcia-factors.json.gz")
        self.write_factor_file("lcia-differences.json")
        (self.releases / "migrations" / "1.1.0__1.2.0.zip").write_bytes(b"a zip")

    def write_database(self, run_id: str = RUN):
        self.database.unlink(missing_ok=True)
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "CREATE TABLE pipeline_runs "
                "(run_id TEXT, timestamp TEXT, git_commit TEXT, git_dirty INTEGER)"
            )
            connection.execute(
                "INSERT INTO pipeline_runs VALUES (?, ?, ?, 0)",
                (run_id, "2026-12-01T10:00:00+00:00", COMMIT),
            )
            connection.commit()

    def write_snapshot(self, **changed):
        stamp = {
            "version": "1.2.0",
            "development": False,
            "run_id": RUN,
            "revision": COMMIT,
            "revision_dirty": False,
            "timestamp": "2026-12-01T10:00:00+00:00",
            **changed,
        }
        with gzip.open(self.releases / "1.2.0.json.gz", "wb") as handle:
            handle.write(orjson.dumps({"stamp": stamp}))

    def write_flows(self, run_id: str = RUN):
        document = {
            "concept_schemes": [
                {"owl:versionInfo": "3.2"},
                {"owl:versionInfo": f"run {run_id}, commit {COMMIT}"},
            ]
        }
        with gzip.open(self.data / "harmonised-flows-simple.json.gz", "wb") as handle:
            handle.write(orjson.dumps(document))

    def write_factor_file(self, name: str, run_id: str = RUN):
        payload = orjson.dumps({"stats": {"build_run_id": run_id}})
        path = self.data / name
        if name.endswith(".gz"):
            with gzip.open(path, "wb") as handle:
                handle.write(payload)
        else:
            path.write_bytes(payload)

    def files(self):
        return release_files(
            "1.2.0", "1.1.0", database=self.database, releases_dir=self.releases
        )

    def upload(self, service: FakeZenodo, **options):
        self.lines: list[str] = []
        with service.client() as client:
            return upload_release(
                client,
                version="1.2.0",
                database=self.database,
                releases_dir=self.releases,
                notes_path=self.notes,
                report=self.lines.append,
                **options,
            )


class WhatIsUploadedTestCase(ReleaseOnDiskTestCase):
    def test_the_six_files_and_the_database_last(self):
        self.assertEqual(
            [(file.key, file.name) for file in self.files()],
            [
                ("snapshot", "release-snapshot.json.gz"),
                ("flows", "harmonised-flows-simple.json.gz"),
                ("factors", "lcia-factors.json.gz"),
                ("differences", "lcia-differences.json"),
                ("migration", "1.1.0__1.2.0.zip"),
                ("database", "consensus-flows.sqlite3"),
            ],
        )

    def test_the_keys_are_the_ones_a_release_file_names(self):
        self.assertEqual({file.key for file in self.files()}, set(ARTIFACT_KEYS))

    def test_one_build_is_accepted_and_its_stamp_returned(self):
        stamp = check_release_files("1.2.0", self.files())
        self.assertEqual((stamp.run_id, stamp.revision), (RUN, COMMIT))

    def test_a_missing_file_is_named(self):
        (self.releases / "migrations" / "1.1.0__1.2.0.zip").unlink()
        with self.assertRaisesRegex(ZenodoError, r"1\.1\.0__1\.2\.0\.zip"):
            check_release_files("1.2.0", self.files())

    def test_a_file_from_another_build_is_refused(self):
        """The data directory holds whichever build ran last."""
        writers = {
            "consensus-flows.sqlite3": self.write_database,
            "harmonised-flows-simple.json.gz": self.write_flows,
            "lcia-factors.json.gz": lambda run: self.write_factor_file(
                "lcia-factors.json.gz", run
            ),
            "lcia-differences.json": lambda run: self.write_factor_file(
                "lcia-differences.json", run
            ),
        }
        for name, write in writers.items():
            with self.subTest(name):
                write("20261202T0000000000000000")
                with self.assertRaisesRegex(
                    ZenodoError, rf"{name} is from build run 20261202T"
                ):
                    check_release_files("1.2.0", self.files())
                write(RUN)

    def test_a_snapshot_of_another_kind_of_build_is_refused(self):
        for changed, said in (
            ({"version": "1.2.1"}, "records release 1.2.1, not 1.2.0"),
            ({"development": True}, "development build"),
            ({"revision_dirty": True}, "uncommitted changes"),
        ):
            with self.subTest(changed):
                self.write_snapshot(**changed)
                with self.assertRaisesRegex(ZenodoError, said):
                    check_release_files("1.2.0", self.files())


class TheNotesTestCase(ReleaseOnDiskTestCase):
    def test_the_date_and_the_first_paragraph_as_plain_text(self):
        notes = read_release_notes("1.2.0", self.notes)
        self.assertEqual(notes.date, "2026-12-01")
        self.assertEqual(
            notes.summary,
            "Built from six lists: ecoinvent 3.13 joins the five of 1.1.0, and "
            "Trifluoromethane is named as other lists name it.",
        )

    def test_a_release_without_notes_is_refused(self):
        with self.assertRaisesRegex(ZenodoError, "no section headed `## 1.3.0"):
            read_release_notes("1.3.0", self.notes)

    def test_the_repository_s_notes_are_read_for_a_release_they_hold(self):
        """The real page, read the way an upload reads it."""
        notes = read_release_notes("1.1.0")
        self.assertEqual(notes.date, "2026-10-21")
        self.assertTrue(notes.summary.startswith("Built from the same five lists"))

    def test_the_description_is_escaped_html(self):
        notes = read_release_notes("1.2.0", self.notes)
        text = describe(
            zenodo.ReleaseNotes("1.2.0", notes.date, "Tin < lead & <b>zinc</b>.")
        )
        self.assertIn("Version 1.2.0: Tin &lt; lead &amp; &lt;b&gt;zinc", text)
        self.assertIn(zenodo.RELEASE_NOTES_URL, text)

    def test_the_metadata_keeps_what_the_record_says_and_drops_the_old_doi(self):
        notes = read_release_notes("1.2.0", self.notes)
        metadata = version_metadata(
            {"creators": ["kept"], "doi": "10.5281/zenodo.1", "version": "1.1.0"},
            notes=notes,
            publication_date="2026-12-02",
            previous_doi="10.5281/zenodo.1",
        )
        self.assertEqual(metadata["creators"], ["kept"])
        self.assertNotIn("doi", metadata)
        self.assertEqual(
            (metadata["title"], metadata["version"], metadata["publication_date"]),
            ("Brightway Flows v1.2.0", "1.2.0", "2026-12-02"),
        )


class TheUploadTestCase(ReleaseOnDiskTestCase):
    def test_a_draft_holds_the_six_files_and_the_new_metadata(self):
        service = FakeZenodo()
        result = self.upload(service)
        self.assertFalse(result.published)
        self.assertFalse(service.published)
        self.assertEqual(
            {name: body for name, body in service.draft_files.items()},
            {file.name: file.path.read_bytes() for file in self.files()},
        )
        self.assertEqual(service.metadata["version"], "1.2.0")
        self.assertEqual(service.metadata["title"], "Brightway Flows v1.2.0")
        self.assertEqual(service.metadata["publication_date"], "2026-12-01")
        self.assertIn("Version 1.2.0: Built from six lists", service.metadata["description"])
        self.assertEqual(service.metadata["creators"], [{"name": "Mutel, Christopher"}])
        self.assertNotIn("doi", service.metadata)
        self.assertEqual(result.doi, f"10.5281/zenodo.{DRAFT}")
        self.assertEqual(result.previous_version, "1.1.0")
        self.assertEqual(result.url, f"https://zenodo.test/uploads/{DRAFT}")

    def test_the_checksums_are_of_the_files_on_disk(self):
        result = self.upload(FakeZenodo())
        by_name = {file.name: file for file in self.files()}
        for uploaded in result.files:
            body = by_name[uploaded.name].path.read_bytes()
            self.assertEqual(uploaded.sha256, hashlib.sha256(body).hexdigest())
            self.assertEqual(uploaded.size, len(body))

    def test_the_previous_version_s_files_do_not_stay_on_the_draft(self):
        service = FakeZenodo()
        self.upload(service)
        self.assertNotEqual(
            service.draft_files["consensus-flows.sqlite3"], b"the 1.1.0 database"
        )
        self.assertIn(
            ("DELETE", f"/api/deposit/depositions/{DRAFT}/files/id-consensus-flows.sqlite3"),
            service.requests,
        )

    def test_an_interrupted_upload_can_be_run_again(self):
        service = FakeZenodo()
        self.upload(service)
        result = self.upload(service)
        self.assertEqual(len(service.draft_files), 6)
        self.assertEqual(len(result.files), 6)

    def test_publishing_is_asked_for(self):
        service = FakeZenodo()
        result = self.upload(service, publish=True)
        self.assertTrue(service.published)
        self.assertTrue(result.published)
        self.assertEqual(result.url, f"https://zenodo.test/records/{DRAFT}")

    def test_the_publication_date_can_be_given(self):
        service = FakeZenodo()
        result = self.upload(service, publication_date="2026-12-03")
        self.assertEqual(service.metadata["publication_date"], "2026-12-03")
        self.assertEqual(result.publication_date, "2026-12-03")


class RefusedBeforeAnythingChangesTestCase(ReleaseOnDiskTestCase):
    def assertRefused(self, service: FakeZenodo, said: str, **options):
        with self.assertRaisesRegex(ZenodoError, said):
            self.upload(service, **options)
        self.assertEqual(service.changes, [])

    def test_a_version_zenodo_already_holds(self):
        self.assertRefused(FakeZenodo(held="1.2.0"), "already 1.2.0")

    def test_a_migration_from_a_release_zenodo_does_not_hold(self):
        self.assertRefused(
            FakeZenodo(), "starts from 1.0.0, and Zenodo's latest version is 1.1.0",
            previous_version="1.0.0",
        )

    def test_a_migration_that_was_not_written(self):
        """Zenodo holds 1.1.1, and the only zip on disk starts from 1.1.0."""
        self.assertRefused(FakeZenodo(held="1.1.1"), r"1\.1\.1__1\.2\.0\.zip")

    def test_a_file_from_another_build(self):
        self.write_factor_file("lcia-factors.json.gz", "20261202T0000000000000000")
        self.assertRefused(FakeZenodo(), "lcia-factors.json.gz is from build run")

    def test_a_release_without_notes(self):
        self.notes.write_text("# What changed in each release\n", encoding="utf-8")
        self.assertRefused(FakeZenodo(), "no section headed")


class RefusedByZenodoTestCase(ReleaseOnDiskTestCase):
    def test_a_file_that_arrived_damaged_stops_the_upload_unpublished(self):
        service = FakeZenodo(corrupt="lcia-factors.json.gz")
        with self.assertRaisesRegex(ZenodoError, "lcia-factors.json.gz arrived with MD5"):
            self.upload(service, publish=True)
        self.assertFalse(service.published)
        self.assertNotIn("consensus-flows.sqlite3", [
            path.rsplit("/", 1)[1] for method, path in service.requests if method == "PUT"
        ])

    def test_a_rejected_token_says_what_a_token_needs(self):
        transport = httpx.MockTransport(lambda _request: httpx.Response(401, text="no"))
        with httpx.Client(base_url="https://zenodo.test", transport=transport) as client:
            with self.assertRaisesRegex(ZenodoError, "deposit:write"):
                upload_release(
                    client, version="1.2.0", database=self.database,
                    releases_dir=self.releases, notes_path=self.notes,
                )


class TheCommandTestCase(ReleaseOnDiskTestCase):
    def invoke(self, *arguments: str, token: str | None = "secret"):
        environment = {"ZENODO_ACCESS_TOKEN": token} if token else {}
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        return CliRunner().invoke(
            app,
            ["release-upload", "--version", "1.2.0", "--database", str(self.database),
             *arguments],
            env={"ZENODO_ACCESS_TOKEN": None, **environment},
        )

    def test_without_a_token_nothing_is_tried(self):
        with mock.patch.object(zenodo, "make_client") as make_client:
            result = self.invoke(token=None)
        self.assertEqual(result.exit_code, 2)
        self.assertIn("ZENODO_ACCESS_TOKEN", result.output)
        make_client.assert_not_called()

    def test_a_rehearsal_names_its_own_record(self):
        result = self.invoke("--sandbox")
        self.assertEqual(result.exit_code, 2)
        self.assertIn("--concept-record", result.output)

    def test_it_writes_the_release_file(self):
        service = FakeZenodo()
        seen: dict = {}

        def make_client(token, *, sandbox=False):
            seen.update(token=token, sandbox=sandbox)
            return service.client()

        with (
            mock.patch.object(zenodo, "make_client", make_client),
            mock.patch.object(zenodo, "RELEASES_DIR", self.releases),
            mock.patch.object(zenodo, "RELEASE_NOTES_FILEPATH", self.notes),
        ):
            result = self.invoke("--release-file", str(self.data / "release.json"))
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(seen, {"token": "secret", "sandbox": False})
        self.assertIn("as a draft, not published", result.output)
        self.assertNotIn("secret", result.output)
        release = read_published_release(self.data / "release.json")
        self.assertEqual(
            (release.version, release.previous_version, release.release_date),
            ("1.2.0", "1.1.0", "2026-12-01"),
        )
        self.assertEqual(release.doi, f"10.5281/zenodo.{DRAFT}")
        self.assertEqual(release.record_url, f"https://zenodo.test/records/{DRAFT}")
        database = release.file("database")
        self.assertEqual(database.name, "consensus-flows.sqlite3")
        self.assertEqual(database.size, self.database.stat().st_size)
        self.assertEqual(
            database.sha256, hashlib.sha256(self.database.read_bytes()).hexdigest()
        )

    def test_a_rehearsal_writes_no_release_file_unless_asked(self):
        service = FakeZenodo()
        with (
            mock.patch.object(zenodo, "make_client", lambda *_a, **_k: service.client()),
            mock.patch.object(zenodo, "RELEASES_DIR", self.releases),
            mock.patch.object(zenodo, "RELEASE_NOTES_FILEPATH", self.notes),
        ):
            result = self.invoke("--sandbox", "--concept-record", CONCEPT)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("no release file written", result.output)
        self.assertFalse((self.data / "release.json").exists())


if __name__ == "__main__":
    unittest.main()
