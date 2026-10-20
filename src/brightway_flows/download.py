"""One way to download a file, for every adapter that downloads one.

Four modules streamed a URL to disk with the same dozen lines -- the EF 3.1
archive, Stepwise's CSV, the cache archive and GreenDelta's openLCA package --
and two of them also carried a SHA-256 of a file, written twice.  A fix to
the download path had to be made in each: a partial file left behind by an
HTTP error, a resume, a timeout.  This is the one copy.

The download goes to ``<name>.part`` beside its destination and is renamed
only once it is complete and, where a digest is given, checked.  A file that
is there under its own name is therefore whole, and a partial one is never
mistaken for it by a caller that looks for the name.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

import httpx
import structlog
from tqdm import tqdm

logger = structlog.get_logger(__name__)


class DigestMismatchError(RuntimeError):
    """What arrived is not the file the caller named by its SHA-256."""


def sha256_of(path: Path) -> str:
    """The file's SHA-256, so a run can say which bytes it read."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(
    url: str,
    destination: Path,
    *,
    sha256: str | None = None,
    timeout: float = 300,
    headers: Mapping[str, str] | None = None,
    description: str | None = None,
) -> Path:
    """Stream *url* to *destination*, through a ``.part`` file beside it.

    *sha256*, when given, is what the complete file must hash to; *headers*
    go on the request; *description* labels the progress bar and defaults to
    the destination's name.  Returns *destination*.

    :raises DigestMismatchError: if the file that arrived hashes to something
        else.  The partial file is removed, so the next attempt starts clean
        and nothing parses a file that is not the one named.
    :raises httpx.HTTPError: as the request raises it.  The partial file is
        removed on the way out.
    """
    partial = destination.with_name(destination.name + ".part")
    logger.info("downloading", url=url, path=str(destination))
    try:
        with httpx.stream(
            "GET", url, follow_redirects=True, timeout=timeout, headers=headers
        ) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            with partial.open("wb") as handle, tqdm(
                total=total or None,
                unit="B",
                unit_scale=True,
                desc=description or destination.name,
            ) as progress:
                for chunk in response.iter_bytes(chunk_size=1024 * 64):
                    handle.write(chunk)
                    progress.update(len(chunk))
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    if sha256 is not None:
        received = sha256_of(partial)
        if received != sha256:
            partial.unlink(missing_ok=True)
            raise DigestMismatchError(
                f"{url} served a file with digest {received}, not the {sha256} "
                f"expected."
            )
    partial.replace(destination)
    return destination
