"""Every fact about this release that no page may write by hand.

`plans/public-site.md` §0's first rule: **every undecided fact is a visible
placeholder, and lives in one place.**  No template writes a version, a date, a
DOI, a licence, a maintainer, an address or an email by hand -- it reads the
value from here, or, while the value is `None`, renders the chip
`partials/placeholder.html` draws instead.

This module is not read from the build or from the database.  A version
number and a data licence are not something a pipeline run produces; they are
decided by Brightway Labs or by legal, once, and then typed in here.  Nothing
here changes because the pipeline ran again.

Every field defaults to unset, and every one of them is decided (#200).
`unfilled_facts` still walks them, and `tests/test_publication.py` asserts it
comes back empty -- that is what keeps this the one place a launch blocker
could hide, now that the tool which reported them is gone.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields


@dataclass(frozen=True)
class Maintainer:
    """One line of the About page's maintainer list."""

    name: str
    role: str


#: The three JSON artifacts a release checksums, plus the database.  Keyed the
#: same way `artifacts.ARTIFACTS` is, so the Download page can look a checksum
#: up by the same key it already has.
CHECKSUM_ARTIFACT_KEYS: tuple[str, ...] = ("flows", "factors", "differences", "database")


@dataclass(frozen=True)
class Publication:
    """One optional value per undecided fact.  `None` means "not decided yet",
    never "blank" -- a fact that is genuinely empty would be `""`, and nothing
    on this list is.
    """

    # From the first Zenodo release. (plan §8)
    version: str | None = None
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


#: The one instance every page reads.  Replaced wholesale once the facts are
#: decided -- there is no reason to mutate a field in place, since every
#: consumer reaches it through this name rather than holding a reference.
#:
#: What is set here is decided; what is left out is still waiting on the first
#: Zenodo release, on legal, or on Brightway Labs (#200).
PUBLICATION = Publication(
    # The first release.
    version="1.0",
    release_date="2026-09-22",
    doi="10.5281/zenodo.22857950",
    # SHA-256 of the four files of the 1.0 release, as they were archived.
    # Read off the release files themselves, not off a build: a rebuild of the
    # same commit does not reproduce these bytes, and what a reader downloads
    # is the archived file.
    checksums={
        "flows": "07a35d2da36fe5b18515fb956757434c785da78186a1e6254b99abfa29ae5b46",
        "factors": "2e820ff0c1d86d8920c06d4f4fa8c1df644f51f88ac699612439a4b7095a6d2a",
        "differences": "bbe57a44745c743317361c61d3ca8b5e44ddc233bad8a62c7bd05f1312dae563",
        "database": "20cfe2b604d66778e2816befe1e79d99d9135c376debda5358d460879486ddc0",
    },
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
