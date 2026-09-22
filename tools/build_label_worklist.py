#!/usr/bin/env python
"""Turn the preferred-label review queue into a curation worklist.

`consensus_match` proposes preferred-label replacements, and
`preferred-label-decisions.json` decides which of them are applied.  A rule not
in `DEFAULT_APPROVED_RULES` defers an unruled pair to the
`undecided-label-replacement` queue in the consensus database, and a curator
rules on it there.

That ruling is one question -- **is the replacement a name this substance
actually has?** -- and the queue alone does not answer it.  This tool answers it
for every queued pair, by asking Common Chemistry and ChEBI what names they hold
for the CAS the rule keyed the replacement on:

    synonym_swap                          both names known -- supported
    systematic_to_common                  replacement known, current not -- usually
                                          a systematic name giving way to a common one
    replacement_not_a_name_for_this_cas   flagged
    neither_name_known_for_this_cas       flagged
    cas_unknown_to_sources                flagged

A flagged pair asserts an identity neither source supports.  That is where a
wrong preferred label comes from -- `'Sodium Chloride' -> 'sea water'` scores
`replacement_not_a_name_for_this_cas`, and the rule proposed it anyway.

That example came from the `entropy` rule, which #222 removed: the audit this
tool automates found 79 of its 117 pairs flagged, and a rule wrong about
identity that often is not one a curator should be asked to salvage row by row.
The queue it fed went with it.

What fills the queue now is `multi_source_consensus`, which defers the same way.
It filled nothing until #245: the rule compared its candidate against the flow
object's label while renaming that object's members, so it proposed 0 pairs in
the 2026-08-06 run.  Compared per member, the same run yields 26 pairs over 279
flows, and this tool flags 2 of them.

Both are false alarms, and in the direction that costs a reader little: names are
compared with case and markup folded but not whitespace, so a replacement that
merely closes a space -- `'2,3,4,5-tetrachlorobenzoyl Chloride'` ->
`'2,3,4,5-tetrachlorobenzoylchloride'` -- is a name the sources do not hold under
that exact spelling and is flagged as if it named something else.

**The verdict is about identity, not specificity.** It cannot see a replacement
that names something broader than the flow is: `'Xylene (all isomers)' ->
'Xylene'` scores `systematic_to_common`, because `xylene` is a name CAS
1330-20-7 holds and `xylene (all isomers)` is not.  That is the error the 26
pairs actually contain -- `'Carbon, Organic, In Soil Or Biomass Stock' ->
'Carbon'` and `'Iodine, 0.03% In Water' -> 'Iodine'` both score unflagged.  So
scope narrowing needs a reader, and the unflagged rows are where to look for it;
`tools/build_scope_narrowing_shortlist.py` is what puts the likeliest of them in
front of one, over the renames a default-approved rule applied without ever
reaching this queue (#224).

Rows come out shaped like `preferred-label-decisions.json` entries: rule on one
by setting `decision`, writing `notes`, dropping the `audit` block, and moving
the row across.

It exists as a repository tool rather than a throwaway script because the
worklist is regenerated from every run, and a worklist that does not match what
the pipeline last emitted is worse than none -- it reads as a decision backlog
while describing a state that no longer exists.

    tools/build_label_worklist.py [--database PATH] [--output PATH]

Defaults read `consensus-flows.sqlite3` from the platform data directory and
write `docs/reference/preferred-label-worklist.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from brightway_flows.curation.label_audit import (
    SUPPORTED_VERDICTS,
    SourceNames,
    public_evidence,
    verdict_for,
    verdict_over_cas,
)
from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH
from brightway_flows.pipeline.review_records import ReviewQueue
from brightway_flows.pipeline.review_tables import read_pipeline_run, read_review_queue

DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "docs" / "reference" / "preferred-label-worklist.json"
)

#: Re-exported so that `verdict_for` reads as this tool's own question when the
#: docstring above is what a reader has in hand.  The definition is shared with
#: `tools/build_scope_narrowing_shortlist.py`, which audits the renames this
#: tool never sees -- the ones a default-approved rule applied.
__all__ = ["SUPPORTED_VERDICTS", "SourceNames", "build", "main", "verdict_for"]


def build(db_path: Path) -> dict[str, Any]:
    """The worklist for every rename pair still awaiting a ruling.

    Reads the `review_queue` table rather than `consensus-match-review.json`,
    which the pipeline wrote only when asked -- so a worklist could be built
    against a review file several runs old without anything saying so.  The
    database is rewritten every run, and the run it came from is stamped on the
    output.
    """
    queued = [
        item.payload
        for item in read_review_queue(db_path, ReviewQueue.UNDECIDED_LABEL_REPLACEMENT)
    ]
    run = read_pipeline_run(db_path)
    sources = SourceNames()

    rows: list[dict[str, Any]] = []
    verdicts: Counter[str] = Counter()
    for item in queued:
        current = str(item.get("current") or "")
        replacement = str(item.get("replacement") or "")
        cas_numbers = [str(c) for c in (item.get("cas_numbers") or []) if c]

        evidence = [sources.evidence(cas) for cas in cas_numbers]
        verdict = verdict_over_cas(current, replacement, evidence)
        verdicts[verdict] += 1

        rows.append({
            "current": current,
            "replacement": replacement,
            "decision": "undecided",
            "notes": "",
            "audit": {
                "verdict": verdict,
                "suspicious": verdict not in SUPPORTED_VERDICTS,
                "rule": item.get("rule", ""),
                "cas_numbers": cas_numbers,
                "flow_count": item.get("flow_count", 0),
                "example_uuid": item.get("example_uuid", ""),
                "sources": [public_evidence(e) for e in evidence],
            },
        })

    rows.sort(key=lambda r: (
        not r["audit"]["suspicious"], -r["audit"]["flow_count"], r["current"]
    ))
    suspicious = [r for r in rows if r["audit"]["suspicious"]]

    return {
        "schema_version": 1,
        "comment": (
            "Curation worklist for preferred-label replacements awaiting a ruling, "
            "generated by tools/build_label_worklist.py from the consensus database. "
            "`audit.verdict` asks whether each name is a name the cited CAS actually has "
            "per Common Chemistry and ChEBI: synonym_swap and systematic_to_common are "
            "supported, the other three are not and are flagged `suspicious`. The verdict "
            "is about identity, not specificity -- it cannot see a replacement that names "
            "something broader than the flow is, so the unflagged rows still want a reader. "
            "Rule on a row by setting `decision`, writing `notes`, dropping the `audit` "
            "block and moving it into preferred-label-decisions.json. Until then the "
            "current label stands, so an unruled row publishes nothing wrong."
        ),
        "source_run": {
            "database": str(db_path),
            "run_id": run.run_id if run is not None else "",
            "timestamp": run.timestamp if run is not None else "",
            "queued_pairs": len(queued),
        },
        "summary": {
            "pairs": len(rows),
            "flows": sum(r["audit"]["flow_count"] for r in rows),
            "suspicious_pairs": len(suspicious),
            "suspicious_flows": sum(r["audit"]["flow_count"] for r in suspicious),
            "verdicts": dict(verdicts.most_common()),
        },
        "decisions": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=CONSENSUS_DB_FILEPATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    if not args.database.exists():
        parser.error(
            f"consensus database not found: {args.database}\n"
            "Run `brightway-flows build` first."
        )

    payload = build(args.database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    summary = payload["summary"]
    print(f"wrote {args.output}")
    print(f"  {summary['pairs']} pairs / {summary['flows']} flows")
    print(f"  {summary['suspicious_pairs']} flagged / {summary['suspicious_flows']} flows")
    for verdict, count in summary["verdicts"].items():
        print(f"    {count:>4}  {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
