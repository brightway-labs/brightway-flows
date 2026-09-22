"""The footer and the error pages.  Step 4 of `plans/public-site.md`.

The footer is on every page, so what matters here is that it survives with no
database (a checkout that has never been built still has a footer) and that
every undecided fact on its bottom line goes through the placeholder chip
rather than being written into the template -- plan §0's first rule.  `/404`
and `/500` are new: there was no custom error page before this step, and a
reader who mistyped a flow UUID got Flask's own text, outside the site's frame.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from brightway_flows.webapps.app import create_app
from brightway_flows.webapps.app.publication import Publication


class FooterTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        app = create_app(Path(self._tmp.name) / "missing.sqlite3")
        app.config["TESTING"] = True
        self.client = app.test_client()

    def body(self, path: str) -> str:
        return self.client.get(path).get_data(as_text=True)

    def test_the_footer_is_on_a_page_with_no_database(self):
        """The frame a checkout that has never been built still gets."""
        body = self.body("/run/")
        self.assertIn('class="footer"', body)

    def test_the_footer_is_on_the_documentation(self):
        body = self.body("/docs/")
        self.assertIn('class="footer"', body)

    def test_the_brand_column_names_brightway_labs(self):
        body = self.body("/docs/")
        self.assertIn("Brightway Flows", body)
        normalized = " ".join(body.split())
        self.assertIn("Built and maintained by Brightway Labs.", normalized)
        self.assertIn('href="https://brightway-lca.com"', body)

    def test_no_page_calls_brightway_labs_the_team_behind_brightway(self):
        """Brightway Labs does not own Brightway; its co-founder created it.

        About's "the team behind Brightway Cloud" is the approved copy, so the
        first pattern stops short of it.
        """
        for path in ("/", "/docs/", "/about/"):
            normalized = " ".join(self.body(path).split())
            for claim in (r"team behind Brightway(?! Cloud)", r"team behind the open-source"):
                with self.subTest(path=path, claim=claim):
                    self.assertNotRegex(normalized, claim)

    def test_the_logo_is_drawn_twice_for_both_themes(self):
        body = self.body("/docs/")
        self.assertIn("brand/brightway-labs.svg", body)
        self.assertIn("brand/brightway-labs-inverted.svg", body)
        self.assertEqual(body.count('alt="Brightway Labs"'), 2)

    def test_every_column_is_present(self):
        body = self.body("/docs/")
        for heading in ("Dataset", "Documentation", "Community", "Build &amp; review"):
            with self.subTest(heading=heading):
                self.assertIn(heading, body)

    def test_an_unset_licence_renders_the_placeholder_chip(self):
        """Plan §0: a fact nobody has decided is a chip, not a blank.

        Both licences are decided now (#200), so the rule is pinned against a
        publication that has decided nothing, which is what any fact still
        waiting on Zenodo or legal looks like.
        """
        with mock.patch("brightway_flows.webapps.app.PUBLICATION", Publication()):
            body = self.body("/docs/")
        self.assertIn('[DATA LICENCE]', body)
        self.assertIn('[CODE LICENCE]', body)
        self.assertIn('class="placeholder"', body)

    def test_the_decided_licences_are_on_the_bottom_line(self):
        """The data under ODbL 1.0, the code under the AGPL (#200)."""
        body = self.body("/docs/")
        self.assertIn("ODbL-1.0", body)
        self.assertIn("AGPL-3.0-or-later", body)
        self.assertNotIn("[DATA LICENCE]", body)

    def test_the_copyright_line_is_present(self):
        self.assertIn("© 2026 Brightway Labs GmbH", self.body("/docs/"))


class ThemeSwitchTestCase(unittest.TestCase):
    """The theme switch lives on the footer's bottom line, not in the top bar.

    Three radios -- System, Light, Dark -- so a reader can go back to
    following the OS setting, which the old two-way toggle could not undo.
    The group is `hidden` until `app.js` runs, like the toggle it replaces.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        app = create_app(Path(self._tmp.name) / "missing.sqlite3")
        app.config["TESTING"] = True
        self.body = app.test_client().get("/docs/").get_data(as_text=True)

    def footer(self) -> str:
        return self.body[self.body.index('<footer class="footer">'):]

    def test_the_switch_is_in_the_footer(self):
        footer = self.footer()
        self.assertIn('<fieldset class="theme-switch" data-theme-switch hidden>', footer)
        self.assertIn("<legend", footer)

    def test_it_offers_system_light_and_dark(self):
        footer = self.footer()
        for value in ("system", "light", "dark"):
            with self.subTest(value=value):
                self.assertIn(f'name="theme" value="{value}"', footer)

    def test_the_top_bar_has_no_theme_control(self):
        header = self.body[
            self.body.index('<header class="masthead">') : self.body.index("</header>")
        ]
        self.assertNotIn("data-theme", header)


class ErrorPageTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app = create_app(Path(self._tmp.name) / "missing.sqlite3")
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_a_missing_page_is_a_404_in_the_site_frame(self):
        response = self.client.get("/nope-nothing-here")
        self.assertEqual(response.status_code, 404)
        body = response.get_data(as_text=True)
        self.assertIn("Page not found", body)
        self.assertIn('class="footer"', body)

    def test_the_404_offers_a_way_back_in(self):
        body = self.client.get("/nope-nothing-here").get_data(as_text=True)
        self.assertIn('href="/"', body)
        self.assertIn('href="/browse/"', body)

    def test_a_raised_exception_is_a_500_in_the_site_frame(self):
        @self.app.route("/_boom")
        def _boom():
            raise RuntimeError("deliberate, for the test")

        self.app.config["PROPAGATE_EXCEPTIONS"] = False
        response = self.client.get("/_boom")
        self.assertEqual(response.status_code, 500)
        body = response.get_data(as_text=True)
        self.assertIn("Something went wrong", body)
        self.assertNotIn("RuntimeError", body)
        self.assertNotIn("Traceback", body)


if __name__ == "__main__":
    unittest.main()
