"""Answering "which consensus flow is this?" without running a build.

Somebody outside this project has a flow list -- their own, a client's, a
version of SimaPro nobody here has fetched -- and one question about every row
of it.  Today the only way to ask is to add the list as a `SourceList`, fetch
it and run a build: thirteen minutes for the transform, the better part of an
hour for the whole thing, and it requires the list to be a first-class citizen
of this project before anyone can find out whether it is worth adding.

This package answers the question in half a second, against a build that has
already happened, writing nothing:

.. code-block:: python

    from brightway_flows.lookup import FlowMatcher, FlowQuery

    matcher = FlowMatcher.from_results()          # read-only, no writes

    result = matcher.match(FlowQuery(
        name="Benzene, chloro-",
        context=["Emissions to air", "low. pop."],
        cas="108-90-7",
        unit="kg",
        simapro_origin=True,
    ))

    result.elementary_flow_id   # the consensus flow's identifier
    result.basis                # "cas"
    result.selector_reason      # "exact-context-iri-match"

and :meth:`FlowMatcher.match_many` for a whole list, which is the same loop with
one index build.

Library only.  No CLI command and no HTTP endpoint: those are wrappers over
`FlowMatcher` and can be added without changing it.

It is a section rather than a module because it owns more than one file, and it
is deliberately not part of ``merge``: ``merge`` is the write path.  The arrow
runs one way -- ``lookup`` imports from ``merge`` and never the reverse -- and
nothing here can reach a function that creates a flow, mints an id or writes a
row.  ``tests/test_lookup_writes_nothing.py`` holds it to that.

What it is *not* is a second implementation of matching.  The two functions that
decide where a row goes, :func:`merge.matching.resolve_flow_object` and
:func:`merge.matching._select_elementary_flow`, are already pure -- they read
frozen indexes and return an answer -- so this calls them.  The guarantee that
buys is the whole point: an answer from here is the answer the build would have
given, or this is broken.

**What it cannot do**, stated here rather than discovered by a caller:

* It answers for *one build*, named in :attr:`FlowMatch.build`.  The consensus
  list moves, so a caller who stores an identifier and never re-asks will drift.
* It will match less often than a build would.  A row whose CAS the build learned
  from Common Chemistry, or whose alternative names came from ChEBI, matches
  inside a build and may not here.
* Water, land and airborne particles are curated per source flow, keyed on a
  uuid a query has none of.  For water and land the tables also record the
  vendor's spelling, and the lookup consults them under the row's prepared name
  (#358), declining any name the tables read two ways that the caller's
  compartment cannot split; a caller who knows better states
  :attr:`FlowQuery.material` or :attr:`FlowQuery.land_class` and wins.  A
  particle row has no such table on purpose: it carries no registry number, so
  an unstated window leaves only the name -- and a name reaching PM10 because
  it resembles PM10's is what #153 was about.  :attr:`FlowQuery.size_class`
  states the window.
* It decides nothing.  No flow is created, no id minted, nothing queued for
  review, nothing written.  A caller who wants their list *in* the consensus list
  still adds it as a `SourceList` and runs a build -- and this is how they find
  out, per row, whether that is worth doing.

See ``plans/lookup-api.md``.
"""

from __future__ import annotations

from brightway_flows.lookup.index import (
    BuildStamp,
    UnusableBuildError,
    load_lookup_index,
    lookup_source_list,
)
from brightway_flows.lookup.matcher import (
    TIER_ALGORITHM,
    TIER_RECORDED,
    TIER_RECORDED_BY_NAME,
    CandidateFlowObject,
    FlowMatch,
    FlowMatcher,
)
from brightway_flows.lookup.query import FlowQuery
from brightway_flows.lookup.recorded import RecordedDecision

__all__ = [
    "TIER_ALGORITHM",
    "TIER_RECORDED",
    "TIER_RECORDED_BY_NAME",
    "BuildStamp",
    "CandidateFlowObject",
    "FlowMatch",
    "FlowMatcher",
    "FlowQuery",
    "RecordedDecision",
    "UnusableBuildError",
    "load_lookup_index",
    "lookup_source_list",
]
