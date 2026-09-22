"""What a run leaves behind, and where a reader can get it.

The build writes four files a consumer wants and the review application named
none of them.  A curator reading the run page could see that 94,270 flows were
processed and had no way to take the list away with them: the answer was a path
on somebody else's machine, printed on the page and useless to anybody not
logged into that machine.

Flask-free, like `queries/`, so what a run produced can be listed in a test
without an application context.  Nothing here reads a file's contents -- only
whether it is there and how big it is -- because the point of the page is to say
what exists, and opening a 2.3 GB database to answer that would be absurd.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH, DATA_DIR

#: What each downloadable artifact is, keyed by the slug its URL uses.
#:
#: The slug is the identity and is not the file name: the file name is where the
#: build happens to put it, and a page that addressed a download by file name
#: would break the day one is renamed.  The description is what a reader needs to
#: choose between them, in the words the rest of the application uses.
#:
#: Only what the build publishes.  The extracted source lists, the caches and
#: the vendor archives are inputs -- some of them licensed -- and this is the
#: run's output.
ARTIFACTS: tuple[tuple[str, str, str, str], ...] = (
    (
        "database",
        "SQLite database",
        "consensus-flows.sqlite3",
        "Everything this application reads: the flows, the flow objects, the "
        "change log, the merge outcomes and the factors, in one file.",
    ),
    (
        "flows",
        "Harmonised flows",
        "harmonised-flows-simple.json.gz",
        "The published list itself: one record per elementary flow, with its "
        "substance, its context, its identifiers and the source rows it "
        "carries.",
    ),
    (
        "factors",
        "Characterisation factors",
        "lcia-factors.json.gz",
        "What each implementation of a method says about each flow: the "
        "categories, the factors and which implementation states them.",
    ),
    (
        "differences",
        "Factor differences",
        "lcia-differences.json",
        "Where two implementations of one method disagree, and where one "
        "skips a context of a substance the other characterises.",
    ),
)


#: The artifacts a release offers on `/download/`, in the Download board's
#: order: the three exports a reader parses, and then the database, which is
#: the whole build in one file.  Decision 8 came back that the database may be
#: published (#200), so it is a release artifact like the other three and
#: nothing gates it.
#:
#: Last rather than first, although it holds everything the other three hold:
#: the first row is the page's "Start here", and a multi-gigabyte download is
#: not where somebody meeting the list should start.
RELEASE_KEYS: tuple[str, ...] = ("flows", "factors", "differences", "database")


def _path(key: str, filename: str, *, data_dir: Path, database_path: Path) -> Path:
    """Where to look for one artifact.

    Both are parameters rather than the `filesystem` constants they default to.
    `filesystem` resolves the data directory once, at import, from the
    environment -- so a constant here would make this module answer about
    whatever directory the *process* was started with, which is the wrong
    directory for a test and for a deployment reading a database from somewhere
    else.  The application already knows both and passes them in.

    The database is named separately because it is the one the application is
    reading: offering a download of a different build from the one every other
    page describes would be worse than offering none.
    """
    return Path(database_path) if key == "database" else Path(data_dir) / filename


@dataclass
class Artifact:
    """One file a run produced, as the page offers it.

    `path` is here for the route, which has to open the file; nothing renders
    it.  A server's directory layout is not something a reader of a published
    list has any use for, and printing it was most of what the old run page
    said about its inputs.
    """

    key: str
    title: str
    filename: str
    description: str
    path: Path
    exists: bool = False
    size: int = 0
    #: When the build wrote it, ISO-8601, or empty where it is not there.  Read
    #: so that a page can say a download is older than the run above it, which
    #: is what a half-finished build looks like from outside.
    modified: str = ""

    @property
    def readable_size(self) -> str:
        """`44.5 MB`, at the precision a reader is deciding on.

        Powers of 1000 and not 1024: the number is here so somebody can tell a
        2 GB download from a 16 MB one before starting it, and every browser and
        operating system they will compare it against says MB for a million.
        """
        size = float(self.size)
        for unit in ("bytes", "kB", "MB", "GB"):
            if size < 1000 or unit == "GB":
                return f"{size:,.0f} {unit}" if unit == "bytes" else f"{size:,.1f} {unit}"
            size /= 1000
        return f"{size:,.1f} GB"


def artifact(
    key: str,
    database_path: Path | None = None,
    data_dir: Path | None = None,
) -> Artifact | None:
    """The artifact *key* names, or `None` if this application has no such key."""
    for slug, title, filename, description in ARTIFACTS:
        if slug != key:
            continue
        path = _path(
            slug,
            filename,
            data_dir=data_dir or DATA_DIR,
            database_path=database_path or CONSENSUS_DB_FILEPATH,
        )
        found = Artifact(
            key=slug,
            title=title,
            filename=filename,
            description=description,
            path=path,
        )
        if path.is_file():
            stat = path.stat()
            found.exists = True
            found.size = stat.st_size
            found.modified = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
        return found
    return None


def available(
    database_path: Path | None = None, data_dir: Path | None = None
) -> list[Artifact]:
    """Every artifact, whether or not the build wrote it.

    All four, including the missing ones.  A build that has not been
    characterised has no factor file, and "this run did not produce it" is a
    thing the page should say -- an absence shown as an absence is how a reader
    finds out that `characterise` has not been run, and a list that quietly
    shrank to two entries would tell them nothing.
    """
    found = [artifact(key, database_path, data_dir) for key, *_ in ARTIFACTS]
    return [entry for entry in found if entry is not None]
