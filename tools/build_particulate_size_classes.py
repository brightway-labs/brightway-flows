"""Write `particulate-size-classes.json`: the particle size windows, ours.

A particulate size class is a **window** -- a pair of aerodynamic-diameter
bounds in micrometres -- and the window is what makes `Particulates, < 10 um`
and `particles (PM10)` one thing without a crosswalk row.  See
`plans/particulate-taxonomy.md` §3.

**Nothing here anchors to a published vocabulary, and that is a decision.**  The
survey in §2 of the plan found two usable ENVO classes out of seven -- PM10 and
PM2.5 -- both defined on plain *diameter* where every source list means
**aerodynamic** diameter, and both restricted to *solid particles* where PM
includes droplets.  Nothing anywhere carries a band: not the 0.2-2.5 um slice,
not the 2.5-10 um coarse fraction, not the above-ten class.  Two loose citations
out of seven buy less than they cost: they make a scheme look anchored when five
sevenths of it is not, and they invite a reader to take our bounds as the
authority's when the authority states different ones.

So this is our own vocabulary, published as ours, and the bounds are what a
reviewer checks it by.

**The nesting is checked against those bounds.**  A class's declared parent must
be the *smallest* class whose window properly contains its own, and no two
classes may state the same window.  A scheme of seven hand-written concepts is
small enough to get subtly wrong -- pointing the 2.5-10 um band at PM2.5 because
both mention 2.5 -- and a number is evidence where a label is not.

That check is not written here.  It lives in
`domain.particulate_size.check_nesting`, which the reader runs on every load, and
this tool validates what it is about to write by parsing it with the same
`classes_from_payload` the build will parse it with.  A generator whose output
its own reader rejects is the failure worth making impossible, and a second copy
of the rule is how the two come to disagree about what a parent is.

Usage::

    uv run python tools/build_particulate_size_classes.py
"""

from __future__ import annotations

import json
import sys
from hashlib import sha1
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from brightway_flows.domain.particulate_size import (  # noqa: E402
    ParticulateSizeError,
    classes_from_payload,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "src" / "brightway_flows" / "data"
OUTPUT_PATH = DATA_DIR / "particulate-size-classes.json"

#: id, parent, label, window, basis, definition, comment.  The parent is the
#: intended edge; whether the bounds agree is checked.
#:
#: `lower_um` and `upper_um` are the aerodynamic-diameter bounds, `None` meaning
#: open on that side.  `None` on both means the source stated no cut at all,
#: which is the absence of a statement rather than a window of infinite width --
#: the distinction `check_nesting` has to be told about.
NODES: tuple[dict[str, Any], ...] = (
    {
        "id": "unsized",
        "parent": None,
        "label": "Particles (unspecified size)",
        "lower_um": None,
        "upper_um": None,
        "basis": "particulate:unsized",
        "definition": (
            "Airborne particles reported without any statement of the size they "
            "were selected at."
        ),
        "comment": (
            "The scheme's root, and the one class that is new. Four flow "
            "objects stand in for it today -- BAFU's `Particulates` and "
            "`Particulates, unspecified`, and the same two names from Stepwise "
            "2006 -- each with one elementary flow and no characterisation "
            "factors at all.\n\n"
            "It states no window, and that is the fact about it: a row that did "
            "not say where the cut was has not said the cut was everywhere. So "
            "it sits at the top of the scheme without being a superset of "
            "anything, and the nesting check is told to treat it that way.\n\n"
            "A fresh basis rather than one of the four names it replaces. The "
            "new object is not any of them; it is the class they were four "
            "spellings of, and giving it one of their identifiers would say it "
            "is that one."
        ),
    },
    {
        "id": "pm10",
        "parent": "unsized",
        "label": "Particles (PM10)",
        "lower_um": None,
        "upper_um": 10.0,
        "basis": "name:particles (pm10)",
        "definition": (
            "Every airborne particle with an aerodynamic diameter below ten "
            "micrometres. What air-quality regulation reports, and the form "
            "most inventories carry their particulate emissions in."
        ),
        "comment": (
            "The class #153 is about on one side: BAFU's `Particulates, < 10 "
            "um` is this, and reached nothing.\n\n"
            "Aerodynamic diameter is not a length. It is the diameter of the "
            "unit-density sphere that settles at the same speed, so even the "
            "selection criterion is an instrument's answer -- which is a large "
            "part of why the published vocabularies are no help here: ENVO's "
            "nearest class says *diameter*, and says *solid particles* where PM "
            "includes droplets.\n\n"
            "Keeps the name basis, so the object EF 3.1 already publishes under "
            "this identifier does not churn. The basis is a stable seed, not a "
            "reading of the name: nothing looks a flow up by it."
        ),
    },
    {
        "id": "pm2_5",
        "parent": "pm10",
        "label": "Particles (PM2.5)",
        "lower_um": None,
        "upper_um": 2.5,
        "basis": "name:particles (pm2.5)",
        "definition": (
            "Every airborne particle with an aerodynamic diameter below 2.5 "
            "micrometres -- the fine fraction, which every method in this list "
            "characterises most heavily."
        ),
        "comment": (
            "Inside PM10, which the bounds say and the nesting check confirms: "
            "0-2.5 is inside 0-10. Every source list in scope ships a row for "
            "it, under four spellings between them."
        ),
    },
    {
        "id": "pm0_2",
        "parent": "pm2_5",
        "label": "Particles (PM0.2)",
        "lower_um": None,
        "upper_um": 0.2,
        "basis": "name:particles (pm0.2)",
        "definition": (
            "Every airborne particle with an aerodynamic diameter below 0.2 "
            "micrometres. EF 3.1's finest cut, and the only list that ships it."
        ),
        "comment": (
            "0.2 um is EF's number and not a convention. The term the "
            "vocabularies offer here -- *ultrafine* -- carries no numeric bound "
            "at all and means 0.1 um where it is used, so it names a different "
            "cut and states neither. The bound is the class."
        ),
    },
    {
        "id": "pm0_2_to_pm2_5",
        "parent": "pm2_5",
        "label": "Particles (PM0.2 - PM2.5)",
        "lower_um": 0.2,
        "upper_um": 2.5,
        "basis": "name:particles (pm0.2 - pm2.5)",
        "definition": (
            "Airborne particles with an aerodynamic diameter between 0.2 and "
            "2.5 micrometres -- the fine fraction with the ultrafine part taken "
            "out."
        ),
        "comment": (
            "A band rather than a cut. Under PM2.5 because 0.2-2.5 is inside "
            "0-2.5, which the nesting check confirms from the bounds rather "
            "than from the name.\n\n"
            "EF gives it the same factor as PM2.5 in every compartment. That is "
            "a characterisation choice and not a reason to call it the same "
            "window: two flows scoring alike are still two flows."
        ),
    },
    {
        "id": "pm2_5_to_pm10",
        "parent": "pm10",
        "label": "Particles (PM2.5 - PM10)",
        "lower_um": 2.5,
        "upper_um": 10.0,
        "basis": "name:particles (pm2.5 - pm10)",
        "definition": (
            "Airborne particles with an aerodynamic diameter between 2.5 and "
            "ten micrometres -- the coarse fraction."
        ),
        "comment": (
            "The class #153 is about on the other side. ecoinvent, BAFU and "
            "every SimaPro-shaped list ship a coarse-fraction row, and until "
            "the window was a field those rows could reach `Particles (PM10)` "
            "by resembling it -- which four BAFU rows did, on a synonym nobody "
            "chose for them.\n\n"
            "Under PM10 and not under PM2.5: 2.5-10 is inside 0-10 and is not "
            "inside 0-2.5. Both readings mention 2.5, and only the bounds tell "
            "them apart.\n\n"
            "EF 3.1 gives it no characterisation factor in any compartment. A "
            "row landing here correctly still scores zero, and that is EF's "
            "answer rather than a defect in the mapping."
        ),
    },
    {
        "id": "above_pm10",
        "parent": "unsized",
        "label": "Particles (> PM10)",
        "lower_um": 10.0,
        "upper_um": None,
        "basis": "name:particles (> pm10)",
        "definition": (
            "Airborne particles with an aerodynamic diameter above ten "
            "micrometres -- too coarse to be respirable, and uncharacterised by "
            "every method in this list."
        ),
        "comment": (
            "Under the root rather than under PM10, which is the whole point of "
            "checking the nesting against the bounds: `> PM10` is spelled out "
            "of PM10 and is not part of it."
        ),
    },
)


def flow_object_id(basis: str) -> str:
    return "fo-" + sha1(basis.encode("utf-8")).hexdigest()[:16]


#: The `Particulates` spelling every window is always published under as an
#: alternative label, beside the `Particles (...)` preferred label EF 3.1 uses.
#:
#: The ecoinvent-2 form, which BAFU, Stepwise and AGRIBALYSE inherit through
#: SimaPro and which a reader searching the export types.  Until this the label
#: was whatever `carry_member_names` happened to keep: on the build of 2
#: September 2026 (`944b274`) PM10 carried only `Particulates, < 10 um
#: (stationary)`, because Stepwise's stray substance held the plain spelling as
#: its own name, and the two sub-2.5 windows carried nothing at all.  Written
#: by the layering with its own provenance, so no pass removes it; the two
#: sub-2.5 spellings are coined on the same pattern, because no vendor ships
#: them and the rule is *always* (`plans/particle-family.md` §2).
ALT_LABELS: dict[str, tuple[str, ...]] = {
    "unsized": ("Particulates, unspecified", "Particulates"),
    "pm10": ("Particulates, < 10 um",),
    "pm2_5": ("Particulates, < 2.5 um",),
    "pm0_2": ("Particulates, < 0.2 um",),
    "pm0_2_to_pm2_5": ("Particulates, > 0.2 um, and < 2.5 um",),
    "pm2_5_to_pm10": ("Particulates, > 2.5 um, and < 10um",),
    "above_pm10": ("Particulates, > 10 um",),
}


#: Where each window's bound is read from.  Not an ontology class -- the
#: survey in plans/particulate-taxonomy.md section 2 and its re-run on 2
#: September 2026 (plans/particle-family.md section 1) found none carrying a
#: band, the above-ten class or the size-unstated total -- but the text that
#: says what `upper_um` means: a size-selective inlet with a 50 % efficiency
#: cut-off at that aerodynamic diameter.  Recorded per concept so that a
#: reader of the file can check the meaning of a bound without taking the
#: number on trust, and printed on the particles page.
DEFINITION_SOURCES: dict[str, str] = {
    "unsized": (
        "None stated. The concept is this scheme's own: airborne particles a "
        "source reported without saying where the sample was cut."
    ),
    "pm10": (
        "EU Directive 2008/50/EC, Article 2(18): particulate matter which passes "
        "through a size-selective inlet with a 50 % efficiency cut-off at 10 um "
        "aerodynamic diameter; ISO 7708:1995 calls the same convention the "
        "thoracic fraction."
    ),
    "pm2_5": (
        "EU Directive 2008/50/EC, Article 2(19): particulate matter which passes "
        "through a size-selective inlet with a 50 % efficiency cut-off at 2.5 um "
        "aerodynamic diameter; ISO 7708:1995's high-risk respirable convention."
    ),
    "pm0_2": (
        "By construction from the bound: the same 50 % cut-off convention as "
        "PM10 and PM2.5 at 0.2 um, EF 3.1's finest cut. No standard defines a "
        "regulated class at this size; the ultrafine convention elsewhere is 0.1 um."
    ),
    "pm0_2_to_pm2_5": (
        "By construction from the bounds: everything the PM2.5 inlet passes that "
        "a 0.2 um inlet would not. A band no standard or vocabulary names."
    ),
    "pm2_5_to_pm10": (
        "By construction from the bounds: everything the PM10 inlet passes that "
        "the PM2.5 inlet would not -- the coarse fraction of air-quality usage, "
        "which no standard defines as a class of its own."
    ),
    "above_pm10": (
        "By construction from the bound: what a PM10 inlet does not pass. Named "
        "by ecoinvent 2 and EF 3.1, defined by neither."
    ),
}


def selection(node: dict[str, Any]) -> str:
    """How the sample was cut, in one word, derived from the bounds."""
    lower, upper = node["lower_um"], node["upper_um"]
    if lower is None and upper is None:
        return "unstated"
    if lower is None:
        return "below"
    if upper is None:
        return "above"
    return "between"


def main() -> int:
    concepts = [
        {
            "id": node["id"],
            "label": node["label"],
            "definition": node["definition"],
            "broader": node.get("parent"),
            "selection": selection(node),
            "lower_um": node["lower_um"],
            "upper_um": node["upper_um"],
            "flow_object_basis": node["basis"],
            "flow_object_id": flow_object_id(node["basis"]),
            "alt_labels": list(ALT_LABELS[node["id"]]),
            "definition_source": DEFINITION_SOURCES[node["id"]],
            "comment": node["comment"],
        }
        for node in NODES
    ]

    payload = {
        "schema_version": 1,
        "description": (
            "The particle size window a flow was cut at. Our own vocabulary, "
            "published as ours: a window is a pair of aerodynamic-diameter "
            "bounds in micrometres, `null` meaning open on that side and `null` "
            "on both meaning the source stated no cut -- which is the absence "
            "of a statement, not a window of infinite width. Two source names "
            "stating one window are one thing, with no crosswalk row required, "
            "which is what #153 is about.\n\n"
            "Nothing here anchors to a published ontology, and that is a "
            "decision rather than an omission. The survey in "
            "plans/particulate-taxonomy.md section 2 found two usable classes "
            "out of seven, both defined on plain diameter where these lists "
            "mean aerodynamic diameter and both restricted to solid particles "
            "where PM includes droplets, and nothing anywhere for a band. Two "
            "loose citations would make a scheme look anchored when five "
            "sevenths of it is not.\n\n"
            "What holds it together instead is the bounds. The nesting is "
            "checked against them on every load -- a class's parent must be the "
            "smallest class whose window contains its own, and no two classes "
            "may state one window -- and "
            "tools/build_particulate_size_classes.py validates its own output "
            "through the same reader before writing it.\n\n"
            "No concept states a ChemROF class. All seven are "
            "brightway:AggregateMeasurement, which aggregate-measurements.json "
            "says once for the family rather than seven times here: what kind "
            "of thing these are is that file's question, and which cut each one "
            "is, is this one's. See plans/particulate-taxonomy.md and issue "
            "#153."
        ),
        "concepts": concepts,
    }

    # Parsed with the reader before it is written, so a scheme the build would
    # reject never reaches the disk to be reviewed as though it were fine.
    try:
        classes_from_payload(payload)
    except ParticulateSizeError as error:
        print(f"refusing to write: {error}", file=sys.stderr)
        return 1

    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
    print(f"wrote {len(concepts)} size classes to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
