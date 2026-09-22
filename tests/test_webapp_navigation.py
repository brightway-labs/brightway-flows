"""The top bar, the Browse panel, the mobile menu and `/browse/`.

Step 3 of `plans/public-site.md`.  What is pinned here is what has to hold with
`app.js` blocked, since every page has to be complete without it: Browse and
the menu icon are links to `/browse/`, which lists every section, so no page is
reachable only through a panel a script opens.  The panel and the menu are in
the markup either way, hidden until the script shows them.

What the script does with them -- Esc, a click outside, keeping focus inside
the menu -- is not reachable from a Flask test client and was checked in a
browser.
"""

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_webapp_sections import SectionTestCase

from brightway_flows.webapps.app import SECTIONS, create_app, navigation
from brightway_flows.webapps.app.publication import Publication
from brightway_flows.webapps.app.queries import navigation as nav_queries
from brightway_flows.webapps.app.sections import SITE_DESCRIPTION


def _meta_description(body: str) -> str:
    match = re.search(r'<meta name="description" content="([^"]*)">', body)
    assert match, "no <meta name=\"description\">"
    return match.group(1)


class SectionGroupTestCase(unittest.TestCase):
    def test_every_section_is_in_one_of_the_three_groups(self):
        self.assertEqual({section.group for section in SECTIONS},
                         {"top", "browse", "build"})

    def test_the_groups_keep_the_order_of_the_browse_panel(self):
        groups = navigation()
        self.assertEqual([s["key"] for s in groups["top"]], ["docs", "download", "about"])
        self.assertEqual([s["key"] for s in groups["browse"]],
                         ["flows", "substances", "factors", "checks"])
        self.assertEqual([s["key"] for s in groups["build"]],
                         ["overview", "scores", "queue", "merge"])

    def test_every_browse_and_build_section_has_a_summary(self):
        """The panel gives every entry, the curators' tools too, one line saying
        what is behind it: nobody should have to open Queue to learn what it is."""
        for section in SECTIONS:
            if section.group == "top":
                continue
            with self.subTest(section=section.key):
                self.assertTrue(section.summary)

    def test_docs_lives_at_docs_not_at_the_root(self):
        """`/` becomes the homepage in step 8; the section is `/docs/` now."""
        self.assertEqual(navigation()["top"][0]["href"], "/docs/")


class NoDatabaseTestCase(unittest.TestCase):
    """The frame on a checkout that has never been built."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        app = create_app(Path(self._tmp.name) / "missing.sqlite3")
        app.config["TESTING"] = True
        self.client = app.test_client()

    def body(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, path)
        return response.get_data(as_text=True)

    def test_browse_is_a_link_to_the_browse_page_without_scripts(self):
        body = self.body("/docs/")
        self.assertIn('href="/browse/"', body)
        self.assertIn('id="browse-panel"', body)

    def test_the_menu_icon_is_a_link_to_the_browse_page_without_scripts(self):
        body = self.body("/docs/")
        self.assertRegex(body, r'<a class="masthead__menu"[^>]*href="/browse/"')
        self.assertRegex(body, r'<nav[^>]*id="mobile-menu"[^>]*hidden')

    def test_the_masthead_carries_the_release_version(self):
        """Decided as 1.0 (#200); it was the chip until then, and any
        publication that has not decided one draws the chip again."""
        self.assertIn('<span class="masthead__version">1.0</span>', self.body("/docs/"))

    def test_the_version_is_a_placeholder_until_it_is_decided(self):
        with mock.patch("brightway_flows.webapps.app.PUBLICATION", Publication()):
            body = self.body("/docs/")
        self.assertIn('<span class="placeholder" title="Not yet decided">[v1.0.0]</span>',
                      body)

    def test_the_bar_links_to_the_repository(self):
        self.assertIn('href="https://github.com/brightway-labs/brightway-flows"',
                      self.body("/docs/"))

    def test_the_current_top_level_page_is_marked_with_more_than_colour(self):
        body = self.body("/docs/")
        self.assertRegex(body, r'<a class="masthead__link"[^>]*href="/docs/"[^>]*aria-current="page"')

    def test_every_bar_label_reserves_its_bold_width(self):
        """The current page and the open Browse button are set in 600.  Each
        label carries its own text for a hidden bold copy to size it by, so
        marking one never pushes the links after it to the right."""
        body = self.body("/docs/")
        bar = body[body.index('class="masthead__nav"'):body.index('id="browse-panel"')]
        labels = re.findall(r'<span class="masthead__label" data-label="([^"]*)">([^<]*)</span>', bar)
        self.assertEqual([text for _, text in labels], ["Docs", "Browse", "Browse"])
        for reserved, text in labels:
            self.assertEqual(reserved, text)
        rest = body[body.index('id="browse-panel"'):body.index('class="masthead__tools"')]
        self.assertEqual(
            re.findall(r'<span class="masthead__label" data-label="[^"]*">([^<]*)</span>', rest),
            ["Download", "About"],
        )

    def test_the_browse_panel_has_no_counts_without_a_database(self):
        """Left out, not shown as 0: this checkout cannot answer."""
        body = self.body("/docs/")
        self.assertIn("Flows, by substance and context", body)
        self.assertIn("Substances, materials and land classes", body)

    def panel(self, body):
        return body[body.index('id="browse-panel"'):body.index('class="masthead__tools"')]

    def test_the_browse_panel_splits_readers_from_curators(self):
        panel = self.panel(self.body("/docs/"))
        readers = panel.index("Browse the list")
        curators = panel.index("For curators")
        self.assertLess(readers, panel.index('href="/checks/"'))
        self.assertLess(panel.index('href="/checks/"'), curators)
        for section in SECTIONS:
            if section.group != "build":
                continue
            with self.subTest(section=section.key):
                self.assertGreater(panel.index(f'href="{section.href}"'), curators)
                self.assertIn(section.summary, panel)

    def test_the_browse_panel_does_not_repeat_the_browse_page(self):
        """Without scripts Browse is already a link to `/browse/`; with them,
        the panel holds every link that page does."""
        panel = self.panel(self.body("/docs/"))
        self.assertNotIn('href="/browse/"', panel)
        self.assertNotIn("tools for curators", panel)

    def test_the_mobile_menu_lists_the_curators_tools(self):
        body = self.body("/docs/")
        menu = body[body.index('id="mobile-menu"'):]
        curators = menu.index("For curators")
        for section in SECTIONS:
            if section.group != "build":
                continue
            with self.subTest(section=section.key):
                self.assertGreater(menu.index(f'href="{section.href}"'), curators)

    def test_the_browse_page_lists_both_groups_with_their_blurbs(self):
        body = self.body("/browse/")
        for section in SECTIONS:
            if section.group == "top":
                continue
            with self.subTest(section=section.key):
                self.assertIn(f'href="{section.href}"', body)
                self.assertIn(section.blurb.split(" ")[0], body)
        self.assertIn("Build &amp; review", body)
        self.assertIn('id="build"', body)

    def test_the_browse_page_marks_browse_as_current(self):
        body = self.body("/browse/")
        self.assertRegex(body, r'<a class="masthead__link[^"]*"[^>]*href="/browse/"[^>]*aria-current="page"')

    def test_a_section_page_is_described_by_its_blurb(self):
        docs = next(section for section in SECTIONS if section.key == "docs")
        self.assertIn(docs.blurb.split(",")[0], _meta_description(self.body("/docs/")))

    def test_a_page_with_no_section_is_described_by_the_site(self):
        self.assertEqual(_meta_description(self.body("/browse/")), SITE_DESCRIPTION)


class WithDatabaseTestCase(SectionTestCase):
    def test_the_browse_panel_counts_current_flows_and_flow_objects(self):
        """Three flows, one deprecated: the panel says two."""
        body = self.client().get("/flows/").get_data(as_text=True)
        self.assertIn("2 flows, by substance and context", body)
        self.assertIn("2 substances, materials and land classes", body)

    def test_a_browse_section_marks_browse_as_current(self):
        body = self.client().get("/flows/").get_data(as_text=True)
        self.assertRegex(body, r'<a class="masthead__link[^"]*"[^>]*href="/browse/"[^>]*aria-current="true"')
        self.assertNotRegex(body, r'href="/docs/"[^>]*aria-current')
        # Inside the panel, the page itself is the current entry.
        self.assertRegex(body, r'<a class="browse-panel__entry[^"]*"[^>]*href="/flows/"[^>]*aria-current="page"')

    def test_the_counts_query(self):
        counts = nav_queries.load_counts(self.connection())
        self.assertEqual(counts.elementary_flows, 2)
        self.assertEqual(counts.flow_objects, 2)


class CountsQueryTestCase(unittest.TestCase):
    def test_a_database_without_the_tables_counts_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.sqlite3"
            sqlite3.connect(path).close()
            connection = sqlite3.connect(path)
            try:
                counts = nav_queries.load_counts(connection)
            finally:
                connection.close()
        self.assertIsNone(counts.elementary_flows)
        self.assertIsNone(counts.flow_objects)


if __name__ == "__main__":
    unittest.main()
