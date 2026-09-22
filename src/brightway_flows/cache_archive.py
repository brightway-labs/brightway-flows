"""The reference-data caches as one archive: pack the local ones, fetch a packed one.

The first run of this pipeline is measured in hours, and almost none of that is
computation.  PubChem, ChEBI, CAS Common Chemistry, Wikidata and Wikipedia are
asked record by record under deliberate rate limits, and their answers are most
of what the data directory holds.  A second machine -- a colleague, a CI job, a
server, a fresh `BRIGHTWAY_FLOWS_DATA_DIR` for one bounded test run -- pays
that cost again from scratch for answers somebody already has.

So the caches can be handed over.  :func:`pack_cache` writes the ones this
machine holds into a single ``.tar.gz`` fit for uploading somewhere;
:func:`fetch_cache` downloads such an archive and unpacks it into the data
directory.  Point ``BRIGHTWAY_FLOWS_CACHE_URL`` at the upload and
`fetch-cache` needs no argument.

What is in the archive is the list below and nothing else -- both when packing
and when unpacking, so an archive from an untrusted place can only write files
this project would have downloaded anyway.  Deliberately absent:

- ``settings.json``, which holds the Common Chemistry API key.  An archive is
  made to be handed to other people.
- Anything licensed.  ecoinvent's flows and BAFU's ecoSpold export arrive under
  terms that are the licence holder's to set, not this tool's to route around,
  and both are per-list files their manifests name.
- Build outputs -- ``consensus-flows.sqlite3``, the layered artifacts, the
  RDKit and OPSIN logs.  Those are what a run *produces*; shipping them would
  make a fetched cache indistinguishable from a build that never happened.

A cache is an answer that was true when it was fetched, so the archive carries
a manifest saying when it was packed and how big each file was, and unpacking
logs it.  Nothing expires on its own: the caches have no expiry during a normal
run either, and `chebi --force` and the rest are still how a source is
refreshed deliberately.
"""

from __future__ import annotations

import io
import os
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

import httpx
import orjson
import structlog
from tqdm import tqdm

from brightway_flows.filesystem import (
    CHEBI_JSON_GZ_FILEPATH,
    CHEMLIN_ISOTOPE_CACHE_FILEPATH,
    COMMONCHEMISTRY_CACHE_FILEPATH,
    COMPOUND_PROFILE_CACHE_FILEPATH,
    DATA_DIR,
    GLAD_ILCD_TO_SIMAPRO_XLSX_FILEPATH,
    PUBCHEM_DATA_FILEPATH,
    PUBCHEM_ELEMENTS_CACHE_FILEPATH,
    WEB_LOOKUP_CACHE_FILEPATH,
    WIKIDATA_CACHE_FILEPATH,
)

logger = structlog.get_logger(__name__)

#: Names the URL an archive is fetched from, so `fetch-cache` takes no argument
#: on a machine that has been told where its team keeps one.
CACHE_URL_ENV_VAR = "BRIGHTWAY_FLOWS_CACHE_URL"

#: What `pack-cache` writes when it is not told where.
DEFAULT_ARCHIVE_NAME = "brightway-flows-cache.tar.gz"

#: Provenance member, written into the archive and never into the data
#: directory: when it was packed, and what was in it.
MANIFEST_MEMBER_NAME = "cache-manifest.json"

HTTP_HEADERS = {"User-Agent": "brightway-flows/1.0.0 (https://github.com/brightway-labs)"}


@dataclass(frozen=True)
class CachedFile:
    """One cache file, named as it sits in the data directory.

    *name* is a bare filename, which is also its name inside the archive: the
    data directory is flat, and keeping it flat is what lets unpacking reject
    every member that is not one of these by name alone.
    """

    name: str
    #: Where the file's contents came from, and why re-fetching it is slow.
    #: Read by `pack-cache --list`, so it is documentation a user can see.
    origin: str

    def path(self, data_dir: Path = DATA_DIR) -> Path:
        return data_dir / self.name


#: Every cache this project fills from a public web service.  Names come from
#: `filesystem` rather than being spelled again here, so a renamed constant
#: cannot leave this list pointing at a file nothing writes.
CACHED_FILES: tuple[CachedFile, ...] = (
    CachedFile(
        PUBCHEM_DATA_FILEPATH.name,
        "PubChem PUG REST, one request per distinct flow name and CAS number",
    ),
    CachedFile(
        PUBCHEM_ELEMENTS_CACHE_FILEPATH.name,
        "PubChem's periodic table and isotope annotations",
    ),
    CachedFile(
        COMMONCHEMISTRY_CACHE_FILEPATH.name,
        "CAS Common Chemistry detail and name search, rate-limited and key-gated",
    ),
    CachedFile(
        COMPOUND_PROFILE_CACHE_FILEPATH.name,
        "compound profiles assembled from the lookups above",
    ),
    CachedFile(
        WEB_LOOKUP_CACHE_FILEPATH.name,
        "Wikipedia page summaries",
    ),
    CachedFile(
        WIKIDATA_CACHE_FILEPATH.name,
        "Wikidata entity lookups",
    ),
    CachedFile(
        CHEMLIN_ISOTOPE_CACHE_FILEPATH.name,
        "ChemLIN isotope pages, parsed from HTML",
    ),
    CachedFile(
        CHEBI_JSON_GZ_FILEPATH.name,
        "the ChEBI ontology dump from the EBI FTP server (~50 MB)",
    ),
    # `EF-v3.1.zip` is not here.  It is 200 MB -- three quarters of the archive
    # -- for one unauthenticated GET from a URL this project already holds
    # (`integrations.ef31.EF31_URL`), which `download` makes on request.  The
    # archive is for what is slow to re-fetch, and a single public download is
    # not that.
    #
    # The workbook, not the 99 MB JSON parsed out of it: `ingest-glad-mapping`
    # skips the download when the workbook is already here, and parsing it is
    # offline work.  Shipping both would grow the archive tenfold to save a
    # step that needs no network.
    CachedFile(
        GLAD_ILCD_TO_SIMAPRO_XLSX_FILEPATH.name,
        "the GLAD ILCD->SimaPro correspondence workbook (~11 MB)",
    ),
)


def cached_file_names() -> frozenset[str]:
    """The archive's whole vocabulary of member names."""
    return frozenset(entry.name for entry in CACHED_FILES)


def present_cache_files(data_dir: Path = DATA_DIR) -> list[CachedFile]:
    """The entries of :data:`CACHED_FILES` this data directory actually holds.

    Absence is normal rather than an error: nobody has every cache.  A machine
    that has never merged a SimaPro-derived list has no GLAD workbook, and one
    that has never needed isotopes has no ChemLIN cache.
    """
    return [entry for entry in CACHED_FILES if entry.path(data_dir).is_file()]


def _manifest(files: list[CachedFile], data_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "packed_at": datetime.now(timezone.utc).isoformat(),
        "files": [
            {"name": entry.name, "bytes": entry.path(data_dir).stat().st_size}
            for entry in files
        ],
    }


def pack_cache(
    destination: Path | None = None, *, data_dir: Path = DATA_DIR
) -> Path:
    """Compress this machine's caches into one archive, ready to upload.

    *destination* may be a file path or a directory; a directory (or nothing at
    all, meaning the working directory) gets :data:`DEFAULT_ARCHIVE_NAME`.

    Written to a `.part` file and renamed at the end, because the failure this
    protects against is silent: an interrupted upload of a truncated archive
    looks exactly like a good one until somebody unpacks it.
    """
    destination = Path(destination) if destination is not None else Path.cwd()
    if destination.is_dir():
        destination = destination / DEFAULT_ARCHIVE_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)

    files = present_cache_files(data_dir)
    if not files:
        raise FileNotFoundError(
            f"No cache files to pack: none of {', '.join(sorted(cached_file_names()))} "
            f"is in {data_dir}."
        )
    missing = sorted(cached_file_names() - {entry.name for entry in files})
    if missing:
        logger.info("cache_files_absent", data_dir=str(data_dir), files=missing)

    manifest = orjson.dumps(_manifest(files, data_dir), option=orjson.OPT_INDENT_2)
    partial = destination.with_name(destination.name + ".part")
    try:
        # `dereference` because a cache may be a symlink -- the ChEBI dump moved
        # to a bigger disk, say.  Without it `tar.add` stores the link itself:
        # a member of size 0 that every unpack skips as not-a-file, while this
        # side logs the real size it stat()ed through the link and reports
        # success.  The publisher would have no way to notice.
        with tarfile.open(partial, "w:gz", dereference=True) as tar:
            info = tarfile.TarInfo(MANIFEST_MEMBER_NAME)
            info.size = len(manifest)
            tar.addfile(info, io.BytesIO(manifest))
            for entry in tqdm(files, desc="Packing caches", unit="file"):
                path = entry.path(data_dir)
                logger.info(
                    "packing_cache_file", file=entry.name, bytes=path.stat().st_size
                )
                tar.add(path, arcname=entry.name)
        os.replace(partial, destination)
    except BaseException:
        # A full disk or a Ctrl-C leaves a truncated archive that looks exactly
        # like a whole one.  It goes rather than sits there waiting to be
        # uploaded.
        partial.unlink(missing_ok=True)
        raise

    logger.info(
        "packed_cache_archive",
        path=str(destination),
        bytes=destination.stat().st_size,
        files=[entry.name for entry in files],
    )
    return destination


@dataclass(frozen=True)
class UnpackedCache:
    """What one unpack did, per file.

    Three lists rather than one, because "nothing was written" has two
    completely different causes -- every cache was already here, or the archive
    held none this project knows -- and only the caller can say which of them
    the user needs to hear about.
    """

    #: Caches taken from the archive and now in the data directory.
    written: list[str]
    #: Caches the data directory already had, left as they were.
    kept: list[str]
    #: Members that are not caches this project writes, ignored.
    ignored: list[str]


def _member_name(raw: str) -> str:
    """A member's name as this project spells it.

    GNU tar writes `tar czf archive.tar.gz .` members as `./chebi.json.gz`, and
    an archive that has been unpacked and repacked somewhere along the way is
    exactly the case the docs invite ("an artifact a CI job already
    downloaded").  Only a leading `./` is stripped: the returned name still has
    to appear in :data:`CACHED_FILES` verbatim, so this cannot turn
    `../../evil/chebi.json.gz` into a name that matches.
    """
    while raw.startswith("./"):
        raw = raw[2:]
    return raw


def unpack_cache(
    archive: Path, *, data_dir: Path = DATA_DIR, overwrite: bool = False
) -> UnpackedCache:
    """Unpack a cache archive into *data_dir*; report what happened to each file.

    Every member is checked against :data:`CACHED_FILES` by name and skipped if
    it is not there, which is the whole of the safety argument: those names are
    bare filenames, so nothing an archive can contain -- ``../../.ssh/config``,
    a symlink, ``settings.json`` -- resolves anywhere except onto a file this
    project downloads itself.  `tarfile`'s own extraction filter is not relied
    on for it.

    A cache already on disk is kept unless *overwrite*, so fetching an archive
    cannot throw away lookups this machine made and the upload has not seen.

    Truncation is caught for the archives this module writes: a short `.tar.gz`
    fails gzip's end-of-stream check, and the `.part` file goes with it.  An
    *uncompressed* truncated tar is not caught -- `tarfile` pads a short member
    with zeros and reports the declared size -- and neither is a file altered
    in place.  Contents are not verified at all here; only which names may be
    written is.  A published checksum is what would close that, and there is
    nowhere yet publishing one.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    known = cached_file_names()
    written: list[str] = []
    kept: list[str] = []
    ignored: list[str] = []
    manifest = ArchiveManifest()

    with tarfile.open(archive, "r:*") as tar:
        for member in tar:
            name = _member_name(member.name)
            if name == MANIFEST_MEMBER_NAME:
                manifest = _read_manifest(_manifest_bytes(tar, member))
                logger.info("cache_archive_manifest", **manifest.as_log_fields())
                continue
            if name not in known:
                logger.warning("cache_archive_member_ignored", member=member.name)
                ignored.append(member.name)
                continue
            if not member.isfile():
                logger.warning("cache_archive_member_not_a_file", member=member.name)
                ignored.append(member.name)
                continue

            destination = data_dir / name
            if destination.exists() and not overwrite:
                logger.info("cache_file_kept", file=name, path=str(destination))
                kept.append(name)
                continue

            handle = tar.extractfile(member)
            if handle is None:  # pragma: no cover -- isfile() already said it has data
                ignored.append(member.name)
                continue
            partial = destination.with_name(destination.name + ".part")
            try:
                copied = 0
                with partial.open("wb") as out:
                    while chunk := handle.read(1024 * 1024):
                        out.write(chunk)
                        copied += len(chunk)
                if copied != member.size:
                    raise ValueError(
                        f"{archive} is truncated: {name} is {copied} bytes, "
                        f"the archive declares {member.size}."
                    )
                os.replace(partial, destination)
            except BaseException:
                # A truncated `.tar.gz` raises here, mid-file, out of gzip's
                # end-of-stream check.  Without this the half-written `.part`
                # stays in the data directory for good: nothing reads it,
                # nothing cleans it, and `pack-cache --list` does not show it.
                partial.unlink(missing_ok=True)
                raise
            written.append(name)
            logger.info("unpacked_cache_file", file=name, bytes=member.size)

            # The manifest is the archive's own claim about itself, so a
            # disagreement means it was repacked or altered on the way here.
            # Said rather than refused: the file is a cache, and the manifest
            # describes the caches without being one of them.
            if name in manifest.sizes and manifest.sizes[name] != member.size:
                logger.warning(
                    "cache_file_size_disagrees_with_manifest",
                    file=name,
                    manifest_bytes=manifest.sizes[name],
                    archive_bytes=member.size,
                )

    logger.info(
        "unpacked_cache_archive",
        archive=str(archive),
        written=written,
        kept=kept,
        ignored=ignored,
    )
    return UnpackedCache(written=written, kept=kept, ignored=ignored)


#: The manifest describes ten-odd files.  Anything beyond this is not a
#: manifest, and reading it whole is the one thing this module does with an
#: untrusted member before any name check -- a 10 GB member of zeroes
#: compresses to nothing and would otherwise be read straight into memory.
MANIFEST_MAX_BYTES = 1024 * 1024


def _manifest_bytes(tar: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    """The manifest member's contents, up to :data:`MANIFEST_MAX_BYTES`."""
    if member.size > MANIFEST_MAX_BYTES:
        logger.warning(
            "cache_archive_manifest_oversized",
            bytes=member.size,
            limit=MANIFEST_MAX_BYTES,
        )
        return b""
    handle = tar.extractfile(member)
    return handle.read(MANIFEST_MAX_BYTES) if handle is not None else b""


@dataclass(frozen=True)
class ArchiveManifest:
    """What an archive says about itself: when it was packed, and file sizes."""

    packed_at: str | None = None
    sizes: dict[str, int] = field(default_factory=dict)

    def as_log_fields(self) -> dict[str, Any]:
        return {
            "packed_at": self.packed_at,
            "file_count": len(self.sizes),
            "bytes": sum(self.sizes.values()),
        }


def _read_manifest(payload: bytes) -> ArchiveManifest:
    """Parse the manifest member; every shape but this module's own is empty.

    A manifest that cannot be read is not a reason to refuse the archive -- it
    describes the caches without being one of them -- and it arrives from the
    same untrusted place they do, so `[]`, `{"files": ["x"]}` and a string
    where a number belongs must all be ordinary answers here.  They were not:
    each raised `AttributeError` out of the *first* member of the archive,
    which stopped the unpack before a single cache had been written.
    """
    try:
        manifest = orjson.loads(payload)
    except orjson.JSONDecodeError:
        return ArchiveManifest()
    if not isinstance(manifest, dict):
        return ArchiveManifest()

    packed_at = manifest.get("packed_at")
    entries = manifest.get("files")
    sizes: dict[str, int] = {}
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        name, size = entry.get("name"), entry.get("bytes")
        if isinstance(name, str) and isinstance(size, int):
            sizes[name] = size
    return ArchiveManifest(
        packed_at=packed_at if isinstance(packed_at, str) else None, sizes=sizes
    )


def cache_url(url: str | None = None) -> str | None:
    """*url* if given, else whatever ``BRIGHTWAY_FLOWS_CACHE_URL`` holds."""
    if url:
        return url
    return os.environ.get(CACHE_URL_ENV_VAR) or None


def _local_path(url: str) -> Path | None:
    """*url* as a local file, if that is what it is.

    A `file://` URL and a plain path both mean "the archive is already on this
    machine" -- a shared drive, a USB stick, an artifact a CI job just
    downloaded -- and there is nothing to fetch.

    Anything without an `http(s)` scheme is a path even when it is not there.
    It used to be a path only if it existed, so the two likeliest mistakes --
    an unmounted share, a typo -- fell through to the downloader and came back
    as `Request URL is missing an 'http://' or 'https://' protocol`, which
    names neither the file nor the fact that it is missing.
    """
    parsed = urlparse(url)
    if parsed.scheme == "file":
        return Path(url2pathname(parsed.path))
    if parsed.scheme in ("http", "https"):
        return None
    return Path(url).expanduser()


def download_cache_archive(url: str, destination: Path) -> Path:
    """Stream the archive at *url* to *destination*."""
    logger.info("downloading_cache_archive", url=url, destination=str(destination))
    with httpx.stream(
        "GET", url, follow_redirects=True, timeout=300, headers=HTTP_HEADERS
    ) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        with destination.open("wb") as out, tqdm(
            total=total or None, unit="B", unit_scale=True, desc="Cache archive"
        ) as progress:
            for chunk in response.iter_bytes(chunk_size=1024 * 64):
                out.write(chunk)
                progress.update(len(chunk))
    return destination


def fetch_cache(
    url: str | None = None, *, data_dir: Path = DATA_DIR, overwrite: bool = False
) -> UnpackedCache:
    """Fetch a cache archive and unpack it into *data_dir*; report what it did.

    *url* defaults to ``BRIGHTWAY_FLOWS_CACHE_URL``.  A local path or a
    `file://` URL is unpacked where it lies; anything else is downloaded to a
    temporary file first and deleted afterwards, because the archive is a
    transport and keeping a second copy of the caches beside the caches is
    gigabytes for nothing.

    That temporary file goes inside the data directory rather than wherever
    `/tmp` points.  An archive of these caches runs to gigabytes and `/tmp` is
    a RAM-backed tmpfs on most Linux installs; the data directory is the one
    place this project has already been told has room.
    """
    resolved = cache_url(url)
    if not resolved:
        raise ValueError(
            "No cache archive URL. Pass one, or set "
            f"{CACHE_URL_ENV_VAR} to where the archive is published."
        )

    local = _local_path(resolved)
    if local is not None:
        if not local.is_file():
            raise FileNotFoundError(
                f"Cache archive not found at {local}. A value with no "
                "http:// or https:// scheme is read as a local path."
            )
        return unpack_cache(local, data_dir=data_dir, overwrite=overwrite)

    data_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="cache-archive-", dir=data_dir) as tmp:
        archive = download_cache_archive(resolved, Path(tmp) / DEFAULT_ARCHIVE_NAME)
        return unpack_cache(archive, data_dir=data_dir, overwrite=overwrite)
