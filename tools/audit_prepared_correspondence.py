"""Where a prepared decision disagrees with the row's own registry number.

What a `prepared` outcome *is* changed with #141.  It used to be ecoinvent's
published correspondence table deciding where most of ecoinvent's rows land,
taking precedence over the CAS number the row itself states -- and this audit
was built against that table, which is how #140's defects were found.  The
tables are retired now, and what lands as `prepared` is this project's own
curated rows: the ``*-match-overrides.json`` files, a few hundred rows across
the lists.  The audit is the same question asked of a different author --
where one of *our* rows sends a flow to an object that is a different
substance from the one the row's stated registry number names, that has to be
a decision written down in the row's comment, never a leftover.  Where the
two disagree, one of three things is true, and only one of them is fine to
leave alone:

* **A scheme.**  An ore-content resource row (``TiO2, 54% in ilmenite...``)
  names its own grade and is translated onto the element it is mined for,
  with the factor stated per row.  (A second scheme used to sit beside this
  one: the tables' element-versus-ion compartment routing.  Its whitelist
  retired with the tables -- ``plans/retire-prepared-correspondence.md`` §3a
  -- so an override row that confuses an element with its ion now prints as
  contradicted rather than being excused.)
* **A signed decision, or a defect.**  The row reaches a flow object that is
  a different substance from the one its own registry number names, while
  that number resolves cleanly to another object in this list.  A curated row
  may *sign* that contradiction -- ``"not_the_stated_substance": true`` in
  its override file, beside the comment that argues it -- and a signed group
  bins as acknowledged.  An unsigned one prints as ``CONTRADICTED`` and is
  presumed a leftover: against the vendor's tables this bin was pure defect
  (#130 found three -- Metaldehyde, Fenpropimorph, Thiocyanate -- and #140
  six more, including a herbicide's resource factor published under
  `Granite`), and a decision nobody signed is indistinguishable from the
  next one of those.  A signature on a row that in fact *agrees* with its
  number is stale, and flags the same way: both directions of drift between
  the file and the build are findings.
* **Nothing decidable.**  The row states no CAS, or states one this list has
  nowhere: the table is then the only opinion in the room, and there is nothing
  to contradict.

This audit classifies every prepared match into those bins, so the scan that
found #140 stops being a one-off script.  The scheme is whitelisted by shape,
not by list: an ore-content row names its grade (``% in``) in the flow name
itself.

Reads one build database and writes nothing:

    uv run python tools/audit_prepared_correspondence.py .data/consensus-flows.sqlite3
    uv run python tools/audit_prepared_correspondence.py .data/consensus-flows.sqlite3 --all
    uv run python tools/audit_prepared_correspondence.py .data/consensus-flows.sqlite3 --strict

``--all`` prints the whitelisted and acknowledged groups too, which is how the
scheme and the signatures themselves are reviewed.  ``--strict`` exits 2 on any
unsigned contradiction and on any stale signature, and passes on a build whose
every disagreement is a signed decision -- which makes it the routine gate.
Everything is grouped by (source name, stated CAS, target object): one line
per decision, not one per context it was made in.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

#: The classifications-payload key that carries a flow object's registry
#: numbers.  The same IRI `flow_objects.classifications_json` stores them under;
#: restated here because this tool reads the build database and the override
#: files, through nothing but their formats.
CAS_CLASSIFICATION_IRI = "http://semanticscience.org/resource/CHEMINF_000446"

#: Where the override files live: the correspondence whose decisions this
#: audits, and the place a signature is written.
OVERRIDES_DIR = Path(__file__).resolve().parents[1] / "src/brightway_flows/data"

# The classification bins.  Plain strings rather than an enum: this is a
# script, its output is text, and the names below appear in that output.
AGREES = "agrees"
NO_CAS = "no CAS stated"
CAS_UNPLACED = "CAS on no other object"
ORE_GRADE = "whitelisted: ore-grade translation"
ACKNOWLEDGED = "acknowledged: the row signs the contradiction"
CONTRADICTED = "CONTRADICTED"

#: The bins `--strict` treats as findings.
FLAGGED = (CONTRADICTED,)


@dataclass
class Group:
    """One decision the table made, however many contexts it made it in."""

    source_name: str
    source_cas: str
    target_id: str
    target_label: str
    target_cas: tuple[str, ...]
    #: The other flow objects the stated CAS resolves to, as (id, label) pairs.
    cas_homes: tuple[tuple[str, str], ...]
    rows: int = 0
    category: str = ""
    detail: str = ""
    versions: set[str] = field(default_factory=set)
    source_uuids: set[str] = field(default_factory=set)


def classify(group: Group, *, signed: frozenset[str] = frozenset()) -> Group:
    """Decide which bin one prepared decision belongs in, and say why.

    *signed* is the set of source uuids whose override row carries
    ``not_the_stated_substance`` -- see :func:`signed_source_uuids`.
    """
    if not group.source_cas:
        group.category = NO_CAS
        return group
    if group.source_cas in group.target_cas:
        group.category = AGREES
        return group
    if not group.cas_homes:
        group.category = CAS_UNPLACED
        group.detail = f"{group.source_cas} resolves to nothing else in this list"
        return group
    if re.search(r"%\s+in\b", group.source_name, re.IGNORECASE):
        group.category = ORE_GRADE
        group.detail = "the flow names its own ore grade"
        return group
    homes = ", ".join(f"{label!r}" for _, label in group.cas_homes)
    if group.source_uuids and group.source_uuids <= signed:
        # Every row of the decision signs it.  A group only partly signed
        # stays contradicted: half a signature is a file that drifted.
        group.category = ACKNOWLEDGED
        group.detail = f"{group.source_cas} is {homes}; signed in the overrides"
        return group
    group.category = CONTRADICTED
    group.detail = f"{group.source_cas} is {homes}"
    return group


def signed_source_uuids(overrides_dir: Path = OVERRIDES_DIR) -> frozenset[str]:
    """Every source uuid whose override row signs its contradiction."""
    signed: set[str] = set()
    for path in sorted(overrides_dir.glob("*-match-overrides.json")):
        payload = json.loads(path.read_text())
        for row in payload.get("overrides", []):
            if row.get("not_the_stated_substance"):
                uuid = str(row.get("source_uuid") or "").strip()
                if uuid:
                    signed.add(uuid)
    return frozenset(signed)


def stale_signatures(
    groups: list[Group], signed: frozenset[str]
) -> list[tuple[str, str]]:
    """Signed uuids whose every decision in this build agrees with its number.

    A uuid the build never placed as `prepared` is not stale -- a build
    merging fewer lists cannot answer -- but one that landed and *agrees* is
    a signature on a contradiction that no longer exists, which is the same
    drift as an unsigned contradiction, in the other direction.
    """
    verdicts: dict[str, set[str]] = defaultdict(set)
    names: dict[str, str] = {}
    for group in groups:
        for uuid in group.source_uuids:
            verdicts[uuid].add(group.category)
            names.setdefault(uuid, group.source_name)
    return sorted(
        (uuid, names[uuid])
        for uuid in signed
        if verdicts.get(uuid) == {AGREES}
    )


def load_groups(
    db_path: Path, *, signed: frozenset[str] | None = None
) -> list[Group]:
    """Every prepared decision in *db_path*, classified.

    *signed* overrides the signatures read from the override files, which is
    what lets a test classify a synthetic build without touching the real
    correspondence.
    """
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row

    labels: dict[str, str] = {}
    cas_of: dict[str, tuple[str, ...]] = {}
    homes_of: dict[str, set[str]] = defaultdict(set)
    for row in db.execute(
        "SELECT flow_object_id, pref_label_value, classifications_json FROM flow_objects"
    ):
        labels[row["flow_object_id"]] = row["pref_label_value"] or ""
        payload = json.loads(row["classifications_json"] or "{}")
        stated = (payload.get(CAS_CLASSIFICATION_IRI) or {}).get("@value") or []
        numbers = tuple(sorted({str(v).strip() for v in stated if str(v).strip()}))
        cas_of[row["flow_object_id"]] = numbers
        for number in numbers:
            homes_of[number].add(row["flow_object_id"])

    grouped: dict[tuple[str, str, str], Group] = {}
    for row in db.execute(
        """SELECT source_name, source_cas, source_uuid, flow_object_id, list_version
           FROM merge_outcomes
           WHERE matching_method = 'prepared' AND flow_object_id != ''"""
    ):
        cas = (row["source_cas"] or "").strip()
        target = row["flow_object_id"]
        key = (row["source_name"] or "", cas, target)
        group = grouped.get(key)
        if group is None:
            homes = tuple(
                sorted(
                    (fo, labels.get(fo, ""))
                    for fo in homes_of.get(cas, set()) - {target}
                )
            )
            group = grouped[key] = Group(
                source_name=key[0],
                source_cas=cas,
                target_id=target,
                target_label=labels.get(target, ""),
                target_cas=cas_of.get(target, ()),
                cas_homes=homes,
            )
        group.rows += 1
        group.versions.add(str(row["list_version"]))
        uuid = str(row["source_uuid"] or "").strip()
        if uuid:
            group.source_uuids.add(uuid)
    db.close()
    if signed is None:
        signed = signed_source_uuids()
    return [classify(group, signed=signed) for group in grouped.values()]


def report(groups: list[Group], *, show_all: bool = False) -> str:
    """The audit as text: a count per bin, then the groups worth reading."""
    by_category: dict[str, list[Group]] = defaultdict(list)
    for group in groups:
        by_category[group.category].append(group)

    lines = ["prepared-correspondence audit", ""]
    order = (AGREES, NO_CAS, CAS_UNPLACED, ORE_GRADE, ACKNOWLEDGED, CONTRADICTED)
    for category in order:
        members = by_category.get(category, [])
        rows = sum(g.rows for g in members)
        lines.append(f"  {len(members):5d} groups  {rows:6d} rows   {category}")
    listed = [
        category
        for category in (CONTRADICTED, ORE_GRADE, ACKNOWLEDGED)
        if category == CONTRADICTED or show_all
    ]
    for category in listed:
        members = sorted(
            by_category.get(category, []), key=lambda g: (g.source_name, g.source_cas)
        )
        if not members:
            continue
        lines += ["", f"== {category} =="]
        for g in members:
            lines.append(
                f"  {g.source_name[:44]:46s} cas={g.source_cas or '—':13s} "
                f"-> {g.target_label!r} [{g.target_id}]  ({g.rows} rows; {g.detail})"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("database", type=Path, help="a build's consensus-flows.sqlite3")
    parser.add_argument(
        "--all", action="store_true", help="print the whitelisted groups too"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 2 on any unsigned contradiction or stale signature",
    )
    args = parser.parse_args(argv)
    if not args.database.exists():
        print(f"no database at {args.database}", file=sys.stderr)
        return 1
    signed = signed_source_uuids()
    groups = load_groups(args.database, signed=signed)
    print(report(groups, show_all=args.all))
    stale = stale_signatures(groups, signed)
    for uuid, name in stale:
        print(
            f"STALE SIGNATURE  {name!r} [{uuid}]: the row signs a "
            f"contradiction, and every decision it made in this build agrees "
            f"with its stated number. Withdraw the signature.",
            file=sys.stderr,
        )
    if args.strict and (stale or any(g.category in FLAGGED for g in groups)):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
