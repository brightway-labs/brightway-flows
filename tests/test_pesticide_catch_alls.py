"""A named pesticide is published as itself, not as the name of its category.

#206 is that a substance's *use class* -- herbicide, fungicide, insecticide --
had nowhere to live in the model, so the only way the pipeline could say "this
is a herbicide" was to stop publishing the substance and publish
`Herbicides, Unspecified` in its place.  #76 is what that costs a consumer:
twenty-one different insecticides published as one substance, alanycarb
indistinguishable from kaolin.

Two mechanisms did the collapsing and both are retired here, which is the point
these tests exist to hold.  Retiring one alone leaves the same substance
published specifically in the contexts that mechanism covered and collapsed in
the contexts the other covered -- which is not an improvement but a second
`Trifloxystrobin`, and it is the shape #46, #316 and #206 all describe:

- **this project's own** ``ecoinvent-unmatched-pesticide-groupings.json``, which
  used to carry thirty positive mappings onto the four buckets.  Only its twelve
  ``not_pesticide`` rows remain, and a row naming no flow object decides
  nothing, so the file now places nothing at all.
- **the prepared correspondence table**, which routed 307 flows of 49 named
  substances onto EF 3.1's catch-alls.  Those rows were held off first by 314
  declines in ``ecoinvent-match-overrides.json`` and then settled for good by
  #141, which retired the published tables outright: with no table, nothing can
  send a named substance to a bucket, and the addition path mints each its own
  flow because nothing routes its rows anywhere else.

The last test is the one that has to keep working.  It recomputes the set from
the shipped tables rather than reading a list somebody typed, so a new ecoinvent
release that adds an eighth context to Thiacloprid, or a new randonneur table
that sends a fiftieth substance to a bucket, fails here instead of quietly
reintroducing #76.
"""

from __future__ import annotations

import unittest

import orjson

from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.merge.additions import _load_manual_additions
from brightway_flows.pipeline.semantic_typing import (
    _GROUPING_LABEL,
    _UNREGISTERED_GROUPING_LABEL,
)
from brightway_flows.match_overrides import load_match_overrides
from brightway_flows.sources import (
    _declared_match_table,
    base_source_list,
    known_source_lists,
)

GROUPINGS = PACKAGE_DATA_DIR / "ecoinvent-unmatched-pesticide-groupings.json"
OVERRIDES = PACKAGE_DATA_DIR / "ecoinvent-match-overrides.json"

#: Source flows whose own name *is* the class the table sends them to, spelled
#: differently.  These are the rows the rule must not fire on, and naming them is
#: what #123 turned out to need: a class mapped onto the same class is the
#: correct answer, and it is only distinguishable from a named chemical folded
#: into a class by reading what the source is.
#:
#: ecoinvent writes each as an initialism and its expansion -- `AOX, Adsorbable
#: Organic Halogen`, `NMVOC, non-methane volatile organic compounds` -- and EF
#: writes the expansion alone, so a plain name comparison sees two different
#: strings and would decline a mapping that is right.  `Hydrocarbons,
#: unspecified` is the same concept with the punctuation moved.
#:
#: Lowercased, and compared against the source's name as the table spells it.
CLASSES_MAPPED_ONTO_THE_SAME_CLASS = frozenset({
    "aox, adsorbable organic halides",
    "aox, adsorbable organic halogen",
    "aox, adsorbable organic halogen as cl",
    "hydrocarbons, unspecified",
    "nmvoc, non-methane volatile organic compounds",
    "nmvoc, non-methane volatile organic compounds, unspecified origin",
    "voc, volatile organic compounds",
    "voc, volatile organic compounds, unspecified origin",
})


def _grouping_class_flow_uuids() -> dict[str, str]:
    """Every EF 3.1 flow this project would type as a class, by uuid.

    Read out of the base list, and typed by **this project's own rule** rather
    than by a second one written here -- `pipeline.semantic_typing` decides what
    is a class of substances rather than a substance, and a guard that used a
    different definition would drift from what the build publishes.

    That is the widening #123 asked for.  #76 read the five pesticide names, so
    the hydrocarbon buckets were never covered and glucose went on being
    published as an unsaturated hydrocarbon.  254 flows are classes; the five
    pesticide buckets are forty of them.
    """
    rows = orjson.loads(base_source_list().flows_path.read_bytes())
    found: dict[str, str] = {}
    for row in rows:
        name = str(row.get("name") or "")
        if _GROUPING_LABEL.search(name) or (
            not row.get("cas_numbers") and _UNREGISTERED_GROUPING_LABEL.search(name)
        ):
            found[row["uuid"]] = name
    return found


def _named_substances_sent_to_a_catch_all() -> dict[str, str]:
    """Source uuid -> source name, over every registered ecoinvent version.

    Every version is asked because one override set covers them all: a flow
    uuid is stable across releases, so a decision about a flow is a decision
    about it wherever it is shipped.

    The table is read *before* the overrides are applied, which is the whole
    reason this reaches for `_declared_match_table` rather than the public
    `load_prepared_match_table`: the latter has already taken the declined rows
    away, so asking it what the table routes to a catch-all would answer
    "nothing" and the guard below would pass by tautology.

    **What separates a defect from a correct class-to-class mapping is what the
    *source* is, not whether it carries a registry number.**  #123 proposed
    keying on the number, and the shipped tables refute it both ways:
    `Pydiflumetofen` is a named fungicide with no registry number at all and is
    correctly declined by #76, while `Curium Alpha`, `Plutonium-alpha`,
    `Uranium Alpha` and `Tributyltin Compounds` each carry one and are correctly
    left alone, because each is a class mapped onto itself.  So the test is the
    name: a row whose source is called what the class is called is the class,
    and `CLASSES_MAPPED_ONTO_THE_SAME_CLASS` holds the four where ecoinvent and
    EF spell that same class differently.
    """
    classes = _grouping_class_flow_uuids()
    found: dict[str, str] = {}
    for source in known_source_lists().values():
        if source.list_name != "ecoinvent":
            continue
        for row in _declared_match_table(source):
            target = (row.get("target") or {}).get("uuid")
            if target not in classes:
                continue
            origin = row.get("source") or {}
            name = str(origin.get("name") or "")
            lowered = name.strip().lower()
            if lowered == classes[target].strip().lower():
                continue
            if lowered in CLASSES_MAPPED_ONTO_THE_SAME_CLASS:
                continue
            uuid = str(origin.get("uuid") or "")
            if uuid:
                found[uuid] = name
    return found


class GroupingsFilePlacesNothing(unittest.TestCase):
    """The half of the collapse this project owned."""

    def setUp(self):
        self.payload = orjson.loads(GROUPINGS.read_bytes())

    def test_no_row_names_a_flow_object(self):
        named = [
            row["source_name"]
            for row in self.payload["mappings"]
            if row.get("flow_object_id")
        ]
        self.assertEqual(named, [], "these rows still collapse a named pesticide")

    def test_the_loader_therefore_yields_no_rules(self):
        # The behavioural half of the test above: a row naming no flow object is
        # dropped at load, so the file that remains cannot place anything even
        # though it is still declared in every ecoinvent manifest.
        self.assertEqual(_load_manual_additions(GROUPINGS), ())

    def test_the_negative_controls_survive_with_their_reasoning(self):
        # The twelve are why the file is kept at all.  Each records a substance
        # somebody checked and decided is not a pesticide, and dropping them
        # would leave the role assertions with no stated negative control.
        controls = [
            row for row in self.payload["mappings"]
            if row.get("pesticide_type") == "not_pesticide"
        ]
        self.assertEqual(len(controls), 12)
        for row in controls:
            with self.subTest(row["source_name"]):
                self.assertTrue(row.get("notes", "").strip())


class PreparedTableRowsAreDeclined(unittest.TestCase):
    """The half that is somebody else's table, answered by declining its rows."""

    @classmethod
    def setUpClass(cls):
        cls.expected = _named_substances_sent_to_a_catch_all()
        overrides = load_match_overrides(OVERRIDES)
        cls.declined = {
            override.source_uuid for override in overrides if override.decline
        }
        cls.rewritten = {
            override.source_uuid
            for override in overrides
            if not override.decline and override.target_uuid
        }

    def test_the_population_is_the_one_405_and_604_measured(self):
        # Stated so that a table which stops routing these rows, or starts
        # routing more of them, is a visible change rather than a silently
        # shorter list of answers.
        #
        # 307 rows over 49 names when this read the five pesticide names; 314
        # over 53 once #123 widened it; **zero since #141 retired the published
        # tables outright** -- with no table, nothing can send a named
        # substance to a catch-all in the first place, and the 314 decline
        # rows that held the line went with the rows they declined.  What
        # remains checkable is that this project's own correspondence never
        # reintroduces the defect, which is the test below.
        self.assertEqual(len(self.expected), 0)

    def test_every_one_of_them_is_answered(self):
        # **Declined *or* rewritten**, which is the correction #124 forced on
        # this test.  #76's rows are all declines because EF 3.1 ships no flow
        # for those substances, so there is nothing to point at; that is a fact
        # about EF's coverage rather than about what a fix must look like.
        # 1,1,2-trichloroethane is the counter-example -- EF ships it in all
        # thirteen compartments, and declining rather than repointing would have
        # thrown away seven correct characterisation factors a row.
        #
        # What the guard is really about is that no named substance goes on
        # being published as a class, and both verdicts achieve that.
        answered = self.declined | self.rewritten
        missing = sorted(
            f"{uuid} ({name})"
            for uuid, name in self.expected.items()
            if uuid not in answered
        )
        self.assertEqual(missing, [], "these rows still reach a catch-all")

    def test_nothing_else_was_declined_for_this_reason(self):
        # This test used to name all thirty-six declines that were *not*
        # catch-all rows, in six documented families -- the water and
        # standing-wood pair that predated #76, #111's eleven land classes,
        # #119's eight substances EF does not carry, #125's nine
        # one-compartment herbicides, #123's three classes given a member's
        # identity, and #118's ore published as its metal.  Retiring the
        # published tables (#141) spent every decline at once: a decline takes
        # a table's rows away, and there are no rows left to take.  The 346
        # spent rows were removed with the tables; their reasoning lives in the
        # issues above and in this file's git record, and every outcome they
        # protected is now the merge's own -- the minted substances exist
        # because nothing routes their rows anywhere else.
        #
        # What must stay true is that every decline left is named and
        # explained.  One family remains -- the four carbon rows #334 wrote
        # while the tables still shipped -- and with the tables retired they
        # decline nothing: a decline takes a table's rows away, and there is
        # no table.  They stand as the written-down withdrawal of #258, and
        # the landing they argue for happens without them -- the rows reach
        # ordinary matching, the name detects as
        # `sequestration_from_land_management`, no flow object carries that
        # qualifier, and #133's rule mints the substance.  `Carbon dioxide,
        # to soil or biomass stock` records carbon entering a long-lived land
        # carbon pool, and EF's carbon model is closed: JRC130796 Table 3 is
        # three origins by two directions, a removal can only be expressed
        # there as a resource from air, and there is no row for carbon
        # entering a pool -- so there is no target to rewrite to (#258 tried
        # EF's biogenic soil flows and put a credit on a substance EF states
        # to be neutral).  See #139 and #333.
        #
        # Any other decline reappearing is a mistake or a mechanism this
        # module no longer describes.
        carbon_into_a_land_pool = {
            "259cf8d6-6ea8-4ccf-84b7-23c930a5b2b3",
            "8ae4d8bb-3e4b-4825-8325-94696d7a64fd",
            "60d424f7-d5a9-4549-9540-da06684bc3bb",
            "375bc95e-6596-4aa1-9716-80ff51b9da77",
        }
        self.assertEqual(sorted(self.declined), sorted(carbon_into_a_land_pool))


class ChlorthalIsTheWorkedExample(unittest.TestCase):
    """#316: one substance, six contexts to one bucket and the seventh to another.

    Kept as its own case because the split is what makes the defect legible --
    nothing about Chlorthal changes between being sprayed on a field and
    drifting into the air, and before this change a reader who looked up the two
    emissions found two different substances.
    """

    def test_all_seven_of_its_flows_reach_one_substance_of_their_own(self):
        # #316's defect needed a route into a bucket, and the routes are gone:
        # no table ships (#141), and this project's own correspondence names no
        # chlorthal row.  Asserted here so a future override that touches the
        # substance has to face the worked example.
        expected = _named_substances_sent_to_a_catch_all()
        self.assertEqual(
            {uuid for uuid, name in expected.items() if name.lower() == "chlorthal"},
            set(),
        )
        touched = {
            override.source_uuid
            for override in load_match_overrides(OVERRIDES)
            if "chlorthal" in (override.source_name or "").lower()
        }
        self.assertEqual(touched, set())


if __name__ == "__main__":
    unittest.main()
