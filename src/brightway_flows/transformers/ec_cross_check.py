"""Cross-check CAS ↔ EC number relationships against the ECHA EC-inventory."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar

import orjson
import structlog

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.records import SerialisableRecord
from brightway_flows.filesystem import PUBCHEM_DATA_FILEPATH
from brightway_flows.integrations.ec_inventory import load_ec_inventory
from brightway_flows.domain.labels import flow_label_value
from brightway_flows.pipeline import Change, Transformer
from brightway_flows.pipeline.review_records import (
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)

logger = structlog.get_logger(__name__)

EC_IDENTIFIER_KEY = "European Community (EC) Number"


class ECMismatchKind(StrEnum):
    """Which direction the flow and the EC inventory disagree in."""

    #: The inventory gives an EC for one of the flow's CAS numbers, and the flow
    #: does not carry it.
    CAS_EC = "cas_ec_mismatch"
    #: The inventory gives a CAS for one of the flow's EC numbers, and the flow
    #: does not carry it.
    EC_CAS = "ec_cas_mismatch"


@dataclass
class ECMismatch(SerialisableRecord):
    """One CAS↔EC disagreement between a flow and the ECHA EC-inventory.

    The record carries both directions' fields rather than one shape per kind.
    The two used to be untyped dicts with overlapping but different keys, which
    meant a reader had to check `type` before it knew which keys existed; a
    single shape with `kind` as the discriminator makes the missing side
    explicitly empty instead of absent.

    `pubchem_confirmed` is only meaningful for :attr:`ECMismatchKind.CAS_EC`,
    where PubChem is consulted as a second opinion and a confirmed EC is added
    to the flow.  It stays None in the other direction rather than defaulting to
    False, because "not confirmed" and "not asked" are different answers.
    """

    kind: ECMismatchKind
    uuid: str
    flow_name: str = ""

    #: The flow's own identifiers.  The singular field is the one the
    #: disagreement is about; the plural is everything the flow carries.
    flow_cas: str = ""
    flow_ec_numbers: list[str] = field(default_factory=list)
    flow_ec: str = ""
    flow_cas_numbers: list[str] = field(default_factory=list)

    #: What the inventory says instead.
    inventory_ec: str = ""
    inventory_cas: str = ""
    inventory_cas_for_ec: list[str] = field(default_factory=list)
    inventory_ec_for_cas: list[str] = field(default_factory=list)
    inventory_names_for_cas: list[str] = field(default_factory=list)
    inventory_names_for_ec: list[str] = field(default_factory=list)

    pubchem_confirmed: bool | None = None

    _ALIASES: ClassVar[dict[str, str]] = {
        "kind": "type",
        "flow_ec_numbers": "flow_ecs",
        "flow_cas_numbers": "flow_cass",
    }

    @property
    def identifier(self) -> str:
        """The inventory identifier this row is about; half of its queue key."""
        return self.inventory_ec or self.inventory_cas


class ECCrossCheckTransformer(Transformer):
    """Compare CAS/EC pairs in flows against the authoritative EC-inventory.

    When one identifier is missing but unambiguously resolvable from the other,
    a :class:`Change` is emitted.  When there is a mismatch and PubChem
    confirms the inventory's EC number for the same CAS, the confirmed EC is
    added to the flow's ``ec_numbers`` list.
    """

    name = "ec_cross_check"
    answers_per_flow = True

    def __init__(self) -> None:
        self._cas_to_ecs: dict[str, set[str]] = {}
        self._ec_to_cass: dict[str, set[str]] = {}
        self._cas_to_names: dict[str, set[str]] = {}
        self._ec_to_names: dict[str, set[str]] = {}
        self._cas_to_pubchem_ecs: dict[str, set[str]] = {}
        self.mismatches: list[ECMismatch] = []

    def setup(self) -> None:
        data = load_ec_inventory()

        for rec in data["records"]:
            cas = rec.get("cas_number")
            ec = rec.get("ec_number")
            name = rec.get("name") or ""
            if cas and ec:
                self._cas_to_ecs.setdefault(cas, set()).add(ec)
                self._ec_to_cass.setdefault(ec, set()).add(cas)
            if cas and name:
                self._cas_to_names.setdefault(cas, set()).add(name)
            if ec and name:
                self._ec_to_names.setdefault(ec, set()).add(name)

        if PUBCHEM_DATA_FILEPATH.exists():
            pubchem = orjson.loads(PUBCHEM_DATA_FILEPATH.read_bytes())
            cas_to_cids: dict[str, set[int]] = {}
            for cas, compounds in pubchem.get("by_cas", {}).items():
                for compound in compounds:
                    cas_to_cids.setdefault(cas, set()).add(compound["cid"])

            identifiers = pubchem.get("identifiers", {})
            for cas, cids in cas_to_cids.items():
                for cid in cids:
                    ec_entries = identifiers.get(str(cid), {}).get(EC_IDENTIFIER_KEY, [])
                    for entry in ec_entries:
                        self._cas_to_pubchem_ecs.setdefault(cas, set()).add(entry["value"])

        logger.info(
            "ec_cross_check_loaded",
            unique_cas=len(self._cas_to_ecs),
            unique_ec=len(self._ec_to_cass),
            pubchem_cas_with_ec=len(self._cas_to_pubchem_ecs),
        )

    def transform(self, flows: list[Flow]) -> list[Change]:
        changes: list[Change] = []
        self.mismatches = []

        for flow in flows:
            cas_list = flow.cas_numbers
            ec_list = flow.ec_numbers
            uuid = flow.uuid
            name = flow_label_value(flow)

            if cas_list and ec_list:
                added_ecs = self._check_mismatches(uuid, name, cas_list, ec_list)
                if added_ecs:
                    changes.append(Change(
                        uuid, "ec_numbers", list(ec_list) + sorted(added_ecs),
                        comment="Added PubChem-confirmed EC: " + ", ".join(sorted(added_ecs)),
                    ))

            elif cas_list and not ec_list:
                resolved = self._resolve_ecs(uuid, name, cas_list)
                if resolved:
                    sources = ", ".join(
                        f"{ec} from CAS {cas}"
                        for cas in cas_list
                        for ec in sorted(self._cas_to_ecs.get(cas, set()) & resolved)
                    )
                    changes.append(Change(
                        uuid, "ec_numbers", sorted(resolved),
                        comment=f"Resolved from EC-inventory: {sources}",
                    ))

            elif ec_list and not cas_list:
                resolved = self._resolve_cass(uuid, name, ec_list)
                if resolved:
                    sources = ", ".join(
                        f"{cas} from EC {ec}"
                        for ec in ec_list
                        for cas in sorted(self._ec_to_cass.get(ec, set()) & resolved)
                    )
                    changes.append(Change(
                        uuid, "cas_numbers", sorted(resolved),
                        comment=f"Resolved from EC-inventory: {sources}",
                    ))

        return changes

    def review_queue_items(self) -> list[ReviewQueueItem]:
        """The CAS↔EC disagreements this run found, as queue rows.

        A row is keyed by the flow, the direction and the inventory identifier,
        because that triple is what a curator rules on: one flow can disagree
        about several identifiers, and each is a separate decision.

        Severity splits on whether the pipeline acted.  A mismatch PubChem
        confirmed had its EC added to the flow and wants checking; one it did
        not confirm changed nothing and is a note.
        """
        return [
            ReviewQueueItem(
                queue_name=ReviewQueue.EC_CROSS_CHECK,
                item_key=f"{mismatch.uuid}:{mismatch.kind}:{mismatch.identifier}",
                title=mismatch.flow_name,
                severity=(
                    Severity.REVIEW if mismatch.pubchem_confirmed else Severity.INFO
                ),
                uuid=mismatch.uuid,
                cas=mismatch.flow_cas or mismatch.inventory_cas,
                payload=mismatch.to_dict(),
            )
            for mismatch in self.mismatches
        ]

    def _resolve_ecs(
        self, uuid: str, name: str | None, cas_list: list[str]
    ) -> set[str]:
        """Collect unambiguous EC numbers for every CAS in the flow."""
        result: set[str] = set()
        for cas in cas_list:
            expected_ecs = self._cas_to_ecs.get(cas)
            if expected_ecs and len(expected_ecs) == 1:
                result.update(expected_ecs)
            elif expected_ecs:
                logger.warning(
                    "ec_ambiguous_from_cas",
                    uuid=uuid,
                    name=name,
                    cas=cas,
                    candidate_ecs=sorted(expected_ecs),
                    candidate_names=[
                        sorted(self._ec_to_names.get(e, set()))
                        for e in sorted(expected_ecs)
                    ],
                )
        return result

    def _resolve_cass(
        self, uuid: str, name: str | None, ec_list: list[str]
    ) -> set[str]:
        """Collect unambiguous CAS numbers for every EC in the flow."""
        result: set[str] = set()
        for ec in ec_list:
            expected_cass = self._ec_to_cass.get(ec)
            if expected_cass and len(expected_cass) == 1:
                result.update(expected_cass)
            elif expected_cass:
                logger.warning(
                    "cas_ambiguous_from_ec",
                    uuid=uuid,
                    name=name,
                    ec=ec,
                    candidate_cass=sorted(expected_cass),
                    candidate_names=[
                        sorted(self._cas_to_names.get(c, set()))
                        for c in sorted(expected_cass)
                    ],
                )
        return result

    def _check_mismatches(
        self,
        uuid: str,
        name: str | None,
        cas_list: list[str],
        ec_list: list[str],
    ) -> set[str]:
        """Check each CAS against the inventory and return confirmed ECs to add."""
        ec_set = set(ec_list)
        ecs_to_add: set[str] = set()

        for cas in cas_list:
            expected_ecs = self._cas_to_ecs.get(cas)
            if expected_ecs is None:
                continue
            missing_ecs = expected_ecs - ec_set
            if not missing_ecs:
                continue

            pubchem_ecs = self._cas_to_pubchem_ecs.get(cas, set())
            for inv_ec in missing_ecs:
                inventory_cass_for_ec = self._ec_to_cass.get(inv_ec, set())
                confirmed = inv_ec in pubchem_ecs
                self.mismatches.append(ECMismatch(
                    kind=ECMismatchKind.CAS_EC,
                    uuid=uuid,
                    flow_name=name or "",
                    flow_cas=cas,
                    flow_ec_numbers=sorted(ec_set),
                    inventory_ec=inv_ec,
                    inventory_cas_for_ec=sorted(inventory_cass_for_ec),
                    inventory_names_for_cas=sorted(self._cas_to_names.get(cas, set())),
                    inventory_names_for_ec=sorted(self._ec_to_names.get(inv_ec, set())),
                    pubchem_confirmed=confirmed,
                ))

                if confirmed:
                    ecs_to_add.add(inv_ec)

        for ec in ec_list:
            expected_cass = self._ec_to_cass.get(ec)
            if expected_cass is None:
                continue
            cas_set = set(cas_list)
            missing_cass = expected_cass - cas_set
            if not missing_cass:
                continue

            for inv_cas in missing_cass:
                inventory_ecs_for_cas = self._cas_to_ecs.get(inv_cas, set())
                self.mismatches.append(ECMismatch(
                    kind=ECMismatchKind.EC_CAS,
                    uuid=uuid,
                    flow_name=name or "",
                    flow_ec=ec,
                    flow_cas_numbers=sorted(cas_set),
                    inventory_cas=inv_cas,
                    inventory_ec_for_cas=sorted(inventory_ecs_for_cas),
                    inventory_names_for_ec=sorted(self._ec_to_names.get(ec, set())),
                    inventory_names_for_cas=sorted(self._cas_to_names.get(inv_cas, set())),
                ))

        return ecs_to_add
