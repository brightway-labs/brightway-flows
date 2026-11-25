"""Upload a release to Zenodo as a new version of the list's record.

A release is six files, and each is already on disk when this runs: the
snapshot `release-snapshot` wrote, the three JSON exports and the database a
build and `characterise` wrote, and the zip `release-migrations` wrote from
the release before.  Uploading them by hand is fifteen minutes of dragging
files into a browser, and three things can go wrong that a browser will not
notice: a file from another build (the data directory holds whichever build
ran last), a migration that starts from a release other than the one Zenodo
holds, and a checksum copied from a file other than the one uploaded.  So the
work here is mostly the checking, and it all happens before the first request
that changes anything.

**Nothing is published unless it is asked for.**  A published Zenodo version
has a DOI and cannot be withdrawn or have its files replaced, so
:func:`upload_release` leaves a draft for a person to read and publish, and
publishes only with ``publish=True``.  A draft can be rerun over: the files
on it are deleted and uploaded again.

What was uploaded is returned as a `published_release.PublishedRelease`, which
the command writes to ``release.json``: the file the review application reads
to say which release it serves, and to download it.

The requests are Zenodo's deposit API, <https://developers.zenodo.org>: a new
version is opened on the latest published one, the files copied forward onto
its draft are deleted, each file is streamed into the draft's bucket, and the
metadata copied forward is sent back with the version, the date, the title
and the description changed.
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from brightway_flows.filesystem import (
    CONSENSUS_DB_FILEPATH,
    HARMONISED_FLOWS_SIMPLE_FILEPATH,
    LCIA_DIFFERENCES_FILEPATH,
    LCIA_FACTORS_FILEPATH,
    RELEASES_DIR,
    REPO_ROOT,
)
from brightway_flows.published_release import PublishedRelease
from brightway_flows.published_release import ReleaseFile as PublishedFile
from brightway_flows.releases.snapshot import (
    ReleaseStamp,
    SnapshotError,
    read_snapshot_payload,
    read_stamp,
    snapshot_path,
)
from brightway_flows.releases.version import named_version

ZENODO_URL = "https://zenodo.org"
#: Zenodo's rehearsal site: the same API, records that mean nothing, and its
#: own accounts and tokens.  A record there has another number, so a rehearsal
#: names its own with ``concept_record_id``.
ZENODO_SANDBOX_URL = "https://sandbox.zenodo.org"

#: The record every version of the list hangs off: 10.5281/zenodo.22857949,
#: the DOI that always resolves to the latest release.
CONCEPT_RECORD_ID = "22857949"

#: Where the release notes are, and where the description sends a reader for
#: the rest of them.
RELEASE_NOTES_FILEPATH = REPO_ROOT / "docs" / "using" / "releases.md"
RELEASE_NOTES_URL = (
    "https://github.com/brightway-labs/brightway-flows/blob/main/docs/using/releases.md"
)

#: What the snapshot is called on the record.  On disk it is named by its
#: release, which the record already says.
SNAPSHOT_UPLOAD_NAME = "release-snapshot.json.gz"

#: The paragraph every version's description opens with.
ABOUT = (
    "Brightway Flows is a list of elementary flows for life cycle assessment. "
    "It takes existing flow lists, like EF 3.1, and then enriches those existing "
    "elementary flows by adding in chemical, physical, and biological properties, "
    "as well as registry numbers and web links. It also creates taxonomies for "
    "specific classes of flows, like agricultural chemicals or elements, and "
    "classifies flows in those taxonomies. It then runs a harmonisation algorithm "
    "to get agreement within and across elementary flow lists. Finally, it links "
    "and compares characterisation factors for elementary flows. All source code "
    "and data outputs are open."
)

_CHUNK = 1024 * 1024


class ZenodoError(RuntimeError):
    """The release cannot be uploaded, or Zenodo refused a request."""


@dataclass(frozen=True)
class ReleaseFile:
    """One file of a release: where it is, and what the record calls it.

    ``key`` is one of `published_release.ARTIFACT_KEYS`, which is how the
    release file and the Download page name the file.
    """

    key: str
    path: Path
    name: str


@dataclass(frozen=True)
class UploadedFile:
    key: str
    name: str
    size: int
    sha256: str
    md5: str


@dataclass(frozen=True)
class ReleaseNotes:
    """What the release notes say about one release."""

    version: str
    #: The date in the release's heading, ``2026-10-21``.
    date: str
    #: The first paragraph of the release's section, as plain text.
    summary: str


@dataclass(frozen=True)
class UploadResult:
    version: str
    previous_version: str
    record_id: str
    doi: str
    #: Where a person reads it: the draft's page, or the record's once published.
    url: str
    #: The version's page once it is published, whether or not it is yet.
    record_url: str
    publication_date: str
    published: bool
    files: list[UploadedFile]

    @property
    def release(self) -> PublishedRelease:
        """What was uploaded, as the release file records it."""
        return PublishedRelease(
            version=self.version,
            previous_version=self.previous_version,
            release_date=self.publication_date,
            doi=self.doi,
            record_url=self.record_url,
            files=tuple(
                PublishedFile(file.key, file.name, file.size, file.sha256)
                for file in self.files
            ),
        )


# -- what is uploaded ----------------------------------------------------------


def release_files(
    version: str,
    previous_version: str,
    *,
    database: Path | None = None,
    releases_dir: Path | None = None,
) -> list[ReleaseFile]:
    """The six files of *version*, in the order they are uploaded.

    The database is last because it is the large one -- 2.6 GB for 1.1.0 --
    so a mistake in any other file is found before the long upload starts.
    The exports are read from beside the database, which is where the build
    that made it wrote them.
    """
    database = database or CONSENSUS_DB_FILEPATH
    releases = releases_dir or RELEASES_DIR
    beside = database.parent
    migration = f"{previous_version}__{version}.zip"
    return [
        ReleaseFile("snapshot", snapshot_path(version, releases), SNAPSHOT_UPLOAD_NAME),
        ReleaseFile(
            "flows",
            beside / HARMONISED_FLOWS_SIMPLE_FILEPATH.name,
            HARMONISED_FLOWS_SIMPLE_FILEPATH.name,
        ),
        ReleaseFile(
            "factors", beside / LCIA_FACTORS_FILEPATH.name, LCIA_FACTORS_FILEPATH.name
        ),
        ReleaseFile(
            "differences",
            beside / LCIA_DIFFERENCES_FILEPATH.name,
            LCIA_DIFFERENCES_FILEPATH.name,
        ),
        ReleaseFile("migration", releases / "migrations" / migration, migration),
        ReleaseFile("database", database, CONSENSUS_DB_FILEPATH.name),
    ]


def check_release_files(version: str, files: list[ReleaseFile]) -> ReleaseStamp:
    """Refuse a set of files that is not one clean build recorded as *version*.

    The data directory holds whichever build ran last, and a release is
    assembled over an afternoon, so each file is asked which build made it:
    the snapshot's stamp is the reference, and the database, the flow list and
    both factor files have to name the same run.  The migration is not asked;
    `release-migrations` only zips one that replays onto the later snapshot.

    :raises ZenodoError: naming everything wrong, not only the first.
    """
    by_key = {file.key: file for file in files}
    missing = [str(file.path) for file in files if not file.path.is_file()]
    if missing:
        raise ZenodoError(
            "these files of the release are not on disk: " + ", ".join(missing)
        )
    try:
        stamp = ReleaseStamp.from_dict(
            read_snapshot_payload(by_key["snapshot"].path)["stamp"]
        )
        database = read_stamp(by_key["database"].path, version=named_version(version))
        flows = read_snapshot_payload(by_key["flows"].path)
        factors = read_snapshot_payload(by_key["factors"].path)
        differences = read_snapshot_payload(by_key["differences"].path)
    except (SnapshotError, KeyError, TypeError) as error:
        raise ZenodoError(f"a file of the release cannot be read: {error}") from error

    problems: list[str] = []
    if stamp.version != version:
        problems.append(
            f"{by_key['snapshot'].path} records release {stamp.version}, not {version}"
        )
    if stamp.development:
        problems.append(
            "the snapshot is of a development build: no git tag named its commit "
            "when it was recorded"
        )
    if stamp.revision_dirty:
        problems.append(
            "the snapshot is of a build made from a tree with uncommitted changes"
        )
    scheme_versions = [
        str(scheme.get("owl:versionInfo") or "")
        for scheme in flows.get("concept_schemes") or []
    ]
    made_by = {
        "database": database.run_id,
        "factors": str((factors.get("stats") or {}).get("build_run_id") or ""),
        "differences": str((differences.get("stats") or {}).get("build_run_id") or ""),
        "flows": next(
            (
                text.removeprefix("run ").split(",")[0]
                for text in scheme_versions
                if text.startswith("run ")
            ),
            "",
        ),
    }
    for key, run_id in made_by.items():
        if run_id != stamp.run_id:
            problems.append(
                f"{by_key[key].path} is from build run {run_id or 'unknown'}, and "
                f"the snapshot records run {stamp.run_id}"
            )
    if problems:
        raise ZenodoError("; ".join(problems))
    return stamp


# -- what the record says ------------------------------------------------------

_HEADING = re.compile(r"^## (?P<version>\S+) — (?P<date>\d{4}-\d{2}-\d{2})\s*$")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def read_release_notes(version: str, path: Path | None = None) -> ReleaseNotes:
    """The date and the opening paragraph of *version*'s section of the notes.

    The section is the one headed ``## 1.1.0 — 2026-10-21``.  Its first
    paragraph is the summary, skipping the ``Published on Zenodo`` line, which
    is added after the upload and says nothing about the release.

    :raises ZenodoError: where the notes have no section for the release, or
        the section has no paragraph.  A release without notes is not ready.
    """
    path = path or RELEASE_NOTES_FILEPATH
    date = ""
    section: list[str] = []
    inside = False
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = _HEADING.match(line)
        if line.startswith("## "):
            if inside:
                break
            if heading and heading["version"] == version:
                inside, date = True, heading["date"]
            continue
        if inside:
            if line.startswith("#"):
                break
            section.append(line)
    if not inside:
        raise ZenodoError(
            f"{path} has no section headed `## {version} — <date>`; write the "
            "release's notes before uploading it"
        )
    for paragraph in "\n".join(section).split("\n\n"):
        text = " ".join(paragraph.split())
        if not text or text.startswith("Published on"):
            continue
        return ReleaseNotes(
            version=version,
            date=date,
            summary=_LINK.sub(r"\1", text).replace("`", "").replace("**", ""),
        )
    raise ZenodoError(f"{path}: the section for {version} has no paragraph to quote")


def describe(notes: ReleaseNotes) -> str:
    """The record's description, which Zenodo stores as HTML."""
    return (
        f"<p>{html.escape(ABOUT)}<br><br>"
        f"Version {html.escape(notes.version)}: {html.escape(notes.summary)}<br><br>"
        f'See the full changelog at the <a href="{RELEASE_NOTES_URL}">GitHub source '
        "repo</a>.</p>"
    )


def version_metadata(
    copied: dict[str, Any],
    *,
    notes: ReleaseNotes,
    publication_date: str,
    previous_doi: str,
) -> dict[str, Any]:
    """The metadata of the new version: the last one's, with four fields changed.

    Creators, licence, keywords and the rest are whatever the record already
    says, so a correction made on Zenodo's own form is not undone by the next
    upload.  The DOI is dropped where the draft still carries the previous
    version's, so Zenodo gives the new version its own.
    """
    metadata = dict(copied)
    if metadata.get("doi") == previous_doi:
        del metadata["doi"]
    metadata["title"] = f"Brightway Flows v{notes.version}"
    metadata["version"] = notes.version
    metadata["publication_date"] = publication_date
    metadata["description"] = describe(notes)
    return metadata


# -- the requests --------------------------------------------------------------


def _checked(response: httpx.Response, doing: str) -> httpx.Response:
    if response.is_success:
        return response
    detail = response.text[:500]
    if response.status_code in (401, 403):
        detail += (
            " -- is ZENODO_ACCESS_TOKEN a token of this Zenodo site, with the "
            "`deposit:write` and `deposit:actions` scopes?"
        )
    raise ZenodoError(f"Zenodo refused {doing} ({response.status_code}): {detail}")


def digests(path: Path) -> tuple[int, str, str]:
    """A file's size, SHA-256 and MD5, read once."""
    sha256, md5, size = hashlib.sha256(), hashlib.md5(), 0  # noqa: S324
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            sha256.update(chunk)
            md5.update(chunk)
            size += len(chunk)
    return size, sha256.hexdigest(), md5.hexdigest()


def _chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            yield chunk


def make_client(token: str, *, sandbox: bool = False) -> httpx.Client:
    """A client for one upload.  No write timeout: the database takes as long
    as the line allows, and a timeout would only restart it."""
    return httpx.Client(
        base_url=ZENODO_SANDBOX_URL if sandbox else ZENODO_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(60.0, read=600.0, write=None),
        follow_redirects=True,
    )


def latest_version(client: httpx.Client, concept_record_id: str) -> dict[str, Any]:
    """The latest published version of the record, as Zenodo describes it."""
    return _checked(
        client.get(f"/api/records/{concept_record_id}/versions/latest"),
        f"the latest version of record {concept_record_id}",
    ).json()


def _open_draft(client: httpx.Client, latest_id: str) -> dict[str, Any]:
    """The draft of the next version, opening one if there is none."""
    opened = _checked(
        client.post(f"/api/deposit/depositions/{latest_id}/actions/newversion"),
        "opening a new version",
    ).json()
    draft_url = (opened.get("links") or {}).get("latest_draft")
    if not draft_url:
        raise ZenodoError(
            "Zenodo opened a new version and did not say where its draft is"
        )
    return _checked(client.get(draft_url), "reading the new version's draft").json()


def upload_release(
    client: httpx.Client,
    *,
    version: str,
    previous_version: str | None = None,
    database: Path | None = None,
    releases_dir: Path | None = None,
    notes_path: Path | None = None,
    publication_date: str | None = None,
    concept_record_id: str = CONCEPT_RECORD_ID,
    publish: bool = False,
    report: Callable[[str], None] = lambda _line: None,
) -> UploadResult:
    """Upload *version* as a new version of the record, and say what was uploaded.

    *previous_version* is the release the migration starts from, and by
    default is whatever Zenodo's latest version calls itself; given by hand it
    must still be that one, because a migration from any other release would
    leave whoever holds the latest with nothing to apply.

    Everything that can be refused is refused before a draft is opened: the
    notes, the six files and which build made them, and the release Zenodo
    holds.  *report* is told each step as it happens, for a command to print.

    :raises ZenodoError: for anything refused, here or by Zenodo.
    """
    notes = read_release_notes(version, notes_path)
    latest = latest_version(client, concept_record_id)
    latest_id = str(latest["id"])
    held = str((latest.get("metadata") or {}).get("version") or "")
    if held == version:
        raise ZenodoError(
            f"Zenodo's latest version of record {concept_record_id} is already "
            f"{version} (record {latest_id}); a published version cannot be replaced"
        )
    if previous_version and previous_version != held:
        raise ZenodoError(
            f"the migration starts from {previous_version}, and Zenodo's latest "
            f"version is {held or 'unnamed'} (record {latest_id})"
        )
    previous_version = held
    if not previous_version:
        raise ZenodoError(
            f"Zenodo's latest version (record {latest_id}) has no version, so "
            "nothing says which migration belongs on the next one"
        )

    files = release_files(
        version, previous_version, database=database, releases_dir=releases_dir
    )
    stamp = check_release_files(version, files)
    report(
        f"{version} is build run {stamp.run_id} of commit {stamp.revision[:12]}; "
        f"Zenodo holds {previous_version} (record {latest_id})."
    )
    measured = {file.key: digests(file.path) for file in files}

    draft = _open_draft(client, latest_id)
    draft_id = str(draft["id"])
    links = draft.get("links") or {}
    bucket = links.get("bucket")
    if not bucket:
        raise ZenodoError(f"draft {draft_id} has no bucket to upload into")
    deposition = f"/api/deposit/depositions/{draft_id}"
    report(f"Opened draft {draft_id}.")

    # A new version starts with the last version's files, and a draft left by
    # an interrupted run has some of this one's.  Neither is wanted.
    for stale in draft.get("files") or []:
        _checked(
            client.delete(f"{deposition}/files/{stale['id']}"),
            f"deleting {stale.get('filename', stale['id'])} from the draft",
        )

    uploaded: list[UploadedFile] = []
    for file in files:
        size, sha256, md5 = measured[file.key]
        report(f"Uploading {file.name} ({size:,} bytes)...")
        answer = _checked(
            client.put(
                f"{bucket}/{file.name}",
                content=_chunks(file.path),
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(size),
                },
            ),
            f"uploading {file.name}",
        ).json()
        received = str(answer.get("checksum") or "").removeprefix("md5:")
        if received != md5:
            raise ZenodoError(
                f"{file.name} arrived with MD5 {received or 'unknown'}, and the file "
                f"on disk has {md5}; the draft {draft_id} is left as it is"
            )
        uploaded.append(UploadedFile(file.key, file.name, size, sha256, md5))

    publication_date = publication_date or notes.date
    _checked(
        client.put(
            deposition,
            json={
                "metadata": version_metadata(
                    draft.get("metadata") or {},
                    notes=notes,
                    publication_date=publication_date,
                    previous_doi=str(latest.get("doi") or ""),
                )
            },
        ),
        "writing the version's metadata",
    )

    # The DOI Zenodo reserved for the draft; on the rehearsal site it has
    # another prefix, so it is read rather than assembled where it is given.
    reserved = (draft.get("metadata") or {}).get("prereserve_doi") or {}
    url = str(links.get("html") or "")
    if publish:
        published = _checked(
            client.post(f"{deposition}/actions/publish"), "publishing the version"
        ).json()
        url = str((published.get("links") or {}).get("record_html") or url)
        report(f"Published {version}.")
    return UploadResult(
        version=version,
        previous_version=previous_version,
        record_id=draft_id,
        doi=str(reserved.get("doi") or f"10.5281/zenodo.{draft_id}"),
        url=url,
        record_url=f"{str(client.base_url).rstrip('/')}/records/{draft_id}",
        publication_date=publication_date,
        published=publish,
        files=uploaded,
    )

