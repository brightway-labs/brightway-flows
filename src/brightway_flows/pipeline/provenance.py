"""The PROV-O activity trail for a transform run.

One activity per applied field change: the transformer is the agent, the flow
version before the change is the entity it used, and the version after it is the
entity it generated.

This used to build a whole JSON-LD graph and write it to `provenance.json` --
entities for every flow version, agents, two dataset collections, and a
consolidated per-field summary, with the old and new value restated on every
activity.  It went into the database instead (see
:mod:`brightway_flows.pipeline.review_tables`), and most of that graph did
not survive the move, for two reasons.

*It was derivable.* An entity IRI is a function of a flow uuid and a version
number, an agent IRI is a function of a transformer name, and the two dataset
collections are the set of flows before and after the run. Nothing was recorded
that the activity rows plus `elementary_flows` do not already say, so the helpers
in :mod:`brightway_flows.pipeline.review_records` mint the IRIs on demand.

*It was duplicated.* Restating `ef:oldValue` and `ef:newValue` per activity
doubled the largest payload in the run. An activity and its change share a key,
so the values are one join away and stored once.

The consolidated field summary -- change count, latest transformer, latest time
per (flow, field) -- was a materialised `GROUP BY` over the same activities. It
is now that query.
"""

from __future__ import annotations

from brightway_flows.pipeline.review_records import ChangeEvent, ProvenanceActivity


def build_provenance_activities(
    changes: list[ChangeEvent],
) -> list[ProvenanceActivity]:
    """The activity trail for a numbered change log, in application order.

    Each activity consumes the flow version the previous activity for that flow
    produced.  Version 0 is the flow as loaded, so a flow's first change
    generates version 1 and consumes version 0.

    *changes* must already carry a `change_index` -- assigned by
    ``number_change_events`` once the whole run's log is known -- because that
    index is this record's key and its link back to the change.

    One activity per (edit, flow), which is why the pair is deduplicated on the
    way through.  `number_change_events` gives one index to an edit that landed
    on several flows, so the same `(change_index, uuid)` can arrive twice if a
    transformer applied an identical change to one flow twice.  Counting that
    as two versions would number the flow's history past the number of things
    that happened to it.

    Iterated in application order -- the order this list is already in -- and
    deliberately *not* sorted by `change_index`, which orders by an edit's first
    appearance anywhere rather than by when it reached this flow.  Sorting by it
    permutes 29,280 of the 2026-08-07 log's 1,407,835 activities across 14,539
    flows: one flow's `prefLabel`, `name` and `synonyms` changes come back as
    v2, v3, v1.  Since each activity consumes what the previous one produced,
    that is not a cosmetic difference -- it asserts a history that did not
    happen.

    This is the same rule `review_tables._changelog_flow_rows` writes into
    `changelog_flows.entity_version`, which is what the `provenance_activities`
    view reads; `tests/test_provenance_activities_view.py` pins the two
    together.
    """
    activities: list[ProvenanceActivity] = []
    version_by_uuid: dict[str, int] = {}
    seen: set[tuple[int, str]] = set()
    for change in changes:
        pair = (change.change_index, change.uuid)
        if pair in seen:
            continue
        seen.add(pair)
        version = version_by_uuid.get(change.uuid, 0) + 1
        version_by_uuid[change.uuid] = version
        activities.append(
            ProvenanceActivity(
                change_index=change.change_index,
                uuid=change.uuid,
                field_name=change.field_name,
                transformer=change.transformer,
                entity_version=version,
            )
        )
    return activities
