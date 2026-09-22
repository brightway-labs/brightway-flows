"""Rendering an assessment: for a terminal, for a machine, and for a reader.

Three renderings of one result, because the three audiences want different
things and collapsing them serves none of them well.

The **terminal** rendering is for the working loop -- run the build, run
`assess`, see whether the thing you changed did what you said.  It leads with
the failures and their traces, because a list of what passed is not why anybody
ran it.

The **JSON** rendering is the whole result including every measure, for
diffing, for archiving beside a build, and for anything that wants to compute
on it.

The **HTML** rendering is a standalone page: the placement table, what moved
since the baseline, and every expectation with its evidence.  Self-contained,
theme-aware, and safe to publish as an artifact -- which is how a build review
gets shared with somebody who is not going to run the command.
"""

from __future__ import annotations

import html
from dataclasses import asdict
from typing import Any

import orjson

from brightway_flows.assessment.baseline import BaselineComparison
from brightway_flows.assessment.evaluate import Assessment, ExpectationResult, Status

# ---------------------------------------------------------------------------
# Terminal
# ---------------------------------------------------------------------------

#: ANSI, applied only when the stream is a terminal.  `typer.echo` handles the
#: stripping, so the caller does not have to ask whether it is being piped.
_STATUS_COLOUR = {
    Status.MET: "green",
    Status.UNMET: "red",
    Status.UNRESOLVED: "yellow",
    Status.ERROR: "magenta",
}

_VERDICT_COLOUR = {
    "improved": "green",
    "regressed": "red",
    "now met": "green",
    "moved": "cyan",
    "new": "cyan",
    "gone": "yellow",
    "changed": "yellow",
}


def terminal_lines(
    assessment: Assessment,
    comparison: BaselineComparison | None = None,
    *,
    verbose: bool = False,
    style: Any = None,
) -> list[str]:
    """The report as lines, ready for `typer.echo`.

    *style* is `typer.style` or anything with its signature; passing `None`
    renders plain text, which is what a test wants to assert against.
    """
    paint = style or (lambda text, **_: text)
    lines: list[str] = []

    run = assessment.run
    lines.append(paint("BUILD", bold=True))
    lines.append(f"  database   {assessment.database}")
    lines.append(f"  pipeline   {run.pipeline_run_id or '(none)'}  {run.timestamp}")
    lines.append(f"  merge      {run.merge_run_id[:8] or '(none)'}  finished {run.merge_finished_at or '-'}")
    lines.append(f"  sources    {', '.join(run.sources) or '(none merged)'}")
    if run.max_flows:
        lines.append(paint(
            f"  bounded    --max-flows {run.max_flows}: counts describe a prefix of the "
            "base list, not the list",
            fg="yellow",
        ))
    for bounded in run.bounded_sources:
        lines.append(paint(
            f"  bounded    --max-rows {bounded}: merge counts describe a prefix "
            "of the source list, not the list",
            fg="yellow",
        ))
    lines.append("")

    lines.extend(_published_lines(assessment, paint))
    lines.extend(_factor_lines(assessment, paint))
    lines.extend(_placement_lines(assessment, paint))
    lines.extend(_expectation_lines(assessment, paint, verbose=verbose))
    if comparison is not None:
        lines.extend(_comparison_lines(comparison, paint))
    return lines


#: The placement columns, and the measure suffix behind each.  Short headings
#: because eight of them have to fit a terminal beside a list name.
_PLACEMENT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("rows", "rows"),
    ("prepared", "prepared"),
    ("algorithm", "algorithm"),
    ("manual_addition", "manual"),
    ("created", "created"),
    ("unmatched", "unplaced"),
    ("on_characterised_flow", "charact'd"),
    ("unit_mismatch", "unit x"),
)


def _placement_lines(assessment: Assessment, paint: Any) -> list[str]:
    """Where each source list lands: the headline table.

    The lists come from the run rather than from the measure keys.  A version
    string contains a dot -- `merge.ecoinvent-3.12.rows` -- so splitting a key
    on dots finds `ecoinvent-3` and drops both ecoinvent lists from the table,
    which is how this printed one row of three the first time it ran.
    """
    lists = [name for name in assessment.run.sources if f"merge.{name}.rows" in assessment.measures]
    if not lists:
        return []
    width = max(len(name) for name in lists) + 2
    lines = [
        paint("WHERE EACH LIST LANDS", bold=True),
        paint(
            "  " + "list".ljust(width)
            + "".join(label.rjust(11) for _, label in _PLACEMENT_COLUMNS)
            + "on existing".rjust(13),
            dim=True,
        ),
    ]
    for name in lists:
        cells = []
        for suffix, _ in _PLACEMENT_COLUMNS:
            measure = assessment.measures.get(f"merge.{name}.{suffix}")
            cells.append((f"{measure.value:,}" if measure else "-").rjust(11))
        total = assessment.measures.get(f"merge.{name}.rows")
        placed = assessment.measures.get(f"merge.{name}.on_existing_flow")
        share = (
            f"{100 * placed.value / total.value:.1f}%"
            if total and placed and total.value else "-"
        )
        lines.append("  " + name.ljust(width) + "".join(cells) + share.rjust(13))
    lines.append("")
    return lines


def _published_lines(assessment: Assessment, paint: Any) -> list[str]:
    """The shape of the list this build published."""
    wanted = (
        ("flows.total", "elementary flows"),
        ("flows.characterised", "of them carrying a factor"),
        ("flows.deprecated", "deprecated"),
        ("flows.deprecated_without_replacement", "deprecated with nowhere to send a consumer"),
        ("substances.total", "substances"),
        ("substances.without_payload", "substances with no published payload"),
    )
    found = [(assessment.measures[key], label) for key, label in wanted if key in assessment.measures]
    if not found:
        return []
    lines = [paint("WHAT IT PUBLISHED", bold=True)]
    lines.extend(f"  {measure.value:>12,}  {label}" for measure, label in found)
    lines.append("")
    return lines


def _factor_lines(assessment: Assessment, paint: Any) -> list[str]:
    """What the characterisation says, where there is one.

    Seven numbers out of the `factors.*` measures, and the choice is the point:
    the headline of this layer is the *agreement* between the implementations of
    one method, so that is what a reader sees without asking for a diff.  Absent entirely from a build nothing has characterised, rather
    than shown as zeros -- "nobody has asked yet" is a different statement from
    "characterised by nobody".

    The four per-implementation counts are EF 3.1's, named by that method's
    slug: a statistic about one method's own work carries it (`ef_jrc_…`), and
    only the run's totals -- `factors_published`, the difference counts -- do
    not.  A second registered method wants a section per method rather than
    another line here.
    """
    wanted = (
        ("factors.factors_published", "factors, over four implementations"),
        ("factors.ef_jrc_factors_published", "the JRC's"),
        ("factors.ef_ecoinvent_centre_factors_published", "the ecoinvent Centre's"),
        ("factors.ef_greendelta_factors_published", "GreenDelta's"),
        ("factors.ef_consensus_factors_published", "this list's"),
        ("factors.difference_shared", "triples more than one of them states"),
        ("factors.difference_identical", "of them identical, to the last digit"),
    )
    found = [
        (assessment.measures[key], label)
        for key, label in wanted
        if key in assessment.measures
    ]
    if not found:
        return []
    lines = [paint("WHAT IT CHARACTERISED", bold=True)]
    lines.extend(f"  {measure.value:>12,}  {label}" for measure, label in found)
    lines.append("")
    return lines


def _expectation_lines(assessment: Assessment, paint: Any, *, verbose: bool) -> list[str]:
    counts = assessment.counts
    if not assessment.results:
        return [
            paint("EXPECTATIONS", bold=True),
            "  none written yet. See expectations/README.md -- a pull request that "
            "fixes an issue adds one.",
            "",
        ]
    summary = "  ".join(
        paint(f"{counts[status.value]} {status.value}", fg=_STATUS_COLOUR[status])
        for status in Status
        if counts[status.value]
    )
    pending = sum(1 for r in assessment.results if r.expectation.pending)
    lines = [
        paint("EXPECTATIONS", bold=True),
        f"  {summary}" + (f"   ({pending} of them pending)" if pending else ""),
        "",
    ]

    shown = [
        result for result in assessment.results
        if verbose or result.status is not Status.MET
    ]
    for result in shown:
        lines.extend(_result_lines(result, paint))
    if not shown:
        lines.append(paint("  every expectation holds.", fg="green"))
        lines.append("")
    return lines


def _result_lines(result: ExpectationResult, paint: Any) -> list[str]:
    expectation = result.expectation
    tag = result.status.value.upper()
    if expectation.pending and result.status is not Status.MET:
        tag += " (pending)"
    lines = [
        "  "
        + paint(tag.ljust(18), fg=_STATUS_COLOUR[result.status], bold=True)
        + paint(expectation.label, bold=True)
        + f"  ({expectation.source_file})",
        f"      {expectation.title}",
    ]
    if result.message:
        lines.append(paint(f"      {result.message}", dim=True))
    for claim in result.claims:
        if claim.met:
            continue
        note = f"   [{claim.note}]" if claim.note else ""
        lines.append(
            f"      {claim.claim}: expected {_render(claim.expected)}, "
            f"got {_render(claim.actual)}{note}"
        )
    for row in result.evidence:
        lines.extend(_evidence_lines(row))
    lines.append("")
    return lines


def _evidence_lines(row: dict[str, Any]) -> list[str]:
    if "outcome" not in row:
        return [f"        {_render(row)}"]
    head = f"        {row.get('source_name', '')!r} {row.get('source_context', [])} -> {row.get('outcome', '')}"
    if row.get("reason"):
        head += f" ({row['reason']})"
    lines = [head]
    if row.get("target_name"):
        lines.append(
            f"          landed on {row['target_name']!r} in {row.get('target_context_display', '')} "
            f"[{row.get('target_unit', '')}]"
            + ("" if row.get("target_characterised") else ", which carries no factor")
        )
    for candidate in row.get("scored_candidates", ()):
        lines.append(
            f"          candidate {candidate.get('score')}  {candidate.get('unit', '')}  "
            f"{' / '.join(candidate.get('context', []))}  {candidate.get('elementary_flow_id', '')[:8]}"
        )
    return lines


def _comparison_lines(comparison: BaselineComparison, paint: Any) -> list[str]:
    lines = [paint("SINCE THE BASELINE", bold=True)]
    if comparison.incomparable:
        lines.append(paint(f"  {comparison.incomparable}", fg="yellow"))
        lines.append("")
        return lines

    recorded = comparison.baseline.recorded
    lines.append(paint(
        f"  recorded {recorded.get('timestamp', '?')} from merge "
        f"{str(recorded.get('merge_run_id', ''))[:8]}",
        dim=True,
    ))
    for change in comparison.statuses:
        lines.append(
            "  "
            + paint(change.verdict.ljust(12), fg=_VERDICT_COLOUR.get(change.verdict, "white"))
            + f"{change.expectation_id}: {change.before} -> {change.after}"
        )
    if not comparison.measures:
        lines.append("  no measure moved.")
        lines.append("")
        return lines

    width = max(len(delta.key) for delta in comparison.measures) + 2
    for delta in sorted(comparison.measures, key=_delta_order):
        before = "-" if delta.before is None else f"{delta.before:,}"
        after = "-" if delta.after is None else f"{delta.after:,}"
        lines.append(
            "  " + delta.key.ljust(width)
            + f"{before:>12} -> {after:<12} "
            + paint(delta.verdict, fg=_VERDICT_COLOUR.get(delta.verdict, "white"))
        )
    lines.append("")
    return lines


def _delta_order(delta: Any) -> tuple[int, str]:
    """Regressions first, then improvements, then everything else."""
    rank = {"regressed": 0, "improved": 1, "gone": 2, "new": 3}.get(delta.verdict, 4)
    return (rank, delta.key)


def _render(value: Any) -> str:
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_render(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {_render(v)}" for k, v in value.items()) + "}"
    return str(value)


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def as_json(
    assessment: Assessment, comparison: BaselineComparison | None = None
) -> bytes:
    """The whole result, indented, newline-terminated, stable in key order.

    Stable because it is meant to be committed beside a build or diffed against
    the last one, and a JSON blob whose keys move is a diff nobody reads.
    """
    payload: dict[str, Any] = {
        "database": assessment.database,
        "run": asdict(assessment.run),
        "counts": assessment.counts,
        "measures": {
            key: {
                "value": measure.value,
                "title": measure.title,
                "direction": measure.direction.value,
                "group": measure.group,
            }
            for key, measure in sorted(assessment.measures.items())
        },
        "expectations": [
            {
                "id": result.expectation.id,
                "issue": result.expectation.issue,
                "title": result.expectation.title,
                "file": result.expectation.source_file,
                "pending": result.expectation.pending,
                "subject": {"kind": result.expectation.kind, **result.expectation.selector},
                "expect": result.expectation.claims,
                "status": result.status.value,
                "matched_rows": result.matched_rows,
                "message": result.message,
                "claims": [asdict(claim) for claim in result.claims],
                "evidence": list(result.evidence),
            }
            for result in assessment.results
        ],
    }
    if comparison is not None:
        payload["since_baseline"] = {
            "incomparable": comparison.incomparable,
            "recorded": comparison.baseline.recorded,
            "measures": [
                {**asdict(delta), "direction": delta.direction.value, "verdict": delta.verdict}
                for delta in comparison.measures
            ],
            "expectations": [
                {**asdict(change), "verdict": change.verdict} for change in comparison.statuses
            ],
        }
    return orjson.dumps(
        payload, option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE | orjson.OPT_SORT_KEYS
    )


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_CSS = """
:root {
  --ground:#f6f7f5; --surface:#fff; --surface-2:#eef1ee; --ink:#101a19; --ink-2:#3a4a47;
  --muted:#5f6d6a; --hair:#dde3e0; --hair-strong:#c3ccc8; --accent:#00695f;
  --ok:#276b3a; --ok-soft:#e2efe5; --warn:#8a5b00; --warn-soft:#f5ecda;
  --crit:#a32b25; --crit-soft:#f7e6e4; --new:#4a3a97; --new-soft:#eae7f6;
  --serif:"Charter","Iowan Old Style",Palatino,Georgia,serif;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --ground:#0f1615; --surface:#151d1c; --surface-2:#1c2625; --ink:#e4ebe8; --ink-2:#bcc8c5;
  --muted:#91a09d; --hair:#243230; --hair-strong:#35443f; --accent:#4fc2b2;
  --ok:#63b97c; --ok-soft:#16281c; --warn:#d3a054; --warn-soft:#2b2113;
  --crit:#e08078; --crit-soft:#2e1917; --new:#a99bea; --new-soft:#1f1c33;
} }
:root[data-theme="dark"] {
  --ground:#0f1615; --surface:#151d1c; --surface-2:#1c2625; --ink:#e4ebe8; --ink-2:#bcc8c5;
  --muted:#91a09d; --hair:#243230; --hair-strong:#35443f; --accent:#4fc2b2;
  --ok:#63b97c; --ok-soft:#16281c; --warn:#d3a054; --warn-soft:#2b2113;
  --crit:#e08078; --crit-soft:#2e1917; --new:#a99bea; --new-soft:#1f1c33;
}
* { box-sizing:border-box; }
body { background:var(--ground); color:var(--ink); font-family:var(--sans); font-size:16px;
       line-height:1.6; margin:0; padding:0 20px 96px; -webkit-font-smoothing:antialiased; }
.wrap { max-width:1040px; margin:0 auto; }
.masthead { padding:56px 0 28px; border-bottom:2px solid var(--ink); }
.eyebrow { font-family:var(--mono); font-size:12px; letter-spacing:.14em; text-transform:uppercase;
           color:var(--accent); margin:0 0 14px; }
h1 { font-family:var(--serif); font-size:clamp(32px,5vw,48px); line-height:1.08; font-weight:600;
     margin:0 0 16px; }
.standfirst { font-size:18px; color:var(--ink-2); margin:0; max-width:62ch; }
.runline { display:flex; flex-wrap:wrap; gap:6px 28px; margin-top:24px; font-family:var(--mono);
           font-size:12.5px; color:var(--muted); }
.runline b { color:var(--ink-2); font-weight:600; }
.tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:1px;
         background:var(--hair); border:1px solid var(--hair); margin:32px 0 0; }
.tile { background:var(--surface); padding:18px; }
.tile .n { font-family:var(--mono); font-size:26px; font-weight:600; display:block;
           font-variant-numeric:tabular-nums; }
.tile .k { font-size:12.5px; color:var(--muted); margin-top:5px; display:block; }
section { margin-top:60px; }
h2 { font-family:var(--serif); font-size:26px; font-weight:600; margin:0 0 4px; }
.sub { color:var(--muted); font-size:14.5px; margin:0 0 24px; max-width:66ch; }
.scroll { overflow-x:auto; margin:18px 0 8px; border:1px solid var(--hair); background:var(--surface); }
table { border-collapse:collapse; width:100%; font-size:14px; min-width:560px; }
th,td { text-align:right; padding:9px 14px; border-bottom:1px solid var(--hair);
        font-variant-numeric:tabular-nums; white-space:nowrap; }
th:first-child, td:first-child { text-align:left; white-space:normal; }
thead th { font-size:11.5px; letter-spacing:.07em; text-transform:uppercase; color:var(--muted);
           font-weight:600; border-bottom:1px solid var(--hair-strong); background:var(--surface-2); }
tbody tr:last-child td { border-bottom:0; }
.caption { font-size:12.5px; color:var(--muted); margin:8px 0 0; }
.issues { display:flex; flex-direction:column; gap:1px; background:var(--hair);
          border:1px solid var(--hair); }
.issue { background:var(--surface); padding:18px 20px; border-left:3px solid var(--stripe,var(--hair-strong));
         display:grid; grid-template-columns:96px 1fr; gap:4px 18px; align-items:baseline; }
.issue .id { font-family:var(--mono); font-size:13px; font-weight:600; color:var(--stripe,var(--ink)); }
.issue .t { font-weight:650; font-size:15px; margin:0 0 6px; }
.issue .ev { margin:0; font-size:14.5px; color:var(--ink-2); }
.issue .meta { grid-column:2; font-size:12.5px; color:var(--muted); margin-top:9px;
               font-family:var(--mono); }
.g-met { --stripe:var(--ok); } .g-unmet { --stripe:var(--crit); }
.g-unresolved { --stripe:var(--warn); } .g-error { --stripe:var(--new); }
.pill { display:inline-block; font-family:var(--mono); font-size:11px; letter-spacing:.05em;
        text-transform:uppercase; padding:2px 8px; border-radius:999px; margin-bottom:8px;
        font-weight:600; }
.p-met { background:var(--ok-soft); color:var(--ok); }
.p-unmet { background:var(--crit-soft); color:var(--crit); }
.p-unresolved { background:var(--warn-soft); color:var(--warn); }
.p-error { background:var(--new-soft); color:var(--new); }
pre { font-family:var(--mono); font-size:12.5px; background:var(--surface-2); padding:12px 14px;
      overflow-x:auto; margin:10px 0 0; border-radius:3px; color:var(--ink-2); }
.improved { color:var(--ok); font-weight:600; } .regressed { color:var(--crit); font-weight:600; }
.moved, .new, .gone { color:var(--muted); }
footer { margin-top:64px; padding-top:22px; border-top:1px solid var(--hair-strong);
         font-size:13.5px; color:var(--muted); max-width:72ch; }
@media (max-width:620px) { .issue { grid-template-columns:1fr; } .issue .meta { grid-column:1; } }
"""


def as_html(assessment: Assessment, comparison: BaselineComparison | None = None) -> str:
    """A standalone page: no external requests, readable in either theme."""
    run = assessment.run
    counts = assessment.counts
    esc = html.escape

    parts = [
        "<title>Build assessment</title>",
        f"<style>{_CSS}</style>",
        '<div class="wrap">',
        '<header class="masthead">',
        f'<p class="eyebrow">Build assessment · {esc(run.timestamp[:10] or "unknown date")}</p>',
        "<h1>What this build did, and what it was supposed to do</h1>",
        '<p class="standfirst">Every expectation the repository states about the pipeline, '
        "graded against this build, with the merge's own trace behind each failure — and "
        "every measure that has moved since the last recorded build.</p>",
        '<div class="runline">',
        f"<span><b>pipeline</b> {esc(run.pipeline_run_id or '-')}</span>",
        f"<span><b>merge</b> {esc(run.merge_run_id[:8] or '-')} · finished {esc(run.merge_finished_at or '-')}</span>",
        f"<span><b>sources</b> {esc(', '.join(run.sources) or 'none')}</span>",
        "</div>",
        '<div class="tiles">',
    ]
    for status in Status:
        if counts[status.value]:
            parts.append(
                f'<div class="tile"><span class="n">{counts[status.value]}</span>'
                f'<span class="k">expectations {esc(status.value)}</span></div>'
            )
    for key, label in (
        ("flows.total", "elementary flows"),
        ("substances.total", "substances"),
        ("flows.characterised", "flows carrying a factor"),
    ):
        if measure := assessment.measures.get(key):
            parts.append(
                f'<div class="tile"><span class="n">{measure.value:,}</span>'
                f'<span class="k">{esc(label)}</span></div>'
            )
    parts.extend(["</div>", "</header>"])

    parts.extend(_html_placement(assessment))
    parts.extend(_html_expectations(assessment))
    if comparison is not None:
        parts.extend(_html_comparison(comparison))
    parts.extend([
        "<footer>Written by <code>brightway-flows assess</code>. Expectations live in "
        "<code>expectations/</code> at the repository root, one file per issue; the baseline "
        "the movement is measured against is <code>expectations/baseline.json</code>.</footer>",
        "</div>",
    ])
    return "\n".join(parts)


def _html_placement(assessment: Assessment) -> list[str]:
    lists = [name for name in assessment.run.sources if f"merge.{name}.rows" in assessment.measures]
    if not lists:
        return []
    rows = (
        ("rows", "Source rows"),
        ("prepared", "Prepared correspondence"),
        ("algorithm", "Matched by algorithm"),
        ("manual_addition", "Manual addition"),
        ("created", "New flow created"),
        ("unmatched", "Reached nothing"),
        ("on_existing_flow", "Landed on an existing flow"),
        ("on_characterised_flow", "Landed on a characterised flow"),
        ("distinct_targets", "Distinct consensus flows reached"),
        ("context_inconsistent", "Context flagged inconsistent"),
        ("unit_mismatch", "Unit mismatch, unconverted"),
    )
    out = [
        "<section><h2>Where each list lands</h2>",
        '<p class="sub">One row per source flow per list, from <code>merge_outcomes</code>.</p>',
        '<div class="scroll"><table><thead><tr><th>&nbsp;</th>',
    ]
    out.extend(f"<th>{html.escape(name)}</th>" for name in lists)
    out.append("</tr></thead><tbody>")
    for suffix, label in rows:
        cells = []
        for name in lists:
            measure = assessment.measures.get(f"merge.{name}.{suffix}")
            cells.append(f"<td>{measure.value:,}</td>" if measure else "<td>–</td>")
        out.append(f"<tr><td>{html.escape(label)}</td>{''.join(cells)}</tr>")
    out.append("</tbody></table></div></section>")
    return out


def _html_expectations(assessment: Assessment) -> list[str]:
    if not assessment.results:
        return [
            "<section><h2>Expectations</h2>",
            '<p class="sub">None written yet. A pull request that fixes an issue adds a file '
            "to <code>expectations/</code> stating what should now be true.</p></section>",
        ]
    esc = html.escape
    out = [
        "<section><h2>Expectations</h2>",
        '<p class="sub">What the repository says should be true of the output, checked against '
        "this build. Unresolved means the selector matched nothing — the subject has been "
        "renamed or removed upstream, so the expectation needs rewriting rather than the "
        "pipeline needing fixing.</p>",
        '<div class="issues">',
    ]
    order = {Status.UNMET: 0, Status.ERROR: 1, Status.UNRESOLVED: 2, Status.MET: 3}
    for result in sorted(assessment.results, key=lambda r: (order[r.status], r.expectation.id)):
        expectation = result.expectation
        status = result.status.value
        pill = f'<span class="pill p-{status}">{esc(status)}</span>'
        if expectation.pending and result.status is not Status.MET:
            pill += ' <span class="pill p-unresolved">pending</span>'
        identifier = f"#{expectation.issue}" if expectation.issue else expectation.id
        body = [
            f'<div class="issue g-{status}"><span class="id">{esc(identifier)}</span><div>',
            pill,
            f'<p class="t">{esc(expectation.title)}</p>',
        ]
        if expectation.comment:
            body.append(f'<p class="ev">{esc(expectation.comment)}</p>')
        if result.message:
            body.append(f'<p class="ev">{esc(result.message)}</p>')
        failed = [claim for claim in result.claims if not claim.met]
        if failed:
            body.append("<pre>" + esc("\n".join(
                f"{claim.claim}: expected {_render(claim.expected)}, got {_render(claim.actual)}"
                + (f"   [{claim.note}]" if claim.note else "")
                for claim in failed
            )) + "</pre>")
        if result.evidence:
            body.append("<pre>" + esc("\n".join(
                line.strip() for row in result.evidence for line in _evidence_lines(row)
            )) + "</pre>")
        body.append(
            f'<p class="meta">{esc(expectation.source_file)} · '
            f"{result.matched_rows} row(s) matched</p></div></div>"
        )
        out.extend(body)
    out.append("</div></section>")
    return out


def _html_comparison(comparison: BaselineComparison) -> list[str]:
    esc = html.escape
    out = ["<section><h2>Since the baseline</h2>"]
    if comparison.incomparable:
        out.append(f'<p class="sub">{esc(comparison.incomparable)}</p></section>')
        return out
    recorded = comparison.baseline.recorded
    out.append(
        f'<p class="sub">Against the build recorded {esc(str(recorded.get("timestamp", "?")))}. '
        "Only measures that moved are listed.</p>"
    )
    if comparison.statuses:
        out.append('<div class="scroll"><table><thead><tr><th>Expectation</th><th>Was</th>'
                   "<th>Now</th></tr></thead><tbody>")
        for change in comparison.statuses:
            out.append(
                f"<tr><td>{esc(change.title)}</td><td>{esc(change.before)}</td>"
                f'<td class="{esc(change.verdict.replace(" ", "-"))}">{esc(change.after)}</td></tr>'
            )
        out.append("</tbody></table></div>")
    if comparison.measures:
        out.append('<div class="scroll"><table><thead><tr><th>Measure</th><th>Was</th>'
                   "<th>Now</th><th>Change</th></tr></thead><tbody>")
        for delta in sorted(comparison.measures, key=_delta_order):
            before = "–" if delta.before is None else f"{delta.before:,}"
            after = "–" if delta.after is None else f"{delta.after:,}"
            out.append(
                f"<tr><td>{esc(delta.title)}<br><small>{esc(delta.key)}</small></td>"
                f"<td>{before}</td><td>{after}</td>"
                f'<td class="{esc(delta.verdict)}">{esc(delta.verdict)}</td></tr>'
            )
        out.append("</tbody></table></div>")
    elif not comparison.statuses:
        out.append('<p class="sub">Nothing moved.</p>')
    out.append("</section>")
    return out
