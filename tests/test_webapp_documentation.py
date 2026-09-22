"""The documentation, served from the review application.

The pages were readable on GitHub and under `mkdocs serve`, and nowhere a
curator working through the queues could reach them. They are rendered from
`docs/` per request now, which is a decision with three consequences worth
pinning:

- **Every link between pages has to be rewritten.** The documentation is
  written for GitHub, where a link to another page is a relative path to a
  `.md` file. Left alone, every one of them 404s here.
- **The tree is the boundary.** One route serves pages and the images beside
  them, so a path that climbs out of `docs/` has to be refused rather than
  read.
- **A checkout without `docs/` is a page.** The package installs without the
  documentation tree, and that is a state to report, not to crash in.

The real tree is used where the assertion is about the real tree -- that every
page `mkdocs.yml` lists exists and renders -- and a fixture where it is about
the rendering, so a page being rewritten cannot break a test about links.
"""

import tempfile
import unittest
from pathlib import Path

from brightway_flows.webapps.app import create_app, documentation
from brightway_flows.webapps.app.documentation import DocLink, DocSection

#: The project's own tree, which the application serves by default.
PROJECT_DOCS = Path(__file__).resolve().parent.parent / "docs"


class RenderingTestCase(unittest.TestCase):
    """A fixture tree: what the renderer does, told apart from what it reads."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "docs"
        (self.root / "concepts").mkdir(parents=True)
        (self.root / "media").mkdir()
        (self.root / "index.md").write_text(
            "# Home\n\nStart with [why](concepts/why.md).\n", encoding="utf-8"
        )
        (self.root / "concepts" / "why.md").write_text(
            "# Why this exists\n\n"
            "Back [home](../index.md), or to a\n"
            "[section](../index.md#start), or [outside](https://example.org).\n\n"
            "![A picture](../media/chart.png)\n\n"
            "| Source | Rows |\n|---|---|\n| ecoinvent | 9,850 |\n",
            encoding="utf-8",
        )
        (self.root / "media" / "chart.png").write_bytes(b"not really a png")

    def render(self, slug):
        page = documentation.load_page(self.root, slug)
        self.assertIsNotNone(page)
        return page

    def test_a_link_to_another_page_becomes_a_route(self):
        self.assertIn('href="/docs/concepts/why"', self.render("index").html)

    def test_a_link_up_a_directory_resolves(self):
        """`../index.md` from `concepts/why` is the home page, not `/docs/../`."""
        self.assertIn('href="/docs/index"', self.render("concepts/why").html)

    def test_an_anchor_survives_the_rewrite(self):
        self.assertIn('href="/docs/index#start"', self.render("concepts/why").html)

    def test_a_link_to_another_site_is_left_alone(self):
        self.assertIn('href="https://example.org"', self.render("concepts/why").html)

    def test_an_image_beside_the_page_is_served_from_the_tree(self):
        self.assertIn('src="/docs/media/chart.png"', self.render("concepts/why").html)

    def test_a_table_is_wrapped_so_the_page_does_not_scroll_sideways(self):
        """The same wrapper every other table in the application sits in."""
        html = self.render("concepts/why").html
        self.assertIn('<div class="table-scroll">', html)
        self.assertIn("<table>", html)

    def test_the_page_carries_its_own_contents(self):
        self.assertIn("Why this exists", self.render("concepts/why").contents)

    def test_the_root_is_the_index(self):
        self.assertEqual(self.render("").slug, "index")

    def test_a_path_that_climbs_out_of_the_tree_is_refused(self):
        """Not a 404 by accident of the file being absent: it is outside."""
        outside = self.root.parent / "secrets.md"
        outside.write_text("# Secrets\n", encoding="utf-8")
        self.assertIsNone(documentation.resolve(self.root, "../secrets"))
        self.assertIsNone(documentation.load_page(self.root, "../secrets"))

    def test_a_tree_without_a_configuration_still_has_a_navigation(self):
        """`mkdocs.yml` is beside the tree, and a fixture has none."""
        sections = documentation.navigation(self.root)
        slugs = [page.slug for section in sections for page in section.pages]
        self.assertEqual(sorted(slugs), ["concepts/why", "index"])


class NavigationHelpersTestCase(unittest.TestCase):
    """`group_of` and `neighbours`, the Docs frame's own reading of `navigation()`.

    Built from `DocSection`/`DocLink` directly rather than from a tree on disk:
    what they answer depends only on the shape `navigation()` returns, not on
    how that shape was read, and a fixture tree adds a second thing that could
    make the order wrong.
    """

    def setUp(self):
        self.sections = [
            DocSection(title="", pages=[DocLink(title="Home", slug="index")]),
            DocSection(
                title="Concepts",
                pages=[
                    DocLink(title="Why this exists", slug="concepts/why"),
                    DocLink(title="Flow contexts", slug="concepts/contexts"),
                ],
            ),
            DocSection(
                title="Reference",
                pages=[DocLink(title="Glossary", slug="reference/glossary")],
            ),
        ]

    def test_a_top_level_page_has_no_group(self):
        self.assertIsNone(documentation.group_of(self.sections, "index"))

    def test_a_grouped_page_has_its_group(self):
        group = documentation.group_of(self.sections, "concepts/why")
        self.assertEqual(group.title, "Concepts")

    def test_a_page_the_navigation_does_not_list_has_no_group(self):
        self.assertIsNone(documentation.group_of(self.sections, "nope"))

    def test_the_first_page_has_no_previous(self):
        before, after = documentation.neighbours(self.sections, "index")
        self.assertIsNone(before)
        self.assertEqual(after.slug, "concepts/why")

    def test_the_last_page_has_no_next(self):
        before, after = documentation.neighbours(self.sections, "reference/glossary")
        self.assertEqual(before.slug, "concepts/contexts")
        self.assertIsNone(after)

    def test_neighbours_cross_a_group_boundary(self):
        """"Flow contexts" is the last page of Concepts; the next is Reference's."""
        before, after = documentation.neighbours(self.sections, "concepts/contexts")
        self.assertEqual(before.slug, "concepts/why")
        self.assertEqual(after.slug, "reference/glossary")

    def test_a_page_the_navigation_does_not_list_has_no_neighbours(self):
        self.assertEqual(
            documentation.neighbours(self.sections, "nope"), (None, None)
        )


class ProjectDocsTestCase(unittest.TestCase):
    """The real tree, and the navigation `mkdocs.yml` declares over it."""

    def test_every_page_the_navigation_lists_exists_and_renders(self):
        """The same check `mkdocs` makes of itself, on the pages as served.

        A `nav` entry naming a file that is not there is a broken link in both
        places, and this is the one that runs in CI.
        """
        sections = documentation.navigation(PROJECT_DOCS)
        self.assertTrue(sections)
        for section in sections:
            for link in section.pages:
                with self.subTest(page=link.slug):
                    page = documentation.load_page(PROJECT_DOCS, link.slug)
                    self.assertIsNotNone(page, f"{link.slug} is in nav and not on disk")
                    self.assertTrue(page.html.strip())

    def test_the_navigation_is_grouped_the_way_the_configuration_groups_it(self):
        titles = [section.title for section in documentation.navigation(PROJECT_DOCS)]
        self.assertEqual(
            titles,
            [
                "",
                "Concepts",
                "How a flow is decided",
                "How a factor is decided",
                "What we have found",
                "What was changed in each source",
                "Using the data",
                "Operating the pipeline",
                "Reference",
            ],
        )

    def test_no_page_links_to_a_page_that_is_not_there(self):
        """Every rewritten `/docs/...` link lands on a file in the tree.

        A relative link between pages is invisible until somebody follows it,
        and the rewriting means a wrong one now 404s in the application rather
        than only on GitHub.
        """
        import re

        pattern = re.compile(r'(?:href|src)="/docs/([^"#]+)')
        sections = documentation.navigation(PROJECT_DOCS)
        for section in sections:
            for link in section.pages:
                page = documentation.load_page(PROJECT_DOCS, link.slug)
                for target in pattern.findall(page.html):
                    with self.subTest(page=link.slug, links_to=target):
                        self.assertIsNotNone(
                            documentation.resolve(PROJECT_DOCS, target),
                            f"{link.slug} links to {target}, which is not in docs/",
                        )


class RouteTestCase(unittest.TestCase):
    def client(self, docs_path=None):
        app = create_app(Path("/nonexistent.sqlite3"), docs_path=docs_path)
        app.config["TESTING"] = True
        return app.test_client()

    def test_the_documentation_renders_without_a_database(self):
        """It is the section that does not read the database at all."""
        response = self.client().get("/docs/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Brightway Flows", response.get_data(as_text=True))

    def test_a_page_renders_in_the_application_layout(self):
        body = self.client().get("/docs/concepts/two-layers").get_data(as_text=True)
        self.assertIn('class="docs__page"', body)
        self.assertIn('class="masthead__nav"', body)

    def test_a_file_beside_the_pages_is_served_from_the_tree(self):
        """Not every file in `docs/` is a page: a worklist a page links to is
        served at its own name by the same route."""
        response = self.client().get(
            "/docs/reference/preferred-label-worklist.json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")

    def test_a_page_that_is_not_there_is_a_404(self):
        self.assertEqual(self.client().get("/docs/nope").status_code, 404)

    def test_a_checkout_without_documentation_is_a_page(self):
        response = self.client(docs_path=Path("/nonexistent-docs")).get("/docs/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No documentation here", response.get_data(as_text=True))


class DocsFrameTestCase(unittest.TestCase):
    """The sidebar, breadcrumb, "On this page" and Previous/Next, on the real
    tree -- `plans/public-site.md` §3, "Docs frame"."""

    def client(self):
        app = create_app(Path("/nonexistent.sqlite3"))
        app.config["TESTING"] = True
        return app.test_client()

    def body(self, slug):
        return self.client().get(f"/docs/{slug}").get_data(as_text=True)

    def test_the_group_holding_the_page_is_open(self):
        body = self.body("concepts/contexts")
        self.assertIn('<details class="docs__group" open>', body)
        self.assertIn("Concepts", body)

    def test_a_closed_group_shows_a_chevron_not_a_page_count(self):
        """"How a flow is decided" has eleven pages and is not open here.

        A two-digit count beside a long title wrapped the chevron onto a line
        of its own, and the number told a reader nothing about which group to
        open."""
        body = self.body("concepts/contexts")
        self.assertIn('<span class="docs__summary-meta">&rsaquo;</span>', body)
        self.assertNotIn("11 &rsaquo;", body)

    def test_a_top_level_page_is_a_plain_link_not_a_group(self):
        """The index is the one page `mkdocs.yml` lists outside a group."""
        body = self.body("concepts/contexts")
        self.assertIn('<ul class="docs__list docs__list--top">', body)
        self.assertIn("Where to start", body)

    def test_the_findings_overview_answers_at_the_directory_url(self):
        """`/docs/findings` was one page and is now a directory of them.

        The footer links to it, and so does every issue and commit written
        while it was a file, so the overview has to answer there.
        """
        body = self.body("findings")
        self.assertIn("What we have found", body)
        self.assertIn("The classes, and where they were found", body)

    def test_the_breadcrumb_names_the_group(self):
        body = self.body("concepts/contexts")
        self.assertIn('class="docs__breadcrumb"', body)
        self.assertIn(">Docs</a> / Concepts", body)

    def test_the_breadcrumb_has_no_second_segment_off_the_group(self):
        """The index is not in any group."""
        start = self.body("").index('class="docs__breadcrumb"')
        breadcrumb = self.body("")[start : start + 200]
        self.assertNotIn(" / ", breadcrumb)

    def test_previous_and_next_are_the_neighbours_in_the_sidebar(self):
        body = self.body("concepts/why")
        self.assertIn(
            'docs__pager-link--next" href="/docs/concepts/two-layers"', body
        )

    def test_previous_and_next_cross_a_group_boundary(self):
        """Concepts' last page is "Glossary"; the next group's first is next."""
        body = self.body("concepts/glossary")
        self.assertIn('docs__pager-link--next" href="/docs/deciding/index"', body)

    def test_the_first_page_has_no_previous(self):
        body = self.body("")
        self.assertNotIn("docs__pager-link--prev", body)

    def test_the_pager_names_the_index_where_to_start(self):
        """Concepts' first page comes right after the index in `navigation()`."""
        body = self.body("concepts/why")
        self.assertIn('docs__pager-link--prev" href="/docs/"', body)
        self.assertIn("Where to start", body)

    def test_report_a_problem_names_the_page(self):
        """The path fills the form's `page` field. It used to be passed as
        `?title=`, which put a file path where a title belongs and left every
        other field of the report empty."""
        body = self.body("concepts/why")
        self.assertIn(
            "issues/new?template=docs.yml&amp;page=docs/concepts/why.md", body
        )

    def test_the_mobile_bar_names_the_current_group(self):
        body = self.body("concepts/why")
        start = body.index('class="docs__mobile-bar"')
        bar = body[start : start + 800]
        self.assertIn("Contents", bar)
        self.assertIn("Concepts", bar)

    def test_the_rest_of_this_site_is_gone(self):
        """`/browse/` replaced it (`plans/public-site.md` §5)."""
        self.assertNotIn("The rest of this site", self.body(""))


class DiagramTestCase(unittest.TestCase):
    """A mermaid fence is drawn here, and the script that draws it is local.

    The application printed the fence as its source until now, which was a
    stated trade-off and stopped being a reasonable one when a section index
    opened with a diagram.  Three things have to stay true, and each of them is
    a way this could quietly stop working:

    - the drawing script is *in the package*, so the application still renders
      with no network;
    - it is fetched only by a page that has a fence, because it is three and a
      half megabytes;
    - a page that has one says so, which is what the template asks.
    """

    STATIC = (
        Path(documentation.__file__).resolve().parent / "static"
    )

    def client(self):
        app = create_app(Path("/nonexistent.sqlite3"))
        app.config["TESTING"] = True
        return app.test_client()

    def test_the_drawing_script_is_checked_in_beside_the_stylesheet(self):
        """Not linked from a CDN, for the reason `layout.html` gives."""
        for name in ("mermaid.min.js", "docs-mermaid.js"):
            with self.subTest(asset=name):
                self.assertTrue((self.STATIC / name).is_file())

    def test_the_vendored_version_is_the_one_that_was_checked(self):
        """A vendored bundle is a dependency with nothing watching it.

        Nothing else in this repository records which mermaid this is, and a
        copy swapped for a newer one is a change to what every diagram looks
        like.  Pinned here so an upgrade is a line in a diff rather than a file
        that quietly grew.
        """
        bundle = (self.STATIC / "mermaid.min.js").read_text(encoding="utf-8")
        self.assertIn('version:"11.17.1"', bundle)
        self.assertIn('globalThis["mermaid"]', bundle)

    def test_a_drawn_fence_is_set_in_the_page_face(self):
        """The drawing inherits its font from the `pre`, which is a code block.

        `docs-mermaid.js` asks mermaid to inherit, so the face the labels are
        measured and drawn in is whatever the drawn element has, and a `pre`
        has the code face unless the stylesheet says otherwise.  Measured in
        monospace every label is wider, more of them wrap, and a question's
        diamond grows with its label: the chart on `deciding/index` was 1,274
        units tall in the code face and 1,138 in the page's, before the rank
        spacing was touched.
        """
        css = (self.STATIC / "app.css").read_text(encoding="utf-8")
        start = css.index("pre.mermaid[data-processed] {")
        rule = css[start : css.index("}", start)]
        self.assertIn("font-family: var(--font-ui)", rule)

    def test_no_page_links_a_script_from_somewhere_else(self):
        body = self.client().get("/docs/deciding/index").get_data(as_text=True)
        self.assertNotIn("//cdn.", body)
        self.assertNotIn("//unpkg.", body)
        self.assertNotIn("fonts.googleapis.com", body)
        self.assertNotIn("fonts.gstatic.com", body)

    def test_a_page_with_a_fence_asks_for_the_script(self):
        page = documentation.load_page(PROJECT_DOCS, "deciding/index")
        self.assertTrue(page.has_diagrams)
        body = self.client().get("/docs/deciding/index").get_data(as_text=True)
        self.assertIn("mermaid.min.js", body)
        self.assertIn("docs-mermaid.js", body)

    def test_a_page_without_one_does_not(self):
        page = documentation.load_page(PROJECT_DOCS, "concepts/two-layers")
        self.assertFalse(page.has_diagrams)
        body = self.client().get("/docs/concepts/two-layers").get_data(as_text=True)
        self.assertNotIn("mermaid.min.js", body)

    def test_the_fence_is_still_the_fallback(self):
        """A blocked script, or a diagram that will not parse, shows the source.

        Which is what every page did before, so the failure mode is the old
        behaviour rather than a blank space.
        """
        body = self.client().get("/docs/deciding/index").get_data(as_text=True)
        self.assertIn('<pre class="mermaid">', body)
        self.assertIn("flowchart TD", body)

    def test_every_page_that_draws_is_found_by_the_same_test(self):
        """The pages with a diagram, so a new one is not silently undrawn."""
        drawn = sorted(
            page.slug
            for section in documentation.navigation(PROJECT_DOCS)
            for link in section.pages
            if (page := documentation.load_page(PROJECT_DOCS, link.slug))
            and page.has_diagrams
        )
        self.assertEqual(
            drawn,
            [
                "deciding-factors/index",
                "deciding/index",
                "deciding/merging",
                "deciding/structures",
            ],
        )


if __name__ == "__main__":
    unittest.main()
