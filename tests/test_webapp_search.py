"""`/search`: flows, flow objects and the documentation, from one box.

Step 7 of `plans/public-site.md`.  What is pinned here is behaviour the Search
boards cannot show:

- **An identifier is routed, not guessed at.**  A current flow's UUID opens the
  flow; a CAS number or an InChIKey never redirects, because one registry
  number reaches several flow objects (decision 3), and gets the Exact match
  card instead.
- **A CAS number is findable at all.**  FTS5 reads the hyphens in `124-38-9` as
  syntax, so the list pages' own search finds nothing for one; the search
  quotes what FTS5 would misread.
- **Every state in §4 renders**: no query, no results, no database, no
  `docs/`, a UUID nobody has, a query FTS5 cannot parse, a very long query.
- **`<mark>` never opens a hole.**  The matched text is wrapped after the rest
  is escaped.

What `app.js` adds -- the `/` shortcut and the hint beside the box -- is not
reachable from a Flask test client and was checked in a browser.
"""

import tempfile
import unittest
from pathlib import Path

from test_webapp_sections import _elementary, _flow, _flow_object, _write_fixture

from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMROF_INCHI2D_KEY_STRING,
)
from brightway_flows.webapps.app import create_app, db, documentation
from brightway_flows.webapps.app.filters import highlight
from brightway_flows.webapps.app.queries import search

CO2_KEY = "CURLTUGMZLYLDI-UHFFFAOYSA-N"

#: Six flow objects share carbon dioxide's CAS number, one more than the Exact
#: match card lists before "Show the other N".
_CO2_OBJECTS = (
    ("fo-co2", "Carbon dioxide", 3),
    ("fo-co2-fossil", "Carbon dioxide (fossil)", 2),
    ("fo-co2-biogenic", "Carbon dioxide (biogenic)", 2),
    ("fo-co2-luc", "Carbon dioxide (land use change)", 1),
    ("fo-co2-seq", "Carbon dioxide (sequestration)", 1),
    ("fo-co2-air", "Carbon dioxide (air capture)", 1),
)

CURRENT_UUID = "0a1b2c3d-0000-4000-8000-000000000001"
DEPRECATED_UUID = "0a1b2c3d-0000-4000-8000-00000000dead"


def _object_with_key(flow_object_id, name, *, cas, inchikey):
    return FlowObject(
        flow_object_id=flow_object_id,
        prefLabel=[{"@value": name, "@language": "en"}],
        altLabel=[],
        classifications={CHEMINF_CAS_REGISTRY_NUMBER: {"@value": [cas]}},
        properties={CHEMROF_INCHI2D_KEY_STRING: {"@value": [inchikey]}},
        references=[],
        created_from={},
    )


def _write_search_fixture(path: Path) -> None:
    flows, objects, elementary = [], [], []
    number = 0
    for flow_object_id, name, flow_count in _CO2_OBJECTS:
        if flow_object_id in ("fo-co2", "fo-co2-fossil"):
            objects.append(_object_with_key(flow_object_id, name,
                                            cas="124-38-9", inchikey=CO2_KEY))
        else:
            objects.append(_flow_object(flow_object_id, name, cas=["124-38-9"]))
        for _ in range(flow_count):
            number += 1
            uuid = CURRENT_UUID if number == 1 else f"flow-{number}"
            flows.append(_flow(uuid, name, cas="124-38-9"))
            elementary.append(_elementary(uuid, flow_object_id))
    # A deprecated flow of its own, and a substance sharing a CAS number with
    # nothing, so a lookup of it has one flow object and no "why" link.
    objects.append(_flow_object("fo-ch4", "Methane", cas=["74-82-8"]))
    flows.append(_flow(DEPRECATED_UUID, "Methane", deprecated=True))
    elementary.append(_elementary(DEPRECATED_UUID, "fo-ch4"))
    flows.append(_flow("flow-ch4", "Methane"))
    elementary.append(_elementary("flow-ch4", "fo-ch4"))
    _write_fixture(path, flows=flows, flow_objects=objects, elementary=elementary)


def _write_docs(root: Path) -> None:
    """A tree whose three pages each match "carbon dioxide" in a different place."""
    (root / "concepts").mkdir(parents=True)
    (root / "index.md").write_text(
        "# Where to start\n\nNothing about gases here.\n", encoding="utf-8"
    )
    (root / "concepts" / "carbon.md").write_text(
        "# Carbon dioxide\n\nThe page named for it.\n", encoding="utf-8"
    )
    (root / "concepts" / "factors.md").write_text(
        "# Characterisation factors\n\n## Carbon dioxide, and the rule under it\n\n"
        "Words.\n", encoding="utf-8"
    )
    (root / "concepts" / "why.md").write_text(
        "# Why this exists\n\n"
        + "Padding that goes on for a while before it arrives. " * 6
        + "A kilogram of [carbon dioxide](factors.md) to air, "
        "and **more** after it that also goes on for a while. " * 3
        + "\n",
        encoding="utf-8",
    )
    (root.parent / "mkdocs.yml").write_text(
        "nav:\n"
        "  - Home: index.md\n"
        "  - Concepts:\n"
        "    - Why this exists: concepts/why.md\n"
        "    - Characterisation factors: concepts/factors.md\n"
        "    - Carbon dioxide: concepts/carbon.md\n",
        encoding="utf-8",
    )


class _SearchTestCase(unittest.TestCase):
    """A build and a documentation tree, both in a temporary directory."""

    with_database = True
    with_docs = True

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.path = base / "consensus-flows.sqlite3"
        self.docs = base / "project" / "docs"
        if self.with_database:
            _write_search_fixture(self.path)
        if self.with_docs:
            _write_docs(self.docs)

    def connection(self):
        connection = db.connect(self.path)
        self.addCleanup(connection.close)
        return connection

    def get(self, url):
        app = create_app(self.path, docs_path=self.docs)
        app.config["TESTING"] = True
        return app.test_client().get(url)

    def body(self, url):
        response = self.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)


class IdentifierTestCase(unittest.TestCase):
    def test_what_each_identifier_looks_like(self):
        cases = {
            CURRENT_UUID: "uuid",
            CURRENT_UUID.upper(): "uuid",
            "124-38-9": "cas",
            "7732-18-5": "cas",
            CO2_KEY: "inchikey",
            "carbon dioxide": None,
            "124-38": None,
            CO2_KEY.lower(): None,
        }
        for query, kind in cases.items():
            with self.subTest(query=query):
                self.assertEqual(search.identifier_kind(query), kind)

    def test_what_fts5_would_misread_is_quoted(self):
        self.assertEqual(search.fts_terms("carbon dioxide"), "carbon dioxide")
        self.assertEqual(search.fts_terms("124-38-9"), '"124-38-9"')
        self.assertEqual(search.fts_terms("benzo[a]pyrene"), '"benzo[a]pyrene"')
        self.assertEqual(search.fts_terms('say "hi"-there'), 'say """hi""-there"')

    def test_an_operator_is_left_for_the_existing_fallback(self):
        """`carbon AND` is §4's example of a query FTS5 cannot parse."""
        self.assertEqual(search.fts_terms("carbon AND"), "carbon AND")

    def test_a_very_long_query_is_cut_to_200_characters(self):
        self.assertEqual(len(search.normalise("x" * 500)), 200)
        self.assertEqual(search.normalise("  carbon \n dioxide "), "carbon dioxide")


class QueryTestCase(_SearchTestCase):
    def test_a_cas_number_finds_the_flow_objects_that_carry_it(self):
        page = search.flow_objects(self.connection(), "124-38-9")
        self.assertEqual(page.total, 6)

    def test_a_cas_number_finds_their_elementary_flows(self):
        page = search.elementary_flows(self.connection(), "124-38-9")
        self.assertEqual(page.total, 10)

    def test_deprecated_flows_are_not_results(self):
        page = search.elementary_flows(self.connection(), "methane")
        self.assertEqual([row.uuid for row in page.rows], ["flow-ch4"])

    def test_a_query_fts5_cannot_parse_does_not_raise(self):
        self.assertEqual(search.flow_objects(self.connection(), "carbon AND").total, 0)
        self.assertEqual(search.elementary_flows(self.connection(), "carbon AND").total, 0)

    def test_only_a_current_flow_uuid_is_a_flow(self):
        connection = self.connection()
        self.assertEqual(search.current_flow(connection, CURRENT_UUID), CURRENT_UUID)
        self.assertEqual(search.current_flow(connection, CURRENT_UUID.upper()), CURRENT_UUID)
        self.assertIsNone(search.current_flow(connection, DEPRECATED_UUID))
        self.assertIsNone(search.current_flow(connection, "0a1b2c3d-0000-4000-8000-00000000beef"))

    def test_the_exact_match_for_a_cas_number(self):
        match = search.exact_match(self.connection(), "124-38-9")
        self.assertEqual(match.label, "CAS number")
        self.assertEqual(match.identifier, "124-38-9")
        self.assertEqual(
            [(row.flow_object_id, row.linked_flows) for row in match.objects],
            [("fo-co2", 3), ("fo-co2-biogenic", 2), ("fo-co2-fossil", 2),
             ("fo-co2-air", 1), ("fo-co2-luc", 1), ("fo-co2-seq", 1)],
        )

    def test_the_exact_match_for_an_inchikey(self):
        match = search.exact_match(self.connection(), CO2_KEY)
        self.assertEqual(match.label, "InChIKey")
        self.assertEqual(sorted(row.flow_object_id for row in match.objects),
                         ["fo-co2", "fo-co2-fossil"])

    def test_a_number_on_no_flow_object_has_no_exact_match(self):
        self.assertIsNone(search.exact_match(self.connection(), "50-00-0"))
        self.assertIsNone(search.exact_match(self.connection(), "carbon dioxide"))


class DocumentationSearchTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "docs"
        _write_docs(self.root)

    def test_a_title_ranks_before_a_heading_before_text(self):
        hits = documentation.search(self.root, "Carbon DIOXIDE")
        self.assertEqual([hit.slug for hit in hits],
                         ["concepts/carbon", "concepts/factors", "concepts/why"])

    def test_each_hit_names_its_group(self):
        hits = documentation.search(self.root, "carbon dioxide")
        self.assertEqual({hit.group for hit in hits}, {"Concepts"})

    def test_a_heading_match_names_the_section(self):
        hit = documentation.search(self.root, "carbon dioxide")[1]
        self.assertEqual(hit.snippet, "Section: Carbon dioxide, and the rule under it")

    def test_a_text_snippet_is_short_plain_and_holds_the_match(self):
        hit = documentation.search(self.root, "carbon dioxide")[2]
        self.assertLessEqual(len(hit.snippet.strip("…")), 120)
        self.assertIn("carbon dioxide to air", hit.snippet)
        self.assertNotIn("](", hit.snippet)
        self.assertNotIn("**", hit.snippet)
        self.assertTrue(hit.snippet.startswith("…"))

    def test_no_match_is_no_hits(self):
        self.assertEqual(documentation.search(self.root, "nitrous oxide"), [])
        self.assertEqual(documentation.search(self.root, ""), [])


class HighlightTestCase(unittest.TestCase):
    def test_the_match_is_marked_and_everything_else_escaped(self):
        self.assertEqual(
            str(highlight("<b>Carbon Dioxide</b> (fossil)", "carbon dioxide")),
            "&lt;b&gt;<mark>Carbon Dioxide</mark>&lt;/b&gt; (fossil)",
        )

    def test_a_query_with_markup_in_it_is_text(self):
        self.assertEqual(str(highlight("a <x> b", "<x>")), "a <mark>&lt;x&gt;</mark> b")

    def test_words_are_marked_where_the_phrase_is_not(self):
        self.assertEqual(str(highlight("Dioxide of carbon", "carbon dioxide")),
                         "<mark>Dioxide</mark> of <mark>carbon</mark>")

    def test_no_query_marks_nothing(self):
        self.assertEqual(str(highlight("a & b", "")), "a &amp; b")


class RoutingTestCase(_SearchTestCase):
    def test_a_current_flow_uuid_opens_the_flow(self):
        response = self.get(f"/search?q={CURRENT_UUID}")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], f"/flows/{CURRENT_UUID}")

    def test_a_deprecated_flow_uuid_is_an_ordinary_search(self):
        self.assertIn("No results for", self.body(f"/search?q={DEPRECATED_UUID}"))

    def test_a_uuid_nobody_has_is_an_ordinary_search(self):
        body = self.body("/search?q=0a1b2c3d-0000-4000-8000-00000000beef")
        self.assertIn("No results for", body)

    def test_a_cas_number_never_redirects(self):
        response = self.get("/search?q=124-38-9")
        self.assertEqual(response.status_code, 200)


class ResultsTestCase(_SearchTestCase):
    def test_the_heading_and_the_form_repeat_the_query(self):
        body = self.body("/search?q=carbon+dioxide")
        self.assertIn("Results for “carbon dioxide”", body)
        self.assertIn('value="carbon dioxide"', body)
        self.assertIn(">Search</button>", body)

    def test_an_identifier_is_set_in_monospace(self):
        self.assertIn('Results for <span class="mono">124-38-9</span>',
                      self.body("/search?q=124-38-9"))

    def test_the_filter_links_count_each_type(self):
        body = self.body("/search?q=carbon+dioxide")
        self.assertRegex(body, r'<a[^>]*aria-current="page"[^>]*>All</a>')
        self.assertRegex(body, r'href="/search\?q=carbon\+dioxide&amp;type=objects"[^>]*>\s*Flow objects <span[^>]*>6</span>')
        self.assertRegex(body, r'href="/search\?q=carbon\+dioxide&amp;type=flows"[^>]*>\s*Elementary flows <span[^>]*>10</span>')
        self.assertRegex(body, r'href="/search\?q=carbon\+dioxide&amp;type=docs"[^>]*>\s*Documentation <span[^>]*>3</span>')

    def test_a_type_with_nothing_is_listed_with_zero_and_not_linked(self):
        body = self.body("/search?q=methane")
        self.assertRegex(body, r'<span class="search-types__type"[^>]*>\s*Documentation <span[^>]*>0</span>')
        self.assertNotIn("type=docs", body)

    def test_the_groups_show_four_and_link_to_the_rest(self):
        body = self.body("/search?q=carbon+dioxide")
        self.assertIn('href="/flow-objects/?q=carbon+dioxide"', body)
        self.assertIn("All 6 in Flow objects →", body)
        self.assertIn('href="/flows/?q=carbon+dioxide"', body)
        self.assertIn("All 10 in Elementary flows →", body)
        self.assertEqual(body.count('class="search-result search-result--object"'), 4)
        self.assertEqual(body.count('class="search-result search-result--flow"'), 4)

    def test_the_link_to_the_list_carries_the_query_it_counted(self):
        """The list page must show the same N the link promises."""
        self.assertIn('href="/flows/?q=%22124-38-9%22"', self.body("/search?q=124-38-9"))

    def test_names_and_snippets_mark_the_match(self):
        body = self.body("/search?q=carbon+dioxide")
        self.assertIn("<mark>Carbon dioxide</mark> (fossil)", body)
        self.assertIn("A kilogram of <mark>carbon dioxide</mark> to air", body)

    def test_the_documentation_group_names_each_page_and_its_group(self):
        body = self.body("/search?q=carbon+dioxide")
        self.assertIn('href="/docs/concepts/factors"', body)
        self.assertIn("Section: <mark>Carbon dioxide</mark>, and the rule under it", body)
        self.assertIn(">Concepts<", body)

    def test_a_type_shows_only_its_group(self):
        body = self.body("/search?q=carbon+dioxide&type=flows")
        self.assertRegex(body, r'<a[^>]*aria-current="page"[^>]*>\s*Elementary flows')
        self.assertEqual(body.count('class="search-result search-result--flow"'), 10)
        self.assertNotIn('class="search-result search-result--object"', body)
        self.assertNotIn('class="search-result search-result--doc"', body)

    def test_an_unknown_type_is_all(self):
        body = self.body("/search?q=carbon+dioxide&type=nonsense")
        self.assertRegex(body, r'<a[^>]*aria-current="page"[^>]*>All</a>')

    def test_markup_in_the_query_is_text(self):
        body = self.body("/search?q=%3Cscript%3Ealert(1)%3C/script%3E")
        self.assertNotIn("<script>alert(1)", body)
        self.assertIn("&lt;script&gt;", body)

    def test_the_aside_explains_identifiers_and_offers_the_report_links(self):
        body = self.body("/search?q=carbon+dioxide")
        self.assertIn("Searching by identifier", body)
        self.assertIn('href="/search?q=124-38-9"', body)
        self.assertIn("Not what you expected?", body)
        self.assertIn("issues/new?template=wrong-match.yml", body)
        self.assertIn('href="/docs/using/matching-your-own-list"', body)


class ExactMatchTestCase(_SearchTestCase):
    def test_a_cas_number_gets_the_card_above_the_results(self):
        body = self.body("/search?q=124-38-9")
        self.assertIn("Exact match", body)
        self.assertIn('CAS number <span class="mono">124-38-9</span>', body)
        self.assertIn("Recorded on 6 flow objects.", body)
        self.assertLess(body.index("search-types"), body.index("Exact match"))
        self.assertLess(body.index("Exact match"), body.index("search-result--flow"))

    def test_several_flow_objects_link_to_why(self):
        body = self.body("/search?q=124-38-9")
        self.assertIn('href="/docs/deciding/registry-numbers"', body)
        self.assertIn("Why one number reaches several flow objects", body)

    def test_one_flow_object_does_not(self):
        body = self.body("/search?q=74-82-8")
        self.assertIn("Recorded on 1 flow object.", body)
        self.assertNotIn("Why one number reaches several flow objects", body)

    def test_five_are_listed_and_the_rest_fold(self):
        body = self.body("/search?q=124-38-9")
        self.assertIn("Show the other 1", body)
        self.assertIn("3 elementary flows", body)
        self.assertIn("1 elementary flow<", body)

    def test_an_inchikey_gets_the_card(self):
        body = self.body(f"/search?q={CO2_KEY}")
        self.assertIn(f'InChIKey <span class="mono">{CO2_KEY}</span>', body)
        self.assertIn("Recorded on 2 flow objects.", body)

    def test_a_number_on_no_flow_object_gets_no_card(self):
        body = self.body("/search?q=50-00-0")
        self.assertNotIn("Exact match", body)
        self.assertIn("No results for", body)


class StatesTestCase(_SearchTestCase):
    def test_an_empty_query_is_the_form_and_the_help(self):
        body = self.body("/search")
        self.assertIn('role="search"', body)
        self.assertIn("Searching by identifier", body)
        self.assertNotIn("Results for", body)
        self.assertNotIn("No results for", body)

    def test_no_results(self):
        body = self.body("/search?q=unobtainium")
        self.assertIn("No results for “unobtainium”", body)
        self.assertIn("Searching by identifier", body)
        self.assertIn("Not what you expected?", body)
        self.assertNotIn("search-types", body)

    def test_a_very_long_query_renders(self):
        body = self.body("/search?q=" + "carbon+" * 100)
        self.assertIn("No results for", body)

    def test_a_query_fts5_cannot_parse_renders(self):
        self.assertIn("No results for", self.body("/search?q=carbon+AND"))


class NoDatabaseTestCase(_SearchTestCase):
    with_database = False

    def test_the_documentation_is_still_searched(self):
        body = self.body("/search?q=carbon+dioxide")
        self.assertIn('class="search-result search-result--doc"', body)
        self.assertNotIn("Flow objects", body.split('id="main"')[1].split("<aside")[0])

    def test_a_uuid_is_not_looked_up(self):
        self.assertIn("No results for", self.body(f"/search?q={CURRENT_UUID}"))


class NoDocumentationTestCase(_SearchTestCase):
    with_docs = False

    def test_there_is_no_documentation_group(self):
        body = self.body("/search?q=carbon+dioxide")
        self.assertIn('class="search-result search-result--object"', body)
        self.assertNotIn("type=docs", body)
        self.assertNotIn(">Documentation <span", body)


class FrameTestCase(unittest.TestCase):
    """The search box in every page's top bar, and what points at it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app = create_app(Path(self._tmp.name) / "missing.sqlite3")
        self.app.config["TESTING"] = True

    def body(self, url):
        return self.app.test_client().get(url).get_data(as_text=True)

    def test_every_page_has_the_search_box(self):
        body = self.body("/docs/")
        self.assertRegex(body, r'<form class="masthead__search" role="search" action="/search" method="get">')
        self.assertIn('<label class="visually-hidden" for="site-search">Search flows and docs</label>', body)
        self.assertRegex(body, r'<input[^>]*id="site-search"[^>]*name="q"')

    def test_the_slash_hint_waits_for_the_script(self):
        self.assertRegex(self.body("/docs/"), r"<kbd[^>]*data-search-hint[^>]*hidden[^>]*>/</kbd>")

    def test_the_box_holds_the_query_on_the_search_page(self):
        body = self.body("/search?q=carbon+dioxide")
        self.assertRegex(body, r'<input[^>]*id="site-search"[^>]*value="carbon dioxide"')

    def test_the_mobile_search_icon_is_a_link(self):
        self.assertRegex(self.body("/docs/"),
                         r'<a class="masthead__search-link" href="/search" aria-label="Search"')

    def test_the_shortcuts_dialog_lists_the_slash(self):
        body = self.body("/docs/")
        self.assertIn("<dt><kbd>/</kbd></dt><dd>Focus search</dd>", body)
        self.assertNotIn("More as the sections are built.", body)

    def test_the_404_offers_the_search_form(self):
        response = self.app.test_client().get("/nope-nothing-here")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 404)
        self.assertIn('action="/search"', body.split('id="main"')[1])


if __name__ == "__main__":
    unittest.main()
