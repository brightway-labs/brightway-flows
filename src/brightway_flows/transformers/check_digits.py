"""Validate CAS and EC number check digits, and attempt corrections.

Both numbers end in a digit computed from the ones before it, so a single
mistyped or transposed digit is caught arithmetically.  CAS is a weighted sum
mod 10 and always has an answer.  EC is a weighted sum mod 11, which has eleven
possible answers and only ten single digits to write them in.

The usual account of what happens to the eleventh -- and the rule this module
implemented until #120 -- is that the registrar skipped those slots: a number
whose sum lands on 10 was never issued, so it is a typing error, and since there
is no digit to put there no correction can be proposed either.

That is true of EINECS, the substances already on the market in 1981, and of
the NLP numbers; it is not true of ELINCS, the substances notified as new
afterwards, whose numbers begin with 4.  There the slot was issued, with a
check digit of 1.  Over the 106,213 substances in the ECHA inventory this
package ships:

* 106,032 numbers satisfy the rule as ordinarily stated;
* 181 have remainder 10, all of them begin with 4, and every one of the 181
  publishes check digit 1;
* no number in the inventory has a check digit wrong in any other way, and no
  number outside the 4 block has remainder 10 at all.

So the exception is read where the evidence puts it and nowhere else: a
remainder of 10 is a valid check digit of 1 in the ELINCS block, and remains an
error everywhere else, which keeps the arithmetic catching transcription
mistakes across the 100,907 EINECS and NLP numbers.  Ten ELINCS numbers reach
EF 3.1 -- Peonile, HFE-7500, furilazole, acryloylmorpholine among them -- and
under the old rule all ten were filed as unfixable errors at the source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import orjson
import structlog

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.records import SerialisableRecord
from brightway_flows.filesystem import PUBCHEM_DATA_FILEPATH
from brightway_flows.integrations.ec_inventory import load_ec_inventory
from brightway_flows.domain.labels import flow_label_value
from brightway_flows.pipeline import Change, Transformer, normalize
from brightway_flows.pipeline.review_records import (
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)

logger = structlog.get_logger(__name__)

CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")
EC_RE = re.compile(r"^\d{3}-\d{3}-\d$")

#: The leading digit of the ELINCS block, the substances notified as new after
#: 1981.  The one block where a weighted sum of 10 was issued rather than
#: skipped, and so the one block where such a number is not an error.
ELINCS_LEADING_DIGIT = "4"

#: The check digit the ELINCS block carries where the weighted sum is 10.  All
#: 181 such numbers in the ECHA inventory carry it and none carries anything
#: else, which is the whole of the evidence for the exception.
ELINCS_REMAINDER_TEN_CHECK_DIGIT = 1


@dataclass
class MalformedEC(SerialisableRecord):
    """An EC number no valid number can be recovered from, on the flow carrying it.

    Distinct from a *wrong* check digit, which this transformer corrects.  Two
    things land here.  Either the string is not nine characters in the form
    `NNN-NNN-N` at all, so there is nothing to compute a check digit over; or
    its weighted sum leaves remainder 10 outside the ELINCS block, where that
    slot was skipped rather than issued and so no digit exists to propose.

    Until #120 the second case swallowed the ELINCS numbers too, and ten real
    substances -- Peonile, HFE-7500, furilazole among them -- were filed here as
    data errors at the source when ECHA publishes an infocard for each.  What is
    left is genuinely unrecoverable, and the only available action is a human
    one.
    """

    uuid: str
    flow_name: str
    ec: str


def cas_check_digit_valid(cas: str) -> bool:
    """Validate the CAS registry number check digit.

    The last digit must equal the weighted sum (mod 10) of the preceding digits,
    where weights count up from 1 starting at the rightmost non-check digit.
    """
    if not CAS_RE.match(cas):
        return False
    digits = cas.replace("-", "")
    check = int(digits[-1])
    total = sum(int(d) * (i + 1) for i, d in enumerate(reversed(digits[:-1])))
    return total % 10 == check


def ec_check_digit_valid(ec: str) -> bool:
    """Validate the EC (EINECS/ELINCS) number check digit.

    The 7th digit must equal the weighted sum (mod 11) of the first 6 digits,
    with weights 1..6.  A remainder of 10 is not a single digit: in the EINECS
    and NLP blocks the number was never issued, and one that turns up there is
    an error.  In the ELINCS block -- the numbers beginning with 4 -- it was
    issued with check digit 1, which is why `423-740-1` (Peonile) is a real EC
    number and not a typing mistake.  See the module docstring for the count
    behind that, and #120.
    """
    if not EC_RE.match(ec):
        return False
    digits = ec.replace("-", "")
    check = int(digits[-1])
    return _expected_ec_check_digit(digits) == check


def correct_cas(cas: str) -> str | None:
    """Return *cas* with the check digit corrected, or ``None`` if malformed."""
    if not CAS_RE.match(cas):
        return None
    digits = cas.replace("-", "")
    total = sum(int(d) * (i + 1) for i, d in enumerate(reversed(digits[:-1])))
    correct_digit = total % 10
    return cas[:-1] + str(correct_digit)


def _expected_ec_check_digit(digits: str) -> int | None:
    """The check digit *digits* should carry, or ``None`` if no number was issued.

    *digits* is the nine-character number with its hyphens removed; only the
    first six are read.  ``None`` is the eleventh answer the mod-11 sum can
    give outside the ELINCS block, where the slot was skipped rather than
    issued and so there is no digit to propose.
    """
    total = sum(int(d) * (i + 1) for i, d in enumerate(digits[:6]))
    remainder = total % 11
    if remainder < 10:
        return remainder
    if digits[0] == ELINCS_LEADING_DIGIT:
        return ELINCS_REMAINDER_TEN_CHECK_DIGIT
    return None


def correct_ec(ec: str) -> str | None:
    """Return *ec* with the check digit corrected, or ``None`` if no valid digit exists."""
    if not EC_RE.match(ec):
        return None
    expected = _expected_ec_check_digit(ec.replace("-", ""))
    if expected is None:
        return None
    return ec[:-1] + str(expected)


class CheckDigitTransformer(Transformer):
    """Validate check digits and attempt corrections via external data sources.

    For each invalid CAS or EC number, the correct check digit is computed and
    the corrected identifier is looked up in PubChem and the EC-inventory.  If a
    match is found and the name is consistent with the flow, a :class:`Change`
    is emitted replacing the invalid entry in the list.
    """

    name = "check_digits"
    answers_per_flow = True

    def __init__(self) -> None:
        self._ec_cas_names: dict[str, set[str]] = {}
        self._ec_ec_names: dict[str, set[str]] = {}
        self._pubchem_cas_names: dict[str, str] = {}
        self.malformed_ecs: list[MalformedEC] = []

    def setup(self) -> None:
        ec_data = load_ec_inventory()
        for rec in ec_data["records"]:
            name = rec.get("name") or ""
            if rec.get("cas_number") and name:
                self._ec_cas_names.setdefault(rec["cas_number"], set()).add(name)
            if rec.get("ec_number") and name:
                self._ec_ec_names.setdefault(rec["ec_number"], set()).add(name)

        if PUBCHEM_DATA_FILEPATH.exists():
            pubchem = orjson.loads(PUBCHEM_DATA_FILEPATH.read_bytes())
            cid_to_name: dict[int, str] = {}
            for pname, compounds in pubchem.get("by_name", {}).items():
                for compound in compounds:
                    cid_to_name.setdefault(compound["cid"], pname)
            for cas, compounds in pubchem.get("by_cas", {}).items():
                for compound in compounds:
                    cid = compound["cid"]
                    if cid in cid_to_name:
                        self._pubchem_cas_names[cas] = cid_to_name[cid]
                        break

    def review_queue_items(self) -> list[ReviewQueueItem]:
        """The uncorrectable EC numbers this run saw.

        Blocking, not informational: the pipeline did not act and cannot,
        so the number stays wrong until someone fixes it at the source.
        """
        return [
            ReviewQueueItem(
                queue_name=ReviewQueue.EC_MALFORMED,
                item_key=f"{malformed.uuid}:{malformed.ec}",
                title=malformed.flow_name,
                severity=Severity.BLOCKING,
                uuid=malformed.uuid,
                payload=malformed.to_dict(),
            )
            for malformed in self.malformed_ecs
        ]

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []
        self.malformed_ecs = []

        for flow in flows:
            uuid = flow.uuid
            flow_name = flow_label_value(flow)

            cas_list = flow.cas_numbers
            new_cas_list = list(cas_list)
            cas_fixes: list[str] = []
            for i, cas in enumerate(cas_list):
                if not cas_check_digit_valid(cas):
                    fixed = self._try_correct_cas(uuid, flow_name, cas)
                    if fixed is not None:
                        new_cas_list[i] = fixed
                        cas_fixes.append(f"{cas} → {fixed}")
            if cas_fixes:
                changes.append(Change(
                    uuid, "cas_numbers", new_cas_list,
                    comment="Corrected CAS check digit: " + "; ".join(cas_fixes),
                ))

            ec_list = flow.ec_numbers
            new_ec_list = list(ec_list)
            ec_fixes: list[str] = []
            for i, ec in enumerate(ec_list):
                if not ec_check_digit_valid(ec):
                    fixed = self._try_correct_ec(uuid, flow_name, ec)
                    if fixed is not None:
                        new_ec_list[i] = fixed
                        ec_fixes.append(f"{ec} → {fixed}")
            if ec_fixes:
                changes.append(Change(
                    uuid, "ec_numbers", new_ec_list,
                    comment="Corrected EC check digit: " + "; ".join(ec_fixes),
                ))

        return changes

    def _name_matches(self, flow_name: str, reference_names: set[str]) -> bool:
        norm = normalize(flow_name)
        return any(normalize(n) == norm for n in reference_names)

    def _try_correct_cas(
        self, uuid: str, flow_name: str, cas: str
    ) -> str | None:
        fixed = correct_cas(cas)
        if fixed is None:
            logger.warning("cas_malformed", uuid=uuid, name=flow_name, cas=cas)
            return None

        found_names: set[str] = set()
        found_names.update(self._ec_cas_names.get(fixed, set()))
        pc_name = self._pubchem_cas_names.get(fixed)
        if pc_name:
            found_names.add(pc_name)

        if not found_names:
            logger.warning(
                "cas_check_digit_invalid_no_match",
                uuid=uuid,
                name=flow_name,
                original_cas=cas,
                corrected_cas=fixed,
            )
            return None

        if self._name_matches(flow_name, found_names):
            return fixed

        logger.warning(
            "cas_check_digit_name_conflict",
            uuid=uuid,
            flow_name=flow_name,
            original_cas=cas,
            corrected_cas=fixed,
            found_names=sorted(found_names),
        )
        return None

    def _try_correct_ec(
        self, uuid: str, flow_name: str, ec: str
    ) -> str | None:
        fixed = correct_ec(ec)
        if fixed is None:
            self.malformed_ecs.append(
                MalformedEC(uuid=uuid, flow_name=flow_name, ec=ec)
            )
            return None

        found_names = self._ec_ec_names.get(fixed, set())

        if not found_names:
            logger.warning(
                "ec_check_digit_invalid_no_match",
                uuid=uuid,
                name=flow_name,
                original_ec=ec,
                corrected_ec=fixed,
            )
            return None

        if self._name_matches(flow_name, found_names):
            return fixed

        logger.warning(
            "ec_check_digit_name_conflict",
            uuid=uuid,
            flow_name=flow_name,
            original_ec=ec,
            corrected_ec=fixed,
            found_names=sorted(found_names),
        )
        return None
