"""Where every file this project reads or writes lives.

Two directories, and they are not the same kind of thing.

``DATA_DIR`` is *derived* data: vendor archives, web-service caches, the
extracted source lists, the SQLite database a build writes. It is outside the
repository, one per worktree (#82), and everything in it can be produced again.

``PACKAGE_DATA_DIR`` is *curated* data: the roughly twenty files of a curator's
rulings, the context vocabulary, the unit table. It ships inside the package
because it is decisions rather than output, and it is reviewed in a diff.

Twenty-three modules used to spell the second one themselves, across 26
statements and four variants -- ``.parent / "data"``, ``.parent.parent /
"data"``, ``.parents[1] / "data"``, and one without ``.resolve()`` at all. The
depth of the spelling depended on how deep the module was, so moving a module
between packages silently moved where it looked for its data. It is one
constant now (#92).
"""

import subprocess
from pathlib import Path

from brightway_flows.data_dir import data_dir

#: Curated, hand-edited inputs that live in the repository rather than the data
#: directory, because they are decisions rather than derived data.
#:
#: Defined here rather than in ``sources``, which is where it was: reading a
#: bundled data file should not mean importing the source-list registry, and
#: that is a fair part of why 23 modules spelled the path themselves instead.
#: This module imports nothing from the project but `data_dir`, which imports
#: nothing at all, so anything may import it.
PACKAGE_DATA_DIR = Path(__file__).resolve().parent / "data"

#: One manifest per list. A file here is the whole of "this list exists".
SOURCE_MANIFEST_DIR = PACKAGE_DATA_DIR / "sources"
#: Corrections for the habits of a naming lineage rather than of one list:
#: applied to every list whose `simapro_origin` is true, after that list's own
#: fixes, and to a lookup query sent with the flag.  See the file's description.
SIMAPRO_LINEAGE_FIXES_FILEPATH = PACKAGE_DATA_DIR / "simapro-lineage-manual-fixes.json"

#: `BRIGHTWAY_FLOWS_DATA_DIR`, else the machine-wide directory; either under the
#: project's old name where only that one exists (`data_dir`).
DATA_DIR = data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)

APP_SETTINGS_FILEPATH = DATA_DIR / "settings.json"
CHEBI_JSON_GZ_FILEPATH = DATA_DIR / "chebi.json.gz"
CHEMLIN_ISOTOPE_CACHE_FILEPATH = DATA_DIR / "chemlin-isotopes.json"
COMMONCHEMISTRY_CACHE_FILEPATH = DATA_DIR / "commonchemistry-cache.json"
COMPOUND_PROFILE_CACHE_FILEPATH = DATA_DIR / "compound-profile-cache.json"
CONSENSUS_DB_FILEPATH = DATA_DIR / "consensus-flows.sqlite3"
EF31_ZIP_FILEPATH = DATA_DIR / "EF-v3.1.zip"
GLAD_ILCD_TO_SIMAPRO_XLSX_FILEPATH = (
    DATA_DIR / "ILCD_EF3.1_TO_SimaProCSV_Professional10.2_SubstanceMappingsGLAD.xlsx"
)
#: GLAD is a correspondence table -- EF 3.1 flow to SimaPro 10.2 flow, with a
#: match condition and a conversion factor -- and that is how it is used, by a
#: manifest declaring `concept_associations.pairs_from: "glad"`.  It was *also*
#: named `additional-flow-input-*`, so input auto-discovery parsed all 124,318
#: rows on every build and discarded every one: the rows have no `uuid`, so
#: `_normalize_input_flow_record` returned None for each.  The name is the whole
#: reason it was on that path.
GLAD_ILCD_TO_SIMAPRO_JSON_FILEPATH = DATA_DIR / "glad-ilcd-ef31-to-simapro-10.2.json"

#: The name it had while it was on the input path.  Read when the current name
#: is absent, so an existing data directory keeps working without re-running
#: `download-glad-mapping`.
GLAD_ILCD_TO_SIMAPRO_JSON_LEGACY_FILEPATH = (
    DATA_DIR / "additional-flow-input-glad-ilcd-ef31-to-simapro-10.2.json"
)


def glad_ilcd_to_simapro_path() -> Path:
    """The GLAD correspondence table, under whichever name is present."""
    if GLAD_ILCD_TO_SIMAPRO_JSON_FILEPATH.exists():
        return GLAD_ILCD_TO_SIMAPRO_JSON_FILEPATH
    if GLAD_ILCD_TO_SIMAPRO_JSON_LEGACY_FILEPATH.exists():
        return GLAD_ILCD_TO_SIMAPRO_JSON_LEGACY_FILEPATH
    return GLAD_ILCD_TO_SIMAPRO_JSON_FILEPATH


def bafu_ecospold_zip_path(list_version: str) -> Path:
    """BAFU's ecoSpold archive for *list_version*, as the vendor names it.

    Derived rather than a constant per release, because BAFU ships more than
    one export a year -- 2026 v1 is followed by a v2 -- and a constant would
    make each one a Python change in a build whose whole claim is that adding a
    list is a registry entry.

    The vendor writes the release with a space where the manifest's
    ``list_version`` has a hyphen: ``2026-v1`` is ``BAFU-2026 v1_ecoSpold
    v1.zip``.  The trailing ``ecoSpold v1`` is the file format, not the export.

    Unlike EF 3.1's archive there is nothing to download this from; BAFU hands
    it over, so it is placed here and the adapter says which path it wanted.
    """
    return DATA_DIR / f"BAFU-{list_version.replace('-', ' ')}_ecoSpold v1.zip"


def stepwise_csv_path(list_version: str) -> Path:
    """Stepwise 2006's SimaPro method export for *list_version*.

    Derived from the version for BAFU's reason: the method is revised -- 1.09
    is the ninth -- and a constant per release would make each one a Python
    change in a build whose claim is that adding a list is a manifest.

    The version has two halves, as BAFU's ``2026-v1`` does: ``2006`` is the
    method and ``1.09`` is the export of it, so ``2006-1.09`` is
    ``Stepwise2006_v1.09.csv`` -- the name SimaPro ships it under and the name
    `tools/seed_data_dir.py` shares between worktrees.
    """
    return DATA_DIR / f"Stepwise{list_version.replace('-', '_v')}.csv"


def agribalyse_csv_path(list_version: str) -> Path:
    """AGRIBALYSE's SimaPro process export for *list_version*.

    Derived from the version for Stepwise's reason.  The name is the one the
    export circulates under -- ``3.2`` is ``AGB32_final.CSV`` -- because the
    file itself states no release (a ``{processes}`` header names a project,
    not a version), so the filename is the version statement the way BAFU's
    archive name is.  Like BAFU's archive it has no stable vendor URL: ADEME
    hands it over, so it is placed here and the adapter says which path it
    wanted.
    """
    return DATA_DIR / f"AGB{list_version.replace('.', '')}_final.CSV"


def greendelta_lcia_zip_path() -> Path:
    """GreenDelta's openLCA method package, under the name it is hosted as.

    One release rather than one per version, unlike BAFU's ecoSpold archive:
    the package inside is ``openLCA LCIA methods 2.8.0``, which is a version of
    GreenDelta's methods and not of BAFU's export, and the file that says which
    one was read is the factors file the adapter writes -- it records the
    package, its version and the archive's digest.

    A function rather than a constant so it reads like its ecoSpold sibling
    above, and so a test can patch ``DATA_DIR`` and be answered.
    """
    return DATA_DIR / "bafu-greendelta-lcia.zip"


ELEMENTARY_FLOWS_FILEPATH = DATA_DIR / "elementary-flows.json"
FLOW_OBJECTS_FILEPATH = DATA_DIR / "flow-objects.json"
FLOW_PROPERTIES_FILEPATH = DATA_DIR / "flow-properties.json"
# `FLOWS_DATA_FILEPATH = DATA_DIR / "ef-31-flows.json"` was here until #14.
# It was the hard-coded half of "EF 3.1 is the base list"; the other half was
# the string `"EF 3.1"` in eight modules.  Both are now one manifest entry with
# `role: "base"`: `brightway_flows.sources.base_source_list().flows_path`.
# `harmonised-flows.json` had a constant here until #5.  All three of the
# unwritten layered files kept theirs, but the other two are still read: the
# fossil validation in `tests/test_schemas.py` opens them if an old data
# directory has them.  Nothing reads this one, so it went with the file.  The
# record it held lives on as `elementary_flows.flow_json`.

HARMONISED_FLOWS_SIMPLE_FILEPATH = DATA_DIR / "harmonised-flows-simple.json.gz"
LCIA_METHODS_FILEPATH = DATA_DIR / "lcia-methods.json"
#: What `characterise` publishes: three implementations of EF 3.1, their 75
#: categories and their factors.  Gzipped like the flow export, for the same
#: reason -- it is the large one.
LCIA_FACTORS_FILEPATH = DATA_DIR / "lcia-factors.json.gz"
#: The comparison between the two published implementations, and where each of
#: them skips a context of a substance it characterises.  Small enough to open.
LCIA_DIFFERENCES_FILEPATH = DATA_DIR / "lcia-differences.json"
#: Where a release's snapshot is kept -- `<version>.json.gz`, one per release
#: `release-snapshot` has recorded -- and, under `migrations/`, the randonneur
#: files `release-migrations` writes between two of them.  Not created at
#: import: most runs never record a release.
RELEASES_DIR = DATA_DIR / "releases"
OPSIN_LOG_FILEPATH = DATA_DIR / "opsin-log.txt"
#: Where the unit-process score artifacts are read from by default: one file
#: per assessed release, written by `tools/export_unit_process_scores.py` under
#: a brightway Python rather than this one.  A default rather than the whole
#: answer, because the artifacts are expensive and a curator keeping them
#: outside any worktree points `score_comparison.artifact_dir` at that
#: directory in `settings.json` instead.
UNIT_PROCESS_SCORES_DIR = DATA_DIR / "unit-process-scores"
PUBCHEM_DATA_FILEPATH = DATA_DIR / "pubchem-data.json"
PUBCHEM_ELEMENTS_CACHE_FILEPATH = DATA_DIR / "pubchem-elements-isotopes.json"
RDKIT_LOG_FILEPATH = DATA_DIR / "rdkit-log.txt"
WEB_LOOKUP_CACHE_FILEPATH = DATA_DIR / "web-lookup-cache.json"
WIKIDATA_CACHE_FILEPATH = DATA_DIR / "wikidata-cache.json"


#: The repository this code is in, for asking git what revision it is at.
REPO_ROOT = Path(__file__).resolve().parents[2]


def git_revision() -> tuple[str, bool]:
    """``(commit, dirty)`` for the working tree, or ``("", False)`` off git.

    Stamped onto every build so that two databases can say whether they are
    comparable.  Diffing a branch build against a build of some older `main`
    reports that `main`'s own commits as the branch's -- a wrong answer that
    reads as a right one, and the only way to notice is to know which revision
    each side came from (#101).

    ``("", False)`` for an installed copy with no repository, or for a git that
    will not answer.  A build is not worth failing over a missing stamp, and a
    comparison that finds no revision says so rather than assuming a match.
    """
    def _git(*args: str) -> str | None:
        try:
            done = subprocess.run(
                ["git", "-C", str(REPO_ROOT), *args],
                capture_output=True, text=True, check=False, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):  # pragma: no cover
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    commit = _git("rev-parse", "HEAD")
    if not commit:
        return "", False
    # `status --porcelain` rather than `diff --quiet`: an untracked file changes
    # a build too, because a curated file the loader globs for is one.
    return commit, bool(_git("status", "--porcelain"))


# `ecoinvent_flows_filepath(version)` was here until #12.  A module of paths
# should not grow a function per flow list: where a list's flows live is one
# line of its manifest in `data/sources/`, resolved against `DATA_DIR` by
# `brightway_flows.sources`.

# `ecoinvent_merge_report_filepath(version)` was here until #243 -- a path with
# no writer and no reader, for a report the merge moved into SQLite.  What
# became of each source flow is the `merge_outcomes` table, which is keyed by
# run rather than by source version and so can describe a run merging several.

