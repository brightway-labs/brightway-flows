"""A list's property statements file, and attaching it to the list's flows.

`<list>-property-statements.json` is where a curator writes down what a source
list says about its own flows that no vendor file states in a form a parser
reads: that BAFU's hard coal is 18.01 MJ per kilogram (ecoinvent's workbook
figure, borrowed and said to be), that every list's uranium is 560,000 MJ of
fission energy per kilogram, that AGRIBALYSE's cooling water is 0.000976 cubic
metres per kilogram.  Each entry is one
:class:`~brightway_flows.domain.property_statements.PropertyStatement` plus the
releases it was checked against, and the merge derives the mapping's
`qudt:conversionMultiplier` from it (`merge.conversions`).  Until #407 the same
numbers were typed as bare `conversion_factor`s on the override rows, four
times for four lists, with no unit, no basis and no provenance.

The file also carries two kinds of ruling that are about quantities rather than
about one flow's value:

``conversion_rules``
    Which statement quantity converts onto a target of another.  Stepwise
    2006's method states gross calorific values, so its rows convert onto EF's
    net-calorific-value flows by the gross value; the rule says so with its
    reason, and the mapping publishes which quantity it used.

``reference_quantities``
    What a named flow's unit measures where the vendor's own flow property is
    wrong or silent.  EF 3.1 labels its `Uranium` flow's megajoule a net
    calorific value; it is fission energy, and nothing converts a heat of
    combustion onto it.

Beside :mod:`brightway_flows.match_overrides` and :mod:`brightway_flows.manual_fixes`,
the two other per-list rulings `sources.py` applies, and following the override
module's vintage rule: a value is a measurement, a measurement has a release it
was read from, and a release nobody has checked is refused rather than given
the default (#162).

The loader takes a path, so it is not cached (rule 13): the merge loads a
list's file once per run, and a test hands it a fixture.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.property_statements import (
    ConversionRule,
    PropertyStatement,
    StatementOrigin,
    factor_between,
    vendor_statement,
)
from brightway_flows.domain.quantities import (
    CALORIFIC_VALUE,
    load_quantities,
    quantity,
    quantity_for_ilcd_flow_property,
)
from brightway_flows.domain.units import unit_row_for
from brightway_flows.filesystem import FLOW_PROPERTIES_FILEPATH
from brightway_flows.manual_fixes import UNIT_CONVERSION_KEY
from brightway_flows.simapro_names import energy_stated_in_name

logger = structlog.get_logger(__name__)

#: The files this module reads, as `domain/rulings.py` registers them.
STATEMENTS_FILE_PATTERN = "*-property-statements.json"

#: This file's own format version, checked where the file is read.  Module-local
#: and so named because `SCHEMA_VERSION` unqualified is the published list's.
DECISIONS_SCHEMA_VERSION = 1

_ATTRIBUTED_TO = "brightway-flows"
_ORIGINS = {origin.value for origin in StatementOrigin}


@dataclass(frozen=True)
class PropertyStatements:
    """One list's file, resolved for one release.

    *statements* is keyed by source uuid, a tuple per flow because a flow can
    carry several -- a net and a gross calorific value -- and
    :func:`~brightway_flows.domain.property_statements.choose_statement` is
    what picks between them.
    """

    statements: dict[str, tuple[PropertyStatement, ...]] = field(default_factory=dict)
    rules: tuple[ConversionRule, ...] = ()
    #: flow uuid -> quantity slug, for flows the file rules a reference
    #: quantity for.  The base list's file is the one that uses it.
    reference_quantities: dict[str, str] = field(default_factory=dict)
    #: flow uuid -> quantity slug, for flows whose unlabelled energy -- the
    #: method's factor, the number in the name -- the file rules to be that
    #: quantity rather than a heat of combustion.  The uranium rows.
    energy_quantities: dict[str, str] = field(default_factory=dict)
    #: flow uuid -> the quantities the vendor's own file states for this
    #: release, by an entry's `stated_by_vendor_in`, so that the entry yields
    #: nothing here and the load checks the vendor did state it.
    expected_from_vendor: dict[str, frozenset[str]] = field(default_factory=dict)
    path: Path | None = None

    @property
    def filename(self) -> str:
        return self.path.name if self.path is not None else ""


def _text(entry: dict[str, Any], key: str, *, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} has no {key!r}.")
    return value.strip()


def _releases(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _kind_of(unit: str) -> str:
    row = unit_row_for(unit)
    if row is None:
        return ""
    return str(row.get("quantity_kind_iri") or "")


def _check_units(
    *, quantity_slug: str, unit: str, per_unit: str, where: str
) -> None:
    """Refuse a statement whose units cannot carry its quantity.

    :raises ValueError: if either unit is unknown to `units.json`, if `unit`
        is not of the quantity's kind -- a net calorific value in kilograms is
        a typo -- or if `unit` and `per_unit` are of one kind, in which case
        the number is a unit-table fact with a second home, which is the
        refusal `match_overrides._validate_conversion` makes for the same
        reason.
    """
    unit_kind = _kind_of(unit)
    per_kind = _kind_of(per_unit)
    if not unit_kind:
        raise ValueError(f"{where} states a unit {unit!r} that units.json does not know.")
    if not per_kind:
        raise ValueError(
            f"{where} states a per-unit {per_unit!r} that units.json does not know."
        )
    wanted = quantity(quantity_slug).quantity_kind_iri
    if unit_kind != wanted:
        raise ValueError(
            f"{where} states {quantity_slug!r} in {unit!r}, which measures "
            f"{unit_kind.rsplit('/', 1)[-1]}, not "
            f"{wanted.rsplit('/', 1)[-1]}."
        )
    if unit_kind == per_kind:
        raise ValueError(
            f"{where} states {unit!r} per {per_unit!r}, two units of one "
            f"quantity kind. That is what units.json converts, and a second "
            f"copy of a fact that has a home is one that can disagree with it."
        )


def _value(raw: Any, *, where: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{where} has a non-numeric 'value'.")
    if not raw > 0:
        raise ValueError(f"{where} states a value of {raw}, which converts nothing.")
    return float(raw)


def _statement_from(
    entry: dict[str, Any],
    *,
    release: str,
    index: int,
    path: Path,
    generated_by: str,
) -> PropertyStatement | None:
    """One entry's statement for *release*.

    ``None`` for a release the entry names in `stated_by_vendor_in`: the
    vendor's own file states the quantity for that release, the curated number
    is for the releases that do not (ecoinvent 3.8 states no heating value on
    its crude oil; 3.9.1 onward do), and the load checks the vendor did.

    :raises ValueError: for a malformed entry, and for a release the entry was
        checked against in neither `checked_against`, `by_release` nor
        `stated_by_vendor_in`.
    """
    where = f"Statement {index} in {path.name}"
    source_uuid = _text(entry, "source_uuid", where=where)
    quantity_slug = _text(entry, "quantity", where=where)
    if quantity_slug not in load_quantities():
        raise ValueError(
            f"{where} names quantity {quantity_slug!r}, which quantities.json "
            f"does not have. Known: {', '.join(sorted(load_quantities()))}."
        )
    unit = _text(entry, "unit", where=where)
    per_unit = _text(entry, "per_unit", where=where)
    value = _value(entry.get("value"), where=where)
    _check_units(quantity_slug=quantity_slug, unit=unit, per_unit=per_unit, where=where)
    comment = _text(entry, "comment", where=where)
    origin = str(entry.get("stated_by") or StatementOrigin.CURATED.value).strip()
    if origin not in _ORIGINS:
        raise ValueError(
            f"{where} is stated by {origin!r}; the origins are "
            f"{', '.join(sorted(_ORIGINS))}."
        )
    primary = entry.get("primary_source")
    if not isinstance(primary, list) or not primary or not all(
        isinstance(item, str) and item.strip() for item in primary
    ):
        raise ValueError(
            f"{where} names no 'primary_source'. A statement says where its "
            f"number came from -- the vendor's file and section, the workbook, "
            f"the IPCC table -- as a list of strings (rule 16)."
        )

    checked = _releases(entry.get("checked_against"))
    if not checked:
        raise ValueError(
            f"{where} names no 'checked_against'. A property is a measurement "
            f"and a measurement has a vintage: ecoinvent restated crude oil "
            f"from 42.3 to 43.4 MJ/kg at 3.9. Name the releases this number was "
            f"checked against, as the versions their manifests declare."
        )
    by_release = entry.get("by_release")
    if by_release is None:
        by_release = {}
    if not isinstance(by_release, dict):
        raise ValueError(
            f"{where} has a 'by_release' that is not an object. It maps a "
            f"release to what that release states instead, as "
            f"{{\"3.8\": {{\"value\": 42.3}}}}."
        )
    resolved: dict[str, dict[str, Any]] = {}
    for named, override in by_release.items():
        named = str(named or "").strip()
        if not named:
            raise ValueError(f"{where} states a value under an empty release.")
        if named in checked:
            raise ValueError(
                f"{where} names release {named!r} in both 'checked_against' and "
                f"'by_release'. The first says the release takes the default and "
                f"the second says it takes another; the entry has not decided."
            )
        if not isinstance(override, dict) or not override:
            raise ValueError(
                f"{where} states {override!r} for release {named!r}; a release's "
                f"entry is an object restating 'value', 'unit' or 'per_unit'."
            )
        unknown = sorted(set(override) - {"value", "unit", "per_unit"})
        if unknown:
            raise ValueError(
                f"{where} restates {', '.join(unknown)} for release {named!r}; "
                f"only 'value', 'unit' and 'per_unit' may differ by release."
            )
        for key in ("unit", "per_unit"):
            if key in override and not str(override[key] or "").strip():
                raise ValueError(
                    f"{where} restates an empty {key!r} for release {named!r}."
                )
        r_unit = str(override.get("unit") or unit).strip()
        r_per = str(override.get("per_unit") or per_unit).strip()
        r_value = _value(override.get("value", value), where=f"{where} for {named!r}")
        _check_units(
            quantity_slug=quantity_slug, unit=r_unit, per_unit=r_per,
            where=f"{where} for release {named!r}",
        )
        resolved[named] = {"value": r_value, "unit": r_unit, "per_unit": r_per}

    by_vendor = _releases(entry.get("stated_by_vendor_in"))
    if "stated_by_vendor_in" in entry and not isinstance(entry["stated_by_vendor_in"], list):
        raise ValueError(
            f"{where} has a 'stated_by_vendor_in' that is not a list of releases."
        )
    for named in by_vendor:
        if named in checked or named in resolved:
            raise ValueError(
                f"{where} names release {named!r} in 'stated_by_vendor_in' and "
                f"also in 'checked_against' or 'by_release'. The first says the "
                f"vendor's file states the number and the second says this entry "
                f"does; the entry has not decided."
            )

    wanted = str(release or "").strip()
    if wanted and wanted in by_vendor:
        return None
    if wanted and wanted not in checked and wanted not in resolved:
        name = str(entry.get("source_name") or source_uuid)
        raise ValueError(
            f"This release is {wanted}, and the {quantity_slug} of {name} "
            f"({source_uuid}) in {path.name} was checked against "
            f"{', '.join([*checked, *resolved, *by_vendor])}. A property is a "
            f"measurement and a measurement has a vintage. Read this release's "
            f"own file or implementation report: add {wanted} to "
            f"'checked_against' if the number holds, state the release's own "
            f"under 'by_release', or name it in 'stated_by_vendor_in' if the "
            f"release's own file states the quantity."
        )
    chosen = resolved.get(wanted, {"value": value, "unit": unit, "per_unit": per_unit})
    return PropertyStatement(
        quantity=quantity_slug,
        value=chosen["value"],
        unit=chosen["unit"],
        per_unit=chosen["per_unit"],
        stated_by=StatementOrigin(origin),
        provenance=Provenance(
            was_generated_by=generated_by or "property_statements",
            was_attributed_to=_ATTRIBUTED_TO,
            had_primary_source=[item.strip() for item in primary],
            was_derived_from=path.name,
        ),
        comment=comment,
    )


def _rules_from(payload: dict[str, Any], *, path: Path) -> tuple[ConversionRule, ...]:
    raw = payload.get("conversion_rules") or []
    if not isinstance(raw, list):
        raise ValueError(f"{path.name} has a 'conversion_rules' that is not a list.")
    rules: list[ConversionRule] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        where = f"Conversion rule {index} in {path.name}"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} is not an object.")
        onto = _text(entry, "onto", where=where)
        convert_by = _text(entry, "convert_by", where=where)
        for slug in (onto, convert_by):
            if slug not in load_quantities():
                raise ValueError(
                    f"{where} names quantity {slug!r}, which quantities.json does "
                    f"not have."
                )
        if onto == convert_by:
            raise ValueError(
                f"{where} converts {onto!r} onto itself, which needs no rule."
            )
        if onto in seen:
            raise ValueError(f"{where} is the second rule onto {onto!r}.")
        seen.add(onto)
        stated_by: StatementOrigin | None = None
        if entry.get("stated_by") is not None:
            origin = str(entry.get("stated_by") or "").strip()
            if origin not in _ORIGINS:
                raise ValueError(
                    f"{where} converts by a statement stated by {origin!r}; the "
                    f"origins are {', '.join(sorted(_ORIGINS))}."
                )
            stated_by = StatementOrigin(origin)
        rules.append(ConversionRule(onto=onto, convert_by=convert_by,
                                    comment=_text(entry, "comment", where=where),
                                    stated_by=stated_by))
    return tuple(rules)


def _quantity_rulings_from(
    payload: dict[str, Any], *, path: Path, key: str, label: str, uuid_key: str,
    kind: str | None = None,
) -> dict[str, str]:
    """A list of ``{<uuid_key>, quantity, comment}`` rulings, as uuid -> slug.

    *kind*, where given, is the quantity kind every ruled slug must be of: an
    energy ruling naming a mass is a typo.
    """
    raw = payload.get(key) or []
    if not isinstance(raw, list):
        raise ValueError(f"{path.name} has a {key!r} that is not a list.")
    by_uuid: dict[str, str] = {}
    for index, entry in enumerate(raw):
        where = f"{label} {index} in {path.name}"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} is not an object.")
        uuid = _text(entry, uuid_key, where=where)
        slug = _text(entry, "quantity", where=where)
        if slug not in load_quantities():
            raise ValueError(
                f"{where} names quantity {slug!r}, which quantities.json does "
                f"not have."
            )
        if kind is not None and quantity(slug).quantity_kind != kind:
            raise ValueError(
                f"{where} rules {slug!r}, which is not an {kind.lower()}."
            )
        _text(entry, "comment", where=where)
        if uuid in by_uuid:
            raise ValueError(f"{where} rules {uuid} a second time.")
        by_uuid[uuid] = slug
    return by_uuid


def _reference_quantities_from(
    payload: dict[str, Any], *, path: Path
) -> dict[str, str]:
    return _quantity_rulings_from(
        payload, path=path, key="reference_quantities",
        label="Reference quantity", uuid_key="flow_uuid",
    )


def _energy_quantities_from(payload: dict[str, Any], *, path: Path) -> dict[str, str]:
    """What an unlabelled energy a vendor states per unit of a named flow is.

    Stepwise's method gives a kilogram of `Uranium` 560,000 MJ and the name
    `Uranium oxide, 332 GJ per kg, in ore` says what it says; neither calls it
    anything.  The adapters read such a number as a calorific value of
    unstated basis, which is what an unlabelled energy per kilogram of a fuel
    is for every fuel but a nuclear one, and this ruling says which rows are
    the nuclear ones.
    """
    return _quantity_rulings_from(
        payload, path=path, key="energy_quantities",
        label="Energy quantity", uuid_key="source_uuid", kind="Energy",
    )


def load_property_statements(
    path: Path | None,
    *,
    release: str = "",
    label: str = "",
    generated_by: str = "",
) -> PropertyStatements:
    """The statements *path* makes, resolved for *release*.

    Empty for a list with no file.  *release* empty asks nothing of the
    vintage, which is right for a caller holding no list; a release the file
    was checked against in neither place is refused, naming the row.

    :raises ValueError: for a malformed file.  A malformed ruling raises and is
        never skipped (rule 14).
    """
    if path is None:
        return PropertyStatements()
    if not path.exists():
        raise FileNotFoundError(f"Property statements for {label or path.stem} not at {path}.")
    payload = orjson.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} is not a JSON object.")
    version = payload.get("schema_version")
    if version != DECISIONS_SCHEMA_VERSION:
        raise ValueError(
            f"{path.name} has schema_version {version!r}; this reader expects "
            f"{DECISIONS_SCHEMA_VERSION}."
        )
    raw = payload.get("statements")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ValueError(f"{path.name} has a 'statements' that is not a list.")
    statements: dict[str, list[PropertyStatement]] = {}
    from_vendor: dict[str, set[str]] = {}
    seen: set[tuple[str, str]] = set()
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"Statement {index} in {path.name} is not an object.")
        statement = _statement_from(
            entry, release=release, index=index, path=path, generated_by=generated_by,
        )
        uuid = str(entry["source_uuid"]).strip()
        slug = str(entry["quantity"]).strip()
        key = (uuid, slug)
        if key in seen:
            raise ValueError(
                f"Statement {index} in {path.name} states {slug!r} "
                f"for {uuid} a second time. One flow states one value per "
                f"quantity; two is a question for a ruling, not a file."
            )
        seen.add(key)
        if statement is None:
            from_vendor.setdefault(uuid, set()).add(slug)
            continue
        statements.setdefault(uuid, []).append(statement)
    return PropertyStatements(
        statements={uuid: tuple(items) for uuid, items in statements.items()},
        rules=_rules_from(payload, path=path),
        reference_quantities=_reference_quantities_from(payload, path=path),
        energy_quantities=_energy_quantities_from(payload, path=path),
        expected_from_vendor={
            uuid: frozenset(slugs) for uuid, slugs in from_vendor.items()
        },
        path=path,
    )


#: The origins whose statements name no quantity of their own: the method's
#: factor and the number in a name are megajoules and nothing more, read as a
#: calorific value of unstated basis until the list's `energy_quantities` says
#: otherwise.  A vendor's flow dataset labels what it states (`heating value,
#: net`), and a curator names the quantity in the entry.
_UNLABELLED_ORIGINS = frozenset({StatementOrigin.VENDOR_METHOD, StatementOrigin.FLOW_NAME})


def _relabelled(
    statements: list[PropertyStatement], slug: str, *, loaded: PropertyStatements,
    flow: Any,
) -> list[PropertyStatement]:
    """*statements* with each unlabelled calorific value made *slug*.

    :raises ValueError: when the flow carries none to relabel: the ruling
        names a row that states no unlabelled energy, which is a ruling about
        nothing and most likely a uuid that moved.
    """
    out: list[PropertyStatement] = []
    relabelled = 0
    for statement in statements:
        if (
            statement.quantity == CALORIFIC_VALUE
            and statement.stated_by in _UNLABELLED_ORIGINS
        ):
            out.append(
                replace(
                    statement,
                    quantity=slug,
                    comment=(
                        f"{statement.comment} Ruled {slug} by "
                        f"{loaded.filename}: the number is not a heat of combustion."
                    ).strip(),
                )
            )
            relabelled += 1
        else:
            out.append(statement)
    if not relabelled:
        raise ValueError(
            f"{loaded.filename} rules the energy of {flow.name or flow.uuid} "
            f"({flow.uuid}) to be {slug}, and the flow carries no unlabelled "
            f"energy -- no method factor, no number in its name -- to apply "
            f"that to. A ruling about nothing is most likely a uuid that moved."
        )
    return out


def attach_property_statements(flows: Iterable[Any], loaded: PropertyStatements) -> int:
    """Put every statement about each flow on its record, the vendor's and the curator's.

    A flow arrives with what its vendor's file stated (`property_statements`
    the adapter wrote, and the number its name states, both already on the
    record), and *loaded* is what the curator adds.  Three rulings are applied
    on the way:

    * a flow the file's `energy_quantities` names has its unlabelled energies
      -- the method's factor, the number in its name -- relabelled with the
      ruled quantity; uranium's 560,000 MJ is fission energy, not a heat of
      combustion;
    * a curated statement of a quantity the vendor also states for the flow is
      refused, naming both: one number has one home, and the curated file is
      for what nobody states;
    * a quantity an entry says the vendor states for this release
      (`stated_by_vendor_in`) has to be there, or the entry is refused as
      covering a release it does not.

    On the records, never into the raw row: a key dropped into the input dict
    would land in `Flow.extra`, which is the untyped shape #407 retires.

    :raises ValueError: for the three cases above; for a statement whose
        `per_unit` is of another kind than the flow's unit -- a heating value
        per cubic metre on a flow in kilograms -- checked against the unit the
        vendor shipped as well as the one the flow is carried in, because a
        manual fix may have rebased it; and for a ruling naming a flow the
        list does not ship.
    :returns: how many flows received a curated statement.
    """
    attached = 0
    for flow in flows:
        statements = list(flow.property_statements or [])
        ruled = loaded.energy_quantities.get(flow.uuid)
        if ruled is not None:
            statements = _relabelled(statements, ruled, loaded=loaded, flow=flow)
        curated = loaded.statements.get(flow.uuid, ())
        for statement in curated:
            vendor = [s for s in statements if s.quantity == statement.quantity]
            if vendor:
                said = vendor[0]
                raise ValueError(
                    f"{loaded.filename} states the {statement.quantity} of "
                    f"{flow.name or flow.uuid} ({flow.uuid}) as {statement.value} "
                    f"{statement.unit} per {statement.per_unit}, and the vendor "
                    f"states it as {said.value} {said.unit} per {said.per_unit} "
                    f"({said.stated_by}). One number has one home: drop the "
                    f"curated entry, or name this release in its "
                    f"'stated_by_vendor_in'."
                )
            statements.append(statement)
        for slug in loaded.expected_from_vendor.get(flow.uuid, ()):
            if not any(
                s.quantity == slug and s.stated_by is not StatementOrigin.CURATED
                for s in statements
            ):
                raise ValueError(
                    f"{loaded.filename} says the vendor states the {slug} of "
                    f"{flow.name or flow.uuid} ({flow.uuid}) in this release, "
                    f"and the flow carries none. The entry's 'stated_by_vendor_in' "
                    f"names a release whose file does not state it."
                )
        if not statements:
            continue
        # The unit the flow is carried in, the one the vendor shipped, and the
        # one a manual fix rebased it from: `Uranium, 451 GJ per kg` is in
        # megajoules by the time it is a record, and its statements are per
        # the kilogram the vendor measured it in.
        rebased = (flow.extra or {}).get(UNIT_CONVERSION_KEY) if hasattr(flow, "extra") else None
        units = {
            _kind_of(str(unit))
            for unit in (
                flow.unit,
                getattr(flow.provided, "unit", None),
                rebased.get("source_unit") if isinstance(rebased, dict) else None,
            )
            if unit
        }
        for statement in statements:
            per_kind = _kind_of(statement.per_unit)
            if units and per_kind not in units:
                raise ValueError(
                    f"{statement.provenance.was_derived_from or loaded.filename} "
                    f"states {statement.quantity} of "
                    f"{flow.name or flow.uuid} ({flow.uuid}) per "
                    f"{statement.per_unit!r}, and the flow is measured in "
                    f"{flow.unit!r}. A statement is about one unit of the flow "
                    f"as the vendor measures it."
                )
        flow.property_statements = statements
        if curated:
            attached += 1
    if attached:
        logger.info(
            "property_statements_attached",
            file=loaded.filename,
            flows=attached,
            statements=sum(len(items) for items in loaded.statements.values()),
        )
    return attached


def refuse_rulings_about_unshipped_flows(
    flows: Iterable[Any], loaded: PropertyStatements
) -> None:
    """Refuse a statement or ruling naming a uuid no flow of the list carries.

    Apart from :func:`attach_property_statements` so that a caller holding a
    few of the list's flows -- a test, a bounded run -- can attach to them;
    `SourceList.load_flows` holds the whole list and asks this of it.

    :raises ValueError: naming the ruling and the first few uuids.  A ruling
        naming a uuid no row carries decides nothing and looks exactly like a
        decision; most likely the uuid moved.
    """
    shipped = {flow.uuid for flow in flows}
    for ruling, uuids in (
        ("statements", loaded.statements),
        ("energy_quantities", loaded.energy_quantities),
        ("stated_by_vendor_in", loaded.expected_from_vendor),
    ):
        missing = sorted(set(uuids) - shipped)
        if missing:
            raise ValueError(
                f"{loaded.filename} has {ruling} for {len(missing)} flow(s) the "
                f"list does not ship: {', '.join(missing[:5])}. A ruling naming "
                f"a uuid no row carries decides nothing and looks like a decision."
            )


def add_statements_from_names(rows: Sequence[dict[str, Any]], *, label: str) -> int:
    """Write the energy a SimaPro-shaped name states onto its raw row.

    `Gas, natural, 46.8 MJ per kg`, `Uranium oxide, 332 GJ per kg, in ore`:
    the lineage's way of saying what a kilogram stands for in a list keyed on
    names alone (`docs/findings/units.md`).  Read before the list's fixes and
    the lineage's, which rename these rows and rebase the uranium ones, so the
    statement is about the row as the vendor shipped it.  The number is read as
    a calorific value of unstated basis, `stated_by` ``flow-name``; the list's
    `energy_quantities` rules the uranium rows fission energy on attach.

    Into the raw row rather than onto a record because this runs where the
    rows are still raw, beside the other things read off the vendor's spelling
    before the record is built; `property_statements` is a declared field of
    the record, so the key lands there and not in `extra`.

    :returns: how many rows gained a statement.
    """
    added = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        parsed = energy_stated_in_name(name)
        if parsed is None:
            continue
        value, unit, per_unit = parsed
        statement = vendor_statement(
            quantity=CALORIFIC_VALUE,
            value=value,
            unit=unit,
            per_unit=per_unit,
            stated_by=StatementOrigin.FLOW_NAME,
            primary_source=[f"the flow's own name: `{name}`"],
            derived_from="the flow's name",
            generated_by=f"load_{label}",
            attributed_to=label,
            comment=(
                f"The flow's name states it: `{name}`. The name says neither net "
                f"nor gross."
            ),
        )
        existing = row.get("property_statements")
        if not isinstance(existing, list):
            existing = []
        row["property_statements"] = [*existing, statement.to_dict()]
        added += 1
    if added:
        logger.info("property_statements_from_names", source=label, rows=added)
    return added


def refuse_a_pair_stated_twice(
    rows: Sequence[dict[str, Any]], loaded: PropertyStatements, *, label: str
) -> None:
    """Refuse an override factor for a pair a statement also converts.

    One number, one home.  An override row keeps a `conversion_factor` only
    for a pair fact no property of the flow expresses -- an ore's share of its
    metal, mine gas at 1.0 from plain to standard cubic metres -- and a row
    that states one where the list's statements file already converts the
    same pair is two copies that can disagree.

    :raises ValueError: naming the row and the statement.
    """
    for row in rows:
        if not isinstance(row, dict) or str(row.get("route") or "") != "override":
            continue
        factor = row.get("conversion_factor")
        if isinstance(factor, bool) or not isinstance(factor, (int, float)):
            continue
        source = row.get("source") if isinstance(row.get("source"), dict) else {}
        target = row.get("target") if isinstance(row.get("target"), dict) else {}
        uuid = str(source.get("uuid") or source.get("identifier") or "").strip()
        for statement in loaded.statements.get(uuid, ()):
            derived = factor_between(
                statement,
                str(source.get("unit") or ""),
                str(target.get("unit_name") or ""),
            )
            if derived is None:
                continue
            raise ValueError(
                f"{label}: the override for {source.get('name') or uuid} ({uuid}) "
                f"states a conversion_factor of {factor} from "
                f"{source.get('unit')!r} to {target.get('unit_name')!r}, and "
                f"{loaded.filename} states its {statement.quantity} as "
                f"{statement.value} {statement.unit} per {statement.per_unit}, "
                f"which converts the same pair ({derived}). One number has one "
                f"home: drop the factor from the override."
            )


def reference_quantities_from_ilcd(path: Path | None = None) -> dict[str, str]:
    """What each EF 3.1 flow's unit measures, from its ILCD flow property.

    `extract` writes `flow-properties.json` from the ILCD flow datasets: for
    every flow, its flow properties and their `meanValue`s.  A flow with
    exactly one property at 1.0 is measured in that property -- `Hard Coal` in
    net calorific value, `Water` in mass -- and that is what tells the merge
    which of a source flow's statements converts onto it.

    Empty, with a log line, when the file is not there: a bounded build that
    never extracted EF falls back to the unit's generic quantity, which is what
    the merge assumes for a flow nobody has said more about.
    """
    path = FLOW_PROPERTIES_FILEPATH if path is None else path
    if not path.exists():
        logger.info("flow_properties_not_extracted", path=str(path))
        return {}
    payload = orjson.loads(path.read_bytes())
    values = payload.get("flow_property_values") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        raise ValueError(f"{path.name} has no 'flow_property_values' list.")
    by_uuid: dict[str, str] = {}
    for entry in values:
        if not isinstance(entry, dict):
            continue
        properties = [
            p for p in (entry.get("properties") or [])
            if isinstance(p, dict) and p.get("amount") == 1.0
        ]
        if len(properties) != 1:
            continue
        slug = quantity_for_ilcd_flow_property(str(properties[0].get("property_id") or ""))
        uuid = str(entry.get("flow_uuid") or "").strip()
        if slug and uuid:
            by_uuid[uuid] = slug
    return by_uuid
