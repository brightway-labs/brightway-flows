"""What a build was supposed to do, written down where a reviewer can read it.

An expectation is one sentence about the published output, in two halves.  The
*subject* names something the build produced -- a row of a vendor list, a
consensus flow, a substance, a counted measure.  The *expect* block states what
should be true of it.  Both halves are data, so a pull request that claims to
fix an issue adds a file here and the claim becomes checkable instead of
remaining a sentence in a description nobody re-reads.

    {
      "id": "0381-bafu-water-unqualified",
      "issue": 381,
      "title": "A BAFU row named `Water` lands on the consensus water flow",
      "subject": {"kind": "source_row", "list": "bafu", "name": "Water"},
      "expect": {"outcome": "matched", "target_name": "Water"},
      "comment": "Why this is the right answer, and what the build did instead."
    }

**Every key is checked against a closed list, and so is every value.**  A
data-driven checker whose unknown keys are ignored is worse than no checker:
`"target_unti": "m3"` would be silently dropped and the expectation would pass
on a build that never looked at the unit.  So an unrecognised subject kind,
selector key or claim raises `ExpectationFileError` at load, and
`tests/test_expectations.py` loads every file in the directory.  A typo fails
the test suite, not the assessment.

The values are checked for the same reason, learned the harder way: the closed
lists covered which claims exist and nothing covered what a claim may say, so a
bound one key deep -- `{"at_mst": 3}` -- got through, matched no comparison, and
reported **met**.  A misspelling that turns a check into a pass is the worst
outcome available, so a bound's keys, a count's type and a boolean's type are
all checked here now.  See `_check_claim_values`.

**`version` is optional on purpose.**  An expectation about ecoinvent should
survive the bump from 3.12 to 3.13 -- the claim is about the list, not about the
release.  Naming a version pins the expectation to it, which is right when the
issue is about that release specifically.

**A selector may match many rows.**  Where it does, every row must satisfy every
claim, except for the aggregate claims listed in `AGGREGATE_CLAIMS`, which are
about the set rather than about each member.  "The 169 BAFU rows named `Water`
all land somewhere" is one expectation, not 169.

**A flow and a substance are different claims.**  Four BAFU rows named
`Silver-110` reach four flows, which is right -- they are in four contexts -- and
two substances, which is not.  `same_target` asks about the flow;
`same_substance` asks about the identity behind it, and it is the second that
catches one source name being read two ways.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson
import structlog

logger = structlog.get_logger(__name__)

#: Where the files live.  Repository root rather than inside the package,
#: because they are not build inputs -- nothing in `pipeline` or `merge` reads
#: them -- and because a contributor adding one should find them without
#: knowing the package layout.
EXPECTATIONS_DIR = Path(__file__).resolve().parents[3] / "expectations"

#: The file the baseline lives in, skipped when reading expectations.
BASELINE_FILENAME = "baseline.json"

#: This directory's own file format, not the published list's.  Rule 13: an
#: unqualified `EXPECTATIONS_SCHEMA_VERSION` is `domain/schema.py`'s -- the version of
#: `harmonised-flows.json` -- and three constants sharing that name is what
#: made grepping it return three answers (#98).
EXPECTATIONS_SCHEMA_VERSION = 1


class ExpectationFileError(ValueError):
    """A file in `expectations/` is not a valid expectation file.

    Raised rather than logged and skipped: an expectation that fails to load is
    an expectation that silently stops being checked, which is the one failure
    mode this whole mechanism exists to prevent.
    """


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------

#: Which keys may select each kind of subject.  `evaluate` turns these into SQL;
#: this is the list a file is validated against.
SUBJECT_SELECTORS: dict[str, frozenset[str]] = {
    # A row of a vendor list, as the merge saw it.  Resolved against
    # `merge_outcomes`, which holds exactly one row per source flow per list.
    "source_row": frozenset({
        "list", "version", "uuid", "name", "name_contains",
        "context", "cas", "unit",
        # Selectable as well as claimable, so that "no row the merge placed is
        # missing from the list" can be asked of every row at once instead of
        # one expectation per row.
        "published",
    }),
    # A consensus elementary flow.  Resolved against `elementary_flows` joined
    # to the flow object that gives it its name.
    "flow": frozenset({
        "uuid", "name", "context_iri", "context_display", "unit",
        "include_deprecated",
    }),
    # A substance: one `flow_objects` row, which many flows may share.
    "substance": frozenset({"id", "label", "cas"}),
    # One published characterisation factor: a flow, an impact category and the
    # implementation that stated it.  The three together are what identifies a
    # number, which is why all three are selectable and why `implemented_by` is
    # not a claim: "the JRC says 4.78E+03 here" and "ecoinvent says 4.78E+03
    # here" are two facts, and an expectation that could only name the flow
    # would have to choose which of them it meant.
    "factor": frozenset({
        "flow_uuid", "flow_name", "substance_cas",
        "context_display", "context_iri",
        "category", "implemented_by",
    }),
    # A named entry in the measure registry.  See `measures.py`.
    # `value_when_absent` is for a measure that vanishes at zero: most counts
    # come off a stats table that writes no row for nothing, so "the defect is
    # gone" and "the measure was renamed" look identical.  Stating the value
    # an absent key means keeps an `at_most: 0` claim alive after the count it
    # bounds reaches zero -- without it the claim reports unresolved, and the
    # guard is silently lost (found by review on #336, for the
    # factor-collision bound of #118).
    "measure": frozenset({"key", "value_when_absent"}),
}

#: What may be claimed about each kind of subject.  Every claim is implemented
#: by a function of the same name in `evaluate`; the two lists are checked
#: against each other by `tests/test_expectations.py`, so a claim named here
#: and not implemented is a test failure rather than a silent pass.
SUBJECT_CLAIMS: dict[str, frozenset[str]] = {
    "source_row": frozenset({
        "outcome", "not_outcome", "reason", "basis",
        "target_uuid", "target_name", "target_unit",
        "target_context_iri", "target_context_display", "target_cas",
        "target_characterised", "target_deprecated", "target_substance_id",
        "unit_mismatch", "context_inconsistency",
        # Whether the merge's decision about this row reached the published
        # list.  Every other claim here reads `merge_outcomes`, which records
        # what the merge *decided*; this one reads the link the writer made
        # from it.  The two can disagree -- #321 and #115 are 427 rows the
        # merge matched correctly and the writer dropped -- and no claim
        # phrased about the decision can say so.
        "published",
        # The factor the merge wrote for this row's pair, as
        # `qudt:conversionMultiplier` on its source reference.  A claim about
        # the *release*, which is why it belongs on `source_row` and not on
        # `flow`: one consensus flow takes kilograms from several lists and
        # several releases, and since #162 they need not agree -- ecoinvent 3.8
        # converts crude oil at 42.3 MJ/kg and 3.12 at 43.4, because ecoinvent
        # revised the value at 3.9 and rebuilt its oil datasets on it. A claim
        # phrased about the flow could not tell the two apart.
        "conversion_factor",
        "row_count", "same_target", "distinct_targets", "target_count",
        "same_substance", "distinct_substances", "substance_count",
    }),
    "flow": frozenset({
        "exists", "count", "unit", "context_iri", "context_display",
        "characterised", "deprecated", "replaced_by", "substance_id",
        "substance_cas",
        # How many factors each implementation of a method states about the flow.
        # `characterised` is the JRC's non-zero count and keeps that meaning --
        # it reads `elementary_flows.lcia_factor_count`, which a query written
        # before `characterise` existed still means -- and these three are how an
        # expectation says that one implementation characterises a flow, another
        # does not, and this list has not decided. #84 is the first claim that
        # needed all three of them at once.
        "jrc_factors", "ecoinvent_factors", "consensus_factors",
    }),
    "substance": frozenset({
        "exists", "count", "label", "cas", "flow_count", "has_payload",
        # How many values the substance publishes for one structural property.
        # A substance publishing two InChIKeys is publishing two identities and
        # a consumer joining on one matches twice, which is #310; the claim
        # worth writing is almost always `1`.
        "inchikey_count", "formula_count",
        # What the substance *is*, as the published `flow_type`: a neutral
        # molecule, a monoatomic ion, a material, or `unclassified` for one the
        # typing rules could not place.  #71 is a claim about this column and
        # could not be stated without it -- 198 of the substances a merge
        # created are `unclassified`, and "this one is an ion" is the sentence
        # that says the enrichment reached it.  Written as the short ChemROF
        # term -- `MonoatomicIon` -- rather than the IRI, for the reason `roles`
        # is written as a label: an expectation is read by a person.
        "flow_type",
        # A name the substance is *also* published under.  Met when the named
        # string is among the substance's alternative labels, so
        # `{"alt_label": "HFC-116"}` asks that the designation is still
        # findable, not that it is the only other name.  Without it the half of
        # a rename that keeps the source's own spelling searchable cannot be
        # claimed at all: #104 and #106 both turn on a designation surviving
        # the rename as an alternative label, and a check that only reads
        # `label` reports that as done when the string has been dropped.
        # Compared without regard to case, unlike `roles`, because a source
        # list's own spelling of a name is exactly what varies between
        # releases -- EF 3.1 ships `HFC-23` and `hfc-23` for one substance.
        "alt_label",
        # What the substance is *used for*, as a published `RO:0000087` role
        # label.  A separate question from what it *is*, which is `cas` and
        # `label`: the whole of #206 is that a herbicide had nowhere to say so
        # except by being replaced with `Herbicides, Unspecified`, and an
        # expectation about that fix has to be able to name the role.
        "roles",
    }),
    "factor": frozenset({
        "exists", "count", "row_count",
        # The number itself, written the way its source document prints it:
        # `"4.78E+03"`, a string rather than a float.  See `AMOUNT_CLAIMS`.
        "amount",
        # How this list arrived at the number -- `sole`, `agreed`, `restated`,
        # `adopted` or `ruled`.  A separate question from what the number *is*:
        # a factor only ecoinvent states can be published because the substance
        # already carries that value elsewhere (`restated`) or because a curator
        # accepted its population (`adopted`), and an expectation about which of
        # those happened is an expectation about the rule, not about the value.
        "derivation",
    }),
    "measure": frozenset({"equals", "at_most", "at_least"}),
}

#: Claims comparing a published number against one somebody transcribed.
#:
#: Written as a string, and the string's own precision is the tolerance.  JRC
#: 130796 Table 6 prints vanadium's freshwater ecotoxicity factor as
#: `4.78E+03`; the build holds `4775.290751488173`, and the two agree to every
#: digit the table states.  A float claim would have to be either exactly equal,
#: which no transcription of a rounded table can be, or bounded by a tolerance
#: somebody picks -- and picking one per row is how a transcription error gets
#: absorbed into a widened bound.  Rounding the build's value to as many
#: significant figures as the claim states asks exactly the question the
#: document answers, and it is the same question for every row.
#:
#: It also survives the two implementations disagreeing in the last bit, which
#: they do: chromium(6+) is 12274.013470217462 under the JRC and
#: 12274.01347021746 under the ecoinvent Centre, one published number rendered
#: twice.  At the three significant figures the table states, that is one number.
AMOUNT_CLAIMS = frozenset({"amount"})

#: `outcome` names a column value; these two name a set of them, because the
#: interesting question is usually "did it land on a flow that already existed"
#: and that is three of the five values.  Written out rather than left to the
#: reader so that `"outcome": "matched"` cannot be read as a sixth value.
OUTCOME_ALIASES: dict[str, tuple[str, ...]] = {
    #: Landed on a flow that already existed, however it got there.
    "matched": ("prepared", "algorithm", "manual-addition"),
    #: Landed anywhere at all, including on a flow the merge minted for it.
    "placed": ("prepared", "algorithm", "manual-addition", "created"),
}

#: The five values `merge_outcomes.outcome` takes.
OUTCOME_VALUES: tuple[str, ...] = (
    "prepared", "algorithm", "manual-addition", "created", "unmatched",
)

#: Claims about the matched set rather than about each row in it.
AGGREGATE_CLAIMS = frozenset({
    "row_count", "count",
    "same_target", "distinct_targets", "target_count",
    "same_substance", "distinct_substances", "substance_count",
})

#: The three keys a bound may carry.
#:
#: Checked at load, and this is not decoration.  `{"at_mst": 3}` used to load,
#: reach a comparison that recognised none of its keys, and report **met** --
#: the exact failure this module's docstring says the closed lists prevent, one
#: level further down than they reached.  The lists covered which claims exist;
#: nothing covered what a claim's value may say.
BOUND_KEYS = frozenset({"equals", "at_most", "at_least"})

#: Claims counting something: an integer, or a bound over one.
NUMERIC_CLAIMS = frozenset({
    "count", "row_count", "target_count", "substance_count", "flow_count",
    "inchikey_count", "formula_count",
})

#: Claims that are yes or no.  A string `"true"` compares unequal to `True` and
#: makes the expectation unmet on every build, which reads as a defect in the
#: pipeline rather than as a defect in the file.
BOOLEAN_CLAIMS = frozenset({
    "exists", "has_payload", "characterised", "deprecated",
    "target_characterised", "target_deprecated",
    "unit_mismatch", "context_inconsistency",
    "same_target", "distinct_targets", "same_substance", "distinct_substances",
})

#: Selector keys whose value is a list of strings rather than a string.  A
#: context written as `"air"` instead of `["air", "unspecified"]` matched
#: nothing and was reported as a subject that had left the build -- the wrong
#: diagnosis, and the one `evaluate` is at pains to keep separate.
LIST_SELECTORS = frozenset({"context"})

#: Selector keys that are yes or no.
BOOLEAN_SELECTORS = frozenset({"include_deprecated", "published"})

#: Selector fields whose value is a number.  Only `value_when_absent` today:
#: the value an absent measure key stands for, which is a count, not a name.
NUMERIC_SELECTORS = frozenset({"value_when_absent"})


@dataclass(frozen=True)
class Expectation:
    """One statement about the build, and where it was written."""

    id: str
    title: str
    kind: str
    selector: dict[str, Any]
    claims: dict[str, Any]
    #: The issue this expectation belongs to, where there is one.  Not required:
    #: an invariant worth pinning need not have been a bug first.
    issue: int | None = None
    comment: str = ""
    #: Which file it came from, so a failure can say where to go and edit.
    source_file: str = ""
    #: An expectation the project has agreed is not yet true.  It is still
    #: evaluated and still reported -- it is the work queue -- but it does not
    #: make `assess --strict` fail, so a known-open issue can be written down
    #: before it is fixed.  See the README.
    pending: bool = False

    @property
    def label(self) -> str:
        """`#65 0381-bafu-water-unqualified`, for a one-line report."""
        return f"#{self.issue} {self.id}" if self.issue else self.id


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_FILE_KEYS = frozenset({"schema_version", "description", "expectations"})
_ENTRY_KEYS = frozenset({
    "id", "issue", "title", "subject", "expect", "comment", "pending",
})


def load_expectations(directory: Path | None = None) -> tuple[Expectation, ...]:
    """Every expectation in *directory*, in file then declaration order.

    Order is stable so that a report and a baseline diff read the same way twice
    running; it is not otherwise meaningful.
    """
    directory = directory or EXPECTATIONS_DIR
    if not directory.exists():
        logger.debug("no_expectations_directory", path=str(directory))
        return ()

    loaded: list[Expectation] = []
    seen: dict[str, str] = {}
    for path in sorted(directory.glob("*.json")):
        if path.name == BASELINE_FILENAME:
            continue
        for expectation in _load_file(path):
            if expectation.id in seen:
                raise ExpectationFileError(
                    f"{path.name}: duplicate expectation id {expectation.id!r}, "
                    f"already defined in {seen[expectation.id]}. Ids are what the "
                    "baseline records status against, so they must be unique."
                )
            seen[expectation.id] = path.name
            loaded.append(expectation)
    return tuple(loaded)


def _load_file(path: Path) -> list[Expectation]:
    try:
        payload = orjson.loads(path.read_bytes())
    except orjson.JSONDecodeError as exc:
        raise ExpectationFileError(f"{path.name}: not valid JSON -- {exc}") from exc
    if not isinstance(payload, dict):
        raise ExpectationFileError(f"{path.name}: top level must be an object")

    if unknown := set(payload) - _FILE_KEYS:
        raise ExpectationFileError(
            f"{path.name}: unknown top-level key(s) {sorted(unknown)}; "
            f"expected {sorted(_FILE_KEYS)}"
        )
    version = payload.get("schema_version")
    if version != EXPECTATIONS_SCHEMA_VERSION:
        raise ExpectationFileError(
            f"{path.name}: schema_version is {version!r}, this build reads "
            f"{EXPECTATIONS_SCHEMA_VERSION}"
        )
    entries = payload.get("expectations")
    if not isinstance(entries, list):
        raise ExpectationFileError(f"{path.name}: `expectations` must be a list")

    return [_parse_entry(path, index, entry) for index, entry in enumerate(entries)]


def _parse_entry(path: Path, index: int, entry: Any) -> Expectation:
    where = f"{path.name}[{index}]"
    if not isinstance(entry, dict):
        raise ExpectationFileError(f"{where}: each expectation must be an object")
    if unknown := set(entry) - _ENTRY_KEYS:
        raise ExpectationFileError(
            f"{where}: unknown key(s) {sorted(unknown)}; expected {sorted(_ENTRY_KEYS)}"
        )

    identifier = str(entry.get("id") or "").strip()
    if not identifier:
        raise ExpectationFileError(f"{where}: `id` is required and must be non-empty")
    title = str(entry.get("title") or "").strip()
    if not title:
        raise ExpectationFileError(
            f"{where} ({identifier}): `title` is required. It is what the report "
            "prints, so it has to say what should be true in plain words."
        )

    subject = entry.get("subject")
    if not isinstance(subject, dict):
        raise ExpectationFileError(f"{where} ({identifier}): `subject` must be an object")
    kind = str(subject.get("kind") or "").strip()
    if kind not in SUBJECT_SELECTORS:
        raise ExpectationFileError(
            f"{where} ({identifier}): unknown subject kind {kind!r}; "
            f"expected one of {sorted(SUBJECT_SELECTORS)}"
        )
    selector = {key: value for key, value in subject.items() if key != "kind"}
    if unknown := set(selector) - SUBJECT_SELECTORS[kind]:
        raise ExpectationFileError(
            f"{where} ({identifier}): subject kind {kind!r} has no selector "
            f"{sorted(unknown)}; expected {sorted(SUBJECT_SELECTORS[kind])}"
        )
    if not selector:
        raise ExpectationFileError(
            f"{where} ({identifier}): a subject with no selector matches the whole "
            "build, which is never what was meant"
        )
    _check_selector_values(where, identifier, kind, selector)

    claims = entry.get("expect")
    if not isinstance(claims, dict) or not claims:
        raise ExpectationFileError(
            f"{where} ({identifier}): `expect` must be a non-empty object"
        )
    if unknown := set(claims) - SUBJECT_CLAIMS[kind]:
        raise ExpectationFileError(
            f"{where} ({identifier}): subject kind {kind!r} has no claim "
            f"{sorted(unknown)}; expected {sorted(SUBJECT_CLAIMS[kind])}"
        )
    _check_claim_values(where, identifier, kind, claims)

    issue = entry.get("issue")
    if issue is not None and not isinstance(issue, int):
        raise ExpectationFileError(
            f"{where} ({identifier}): `issue` must be the issue number as an integer"
        )
    pending = entry.get("pending", False)
    if not isinstance(pending, bool):
        raise ExpectationFileError(f"{where} ({identifier}): `pending` must be true or false")

    return Expectation(
        id=identifier,
        title=title,
        kind=kind,
        selector=selector,
        claims=dict(claims),
        issue=issue,
        comment=str(entry.get("comment") or ""),
        source_file=path.name,
        pending=pending,
    )


def _check_claim_values(where: str, identifier: str, kind: str, claims: dict[str, Any]) -> None:
    """Reject values a claim cannot mean, at load rather than at evaluation.

    Naming the claims was not enough.  A claim name off the list raises; a claim
    *value* the evaluator cannot act on used to get through, and the three ways
    it did so were each worse than the last:

    - `{"at_mst": 3}` reported **met**, because the comparison recognised none
      of its keys and had nothing left to fail on.  A checker that passes when
      it does not understand the question is the thing this file exists to
      prevent.
    - `{"at_most": "five"}` raised `TypeError` out of `assess` and took every
      other expectation with it, naming no file.
    - `"outcome": "matchd"` resolved to no rows and was reported as a subject
      that had left the build, which sends a reader to the wrong place.

    All three are one mistake -- a hand-edited value -- and all three are caught
    here, where the message can name the file, the entry and the key.
    """
    _check_outcome_values(where, identifier, kind, claims)
    for claim, value in claims.items():
        if kind == "measure" or claim in NUMERIC_CLAIMS:
            _check_number_or_bound(where, identifier, claim, value)
        elif claim in AMOUNT_CLAIMS:
            _check_transcribed_number(where, identifier, claim, value)
        elif claim in BOOLEAN_CLAIMS:
            if not isinstance(value, bool):
                raise ExpectationFileError(
                    f"{where} ({identifier}): `{claim}` is {value!r}; it has to be "
                    "true or false"
                )


def _check_outcome_values(
    where: str, identifier: str, kind: str, claims: dict[str, Any]
) -> None:
    if kind != "source_row":
        return
    permitted = set(OUTCOME_VALUES) | set(OUTCOME_ALIASES)
    for key in ("outcome", "not_outcome"):
        value = claims.get(key)
        if value is None:
            continue
        values = value if isinstance(value, list) else [value]
        if bad := [str(item) for item in values if str(item) not in permitted]:
            raise ExpectationFileError(
                f"{where} ({identifier}): `{key}` {bad} is not an outcome; "
                f"expected one of {sorted(permitted)}"
            )


def _check_transcribed_number(where: str, identifier: str, claim: str, value: Any) -> None:
    """A number copied out of a document, as the document prints it.

    A string, because the digits somebody typed are the whole of the tolerance:
    `"4.78E+03"` claims three significant figures and `"4.7830E+03"` claims five,
    and a float cannot tell the two apart.  A float here is refused rather than
    coerced -- `4.78e3` would silently become an exact-equality claim against a
    number no published table states to seventeen digits, and would be unmet on
    every build for a reason that is not about the pipeline.
    """
    if not isinstance(value, str):
        raise ExpectationFileError(
            f"{where} ({identifier}): `{claim}` is {value!r}; it has to be a string "
            'holding the number as its source prints it, like "4.78E+03" -- the '
            "digits are what states the precision the claim is made to"
        )
    try:
        float(value)
    except ValueError:
        raise ExpectationFileError(
            f"{where} ({identifier}): `{claim}` is {value!r}, which is not a number"
        ) from None
    if not significant_figures(value):
        raise ExpectationFileError(
            f"{where} ({identifier}): `{claim}` is {value!r}, which states no "
            "significant figures to compare against"
        )


def significant_figures(rendered: str) -> int:
    """How many significant figures *rendered* states.

    Leading zeros are placeholders and trailing ones are not: `0.00420` states
    three and `4200` states four, which is the ordinary reading and the one a
    table's own footnotes assume.  The exponent is not part of the mantissa.
    """
    mantissa = rendered.strip().lower().split("e")[0]
    digits = mantissa.lstrip("+-").replace(".", "")
    return len(digits.lstrip("0"))


def _check_number_or_bound(where: str, identifier: str, claim: str, value: Any) -> None:
    """`3`, or `{"at_most": 3}`, and nothing else.

    `bool` is excluded explicitly because it is an `int` in Python, and
    `{"at_most": true}` would otherwise compare a count against 1.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if not isinstance(value, dict):
        raise ExpectationFileError(
            f"{where} ({identifier}): `{claim}` is {value!r}; it has to be a number "
            'or a bound like {"at_most": 5}'
        )
    if not value:
        raise ExpectationFileError(
            f"{where} ({identifier}): `{claim}` is an empty bound, which claims nothing"
        )
    if unknown := set(value) - BOUND_KEYS:
        raise ExpectationFileError(
            f"{where} ({identifier}): `{claim}` bound has no key {sorted(unknown)}; "
            f"expected some of {sorted(BOUND_KEYS)}"
        )
    for key, bound in value.items():
        if not isinstance(bound, int) or isinstance(bound, bool):
            raise ExpectationFileError(
                f"{where} ({identifier}): `{claim}.{key}` is {bound!r}; it has to be "
                "a number"
            )


def _check_selector_values(
    where: str, identifier: str, kind: str, selector: dict[str, Any]
) -> None:
    """A selector written in the wrong shape names nothing, and "names nothing"
    is reported as a subject that has left the build.  That is a true statement
    about a malformed selector and a useless one, so the shape is checked here.
    """
    for key, value in selector.items():
        if key in LIST_SELECTORS:
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ExpectationFileError(
                    f"{where} ({identifier}): subject `{key}` is {value!r}; it has to "
                    'be a list of strings, like ["emissions to water", "river"]'
                )
        elif key in BOOLEAN_SELECTORS:
            if not isinstance(value, bool):
                raise ExpectationFileError(
                    f"{where} ({identifier}): subject `{key}` is {value!r}; it has to "
                    "be true or false"
                )
        elif key in NUMERIC_SELECTORS:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ExpectationFileError(
                    f"{where} ({identifier}): subject `{key}` is {value!r}; it has to "
                    "be a number"
                )
        elif not isinstance(value, str) or not value.strip():
            raise ExpectationFileError(
                f"{where} ({identifier}): subject `{key}` is {value!r}; it has to be "
                "a non-empty string"
            )


def summarise_by_issue(expectations: tuple[Expectation, ...]) -> dict[int | None, list[Expectation]]:
    """Group by issue, for a report that reads as a list of issues."""
    grouped: dict[int | None, list[Expectation]] = {}
    for expectation in expectations:
        grouped.setdefault(expectation.issue, []).append(expectation)
    return grouped
