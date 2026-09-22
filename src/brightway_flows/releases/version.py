"""What a build is called when it is a release, and when it is not.

A migration file names its two sides, and randonneur wants each name in the
form ``<list>-<version>``.  A build's own stamp -- a run id and a commit -- is
exact but says nothing a consumer recognises, so a release is named by the
git tag on the commit that built it.  A build of a commit nobody tagged is a
*development* build: it is named by ``git describe``, which says how far past
the last tag it is, and it carries the ``-dev`` modifier so that a migration
written from one is never mistaken for a migration between two releases.

A build from a modified tree is refused outright.  Its revision cannot be
checked out again, so nothing could reproduce either side of a migration
written from it -- the same rule `tools/compare_merge_outcomes.py` applies to
a comparison.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from brightway_flows.filesystem import REPO_ROOT

#: The list's name in a randonneur ``source_id`` / ``target_id``.
LIST_NAME = "brightway-flows"


class ReleaseVersionError(ValueError):
    """The build cannot be given a release name."""


@dataclass(frozen=True)
class ReleaseVersion:
    """A release's name, and whether it is one."""

    version: str
    #: True for a build of a commit no tag names.  Its version is what
    #: ``git describe`` says, which is reproducible but is not a release.
    development: bool = False

    @property
    def randonneur_id(self) -> str:
        """``<list>-<version>``, with ``-dev`` appended for a development build."""
        suffix = "-dev" if self.development else ""
        return f"{LIST_NAME}-{self.version}{suffix}"


def _git(*args: str) -> str | None:
    try:
        done = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def release_version(revision: str, *, dirty: bool = False) -> ReleaseVersion:
    """The release name of the build stamped with *revision*.

    The tag on the commit, if there is exactly one; otherwise what ``git
    describe --tags --long --always`` says -- ``<tag>-<n>-g<sha>`` past the
    last tag, or the bare short sha where the repository has no tags at all --
    marked as a development build.

    :raises ReleaseVersionError: for a build from a modified tree, for one
        that carries no revision, or where git cannot describe the revision
        (a build of a commit this checkout does not have).
    """
    if dirty:
        raise ReleaseVersionError(
            f"the build of {revision[:12]} was made from a modified tree, so "
            "nothing can reproduce it; a release is built from a commit"
        )
    if not revision:
        raise ReleaseVersionError(
            "the build carries no git revision, so nothing says which commit "
            "built it; name it with --version if it is a release"
        )
    exact = _git("describe", "--tags", "--exact-match", revision)
    if exact:
        return ReleaseVersion(exact, development=False)
    described = _git("describe", "--tags", "--long", "--always", revision)
    if not described:
        raise ReleaseVersionError(
            f"git cannot describe {revision[:12]}; is that commit in this checkout?"
        )
    return ReleaseVersion(described, development=True)


def named_version(name: str) -> ReleaseVersion:
    """A release name given by hand, for a fixture or a build made off git."""
    cleaned = name.strip()
    if not cleaned:
        raise ReleaseVersionError("a release name cannot be empty")
    return ReleaseVersion(cleaned, development=False)
