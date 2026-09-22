"""The substance-in-two-places page: one row per place, not three lists.

The queue's item is a substance published in several contexts, and until this
page it was rendered through the shared `queue.html` as three deduplicated
lists -- every context, every unit, every source list -- with nothing saying
which went with which.  On `Peat` that is `Resource -> Biotic, Resource ->
Ground` beside `MJ, kg` beside `EF 3.1, ecoinvent algorithm addition`: two of
the six pairings a reader could draw are right, and drawing the wrong one
reverses which place holds the characterisation and which place the merge
invented.

What is pinned here:

- **The three travel together.**  A place's unit and the source lists that
  publish it there are on the place's own row, so the pairing is read rather
  than guessed.  This is the whole point of the page.
- **Every place is shown**, stranded or not: a place is only stranded relative
  to the others, so a page showing the stranded one alone would state a
  contradiction without its other half.
- **The stranded place is marked**, and a minted place that found somewhere to
  belong is not marked as stranded -- that is the `Water -> River` beside
  `Water -> Unknown` case, which is a flow that landed where it wanted.
- **The flows are named per place**, because the flow a curator opens is the one
  sitting in the place they are ruling on.
- **A payload older than the per-place field still renders its contexts**,
  rather than an empty table.
"""

import tempfile
import unittest
from pathlib import Path

from brightway_flows.pipeline.review_records import (
    PipelineRun,
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)
from brightway_flows.pipeline.review_tables import (
    REVIEW_SCHEMA_VERSION,
    write_review_tables,
)
from brightway_flows.webapps.app import create_app, db
from brightway_flows.webapps.app.queries import places as place_queries
from brightway_flows.webapps.app.queries import queue as queue_queries

BIOTIC = "https://vocab.brightway.one/flow-contexts/reso-biot"
GROUND = "https://vocab.brightway.one/flow-contexts/reso-grou"
WATER = "https://vocab.brightway.one/flow-contexts/reso-wate"
RIVER = "https://vocab.brightway.one/flow-contexts/reso-wate-rive"

MINTED_SOURCE = "ecoinvent algorithm addition"

#: `Peat`, from the 2026-08-24 build.  EF 3.1 publishes it as a ground resource
#: in megajoules and carries the characterisation factor; the merge wrote a
#: second flow into `Resource -> Biotic` in kilograms on behalf of a list that
#: files peat as biomass, and nothing characterises that one.  Two units, two
#: source lists, two places, and the old row could not say which was which.
PEAT = ReviewQueueItem(
    queue_name=ReviewQueue.SUBSTANCE_IN_TWO_PLACES,
    item_key="fo-peat",
    title="Peat is published in 2 places: Resource → Biotic, Resource → Ground",
    severity=Severity.REVIEW,
    flow_object_id="fo-peat",
    item_index=0,
    payload={
        "flow_object_id": "fo-peat",
        "substance": "Peat",
        "contexts": ["Resource → Biotic", "Resource → Ground"],
        "units": ["MJ", "kg"],
        "sources": ["EF 3.1", MINTED_SOURCE],
        "places": [
            {
                "context_iri": BIOTIC,
                "context": "Resource → Biotic",
                "elementary_flow_ids": ["u-biotic"],
                "units": ["kg"],
                "sources": [MINTED_SOURCE],
                "lcia_factor_count": 0,
                "minted_by_merge": ["u-biotic"],
                "belongs_nowhere_else": True,
            },
            {
                "context_iri": GROUND,
                "context": "Resource → Ground",
                "elementary_flow_ids": ["u-ground"],
                "units": ["MJ"],
                "sources": ["EF 3.1"],
                "lcia_factor_count": 1,
                "minted_by_merge": [],
                "belongs_nowhere_else": False,
            },
        ],
        "belongs_nowhere_else": [BIOTIC],
        "minted_by_merge": ["u-biotic"],
    },
)

#: The other shape the report can produce: a substance holding a minted place
#: that *did* find somewhere to belong.  `Resource -> Water -> River` is
#: `Resource -> Water` described more precisely, so the river flow is ordinary
#: and only the biotic place is stranded.
GROUNDWATER = ReviewQueueItem(
    queue_name=ReviewQueue.SUBSTANCE_IN_TWO_PLACES,
    item_key="fo-water",
    title="Water is published in 3 places",
    severity=Severity.REVIEW,
    flow_object_id="fo-water",
    item_index=1,
    payload={
        "flow_object_id": "fo-water",
        "substance": "Water",
        "contexts": ["Resource → Biotic", "Resource → Water", "Resource → Water → River"],
        "places": [
            {
                "context_iri": BIOTIC,
                "context": "Resource → Biotic",
                "elementary_flow_ids": ["w-biotic"],
                "units": ["m3"],
                "sources": [MINTED_SOURCE],
                "lcia_factor_count": 0,
                "minted_by_merge": ["w-biotic"],
                "belongs_nowhere_else": True,
            },
            {
                "context_iri": WATER,
                "context": "Resource → Water",
                "elementary_flow_ids": ["w-water"],
                "units": ["m3"],
                "sources": ["EF 3.1"],
                "lcia_factor_count": 2,
                "minted_by_merge": [],
                "belongs_nowhere_else": False,
            },
            {
                "context_iri": RIVER,
                "context": "Resource → Water → River",
                "elementary_flow_ids": ["w-river"],
                "units": ["m3"],
                "sources": [MINTED_SOURCE],
                "lcia_factor_count": 0,
                "minted_by_merge": ["w-river"],
                "belongs_nowhere_else": False,
            },
        ],
        "belongs_nowhere_else": [BIOTIC],
        "minted_by_merge": ["w-biotic"],
    },
)


def _write_fixture(path: Path, *, items) -> None:
    write_review_tables(
        path,
        run=PipelineRun(
            run_id="run-1",
            timestamp="2026-08-24T00:00:00+00:00",
            schema_version=REVIEW_SCHEMA_VERSION,
        ),
        stats=[],
        changes=[],
        queue_items=list(items),
        formula_mismatches=[],
        element_coverage=[],
        context_mappings=[],
    )


def _cells(row: str) -> str:
    """One table row's text, with the markup taken out of it.

    The assertions are about what sits on one row together, and a row is where
    that is stated -- so they are made on the row rather than on the page, where
    every value of every place is present whatever the pairing.
    """
    out: list[str] = []
    depth = 0
    for character in row:
        if character == "<":
            depth += 1
        elif character == ">":
            depth -= 1
        elif not depth:
            out.append(character)
    return " ".join("".join(out).split())


class PlacesPageTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consensus-flows.sqlite3"
        _write_fixture(self.path, items=(PEAT, GROUNDWATER))

    def connection(self):
        connection = db.connect(self.path)
        self.addCleanup(connection.close)
        return connection

    def client(self, path: Path | None = None):
        app = create_app(path or self.path)
        app.config["TESTING"] = True
        return app.test_client()

    def body(self, path: Path | None = None) -> str:
        response = self.client(path).get(f"/queue/{queue_queries.PLACES}")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def splits(self, **kwargs):
        connection = self.connection()
        return place_queries.splits(
            queue_queries.items(connection, queue_queries.PLACES, **kwargs)
        )

    def rows(self, body: str, substance: str) -> list[str]:
        """The place rows of one substance's section, as plain text."""
        section = body.split(f"<h2>{substance}</h2>", 1)[1].split("</section>", 1)[0]
        return [
            _cells(chunk.split("</tr>", 1)[0])
            for chunk in section.split("<tr>")[1:]
            if "<th" not in chunk.split("</tr>", 1)[0]
        ]

    def test_the_place_its_unit_and_its_source_list_are_on_one_row(self):
        """The whole point of the page.

        Through the shared template these were three cells holding
        `Resource → Biotic, Resource → Ground`, `MJ, kg` and
        `EF 3.1, ecoinvent algorithm addition`, and the pairing was the reader's
        guess.
        """
        biotic, ground = self.rows(self.body(), "Peat")
        self.assertIn("Resource → Biotic", biotic)
        self.assertIn("kg", biotic)
        self.assertIn(MINTED_SOURCE, biotic)
        self.assertNotIn("MJ", biotic)
        self.assertNotIn("EF 3.1", biotic)

        self.assertIn("Resource → Ground", ground)
        self.assertIn("MJ", ground)
        self.assertIn("EF 3.1", ground)
        self.assertNotIn(MINTED_SOURCE, ground)

    def test_the_side_holding_the_characterisation_is_on_the_row_too(self):
        """The consequence of the split, and it belongs to one place: an
        inventory that used the other flow scores zero."""
        biotic, ground = self.rows(self.body(), "Peat")
        self.assertEqual(
            [place.factor_count for place in self.splits().rows[0].places], [0, 1]
        )
        self.assertIn("0", biotic.split("kg")[1])
        self.assertIn("1", ground.split("MJ")[1])

    def test_every_place_is_shown_not_only_the_stranded_one(self):
        """A place is stranded relative to the others, so the others are what
        makes the finding readable."""
        self.assertEqual(len(self.rows(self.body(), "Water")), 3)
        self.assertEqual([len(split.places) for split in self.splits().rows], [2, 3])

    def test_the_stranded_place_is_marked_and_the_others_are_not(self):
        biotic, ground = self.rows(self.body(), "Peat")
        self.assertIn("belongs nowhere else", biotic)
        self.assertNotIn("belongs nowhere else", ground)

    def test_a_minted_place_that_found_its_home_is_not_marked_stranded(self):
        """`Resource → Water → River` is `Resource → Water` described more
        precisely: the merge wrote the river flow and it landed where it wanted,
        so it is not the place the ruling is about."""
        rows = self.rows(self.body(), "Water")
        river = next(row for row in rows if "River" in row)
        self.assertNotIn("belongs nowhere else", river)
        self.assertIn("written by the merge", river)

    def test_the_flows_are_named_per_place(self):
        body = self.body()
        biotic, ground = self.rows(body, "Peat")
        self.assertIn("u-biotic", biotic)
        self.assertIn("u-ground", ground)
        # And each is a link to the flow, which is what a curator opens.
        self.assertIn("/flows/u-biotic", body)
        self.assertIn("/flows/u-ground", body)

    def test_the_substance_is_named_and_linked_once(self):
        body = self.body()
        self.assertIn("/flow-objects/fo-peat", body)
        self.assertIn("<h2>Peat</h2>", body)

    def test_the_places_keep_the_order_the_report_wrote_them_in(self):
        """The title names them in that order, and a page that re-sorted would
        contradict its own heading."""
        self.assertEqual(
            [place.context for place in self.splits().rows[0].places],
            ["Resource → Biotic", "Resource → Ground"],
        )

    def test_search_and_severity_still_select_the_items(self):
        """The reader is the only thing this queue does differently: the paging,
        the search and the severity filter are the shared ones."""
        self.assertEqual([split.substance for split in self.splits(query="peat").rows],
                         ["Peat"])
        self.assertEqual(self.splits(query="peat").total, 1)
        self.assertEqual(self.splits(severity=str(Severity.INFO)).total, 0)
        # The search reads the payload, so a unit only one place states finds
        # the substance that place belongs to.
        self.assertEqual([split.substance for split in self.splits(query="MJ").rows],
                         ["Peat"])

    def test_an_older_payload_still_renders_its_contexts(self):
        """A payload written before the per-place field carries the contexts and
        the unpaired lists. The contexts are what it can show, and showing them
        beats an empty table."""
        older = ReviewQueueItem(
            queue_name=ReviewQueue.SUBSTANCE_IN_TWO_PLACES,
            item_key="fo-peat",
            title=PEAT.title,
            severity=Severity.REVIEW,
            flow_object_id="fo-peat",
            item_index=0,
            payload={
                key: value
                for key, value in PEAT.payload.items()
                if key != "places"
            },
        )
        path = Path(self._tmp.name) / "older-payload.sqlite3"
        _write_fixture(path, items=(older,))
        connection = db.connect(path)
        self.addCleanup(connection.close)
        split = place_queries.splits(
            queue_queries.items(connection, queue_queries.PLACES)
        ).rows[0]
        self.assertEqual(
            [place.context for place in split.places],
            ["Resource → Biotic", "Resource → Ground"],
        )
        self.assertEqual([place.units for place in split.places], [(), ()])
        biotic, ground = self.rows(self.body(path), "Peat")
        self.assertIn("Resource → Biotic", biotic)
        self.assertIn("Resource → Ground", ground)

    def test_the_page_is_reachable_and_listed(self):
        index = self.client().get("/queue/").get_data(as_text=True)
        self.assertIn(f"/queue/{queue_queries.PLACES}", index)

    def test_the_queue_renders_its_own_template_and_no_columns(self):
        """The shared template is a column list and nothing else, and the three
        columns this queue used to carry are the unpaired lists themselves."""
        definition = queue_queries.definition(queue_queries.PLACES)
        self.assertEqual(definition.template, "queue_places.html")
        self.assertEqual(definition.columns, [])
