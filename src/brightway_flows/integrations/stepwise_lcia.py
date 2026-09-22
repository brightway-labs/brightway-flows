"""Reading Stepwise 2006's characterisation factors.

The flows and the factors come out of one file, and :mod:`stepwise` already
walks it: a category's factor rows are how its flows are found, so the reading
is written and tested there.  What that module deliberately does not do is
*write* the numbers -- a list's factors reach the build through the manifest's
``lcia`` block and ``characterise``, never as a payload on a flow record, which
is the route #207 took and #346 rules out.  Ranking a merge on how many factors a
row carries would let characterisation decide where a flow lands.

This is the other half: the same 9,698 rows, as :class:`StatedFactor` records
against the flow uuids :mod:`stepwise` mints.

**The factor's unit is not always the flow's, and 307 rows turn on it.**  A
factor row states the unit the *factor* is per, and the substance blocks state
the unit the flow is *inventoried* in.  Usually they agree.  Where they do not,
the number has to be rescaled or it is published per a unit nobody holds:

======================  ====================  ======  ==========
factor stated per       flow inventoried in    rows    rescaled by
======================  ====================  ======  ==========
``g``                   ``kg``                   263        1,000
``Bq``                  ``kBq``                   36        1,000
``kg``                  ``ton``                    6        1,000
``m2a``                 ``ha a``                   2       10,000
======================  ====================  ======  ==========

The radionuclides are the case that shows why: Stepwise inventories them in
kilobecquerels and states all 36 of ``Ionizing radiation``'s factors per
becquerel, so a factor carried across unconverted is a thousandfold out and
looks entirely ordinary.

That the row's unit means something is #164's finding rather than this module's
guess: :mod:`stepwise` takes a flow's unit from the substance blocks precisely
because "the radionuclides are inventoried in ``kBq`` and the 36 factor rows of
``Ionizing radiation`` are stated per ``Bq``".  The same fact read from the other
end is that a factor published against the flow has to be rescaled.  The second
piece of evidence is the shape of the disagreement: all 307 are a pure scale
inside one quantity kind, in four clean pairs, and none crosses from a mass to a
volume or an activity.  A unit written decoratively would not land that way.

Because each is a scale, ``units.json`` is what does the conversion
(:func:`unit_table_factor`) rather than a table written here -- and a pair the
file cannot convert raises rather than being published unscaled.  Each rescaled
row keeps the publisher's own unit in ``characterization_factor_flow_unit``,
which is the key the record's ``extra`` bag exists for (rule 3), so what was read
is still readable beside what was published.

One number in #346's own text moves because of this: it quotes methane's
respiratory organics factor as ``3.8e-05``, which is the row as written, per
gram.  Per kilogram -- the unit the flow is published in -- it is ``0.038``.

**Nothing is dropped.**  The 69 factors the method states as exactly zero are
published: "this method looked at this substance and says it does not
contribute" is a statement, and a table that dropped it reads the same as one
that never assessed the substance (#47, #48).  So are the three
``as CO2e (GWP aggr timing)`` rows at 1, 1 and -1, which are the method's own
numbers about flows #164 files under ``Impact Assessment Score``; a consumer
that applies them to an amount which is already a result counts it twice, and
that is a fact about those flows rather than a reason to withhold what the file
says.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.lcia.records import (
    StatedCategory,
    StatedFactor,
    stated_category,
)
from brightway_flows.domain.units import unit_table_factor
from brightway_flows.integrations.stepwise import (
    _BLOCK_BY_COMPARTMENT,
    _blocks,
    _flow_uuid,
    _method_block,
    _method_version,
    _named,
    _substances,
    download,
    method_revision,
    STEPWISE_METHOD_NAME,
)
from brightway_flows.sources import SourceList

logger = structlog.get_logger(__name__)

#: The shape :func:`fetch` writes.  Its own, not ecoinvent's: the two files hold
#: the same records and neither is a version of the other, so a reader that
#: opened one expecting the other should fail on the version rather than on a
#: missing key.
FACTORS_SCHEMA_VERSION = 1

#: The key a rescaled row keeps its publisher's unit under.  Named by the
#: publisher rather than by us -- it is what their row said -- and the one key
#: in the wild that :attr:`StatedFactor.extra` carries.
FLOW_UNIT_KEY = "characterization_factor_flow_unit"


class StepwiseLciaError(ValueError):
    """The export does not say what this module needs to read it."""


def _category_records(blocks: list[Any]) -> dict[str, StatedCategory]:
    """Every category the export declares, as a record.

    ``name`` is the category's own name and not the method's, because that is
    what the crosswalk matches on: `LCIAMethodDefinition.definition_for` looks a
    factor's category up by ``name`` against the ``stated`` block, so a record
    naming the method here would file every row under a category the method file
    does not declare.

    ``methodology`` is ``None`` rather than the method's name: the export states
    none, and a record that filled it in would publish a value the file does not
    have.  So is ``impact_category``, the publisher's own grouping, which this
    export has no column for.
    """
    out: dict[str, StatedCategory] = {}
    for block in _named(blocks, "ImpactCategory"):
        name = str(block.parsed.get("name") or "").strip()
        if not name:
            continue
        out[name] = stated_category(
            uuid=None,
            name=name,
            methodology=None,
            reference_unit=str(block.parsed.get("unit") or "").strip() or None,
        )
    return out


def _rescale(amount: float, *, factor_unit: str, flow_unit: str, name: str) -> float:
    """*amount*, stated per *factor_unit*, restated per *flow_unit*.

    The ratio is the flow's unit expressed in the factor's -- a factor per gram
    is a thousand times as much per kilogram -- which is
    ``unit_table_factor(flow_unit, factor_unit)`` and not its inverse.

    :raises StepwiseLciaError: where ``units.json`` cannot convert the pair.
        Publishing it unscaled would state a number per a unit nobody asked for,
        and silently, since a factor carries no unit of its own once published.
    """
    ratio = unit_table_factor(flow_unit, factor_unit)
    if ratio is None:
        raise StepwiseLciaError(
            f"{name!r} states a factor per {factor_unit!r} and the flow is "
            f"inventoried in {flow_unit!r}, which `units.json` does not convert. "
            "The number cannot be published against that flow without inventing "
            "the conversion."
        )
    return amount * ratio


def read_factors(blocks: list[Any]) -> tuple[list[StatedFactor], dict[str, int]]:
    """Every factor the export states, against the flow uuids `stepwise` mints.

    Returns the records and the counts the run's log and the written file both
    report: how many rows were read, how many were rescaled, and how many the
    method states as zero.
    """
    substances = _substances(blocks)
    categories = _category_records(blocks)
    factors: list[StatedFactor] = []
    counts: dict[str, int] = defaultdict(int)

    for block in _named(blocks, "ImpactCategory"):
        category_name = str(block.parsed.get("name") or "").strip()
        category = categories.get(category_name)
        if category is None:
            continue
        for row in block.parsed.get("cfs", []):
            name = str(row.get("name") or "").strip()
            context = [str(part) for part in (row.get("context") or [])]
            if not name or len(context) != 2:
                counts["rows_without_a_flow"] += 1
                continue
            heading = _BLOCK_BY_COMPARTMENT.get(context[0])
            substance = substances.get((heading, name)) if heading else None
            if substance is None:
                # `stepwise.flows_from_blocks` emits no flow for these, so there
                # is nothing for the factor to name.  It counts them too.
                counts["rows_without_a_substance_block"] += 1
                continue
            flow_unit = str(substance.get("unit") or "").strip()
            factor_unit = str(row.get("unit") or "").strip()
            amount = float(row.get("factor") or 0.0)
            extra: dict[str, Any] = {}
            if factor_unit and flow_unit and factor_unit != flow_unit:
                amount = _rescale(
                    amount, factor_unit=factor_unit, flow_unit=flow_unit, name=name
                )
                extra[FLOW_UNIT_KEY] = factor_unit
                counts["factors_rescaled"] += 1
            counts["factors"] += 1
            if amount == 0.0:
                counts["factors_stated_zero"] += 1
            factors.append(
                StatedFactor(
                    category=category,
                    flow_uuid=_flow_uuid(name, context[0], context[1], flow_unit),
                    amount=amount,
                    extra=extra,
                )
            )
    counts["flows"] = len({factor.flow_uuid for factor in factors})
    counts["categories"] = len(categories)
    return factors, dict(counts)


def _payload(
    *,
    source: SourceList,
    csv_path: Path,
    factors: list[StatedFactor],
    blocks: list[Any],
    counts: dict[str, int],
) -> dict[str, Any]:
    """What the file holds: the records' own shape, not a flow record's."""
    per_category: dict[str, list[StatedFactor]] = defaultdict(list)
    for factor in factors:
        per_category[factor.category.name or ""].append(factor)
    categories = _category_records(blocks)
    return {
        "schema_version": FACTORS_SCHEMA_VERSION,
        "source": source.key,
        "list_version": source.list_version,
        "export": csv_path.name,
        "methods": [
            {
                "method": STEPWISE_METHOD_NAME,
                "categories": [
                    {
                        "category": name,
                        "unit": category.reference_unit,
                        "factor_count": len(per_category[name]),
                        "zero_count": sum(
                            1 for row in per_category[name] if row.amount == 0.0
                        ),
                    }
                    for name, category in sorted(categories.items())
                ],
                "factor_count": counts.get("factors", 0),
                "flow_count": counts.get("flows", 0),
                "rescaled_count": counts.get("factors_rescaled", 0),
                "factors": [
                    {
                        "flow_uuid": factor.flow_uuid,
                        "category": factor.category.name,
                        "amount": factor.amount,
                        **(
                            {FLOW_UNIT_KEY: factor.extra[FLOW_UNIT_KEY]}
                            if FLOW_UNIT_KEY in factor.extra
                            else {}
                        ),
                    }
                    for factor in factors
                ],
            }
        ],
    }


def fetch(source: SourceList, *, force: bool = False) -> Path:
    """The LCIA adapter for Stepwise 2006: the export's factors, as a file.

    *force* re-downloads the export.  The parse costs one pass over a 1.1 MB
    text file either way, so there is nothing to skip on a second run.

    The method and its version are checked exactly as ``stepwise.fetch`` checks
    them, and for the same reason: an export that says it is a different release
    is a file to register rather than one to read under this list's key.
    """
    from brightway_flows.filesystem import stepwise_csv_path

    assert source.lcia is not None
    csv_path = download(stepwise_csv_path(source.list_version), force=force)
    blocks = _blocks(csv_path)
    method = _method_block(blocks)
    declared = _method_version(method)
    expected = method_revision(source.list_version)
    name = str(method.get("Name") or "").strip()
    if name != STEPWISE_METHOD_NAME or declared != expected:
        raise StepwiseLciaError(
            f"{csv_path} is method {name!r} version {declared!r}; "
            f"{source.key} is {STEPWISE_METHOD_NAME!r} version {expected!r}. "
            "Register the other release rather than reading it under this "
            "list's key."
        )

    factors, counts = read_factors(blocks)
    path = source.lcia.factors_path
    path.write_bytes(
        orjson.dumps(
            _payload(
                source=source,
                csv_path=csv_path,
                factors=factors,
                blocks=blocks,
                counts=counts,
            ),
            option=orjson.OPT_INDENT_2,
        )
    )
    logger.info(
        "stepwise_factors_written",
        path=str(path),
        categories=counts.get("categories", 0),
        factors=counts.get("factors", 0),
        flows=counts.get("flows", 0),
        rescaled=counts.get("factors_rescaled", 0),
        stated_zero=counts.get("factors_stated_zero", 0),
    )
    return path


def load_factors(path: Path) -> dict[str, list[StatedFactor]]:
    """What :func:`fetch` wrote, back as records, keyed by method.

    The read side of the file, here rather than in the pass that matches these
    onto consensus flows, because the shape belongs to whoever writes it.
    """
    payload = orjson.loads(path.read_bytes())
    version = payload.get("schema_version")
    if version != FACTORS_SCHEMA_VERSION:
        raise StepwiseLciaError(
            f"{path.name} states schema_version {version!r}; this reads "
            f"{FACTORS_SCHEMA_VERSION}. Re-run the fetch."
        )
    out: dict[str, list[StatedFactor]] = defaultdict(list)
    for method in payload.get("methods") or ():
        name = str(method.get("method") or "")
        categories = {
            str(row.get("category") or ""): stated_category(
                uuid=None,
                name=str(row.get("category") or ""),
                methodology=None,
                reference_unit=row.get("unit"),
            )
            for row in method.get("categories") or ()
        }
        for row in method.get("factors") or ():
            extra = (
                {FLOW_UNIT_KEY: row[FLOW_UNIT_KEY]} if FLOW_UNIT_KEY in row else {}
            )
            out[name].append(
                StatedFactor(
                    category=categories[str(row["category"])],
                    flow_uuid=str(row["flow_uuid"]),
                    amount=float(row["amount"]),
                    extra=extra,
                )
            )
    return dict(out)
