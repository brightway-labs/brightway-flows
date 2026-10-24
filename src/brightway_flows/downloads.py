"""A file downloaded from a pinned copy, and checked to be that copy.

Five of the files a build reads used to come from somewhere that could change
or vanish under it: AGRIBALYSE's export and BAFU's archive were placed by hand,
the GLAD workbook came from the tip of a GitHub branch, ChEBI from whatever
release the EBI served that day, and the caches from nowhere at all (#429 to
#433).  Each is now downloaded from an address that names one version, and the
bytes that arrive are checked against the digest this project recorded for it.

The digest is checked on a download only.  A file already in the data
directory is read as it is, the way it always was: a hand-placed copy of a
newer release is a new artifact to read, not a failure, and the adapters that
read one say which bytes they read where it matters.
"""

from __future__ import annotations

import gzip
import hashlib
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx
import structlog
from tqdm import tqdm

logger = structlog.get_logger(__name__)

#: Where this project keeps the copies it reads.  Files are never replaced
#: there: a new version is uploaded under a new name, so an address always
#: means the same bytes and an old build can still say which file it read.
FILES_BRIGHTWAY_DEV = "https://files.brightway.dev/"


class DownloadDigestError(RuntimeError):
    """A pinned address served bytes other than the ones it was pinned to."""


@dataclass(frozen=True)
class PinnedFile:
    """One file, where to get it, and which bytes it must be.

    *urls* are tried in order; the next one is asked only when one does not
    answer.  A URL that answers with the wrong bytes stops the download rather
    than falling through, because that is a defect in the pin to be looked at,
    not an outage to route around.

    *sha256* is the digest of the file as it is written to the data directory.
    Where *gzipped*, the URLs serve it compressed and it is unpacked on the way
    in, so the digest is the same one a hand-placed copy of the file has.
    """

    urls: tuple[str, ...]
    sha256: str
    gzipped: bool = False

    def download(self, destination: Path, *, force: bool = False) -> Path:
        """The file at *destination*, downloaded unless it is already there."""
        return download_pinned(
            destination, self.urls, self.sha256, gzipped=self.gzipped, force=force
        )


def sha256(path: Path) -> str:
    """The file's SHA-256, read in chunks so a 500 MB export is not held whole."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stream(url: str, destination: Path) -> None:
    logger.info("downloading", url=url, destination=str(destination))
    with httpx.stream("GET", url, follow_redirects=True, timeout=300) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        with destination.open("wb") as handle, tqdm(
            total=total or None, unit="B", unit_scale=True, desc=destination.name
        ) as progress:
            for chunk in response.iter_bytes(chunk_size=1024 * 64):
                handle.write(chunk)
                progress.update(len(chunk))


def _gunzip(source: Path, destination: Path) -> None:
    with gzip.open(source, "rb") as compressed, destination.open("wb") as out:
        shutil.copyfileobj(compressed, out, length=1024 * 1024)


def download_pinned(
    destination: Path,
    urls: Sequence[str],
    expected_sha256: str,
    *,
    gzipped: bool = False,
    force: bool = False,
) -> Path:
    """Download the file *expected_sha256* names to *destination*.

    Skipped when *destination* exists, unless *force*.  The download is written
    beside it as ``.part`` and renamed into place only once its digest matches,
    so a download that stops part-way, or serves the wrong bytes, leaves
    nothing a later run would take for the file.

    :raises httpx.HTTPError: if no URL answers.
    :raises DownloadDigestError: if one answers with other bytes.
    """
    if destination.exists() and not force:
        logger.info("already_downloaded", path=str(destination))
        return destination
    if not urls:
        raise ValueError(f"No URL to download {destination.name} from.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    compressed = destination.with_name(destination.name + ".gz.part")
    try:
        for position, url in enumerate(urls):
            try:
                _stream(url, compressed if gzipped else partial)
            except httpx.HTTPError as error:
                if position == len(urls) - 1:
                    raise
                logger.warning(
                    "download_unavailable_trying_next",
                    url=url,
                    error=str(error),
                    next_url=urls[position + 1],
                )
                continue
            if gzipped:
                _gunzip(compressed, partial)
                compressed.unlink()
            received = sha256(partial)
            if received != expected_sha256:
                raise DownloadDigestError(
                    f"{url} served {destination.name} with digest {received}, "
                    f"not the {expected_sha256} it is pinned to."
                )
            partial.replace(destination)
            logger.info("downloaded", url=url, path=str(destination), sha256=received)
            return destination
    finally:
        partial.unlink(missing_ok=True)
        compressed.unlink(missing_ok=True)
    raise AssertionError("unreachable: the last URL either returns or raises")
