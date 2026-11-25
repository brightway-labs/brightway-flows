"""Every fact about this release that no page may write by hand.

`plans/public-site.md` §0's first rule: **every undecided fact is a visible
placeholder, and lives in one place.**  No template writes a version, a date, a
DOI, a licence, a maintainer, an address or an email by hand -- it reads the
value from here, or, while the value is `None`, renders the chip
`partials/placeholder.html` draws instead.

Two kinds of fact, kept apart by how often they change.

The licences, the maintainers, the address: decided by Brightway Labs or by
legal, once, and typed in here as `PUBLICATION`.  Nothing a pipeline run
produces, and nothing that changes because one ran again.

The version, the release it follows, the date, the DOI and the checksums:
these move with every release, and are not typed in anywhere.  They are read
from the release file -- `brightway_flows.published_release`, which
`release-upload` writes -- and laid over `PUBLICATION` by `with_release`.  An
installation with no release file shows the placeholder for each.

Every field defaults to unset.  `unfilled_facts` walks them, and
`tests/test_publication.py` asserts it comes back empty for `PUBLICATION`
under a release -- that is what keeps this the one place a launch blocker
could hide, now that the tool which reported them is gone.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace

from brightway_flows.published_release import ARTIFACT_KEYS, PublishedRelease


@dataclass(frozen=True)
class Maintainer:
    """One line of the About page's maintainer list."""

    name: str
    role: str


#: Every file a release uploads to Zenodo: the snapshot, the three JSON
#: exports, the migration from the release before and the database.  Keyed the
#: same way `artifacts.ARTIFACTS` is, so the Download page can look a checksum
#: up by the same key it already has.
CHECKSUM_ARTIFACT_KEYS: tuple[str, ...] = ARTIFACT_KEYS


@dataclass(frozen=True)
class Publication:
    """One optional value per undecided fact.  `None` means "not decided yet",
    never "blank" -- a fact that is genuinely empty would be `""`, and nothing
    on this list is.
    """

    # The release: read from the release file, never typed in. (plan §8)
    version: str | None = None
    #: The release the migration on Download starts from: it names the file,
    #: `<previous_version>__<version>.zip`.
    previous_version: str | None = None
    release_date: str | None = None
    doi: str | None = None
    #: SHA-256, one per `CHECKSUM_ARTIFACT_KEYS` entry.  Absent keys are
    #: unfilled, the same as a `None` scalar field.
    checksums: dict[str, str] = field(default_factory=dict)

    # Owned by Brightway Labs or legal. (plan §8)
    data_licence: str | None = None
    code_licence: str | None = None
    source_list_terms: str | None = None

    # Maintainers and governance. (plan §8)
    maintainers: tuple[Maintainer, ...] = ()
    governance: str | None = None

    # Contact. (plan §8)
    postal_address: str | None = None
    contact_email: str | None = None
    log_retention_period: str | None = None

    def checksum(self, artifact_key: str) -> str | None:
        """The checksum for one artifact, or `None` while it is unset."""
        return self.checksums.get(artifact_key)

    def with_release(self, release: PublishedRelease | None) -> Publication:
        """These facts with *release*'s laid over them.

        No release leaves them as they are, which for `PUBLICATION` is unset:
        an installation that names no release claims none.
        """
        if release is None:
            return self
        return replace(
            self,
            version=release.version,
            previous_version=release.previous_version,
            release_date=release.release_date,
            doi=release.doi,
            checksums=release.checksums,
        )


#: The facts that do not move with a release.  Every page reads them through
#: `with_release`, which adds the ones that do.
#:
#: What is set here is decided; what is left out is the release's, and comes
#: from the release file.
PUBLICATION = Publication(
    # Both licences are written as SPDX identifiers rather than as titles: the
    # `CITATION.cff` block on Download quotes `data_licence` straight into its
    # `license:` field, which is an SPDX identifier there, and the footer and
    # About read the same string.  The data licence is the Open Database
    # Licence 1.0, https://opendatacommons.org/licenses/odbl/1-0/.
    data_licence="ODbL-1.0",
    code_licence="AGPL-3.0-or-later",
    source_list_terms=(
        "Every source list this one is built from is either in the public "
        "domain -- the GLAD mapping files, which is how the ecoinvent and "
        "SimaPro names reach this list -- or published under the same Open "
        "Database Licence this list uses, as ecoinvent's glossary is. No "
        "field here carries terms stricter than ODbL-1.0."
    ),
    # The About page's company card already says Chris Mutel co-founded
    # Brightway Labs and created Brightway; this is the separate fact of who
    # maintains *this list*, which is what the card under "Maintainers"
    # answers.  Every role is "Maintainer": the heading says that much already,
    # and naming a discipline per person would claim something the list itself
    # does not decide.
    maintainers=(
        Maintainer(name="Chris Mutel", role="Maintainer"),
        Maintainer(name="João Gonçalves", role="Maintainer"),
        Maintainer(name="David Turner", role="Maintainer"),
    ),
    governance=(
        "Decisions on the Brightway Flows list are currently made by the "
        "maintainers, working with experienced life cycle impact assessment "
        "experts and scientists. Our goal is to develop a more formal and "
        "inclusive governance structure over time."
    ),
    postal_address="Dorfsteig 8, 5223 Riniken, Switzerland",
    contact_email="flows@brightway-lca.com",
    log_retention_period="14 days",
)


def unfilled_facts(publication: Publication = PUBLICATION) -> list[str]:
    """The name of every fact still unset, in field-declaration order.

    A scalar counts as unfilled when it is `None`; `maintainers` when it is
    empty; `checksums` once per artifact key `CHECKSUM_ARTIFACT_KEYS` names
    that is missing from the dict, so a release with three of four checksums
    still reports the one it is missing.
    """
    unfilled: list[str] = []
    for one_field in fields(publication):
        value = getattr(publication, one_field.name)
        if one_field.name == "checksums":
            for key in CHECKSUM_ARTIFACT_KEYS:
                if key not in value:
                    unfilled.append(f"checksums[{key}]")
            continue
        if value is None or value == ():
            unfilled.append(one_field.name)
    return unfilled
