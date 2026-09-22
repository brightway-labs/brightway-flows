"""Releases of the list, and the migrations between them.

A consumer who loaded one release into their own database -- a Brightway
biosphere, a SimaPro library, a method table -- moves to the next one by
applying three randonneur files: one for the substances, one for the flows,
one for the characterisation factors.  This package writes them.

`snapshot` projects a build onto what a migration compares and stores it
per release; `version` names a release from its git tag; `alignment` works
out which identifier became which; `diff` turns that into one record per
change; `randonneur_files` writes the records in randonneur's format; and
`rulings` reads the curated answers for what the alignment could not decide.
"""

from brightway_flows.releases.diff import Delta, DeltaKind, ReleaseDiff, diff_releases
from brightway_flows.releases.randonneur_files import (
    MigrationFiles,
    write_migration_files,
)
from brightway_flows.releases.rulings import (
    EntityKind,
    MigrationRuling,
    load_release_migration_rulings,
)
from brightway_flows.releases.snapshot import (
    RELEASE_SNAPSHOT_SCHEMA_VERSION,
    ReleaseSnapshot,
    ReleaseStamp,
    build_snapshot,
    load_snapshot,
    snapshot_path,
    write_snapshot,
)
from brightway_flows.releases.version import (
    ReleaseVersion,
    ReleaseVersionError,
    named_version,
    release_version,
)

__all__ = [
    "Delta",
    "DeltaKind",
    "EntityKind",
    "MigrationFiles",
    "MigrationRuling",
    "RELEASE_SNAPSHOT_SCHEMA_VERSION",
    "ReleaseDiff",
    "ReleaseSnapshot",
    "ReleaseStamp",
    "ReleaseVersion",
    "ReleaseVersionError",
    "build_snapshot",
    "diff_releases",
    "load_release_migration_rulings",
    "load_snapshot",
    "named_version",
    "release_version",
    "snapshot_path",
    "write_migration_files",
    "write_snapshot",
]
