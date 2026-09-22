"""Write `particulate-flow-classes.json`: which size window each particle flow is.

`plans/particulate-taxonomy.md` §3.5.  An airborne-particle flow says which
particles were counted -- everything below ten micrometres, or the 2.5-10 um
slice -- and until `domain/particulate_size.py` the list had no field for it, so
it lived in a name that five source lists spell seventeen ways.  This file is
where that stops being the only place the window lives.

The same shape as `water-flow-materials.json` and `land-flow-classes.json`, and
for the same reason.  The layering could read a flow's name at run time and
recognise `< 10 um`; that is exactly what these files exist to avoid.  BAFU
ships both `Particulates` and `Particulates, unspecified` and Stepwise 2006
characterises them **differently** -- 0.157 against 0.536 kg PM2.5-eq -- so
whether those two names mean one thing is a judgement about what a vendor meant,
not a string comparison.  A rule that answered it in the build would answer it
silently, and would answer it the same way for the next list without being asked.

So: the uuid, name, context and unit columns are the vendor's, taken
mechanically from the shipped files and unable to drift from them by
transcription; `size_class` and `source_category` are the curated part; and
:data:`READINGS` below is where a curator writes the reading down, once per
spelling, with the reason beside it.  A selected name that :data:`READINGS` does
not carry is printed and left out -- a question for a person, never a fallback.

**Two axes, and only one of them is a size.**  `(stationary)` and `(mobile)` say
what emitted the particles, not how large they were.  They take
`source_category` and land on the unqualified window, because Stepwise 2006 --
the only list in scope that characterises them -- gives plain, mobile and
stationary PM10 the same factor to nine digits.  Recording the category costs
nothing and buys the row eleven characterisation factors; minting it as a
substance of its own, which is what the build does today, buys a distinction no
method uses.  See §3.3.

Usage::

    uv run python tools/build_particulate_flow_classes.py
    uv run python tools/build_particulate_flow_classes.py --check
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from brightway_flows.domain.particulate_size import (  # noqa: E402
    names_a_particle_by_size,
    size_classes,
)
from brightway_flows.sources import registered_source_list  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "src" / "brightway_flows" / "data"
OUTPUT_PATH = DATA_DIR / "particulate-flow-classes.json"

#: Every registered list, read through the source registry rather than by a path
#: spelled here, so what this classifies is what the merge loads.  The registry
#: also supplies the `source` column: the merge looks a row up under
#: `SourceList.source_label`, and writing anything else here produces a table
#: that loads and never matches.
#:
#: Stepwise 2006 was absent while it was not registered (#2); its six spellings
#: were in :data:`READINGS` from the start, five of them BAFU's plus a
#: mobile-source PM10 BAFU does not have.  Registered without this key being
#: added, the list went on minting `Particulates, < 10 um` and `(mobile)` as
#: substances of their own on every five-list build, beside the PM10 its
#: `(stationary)` row reached by label -- which is why the merge now refuses a
#: particle row this file has not read (#196).
SOURCE_KEYS = (
    "EF-3.1",
    "ecoinvent-3.8",
    "ecoinvent-3.9.1",
    "ecoinvent-3.10.1",
    "ecoinvent-3.11",
    "ecoinvent-3.12",
    "bafu-2026-v1",
    "stepwise-2006-1.09",
    "agribalyse-3.2",
)

#: How a list says a flow is an airborne-particle measurement.
#:
#: Deliberately narrow, and narrower than "mentions particles".  Two families
#: look like this one and are not, and both are placed correctly today by rules
#: that must keep them (§3.4):
#:
#: * **composition**, not size -- Stepwise's `Zinc, fume or dust` is zinc, and
#:   ENVO's `silica dust` is silicon dioxide.  The chemistry rules place these.
#: * **radioactivity**, not size -- `Aerosols, radioactive, unspecified`, in all
#:   four merged lists, is a class over nuclides and is typed `AtomGroupingClass`.
#:
#: Neither answers a prefix test, which is why this is a prefix test -- and it
#: is the merge's own, `names_a_particle_by_size`, so that what this tool shows
#: a curator as unplaced and what the merge refuses to import are one
#: population (#196).

#: What each spelling means, and why.  One entry per name a vendor ships.
#:
#: This table is a **proposal mechanism**, not the record.  What the build reads
#: is the generated file, one row per (source, uuid); this is how those rows come
#: to say what they say, kept here so that adding a list means reviewing a
#: handful of readings rather than two hundred rows.
#:
#: Keyed by the vendor's name lower-cased.  `source_category` is empty unless the
#: name states one.
READINGS: dict[str, tuple[str, str, str]] = {
    # ── EF 3.1 ──────────────────────────────────────────────────────────────
    "particles (pm0.2)": (
        "pm0_2", "",
        "EF 3.1's finest cut. Below 0.2 um, stated as a cut and not a band.",
    ),
    "particles (pm0.2 - pm2.5)": (
        "pm0_2_to_pm2_5", "",
        "A band: the fine fraction with the ultrafine part taken out. EF gives "
        "it the same factor as PM2.5 in every compartment, which is a "
        "characterisation choice and not a reason to call it the same window.",
    ),
    "particles (pm2.5)": (
        "pm2_5", "",
        "The fine fraction, and the flow every list's `< 2.5 um` row reaches.",
    ),
    "particles (pm2.5 - pm10)": (
        "pm2_5_to_pm10", "",
        "The coarse fraction as EF spells it. Uncharacterised by EF 3.1 in "
        "every compartment, which is what #37's trade was made to work around; "
        "the trade is now a per-list override rather than something a synonym "
        "carries.",
    ),
    "particles (pm10)": (
        "pm10", "",
        "PM10 itself: every particle below ten micrometres. The flow BAFU's "
        "`Particulates, < 10 um` should have reached and did not (#153).",
    ),
    "particles (> pm10)": (
        "above_pm10", "",
        "Above ten micrometres. Spelled out of PM10 and therefore not part of "
        "it, which is why it hangs off the root of the scheme.",
    ),
    # ── ecoinvent 3.8 ───────────────────────────────────────────────────────
    "particulates, < 2.5 um": (
        "pm2_5", "",
        "ecoinvent 3.8's spelling, which BAFU inherits verbatim. Renamed "
        "`Particulate Matter, < 2.5 um` at 3.9.1 with the uuid unchanged.",
    ),
    "particulates, > 2.5 um, and < 10um": (
        "pm2_5_to_pm10", "",
        "The coarse band, and the row #153 is about. It reached "
        "`Particles (PM10)` on this build -- ecoinvent by a curated override "
        "(#37), BAFU by an alternative label that override had left behind. "
        "The window says 2.5 to 10, and that is a different class from below "
        "10 however the two are spelled.",
    ),
    "particulates, > 10 um": (
        "above_pm10", "",
        "ecoinvent 3.8's spelling of the above-ten fraction.",
    ),
    # ── ecoinvent 3.9.1 and later: the same three, renamed ───────────────────
    "particulate matter, < 2.5 um": (
        "pm2_5", "",
        "The 3.9.1 rename of `Particulates, < 2.5 um`, same uuid. A vendor "
        "renaming its own rows is exactly the event a name-based identity "
        "cannot survive, and the window is unmoved by it.",
    ),
    "particulate matter, > 2.5 um and < 10um": (
        "pm2_5_to_pm10", "",
        "The 3.9.1 rename of the coarse band, same uuid -- and note the comma "
        "ecoinvent dropped along with the word. Two spellings, one window.",
    ),
    "particulate matter, > 10 um": (
        "above_pm10", "",
        "The 3.9.1 rename of the above-ten fraction, same uuid.",
    ),
    # ── BAFU 2026-v1, and Stepwise 2006 when it is registered ───────────────
    "particulates, < 10 um": (
        "pm10", "",
        "PM10 in the ecoinvent-2 spelling three SimaPro-shaped lists inherit. "
        "On the 25 August 2026 build this minted a substance of its own with "
        "one elementary flow and no characterisation factors, beside the PM10 "
        "the list already published with eleven (#153).",
    ),
    "particulates, < 10 um (stationary)": (
        "pm10", "stationary",
        "The same window, from a stationary source. The category is recorded "
        "and the row lands on PM10: Stepwise 2006 gives plain, mobile and "
        "stationary PM10 the identical factor -- 0.535714286 kg PM2.5-eq -- so "
        "a separate identity would buy a distinction no method in this list "
        "uses, at the cost of every factor the row could have had.",
    ),
    "particulates, < 10 um (mobile)": (
        "pm10", "mobile",
        "Stepwise 2006's mobile-source PM10, which BAFU does not ship. Same "
        "window, same factor as the stationary and unqualified rows; carried "
        "here so that registering Stepwise (#2) needs no new reading.",
    ),
    "particulates": (
        "unsized", "",
        "No cut stated. See the note on `particulates, unspecified`: these two "
        "are one class here, and Stepwise characterises them differently.",
    ),
    "particulates, unspecified": (
        "unsized", "",
        "Also no cut stated, and read as the same class as bare `Particulates` "
        "-- a stated `unspecified` is the absence of a statement, not a "
        "statement, which is the rule the land taxonomy applies to `arable "
        "land, unspecified use`.\n\n"
        "The evidence argues, and it is recorded rather than hidden: Stepwise "
        "2006 characterises `Particulates` at 0.157142857 and "
        "`Particulates, unspecified` at 0.535714286 kg PM2.5-eq, the second "
        "being exactly its PM10 factor. That is Stepwise deciding what factor "
        "to give a row that did not say, which is a characterisation choice "
        "rather than a statement about what the row is. When #2 lands, the "
        "two factors meet on one flow and the conflict belongs in "
        "lcia-factor-rulings.json, where it is visible. Minting a second "
        "identity to carry one list's default is how `Particulates, < 10 Um` "
        "came to be a substance in the first place. See "
        "plans/particulate-taxonomy.md §6.",
    ),
    # ── AGRIBALYSE 3.2 ──────────────────────────────────────────────────────
    # AGRIBALYSE ships BAFU's spellings verbatim -- the same SimaPro export
    # vocabulary -- and every one of them is already read above.  Three are
    # its own.
    "particulates, > 10 um (process)": (
        "above_pm10", "process",
        "The above-ten fraction from a process source rather than combustion "
        "-- the third source category, beside `(stationary)` and `(mobile)`, "
        "and read the same way: the window is the identity, the category is "
        "recorded. Without a reading the row minted a substance of its own "
        "with no factors on the first five-list build (1 September 2026, "
        "b0b8d76); see #190.",
    ),
    "particulates, diesel soot": (
        "pm0_2_to_pm2_5", "",
        "Diesel exhaust particles, read as the fine band. The name says what "
        "the particles are made of and where they came from, not where the "
        "sample was cut, and the plan left it to a person (#190 group J). "
        "The owner's ruling of 2 September 2026: diesel soot is fine "
        "particulate, almost entirely below 2.5 um and above the 0.2 um "
        "ultrafine cut, so it is PM0.2 - PM2.5 rather than PM2.5 as a whole "
        "(plans/particle-family.md section 4). One AGRIBALYSE row, in "
        "unspecified air.",
    ),
    "particulates, spm": (
        "unsized", "",
        "Suspended particulate matter: a sampling term that states no cut. "
        "Read as the size-unstated total, with `Particulates` and "
        "`Particulates, unspecified`, by the owner's ruling of 2 September "
        "2026 (plans/particle-family.md section 4). One AGRIBALYSE row, in "
        "unspecified air; on the build of 944b274 it minted a substance of "
        "its own with no factor, which is what the merge now refuses to do "
        "silently (#196).",
    ),
}

#: The source categories `source_category` may take.  Closed, because an open
#: field is where `(stationary)`, `(Stationary)` and `stationary source` become
#: three answers.
CATEGORIES = frozenset({"", "stationary", "mobile", "process"})


def _is_particulate_flow(name: str) -> bool:
    return names_a_particle_by_size(name)


def source_rows(key: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One list's airborne-particle flows, classified, and the ones unplaced."""
    source = registered_source_list(key)
    rows: list[dict[str, Any]] = []
    unplaced: list[dict[str, Any]] = []

    for flow in json.loads(Path(source.flows_path).read_bytes()):
        name = flow["name"]
        if not _is_particulate_flow(name):
            continue

        reading = READINGS.get(name.strip().lower())
        if reading is None:
            unplaced.append({"source": source.source_label, "name": name})
            continue
        class_id, category, comment = reading

        rows.append(
            {
                "source": source.source_label,
                "source_uuid": flow["uuid"],
                "source_name": name,
                "source_context": list(flow.get("context") or []),
                "unit": flow.get("unit") or "",
                "size_class": class_id,
                "source_category": category,
                "comment": comment,
            }
        )

    return rows, unplaced


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail instead of writing if the output would change",
    )
    args = parser.parse_args()

    known = size_classes()
    for name, (class_id, category, _comment) in READINGS.items():
        if class_id not in known:
            raise SystemExit(
                f"{name!r} reads as {class_id!r}, which "
                f"particulate-size-classes.json does not carry."
            )
        if category not in CATEGORIES:
            raise SystemExit(
                f"{name!r} states the source category {category!r}, which is not "
                f"one of {sorted(CATEGORIES)}."
            )

    rows: list[dict[str, Any]] = []
    unplaced: list[dict[str, Any]] = []
    for key in SOURCE_KEYS:
        placed, missed = source_rows(key)
        rows.extend(placed)
        unplaced.extend(missed)
    rows.sort(
        key=lambda row: (row["source"], row["source_name"].lower(), row["source_uuid"])
    )

    payload = {
        "schema_version": 1,
        "description": (
            "Which size window in particulate-size-classes.json each airborne "
            "particle flow was cut at. Curated: BAFU ships both `Particulates` "
            "and `Particulates, unspecified`, and whether those are one thing "
            "is a judgement about what a vendor meant rather than a string "
            "comparison -- which is why the merge does a lookup here instead of "
            "reading `< 10 um` out of a name at run time. Generated by "
            "tools/build_particulate_flow_classes.py: the uuid, name, context "
            "and unit columns are the vendor's, and `size_class` and "
            "`source_category` are the curated part.\n\n"
            "`source_category` is the second axis and is not a size. "
            "`(stationary)` and `(mobile)` say what emitted the particles; both "
            "land on the unqualified window because Stepwise 2006, the only "
            "list in scope that characterises them, gives all three the same "
            "factor. One row per (source, uuid): a flow was cut at one window, "
            "and two rows arbitrated by file order is the collapse this file "
            "exists to stop. See plans/particulate-taxonomy.md and issue #153."
        ),
        "rows": rows,
    }
    rendered = json.dumps(payload, indent=2) + "\n"

    if args.check:
        current = OUTPUT_PATH.read_text() if OUTPUT_PATH.exists() else ""
        if current != rendered:
            print(f"{OUTPUT_PATH} is out of date; re-run without --check")
            return 1
        print(f"{OUTPUT_PATH} is up to date")
        return 0

    OUTPUT_PATH.write_text(rendered)

    by_source = collections.Counter(row["source"] for row in rows)
    by_class = collections.Counter(row["size_class"] for row in rows)
    print(f"{len(rows)} rows over {len(by_class)} size classes -> {OUTPUT_PATH.name}")
    for source, count in sorted(by_source.items()):
        print(f"  {source:<18} {count}")
    print(f"  by class: {dict(sorted(by_class.items()))}")
    categorised = collections.Counter(
        row["source_category"] for row in rows if row["source_category"]
    )
    print(f"  with a source category: {dict(categorised) or 'none'}")
    print(f"  unplaced: {len(unplaced)}")
    for row in unplaced:
        print(f"    {row['source']:<18} {row['name']!r}")
    return 1 if unplaced else 0


if __name__ == "__main__":
    raise SystemExit(main())
