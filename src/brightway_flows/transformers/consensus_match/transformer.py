"""The transformer itself: lifecycle, wiring, and the loop over flow objects.

Nothing is decided here.  `setup()` loads the source tables and the caches,
`transform()` groups the run's flows and hands each substance to the rules in
order, and the two review methods hand what the rules could not decide to the
queues.
"""

from __future__ import annotations

import structlog
from tqdm import tqdm

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.preferred_label_decisions import (
    UndecidedLabelPair,
    decision_key,
    load_preferred_label_decisions,
    undecided_label_item_key,
)
from brightway_flows.pipeline import Change, Transformer
from brightway_flows.pipeline.review_records import (
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)
from brightway_flows.transformers.consensus_match import grouping, rules
from brightway_flows.transformers.consensus_match.grouping import (
    GroupEvidence,
    GroupKey,
    ObjectUnit,
)
from brightway_flows.transformers.consensus_match.indexes import SourceIndexes
from brightway_flows.transformers.consensus_match.lookups import LookupClient
from brightway_flows.transformers.consensus_match.profiles import CompoundProfiles
from brightway_flows.transformers.consensus_match.records import (
    ConsensusMatchReviewItem,
)
from brightway_flows.transformers.consensus_match.relationships import (
    RelationshipClassifier,
)
from brightway_flows.flow_layers.contested_cas import Verdict as ContestedVerdict
from brightway_flows.flow_layers.contested_cas import (
    load_decisions as load_contested_cas_decisions,
)
from brightway_flows.transformers.consensus_match.rename_gate import RenameGate
from brightway_flows.transformers.consensus_match.voting import ConsensusVotes

logger = structlog.get_logger(__name__)


class ConsensusMatchTransformer(Transformer):
    """Apply safe-overwrite flow updates based on multi-source consensus evidence."""

    name = "consensus_match"
    # Consensus is agreement between lists, so the lists already merged have to
    # be in front of it.  This is the transformer the merge exists to feed, and
    # showing it only the incoming rows would leave it with nothing to agree
    # with.
    answers_per_flow = False

    def __init__(self) -> None:
        self.indexes = SourceIndexes()
        self.lookups = LookupClient()
        self.profiles = CompoundProfiles(indexes=self.indexes, lookups=self.lookups)
        self.votes = ConsensusVotes(indexes=self.indexes, lookups=self.lookups)
        self.classifier = RelationshipClassifier(
            indexes=self.indexes, lookups=self.lookups, profiles=self.profiles
        )
        self.gate = RenameGate()

        self.review: list[ConsensusMatchReviewItem] = []
        self._flow_objects: list[FlowObject] = []
        self._members_by_object_id: dict[str, list[Flow]] = {}
        self._object_id_by_uuid: dict[str, str] = {}

    def set_flow_object_context(
        self,
        flow_objects: list[FlowObject],
        members_by_object_id: dict[str, list[Flow]],
        object_id_by_uuid: dict[str, str],
    ) -> None:
        self._flow_objects = list(flow_objects)
        self._members_by_object_id = {
            str(k): list(v)
            for k, v in members_by_object_id.items()
            if isinstance(k, str)
        }
        self._object_id_by_uuid = {
            str(k): str(v)
            for k, v in object_id_by_uuid.items()
            if isinstance(k, str) and isinstance(v, str)
        }

    def setup(self) -> None:
        self.indexes.load()
        self.lookups.load()
        self.profiles.load()
        self.gate.decisions = load_preferred_label_decisions()
        # A number ruled contested carries two substances, so the name it "has"
        # is one of theirs and cannot be written over the other (#34).
        self.gate.separated_cas = frozenset(
            cas for cas, ruling in load_contested_cas_decisions().items()
            if ruling.verdict is ContestedVerdict.SEPARATE
        )

        logger.info(
            "consensus_match_setup_complete",
            chebi_records=len(self.indexes.chebi_records),
            ec_cas=len(self.indexes.ec_names_by_cas),
            pubchem_cas=len(self.indexes.pubchem_names_by_cas),
            commonchemistry_configured=bool(self.lookups.api_key),
            services_available=self.lookups.service_available,
        )

    def transform(self, flows: list[Flow]) -> list[Change]:
        self.review = []
        self.gate.reset()
        self.lookups.web_lookups_this_run = 0
        self.lookups.reload_commonchem_cache()
        self.lookups.prefetch_commonchem(flows)

        object_rows = grouping.build_object_rows(
            flow_objects=self._flow_objects,
            members_by_object_id=self._members_by_object_id,
            flows=flows,
        )
        group_analysis = self._analyze_groups(object_rows)
        altlabel_cas_in_dataset = grouping.build_altlabel_cas_index(
            flow_objects=self._flow_objects,
            object_rows=object_rows,
            indexes=self.indexes,
        )

        out = rules.Proposals()
        for row in tqdm(object_rows, desc="Consensus matching (flow objects)"):
            unit = ObjectUnit.from_row(row, group_analysis[grouping.flow_group_key(row)])
            if not unit.flow_name:
                continue
            rules.assign_consensus_cas(
                unit,
                votes=self.votes,
                classifier=self.classifier,
                altlabel_cas_in_dataset=altlabel_cas_in_dataset,
                out=out,
            )
            rules.apply_name_rules(
                unit,
                votes=self.votes,
                classifier=self.classifier,
                lookups=self.lookups,
                gate=self.gate,
                out=out,
            )
            rules.assign_cas_match_labels(unit, out=out)

        self.review = out.review
        self._save_caches()
        self.lookups.close()

        # This used to also accumulate `self.applied_changes`, a second copy of
        # every change this transformer proposed, written to
        # `consensus-match-applied-changes.json` -- 1.26 GB, which the ETL
        # review app parsed on every request.  The engine already records every
        # applied change in the `changelog` table, keyed by transformer, so the
        # copy said nothing the database did not, and said it more slowly.

        logger.info(
            "consensus_match_completed",
            proposed_changes=len(out.changes),
            review_items=len(self.review),
            web_lookups=self.lookups.web_lookups_this_run,
            # An undecided pair is a rename that did *not* happen, and work
            # deferred silently is work forgotten.  The pairs themselves are in
            # the review queue; this is the signal that there are any.
            undecided_label_replacements=len({
                decision_key(row.current, row.replacement)
                for row in self.gate.undecided
            }),
            # Renames refused because the number they were derived from carries
            # two substances.  Zero until a contested number is ruled, so a
            # non-zero count is a ruling taking effect rather than a regression.
            renames_declined_contested_cas=len(self.gate.declined_contested),
        )
        return out.changes

    def _analyze_groups(self, object_rows: list[Flow]) -> dict[GroupKey, GroupEvidence]:
        groups: dict[GroupKey, list[Flow]] = {}
        for row in object_rows:
            groups.setdefault(grouping.flow_group_key(row), []).append(row)
        return {
            group_key: grouping.analyze_group(
                group_key,
                members,
                indexes=self.indexes,
                profiles=self.profiles,
                classifier=self.classifier,
            )
            for group_key, members in groups.items()
        }

    def _save_caches(self) -> None:
        self.lookups.save_caches()
        self.profiles.save()

    def undecided_label_pairs(self) -> list[UndecidedLabelPair]:
        return self.gate.undecided_pairs()

    def review_queue_items(self) -> list[ReviewQueueItem]:
        """Two queues: blocked consensus decisions, and renames awaiting a ruling.

        Both were `consensus-match-review.json`, written only when someone
        passed `--export-consensus-review`, which is why the count of undecided
        renames was logged on every run -- the log line was the only reliable
        signal that the queue was not empty.  They are always written now, so
        the log line is redundant with a query.

        A rename pair is keyed by the pair itself, not by a flow: that is what a
        ruling in `preferred-label-decisions.json` binds.
        """
        items = [
            ReviewQueueItem(
                queue_name=ReviewQueue.CONSENSUS_MATCH,
                # The flow object plus the decision: one substance can be
                # blocked on its CAS and on its name independently.
                item_key=f"{item.uuid}:{item.decision}",
                title=item.flow_name,
                severity=Severity.BLOCKING,
                uuid=item.member_uuids[0] if item.member_uuids else "",
                flow_object_id=item.uuid,
                cas=item.candidate_cas or item.cas,
                payload=item.to_dict(),
            )
            for item in self.review
        ]
        items.extend(
            ReviewQueueItem(
                queue_name=ReviewQueue.UNDECIDED_LABEL_REPLACEMENT,
                item_key=undecided_label_item_key(
                    pair.rule, pair.current, pair.replacement
                ),
                title=f"{pair.current} → {pair.replacement}",
                severity=Severity.BLOCKING,
                uuid=pair.example_uuid,
                cas=pair.cas_numbers[0] if pair.cas_numbers else "",
                payload=pair.to_dict(),
            )
            for pair in self.undecided_label_pairs()
        )
        return items
