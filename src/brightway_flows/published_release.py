"""Which release is published, as one JSON file, and its files fetched from Zenodo.

The facts that move with every release -- the version, the release it follows,
the date, the DOI, and the name, size and SHA-256 of each of its six files --
were typed into `webapps/app/publication.py` by hand after each upload, and
then into four test files.  They are one file now, ``release.json``:
`release-upload` writes it from what it uploaded, and the review application
reads it to say which release it serves and to download that release.

    {
      "version": "1.1.0",
      "previous_version": "1.0.0",
      "release_date": "2026-10-21",
      "doi": "10.5281/zenodo.23554066",
      "record_url": "https://zenodo.org/records/23554066",
      "files": {
        "database": {"name": "consensus-flows.sqlite3", "size": 2627653632,
                     "sha256": "e042..."},
        ...
      }
    }

**Where it is.**  The file ``BRIGHTWAY_FLOWS_RELEASE_FILE`` names, else
``release.json`` in the data directory.  A file the variable names has to be
there; the default one need not be, and an installation without it has no
release to speak of -- its pages show a placeholder for each of these facts
and it serves whatever build is in its data directory.

**What is fetched.**  The database, into ``published/<version>/`` of the data
directory, and nothing else.  Every page the application renders reads that
one file; the other five are files a reader downloads, and a reader gets them
from Zenodo, where the Download page already sends them.  What the pages say
about those five -- that they exist, and how big they are -- is in the release
file.  The database is written under a ``.part`` name, resumed where a run was
cut off, checked against its SHA-256 and only then given its own name, so a
file with its own name is one that arrived whole.

Standard library only for the requests.  The review application's install
does not bring `httpx`, and this is one ``GET`` per file.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import orjson
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from brightway_flows.data_dir import data_dir as resolve_data_dir

#: The variable naming the release file.
RELEASE_FILE_ENV = "BRIGHTWAY_FLOWS_RELEASE_FILE"
#: The file's name where the variable is unset, in the data directory.
RELEASE_FILENAME = "release.json"

#: Every file a release publishes, by the key the Download page knows it
#: under, in the order the page shows them.
ARTIFACT_KEYS: tuple[str, ...] = (
    "snapshot", "flows", "factors", "differences", "migration", "database",
)

#: The files the application reads, and so the ones fetched.
FETCHED_KEYS: tuple[str, ...] = ("database",)

_CHUNK = 1024 * 1024
_USER_AGENT = "brightway-flows"
#: How many times one file is asked for, and how long to wait before asking
#: again.  Zenodo answers the odd request with a 500 and the next one with the
#: file -- the first real download made with this code met one -- and a 2.6 GB
#: transfer can be cut off part-way; each further try carries on from what
#: has already arrived.
_ATTEMPTS = 5
_WAIT_SECONDS = 5.0


class ReleaseFileError(ValueError):
    """The release file is missing where it was named, or is not one."""


class ReleaseDownloadError(RuntimeError):
    """A file of the release could not be fetched, or is not the file published."""


@dataclass(frozen=True)
class ReleaseFile:
    """One published file: what Zenodo calls it, and which bytes it is."""

    key: str
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class PublishedRelease:
    """One release as Zenodo holds it."""

    version: str
    previous_version: str
    #: The day the Zenodo version was published, ``2026-10-21``.
    release_date: str
    #: The version's own DOI, not the record's.
    doi: str
    #: The version's page on Zenodo; its files are downloaded from under it.
    record_url: str
    files: tuple[ReleaseFile, ...]

    def file(self, key: str) -> ReleaseFile | None:
        return next((file for file in self.files if file.key == key), None)

    @property
    def checksums(self) -> dict[str, str]:
        """SHA-256 by artifact key, as the Download page looks one up."""
        return {file.key: file.sha256 for file in self.files}

    def download_url(self, file: ReleaseFile) -> str:
        return f"{self.record_url.rstrip('/')}/files/{file.name}?download=1"

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "previous_version": self.previous_version,
            "release_date": self.release_date,
            "doi": self.doi,
            "record_url": self.record_url,
            "files": {
                file.key: {"name": file.name, "size": file.size, "sha256": file.sha256}
                for file in self.files
            },
        }


# -- the file ------------------------------------------------------------------


#: A version or a file name, each of which becomes one component of a path
#: under the data directory: letters, digits and `._+-`, starting with a
#: letter or a digit, so neither `.` nor `..` nor anything with a slash.
_PATH_COMPONENT = r"^[0-9A-Za-z][0-9A-Za-z._+-]*$"


class _FilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=_PATH_COMPONENT)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class _ReleasePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(pattern=_PATH_COMPONENT)
    previous_version: str = Field(pattern=_PATH_COMPONENT)
    release_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    doi: str = Field(pattern=r"^10\.\d+/\S+$")
    record_url: str = Field(pattern=r"^https://\S+$")
    files: dict[str, _FilePayload]


def release_file_path(data_dir: Path | None = None) -> Path:
    """Where the release file is looked for: the variable's, else *data_dir*'s."""
    if named := os.environ.get(RELEASE_FILE_ENV):
        return Path(named)
    return (data_dir or resolve_data_dir()) / RELEASE_FILENAME


def read_published_release(path: Path) -> PublishedRelease:
    """The release *path* describes.

    :raises ReleaseFileError: where the file is not there, is not JSON, or does
        not describe a release with all six files.  Never read in part: a
        release with five files would be served as one with a file missing.
    """
    try:
        payload = _ReleasePayload.model_validate(orjson.loads(path.read_bytes()))
    except OSError as error:
        raise ReleaseFileError(f"{path}: {error}") from error
    except (orjson.JSONDecodeError, ValidationError) as error:
        raise ReleaseFileError(f"{path} is not a release file: {error}") from error
    if set(payload.files) != set(ARTIFACT_KEYS):
        raise ReleaseFileError(
            f"{path} names the files {sorted(payload.files)}, and a release has "
            f"exactly {sorted(ARTIFACT_KEYS)}"
        )
    return PublishedRelease(
        version=payload.version,
        previous_version=payload.previous_version,
        release_date=payload.release_date,
        doi=payload.doi,
        record_url=payload.record_url,
        files=tuple(
            ReleaseFile(
                key=key,
                name=payload.files[key].name,
                size=payload.files[key].size,
                sha256=payload.files[key].sha256,
            )
            for key in ARTIFACT_KEYS
        ),
    )


def load_published_release(
    path: Path | None = None, *, data_dir: Path | None = None
) -> PublishedRelease | None:
    """The published release, or ``None`` where this installation names none.

    *path* or the variable names a file that must be there.  Otherwise the
    data directory's ``release.json`` is read if it exists, and its absence is
    an answer rather than an error.
    """
    if path is not None or os.environ.get(RELEASE_FILE_ENV):
        return read_published_release(path or release_file_path())
    default = release_file_path(data_dir)
    return read_published_release(default) if default.is_file() else None


def write_published_release(release: PublishedRelease, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        orjson.dumps(release.to_dict(), option=orjson.OPT_INDENT_2) + b"\n"
    )
    return path


# -- the files -----------------------------------------------------------------


def release_directory(release: PublishedRelease, data_dir: Path | None = None) -> Path:
    """Where *release*'s files are kept: ``published/<version>/`` of the data
    directory.  One directory per release, so moving to the next one never
    serves half of each."""
    return (data_dir or resolve_data_dir()) / "published" / release.version


def fetched_files(release: PublishedRelease) -> list[ReleaseFile]:
    """The files of *release* the application reads: `FETCHED_KEYS`."""
    return [file for file in release.files if file.key in FETCHED_KEYS]


def local_path(file: ReleaseFile, directory: Path) -> Path:
    """Where a fetched *file* is kept: under the name Zenodo gives it."""
    return directory / file.name


def missing_files(release: PublishedRelease, directory: Path) -> list[ReleaseFile]:
    """The fetched files not yet in *directory*, without reading any of them.

    A file under its own name was checked against its SHA-256 before it was
    given that name, so here its size is enough; hashing 2.6 GB on every
    start of the application would be the slowest thing it does.
    """
    missing = []
    for file in fetched_files(release):
        path = local_path(file, directory)
        if not path.is_file() or path.stat().st_size != file.size:
            missing.append(file)
    return missing


@contextlib.contextmanager
def _locked(directory: Path) -> Iterator[None]:
    """One fetch into *directory* at a time, across processes.

    Two workers of one server start together and both find the release
    missing.  The second waits here, and then finds it present.
    """
    directory.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl
    except ImportError:  # pragma: no cover -- Windows: one process, or take turns
        yield
        return
    with (directory / ".fetch.lock").open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


#: Answers in the 400s that asking again can change: the server timed the
#: request out, or wants fewer requests.  Every other one is a refusal.
_RETRIED_CLIENT_ERRORS = frozenset({408, 429})


def _size(part: Path) -> int:
    return part.stat().st_size if part.exists() else 0


def _download(url: str, part: Path, size: int) -> None:
    """Fetch *url* into *part*, asking again where the server fails or the
    transfer is cut off.

    :raises ReleaseDownloadError: after `_ATTEMPTS` tries.  A refusal that
        asking again will not change -- the file is not there, or not ours to
        read -- is raised at once.
    """
    for attempt in range(1, _ATTEMPTS + 1):
        before = _size(part)
        try:
            _download_once(url, part, size)
        except ReleaseDownloadError as error:
            cause = error.__cause__
            code = cause.code if isinstance(cause, urllib.error.HTTPError) else None
            if code == 416 and before:
                # What is here is not the start of what the server has, so
                # there is nothing to carry on from: the next try starts over.
                part.unlink(missing_ok=True)
                if attempt == _ATTEMPTS:
                    raise
                continue
            refused = (
                code is not None
                and 400 <= code < 500
                and code not in _RETRIED_CLIENT_ERRORS
            )
            if refused or attempt == _ATTEMPTS:
                raise
            time.sleep(_WAIT_SECONDS * attempt)
            continue
        arrived = _size(part)
        if arrived >= size or arrived == before:
            # All of it -- or the server has no more to give, and the file is
            # not the one recorded.  The caller's checksum says which.
            return
    raise ReleaseDownloadError(
        f"{url}: {_size(part):,} of {size:,} bytes arrived in {_ATTEMPTS} tries"
    )


def _download_once(url: str, part: Path, size: int) -> None:
    """One request: fetch *url* into *part*, carrying on from what it holds."""
    have = part.stat().st_size if part.exists() else 0
    if have > size:
        part.unlink()
        have = 0
    if have == size:
        return
    headers = {"User-Agent": _USER_AGENT}
    if have:
        headers["Range"] = f"bytes={have}-"
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310
            # 206 is the rest of the file; 200 is all of it, from a server
            # that would not resume, so what is here is written over.
            resumed = have and response.status == 206
            with part.open("ab" if resumed else "wb") as handle:
                while chunk := response.read(_CHUNK):
                    handle.write(chunk)
    except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
        # `HTTPException` as well: a response cut off part-way is an
        # `IncompleteRead`, which is neither of the other two.
        raise ReleaseDownloadError(f"{url}: {error or repr(error)}") from error


def fetch_release(
    release: PublishedRelease,
    directory: Path | None = None,
    *,
    report: Callable[[str], None] = lambda _line: None,
) -> Path:
    """Make *directory* hold *release*, downloading what it lacks.

    Does nothing, and asks nothing of the network, where the database is
    already there.  *report* is told each file as its download starts.

    :raises ReleaseDownloadError: where a file cannot be fetched, or arrives
        as other bytes than the release file records.  What had arrived stays,
        under its ``.part`` name, for the next run to carry on from -- except
        a file of the wrong bytes, which is removed.
    """
    directory = directory or release_directory(release)
    if not missing_files(release, directory):
        return directory
    try:
        _fetch_missing(release, directory, report)
    except OSError as error:
        # A directory that cannot be written, a full disk: the release is not
        # here and cannot be put here, which is what the caller is told for
        # every other reason too.
        raise ReleaseDownloadError(
            f"release {release.version} cannot be written to {directory}: {error}"
        ) from error
    return directory


def _fetch_missing(
    release: PublishedRelease, directory: Path, report: Callable[[str], None]
) -> None:
    with _locked(directory):
        for file in missing_files(release, directory):
            destination = local_path(file, directory)
            destination.parent.mkdir(parents=True, exist_ok=True)
            part = destination.with_name(destination.name + ".part")
            report(
                f"Downloading {file.name} of {release.version} "
                f"({file.size:,} bytes) from {release.record_url}"
            )
            _download(release.download_url(file), part, file.size)
            arrived = _sha256(part)
            if arrived != file.sha256:
                part.unlink()
                raise ReleaseDownloadError(
                    f"{file.name} of {release.version} arrived with SHA-256 "
                    f"{arrived}, and the release file records {file.sha256}"
                )
            part.replace(destination)
