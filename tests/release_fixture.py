"""Release 1.1.0 as its release file records it, for the pages that show a release.

The values are the Zenodo record's own (<https://zenodo.org/records/23554066>):
the sizes as Zenodo lists them, and the SHA-256 of each file as uploaded.  They
are a fixture and nothing reads them outside the tests -- an installation's
release is whatever its own ``release.json`` says.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from unittest import mock

from brightway_flows.published_release import (
    RELEASE_FILENAME,
    PublishedRelease,
    ReleaseFile,
    write_published_release,
)
from brightway_flows.webapps.app.publication import Publication

RELEASE_1_1_0 = PublishedRelease(
    version="1.1.0",
    previous_version="1.0.0",
    release_date="2026-10-21",
    doi="10.5281/zenodo.23554066",
    record_url="https://zenodo.org/records/23554066",
    files=(
        ReleaseFile(
            "snapshot", "release-snapshot.json.gz", 59538616,
            "7072cc8e67dc0e85b0d8d75bfcf307e929b4c1f20b24f0c786a8f2336b5e6bd6",
        ),
        ReleaseFile(
            "flows", "harmonised-flows-simple.json.gz", 45908919,
            "47850016a251ca00d4f806f305293eaa735e3cb59219ea2a27ef7ceb12028271",
        ),
        ReleaseFile(
            "factors", "lcia-factors.json.gz", 16388084,
            "a5972f7b09de42cb402b378a623b679206b47b05437329c7984e61f70d2e518e",
        ),
        ReleaseFile(
            "differences", "lcia-differences.json", 29535680,
            "aff0cdbf6be6af44ed361af169e408dc2548b31b637514d2491b1efd3f0b6b6c",
        ),
        ReleaseFile(
            "migration", "1.0.0__1.1.0.zip", 6413788,
            "98b6ab821ea4e3922e3c5b9d6f981a8daa7d0bd296b07e7cf54d06165c147f28",
        ),
        ReleaseFile(
            "database", "consensus-flows.sqlite3", 2627653632,
            "e04211d17a93d75c004ac9f582efddb567ed282ea2a40c80b686c8dc920b1433",
        ),
    ),
)


def write_release_file(directory: Path, release: PublishedRelease = RELEASE_1_1_0) -> Path:
    """Put *release*'s file where an application reading *directory* finds it."""
    return write_published_release(release, Path(directory) / RELEASE_FILENAME)


@contextlib.contextmanager
def only_publication(publication: Publication):
    """Every page reads exactly *publication*: no release is laid over it.

    For a test about the chips and the facts themselves, on an application
    that was started with a release.
    """
    with (
        mock.patch("brightway_flows.webapps.app.PUBLICATION", publication),
        mock.patch.object(Publication, "with_release", lambda self, _release: self),
    ):
        yield
