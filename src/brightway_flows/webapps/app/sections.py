"""The sections the application has, and what each of them is for.

In a module of its own rather than in the package's `__init__`, because two
things read it and one of them is a view: the masthead needs the label and the
address, and `/browse/` needs a sentence saying what a reader would go there
for.  `__init__` imports every view, so a view importing `__init__` would be a
cycle.

The labels are the two words the data model uses.  A flow object is the
substance -- one per compound, whatever it is released into -- and an elementary
flow is that substance in one context, which is what a source list carries a row
for.  Naming them "Substances" and "Flows" made the distinction the merge pages
turn on invisible in the navigation, and put the derived thing first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: Where the repository is.  Private until launch (`plans/public-site.md` §7),
#: so this link works for the team now and for everyone after.
REPOSITORY_URL = "https://github.com/brightway-labs/brightway-flows"

#: The description of a page that belongs to no section, and of the site.  The
#: homepage's pitch, word for word, from the canvas.
SITE_DESCRIPTION = (
    "One identity for every elementary flow, and a traceable link back to each "
    "life cycle inventory database that names it differently."
)

#: `top` is a link of its own in the top bar; `browse` and `build` are the two
#: halves of the Browse panel -- the published records, and the curators'
#: tools under "Build & review".
Group = Literal["top", "browse", "build"]


@dataclass(frozen=True)
class Section:
    """One entry of the top bar or the Browse panel, and of `/browse/`.

    `blurb` is written for somebody who has just arrived and does not yet know
    what this list is: it says what question the section answers, not what table
    it renders.  Empty on no section -- a section nobody can describe is a
    section nobody can be sent to.  It is also the page's
    `<meta name="description">`, unless the page writes its own.

    `summary` is the one line under the label in the Browse panel.  Every
    `browse` and `build` section has one.  A `browse` summary is written to
    read on its own, because with no database it is shown on its own; the
    panel puts the build's count in front of it when there is one (see
    `partials/masthead.html`).  A `build` summary never takes a count and has
    to fit one line of the panel's narrow curators' column, so a reader who
    is not a curator can tell what the tool is without opening it.
    """

    key: str
    label: str
    href: str
    blurb: str
    group: Group
    summary: str = ""


#: Every section, in the order the top bar and then the Browse panel show them
#: (`plans/public-site.md` §3).
#:
#: The published records come before the build that produced them: a reader
#: arriving at a public list is asking what a flow is, and the curators' tools
#: are one group further down, under "Build & review".  In the top bar Browse
#: sits between Docs and the rest of `top` (see `partials/masthead.html`).
SECTIONS: tuple[Section, ...] = (
    Section(
        key="docs",
        label="Docs",
        href="/docs/",
        blurb="What this list is, how a source row becomes a published flow, "
              "and what each word on these pages means.",
        group="top",
    ),
    #: Both blurbs are the ledes of their pages on the canvas, word for word.
    Section(
        key="download",
        label="Download",
        href="/download/",
        blurb="Each release is a fixed, citable snapshot of the list. Pick a "
              "file below, or cite the release so others can get exactly the "
              "same data.",
        group="top",
    ),
    Section(
        key="about",
        label="About",
        href="/about/",
        blurb="The Brightway Flows is built and maintained by Brightway "
              "Labs, and published openly for the Brightway community and for "
              "anyone else who works with life cycle inventory data.",
        group="top",
    ),
    Section(
        key="flows",
        label="Elementary flows",
        href="/flows/",
        blurb="A substance in a compartment — carbon dioxide to air, copper to "
              "agricultural soil — which is what a source list carries a row "
              "for and what an inventory names.",
        group="browse",
        summary="Flows, by substance and context",
    ),
    Section(
        key="substances",
        label="Flow objects",
        href="/flow-objects/",
        blurb="A chemical identity, independent of context and source: the "
              "formula, the registry numbers, what the substance is used for. "
              "Every flow resolves to one of these.",
        group="browse",
        summary="Substances, materials and land classes",
    ),
    #: After the flows and before the checks, because that is what it is: a
    #: layer over the flows, and the thing a reader asks about one once they
    #: have found it.
    Section(
        key="factors",
        label="Factors",
        href="/factors/",
        blurb="What each implementation of a method says a flow is worth, "
              "where two of them disagree, and what this build declined to "
              "publish.",
        group="browse",
        summary="Characterisation factors, by method and implementation",
    ),
    Section(
        key="checks",
        label="Checks",
        href="/checks/",
        blurb="Six questions asked of the finished list — a name on two "
              "substances, a formula that disagrees with its own source, a "
              "row measured in the wrong unit.",
        group="browse",
        summary="Where the source lists disagree with each other",
    ),
    Section(
        key="overview",
        label="Current run",
        href="/run/",
        blurb="What the last build did, what it is waiting on, and the files "
              "it published — the JSON exports are downloadable from there.",
        group="build",
        summary="What the last build did",
    ),
    #: After the factors, because it is what the factors do once applied: a
    #: vendor's own datasets scored with its factors and with ours, and the
    #: flows ranked by how much of the difference they carry.
    Section(
        key="scores",
        label="Scores",
        href="/scores/",
        blurb="Five hundred datasets of a vendor scored with the factors the "
              "vendor ships and again with the factors of this list, and which "
              "flows carry the difference — the fix list, ordered by "
              "consequence.",
        group="build",
        summary="Vendor datasets, rescored",
    ),
    Section(
        key="queue",
        label="Queue",
        href="/queue/",
        blurb="Where the pipeline declined to decide and is waiting for a "
              "person. A work list, not a browser.",
        group="build",
        summary="Waiting for a person",
    ),
    Section(
        key="merge",
        label="Merge",
        href="/merge/",
        blurb="What the run did with every row of every source list: matched, "
              "created, or left unplaced, and on what evidence.",
        group="build",
        summary="Where every source row went",
    ),
)


def navigation() -> dict[Group, list[dict[str, str]]]:
    """The top bar, the Browse panel and the mobile menu, by group.

    Plain dictionaries because that is what the template reads.  The blurb is
    left out: the panel has one line per entry, and that is `summary`.
    """
    groups: dict[Group, list[dict[str, str]]] = {"top": [], "browse": [], "build": []}
    for section in SECTIONS:
        groups[section.group].append({
            "key": section.key,
            "label": section.label,
            "href": section.href,
            "summary": section.summary,
        })
    return groups


def description(key: str | None) -> str:
    """A page's `<meta name="description">`: its section's blurb, or the site's."""
    for section in SECTIONS:
        if section.key == key:
            return section.blurb
    return SITE_DESCRIPTION
