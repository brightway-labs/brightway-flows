"""A factor about an identifier the build retired.

`harmonised-flows-simple.json.gz` drops a deprecated flow from `flows` and files
it under `redirects`; until #163 `lcia-factors.json.gz` went on publishing
factors against it, so one build's two artifacts disagreed about which flows
exist.  1,674 factors on 166 identifiers, and a consumer that loaded both saw
numbers about flows it did not have.

Four things have to be true, and each is a case below:

* a redirect the export tells a consumer to follow is followed here too, and the
  number lands on the survivor;
* one it tells a consumer to refuse is refused here too, and the numbers are
  reported rather than republished under a dead identifier;
* where both flows describe one factor, the survivor's own number stands -- the
  deduplication that collapsed them already settled that pair, and asking again
  would publish neither;
* where only the retired identifier described it, the number is carried and said
  out loud, because that is the one case where following a redirect adds a
  factor rather than restating one.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import orjson

from brightway_flows.domain.lcia.records import StatedFactor, stated_category
from brightway_flows.domain.lcia.crosswalk import ef_method
from brightway_flows.lcia.matching import (
    RetiredFlow,
    match,
    retired_flows,
)
from brightway_flows.lcia.report import FindingKind
from brightway_flows.lcia.sources import FactorSource
from brightway_flows.pipeline.redirects import (
    CONTEXT_COLLAPSE,
    IDENTITY_MERGE,
    UNCLASSIFIED,
)

#: EF 3.1's implementations, read from its method file rather than from an enum:
#: an implementation belongs to a method, and which four these are is what
#: `data/lcia-impact-categories.json` says.
_METHOD = ef_method()
JRC_IMPL = _METHOD.reference
ECOINVENT_IMPL = _METHOD.implementation("ecoinvent-centre")
GREENDELTA_IMPL = _METHOD.implementation("greendelta")
CONSENSUS_IMPL = _METHOD.consensus
IMPLEMENTATION_NAMES = {row.name for row in _METHOD.implementations}

JRC_CATEGORY = next(iter(ef_method().by_stated_identifier("jrc")))
OTHER_CATEGORY = list(ef_method().by_stated_identifier("jrc"))[1]

#: The list both sides of a deprecation are in, since the reason is decided only
#: on the lists they share (#59).
EF = ("EF", "3.1")


def _factor(amount: float, *, category: str = JRC_CATEGORY) -> StatedFactor:
    return StatedFactor(
        category=stated_category(
            uuid=category, name=ef_method().by_stated_identifier("jrc")[category].stated["jrc"].name
        ),
        flow_uuid="",
        amount=amount,
    )


def _source(by_flow) -> FactorSource:
    return FactorSource(
        implementation=JRC_IMPL,
        by_flow=by_flow,
        flows_are_consensus=True,
        read_from="a test",
    )


class TheRetirementsAreReadFromTheBuildTestCase(unittest.TestCase):
    """`retired_flows` is the export's classification, asked of the database."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.db = Path(self._directory.name) / "consensus-flows.sqlite3"
        connection = sqlite3.connect(self.db)
        connection.execute(
            "CREATE TABLE elementary_flows (uuid TEXT, is_deprecated INTEGER, "
            "replaced_by_uuid TEXT)"
        )
        connection.execute(
            "CREATE TABLE elementary_flow_sources (elementary_flow_uuid TEXT, "
            "list_name TEXT, list_version TEXT, source_metadata_json TEXT)"
        )
        connection.executemany(
            "INSERT INTO elementary_flows VALUES (?, ?, ?)",
            [
                ("live", 0, None),
                ("twin", 1, "live"),
                ("collapsed", 1, "live"),
                ("chained", 1, "twin"),
                ("stranger", 1, "live"),
                ("into-the-void", 1, "never-published"),
            ],
        )
        connection.executemany(
            "INSERT INTO elementary_flow_sources VALUES (?, ?, ?, ?)",
            [
                (uuid, *EF, orjson.dumps({"original_context": context}).decode())
                for uuid, context in (
                    ("live", ["Emissions to air", "unspecified"]),
                    ("twin", ["Emissions to air", "unspecified"]),
                    ("chained", ["Emissions to air", "unspecified"]),
                    ("collapsed", ["Emissions to air", "low population density"]),
                )
            ]
            + [
                (
                    "stranger",
                    "ecoinvent",
                    "3.12",
                    orjson.dumps({"original_context": ["air", "unspecified"]}).decode(),
                )
            ],
        )
        connection.commit()
        connection.close()

    def test_a_flow_reached_twice_is_a_redirect_to_follow(self):
        retired = retired_flows(self.db)
        self.assertEqual(retired["twin"], RetiredFlow("live", IDENTITY_MERGE))
        self.assertTrue(retired["twin"].followable)

    def test_two_source_contexts_collapsed_is_a_redirect_to_refuse(self):
        """EF filed the two rows in different contexts and our vocabulary cannot
        tell them apart, so their factors may legitimately differ (#1)."""
        retired = retired_flows(self.db)
        self.assertEqual(retired["collapsed"], RetiredFlow("live", CONTEXT_COLLAPSE))
        self.assertFalse(retired["collapsed"].followable)

    def test_a_chain_resolves_to_the_flow_still_published(self):
        self.assertEqual(retired_flows(self.db)["chained"].replaced_by, "live")

    def test_sharing_no_source_list_leaves_nothing_to_compare(self):
        retired = retired_flows(self.db)
        self.assertEqual(retired["stranger"].reason, UNCLASSIFIED)
        self.assertFalse(retired["stranger"].followable)

    def test_a_replacement_this_build_does_not_publish_resolves_to_nothing(self):
        retired = retired_flows(self.db)
        self.assertEqual(retired["into-the-void"].replaced_by, "")
        self.assertFalse(retired["into-the-void"].followable)

    def test_a_live_flow_is_not_a_redirect(self):
        self.assertNotIn("live", retired_flows(self.db))


class TheFactorsFollowTheRedirectTestCase(unittest.TestCase):
    FOLLOW = {"twin": RetiredFlow("live", IDENTITY_MERGE)}
    REFUSE = {"collapsed": RetiredFlow("live", CONTEXT_COLLAPSE)}

    def test_nothing_is_published_under_a_retired_identifier(self):
        matched, _findings = match(
            _source({"live": [_factor(1.5)], "twin": [_factor(1.5)]}),
            retired=self.FOLLOW,
        )
        self.assertEqual(
            {row.elementary_flow_uuid for row in matched}, {"live"}
        )

    def test_the_flows_own_number_stands_where_both_state_one(self):
        """#64's kresoxim-methyl: 134.73 on the flow, 53,540 on the identifier
        it absorbed.  `deduplication.settle_factor_values` chose when it
        collapsed them and wrote the other onto the survivor, so this publishes
        the survivor's rather than asking a settled question again."""
        matched, findings = match(
            _source({"live": [_factor(134.73)], "twin": [_factor(53540.0)]}),
            retired=self.FOLLOW,
        )
        self.assertEqual([row.factor.amount for row in matched], [134.73])
        self.assertEqual(
            [f.kind for f in findings if f.kind is FindingKind.FACTOR_COLLISION], []
        )

    def test_a_factor_only_the_retired_identifier_holds_is_carried(self):
        matched, findings = match(
            _source({
                "live": [_factor(1.5)],
                "twin": [_factor(1.5), _factor(9.5, category=OTHER_CATEGORY)],
            }),
            retired=self.FOLLOW,
        )
        carried = [row for row in matched if row.source_flow_uuid == "twin"]
        self.assertEqual([row.factor.amount for row in carried], [9.5])
        self.assertEqual(carried[0].elementary_flow_uuid, "live")
        followed = [f for f in findings if f.kind is FindingKind.REDIRECT_FOLLOWED]
        self.assertEqual(len(followed), 1)
        self.assertEqual(followed[0].context["retired_flow_uuid"], "twin")
        self.assertEqual(followed[0].elementary_flow_uuid, "live")

    def test_a_factor_the_flow_states_itself_carries_no_source_row(self):
        """`source_flow_uuid` is what tells a carried factor from a stated one,
        so it is set on one and not the other."""
        matched, _findings = match(
            _source({"live": [_factor(1.5)], "twin": [_factor(1.5)]}),
            retired=self.FOLLOW,
        )
        self.assertEqual([row.source_flow_uuid for row in matched], [None])

    def test_a_refused_redirect_publishes_nothing_and_says_so(self):
        matched, findings = match(
            _source({"live": [_factor(1.5)], "collapsed": [_factor(2.5)]}),
            retired=self.REFUSE,
        )
        self.assertEqual(
            [(row.elementary_flow_uuid, row.factor.amount) for row in matched],
            [("live", 1.5)],
        )
        refused = [f for f in findings if f.kind is FindingKind.REDIRECT_REFUSED]
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0].context["retired_flow_uuid"], "collapsed")
        self.assertEqual(refused[0].context["reason"], CONTEXT_COLLAPSE)
        self.assertEqual(refused[0].context["factors"][0]["amount"], 2.5)

    def test_the_counts_say_what_the_redirects_did(self):
        counts: Counter = Counter()
        match(
            _source({
                "live": [_factor(1.5)],
                "twin": [_factor(1.5), _factor(9.5, category=OTHER_CATEGORY)],
                "collapsed": [_factor(2.5)],
            }),
            retired={**self.FOLLOW, **self.REFUSE},
            counts=counts,
        )
        self.assertEqual(counts["retired_flows_followed"], 1)
        self.assertEqual(counts["factors_redirected"], 2)
        self.assertEqual(counts["factors_restated"], 1)
        self.assertEqual(counts["factors_carried"], 1)
        self.assertEqual(counts["retired_flows_refused"], 1)
        self.assertEqual(counts["factors_refused"], 1)

    def test_without_the_map_the_factor_stays_where_it_was_stated(self):
        """The parameter is optional, and omitting it is the behaviour #163
        describes rather than an error."""
        matched, findings = match(_source({"twin": [_factor(1.5)]}))
        self.assertEqual([row.elementary_flow_uuid for row in matched], ["twin"])
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
