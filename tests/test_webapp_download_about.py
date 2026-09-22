"""Download and About.  Step 5 of `plans/public-site.md`.

Both pages are mostly undecided facts -- a version, a DOI, two licences, the
maintainers, an address -- so most of what is pinned here is plan §0's first
rule: every one of them renders the placeholder chip while `publication.py`
leaves it unset, and the value once it is set.  The rest is what has to hold
with `app.js` blocked: the three citation formats are all on the page, one
after another, and the tabs and the Copy button are hidden until the script
shows them.

What the script does with them -- arrow keys between tabs, copying -- is not
reachable from a Flask test client and was checked in a browser.
"""

import dataclasses
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_webapp_controls import _AppTestCase

from brightway_flows.webapps.app import create_app
from brightway_flows.webapps.app.publication import PUBLICATION, Maintainer, Publication

_DECIDED = dataclasses.replace(
    PUBLICATION,
    version="v1.0.0",
    release_date="2026-10-01",
    doi="10.5281/zenodo.1234567",
    checksums={"flows": "ab" * 32},
    data_licence="CC-BY-4.0",
    maintainers=(Maintainer(name="Ada Example", role="Maintainer"),),
    contact_email="list@example.org",
)


def _decided():
    """Every page reads the one instance through the context processor."""
    return mock.patch("brightway_flows.webapps.app.PUBLICATION", _DECIDED)


def _undecided():
    """Nothing decided at all.

    Some facts are decided now (#200: the version, the release date, both
    licences), so a page rendered from the real `PUBLICATION` no longer shows
    their chips.  The rule the chips exist for is not about *which* facts are
    open, so it is pinned against a publication where every one of them is.
    """
    return mock.patch("brightway_flows.webapps.app.PUBLICATION", Publication())


class _NoDatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
        app = create_app(self.data_dir / "missing.sqlite3", data_dir=self.data_dir)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def body(self, path: str) -> str:
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, path)
        return response.get_data(as_text=True)


class TopBarTestCase(_NoDatabaseTestCase):
    def test_download_and_about_follow_browse(self):
        """Docs · Browse · Download · About, the order of the Top bar board."""
        body = self.body("/docs/")
        bar = body[body.index('class="masthead__nav"'):body.index('class="masthead__tools"')]
        order = [bar.index(marker) for marker in
                 ('href="/docs/"', 'data-browse-link', 'href="/download/"', 'href="/about/"')]
        self.assertEqual(order, sorted(order))

    def test_the_mobile_menu_has_the_same_order(self):
        body = self.body("/docs/")
        menu = body[body.index('id="mobile-menu"'):]
        order = [menu.index(marker) for marker in
                 ('href="/docs/"', 'href="/checks/"', 'href="/download/"', 'href="/about/"')]
        self.assertEqual(order, sorted(order))

    def test_the_current_page_is_marked(self):
        for path in ("/download/", "/about/"):
            with self.subTest(path=path):
                self.assertRegex(
                    self.body(path),
                    rf'<a class="masthead__link" href="{path}" aria-current="page">',
                )


class DownloadWithoutDatabaseTestCase(_NoDatabaseTestCase):
    def test_every_undecided_fact_is_a_placeholder(self):
        with _undecided():
            body = self.body("/download/")
        for label in ("[v1.0.0]", "[2026-09-DD]", "[10.5281/zenodo.XXXXXXX]",
                      "[DATA LICENCE]", "[checksum]"):
            with self.subTest(label=label):
                self.assertIn(label, body)

    def test_the_release_is_decided_and_no_chip_is_left_on_the_page(self):
        """#200's "done when" for this page: version, date, DOI, licence,
        source-list terms and four checksums, and no amber chip anywhere."""
        body = self.body("/download/")
        self.assertIn("Latest release · 1.0 · Released 2026-09-22", body)
        self.assertIn("10.5281/zenodo.22857950", body)
        self.assertIn("ODbL-1.0", body)
        self.assertNotIn('class="placeholder"', body)

    def test_each_file_carries_the_checksum_of_the_released_file(self):
        body = self.body("/download/")
        for checksum in (
            "07a35d2da36fe5b18515fb956757434c785da78186a1e6254b99abfa29ae5b46",
            "2e820ff0c1d86d8920c06d4f4fa8c1df644f51f88ac699612439a4b7095a6d2a",
            "bbe57a44745c743317361c61d3ca8b5e44ddc233bad8a62c7bd05f1312dae563",
            "20cfe2b604d66778e2816befe1e79d99d9135c376debda5358d460879486ddc0",
        ):
            with self.subTest(checksum=checksum[:8]):
                self.assertIn(checksum, body)

    def test_the_concept_doi_line_is_gone(self):
        """There is no concept DOI to point at, so the line that named one
        went with the field (#200)."""
        body = self.body("/download/")
        self.assertNotIn("concept DOI", body)

    def test_the_release_is_text_while_there_is_one(self):
        self.assertNotIn("<select", self.body("/download/"))

    def test_the_page_links_to_run_instead_of_repeating_build_details(self):
        """The facts strip, change-count grid and build/database card are
        gone: `/run/` already says all of it (`views/overview.py`)."""
        body = self.body("/download/")
        self.assertIn('Build details</a> live in Build &amp; review', body)
        self.assertIn('href="/run/"', body)
        for gone in ("Built from", "Flows processed", "Flows added"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, body)

    def test_every_file_a_release_offers_is_listed_with_the_database_last(self):
        """Decision 8 decided (#200): the database is a release file too, and
        it is last so that "Start here" stays on the harmonised flows."""
        body = self.body("/download/")
        found = [body.index(filename) for filename in
                 ("harmonised-flows-simple.json.gz", "lcia-factors.json.gz",
                  "lcia-differences.json", "consensus-flows.sqlite3")]
        self.assertEqual(found, sorted(found))
        # The chip sits in the first row, between its title and its file name.
        self.assertLess(body.index("Harmonised flows"), body.index("Start here"))
        self.assertLess(body.index("Start here"), found[0])

    def test_a_file_the_build_did_not_write_keeps_its_row(self):
        body = self.body("/download/")
        self.assertEqual(body.count("Not in this build"), 4)
        self.assertNotIn("/run/download/flows", body)

    def test_a_written_file_is_a_download_with_its_size(self):
        """The release has a DOI, so the link is the archived release and
        not this build's own copy of the file."""
        (self.data_dir / "lcia-differences.json").write_bytes(b"x" * 2_500)
        body = self.body("/download/")
        self.assertIn('href="https://doi.org/10.5281/zenodo.22857950"', body)
        self.assertNotIn("/run/download/differences", body)
        self.assertIn("2.5 kB", body)
        self.assertEqual(body.count("Not in this build"), 3)

    def test_every_citation_format_is_on_the_page_without_scripts(self):
        body = self.body("/download/")
        self.assertIn('id="cite"', body)
        for heading in ("Text", "BibTeX", "CITATION.cff"):
            with self.subTest(heading=heading):
                self.assertRegex(body, rf'<h3 class="cite__heading"[^>]*>{re.escape(heading)}</h3>')
        self.assertRegex(body, r'<div class="cite__tabs" role="tablist"[^>]*hidden')
        self.assertRegex(body, r'<button class="button cite__copy"[^>]*hidden')


class DownloadDecidedTestCase(_NoDatabaseTestCase):
    def test_a_decided_fact_replaces_its_placeholder(self):
        with _decided():
            body = self.body("/download/")
        self.assertIn("Latest release · v1.0.0 · Released 2026-10-01", body)
        self.assertIn("Brightway Labs (2026). Brightway Flows v1.0.0 [Data set].", body)
        self.assertIn("https://doi.org/10.5281/zenodo.1234567", body)
        self.assertIn("ab" * 32, body)
        self.assertNotIn("[v1.0.0]", body)
        self.assertNotIn("[DATA LICENCE]", body)

    def test_a_file_links_to_the_release_once_it_has_a_doi(self):
        (self.data_dir / "lcia-differences.json").write_bytes(b"{}")
        with _decided():
            body = self.body("/download/")
        self.assertNotIn("/run/download/differences", body)
        self.assertIn('href="https://doi.org/10.5281/zenodo.1234567"', body)


class DownloadWithDatabaseTestCase(_AppTestCase):
    def test_a_database_does_not_bring_back_the_build_details(self):
        """A run existing does not change the page: build details are
        `/run/`'s alone, database or not."""
        body = self.body("/download/")
        self.assertIn('href="/run/"', body)
        for gone in ("Built from", "run-1", "Flows processed"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, body)

    def test_the_database_is_a_download_like_the_other_files(self):
        """The whole build in one file, which is what a reader who wants
        everything came for (#200)."""
        body = self.body("/download/")
        self.assertIn("consensus-flows.sqlite3", body)
        self.assertIn('href="https://doi.org/10.5281/zenodo.22857950"', body)

    def test_the_database_row_says_how_big_the_download_is(self):
        """A reader decides whether to start a multi-gigabyte download before
        starting it, so the row says the size in words, read off the file."""
        body = self.body("/download/")
        row = body[body.index("SQLite database"):body.index("consensus-flows.sqlite3")]
        self.assertRegex(row, r"<strong>[\d,.]+ (bytes|kB|MB|GB)\.</strong> The whole build")


class AboutTestCase(_NoDatabaseTestCase):
    def section(self, body: str, anchor: str) -> str:
        """The body from `id="<anchor>"` to the next `<section`."""
        start = body.index(f'id="{anchor}"')
        end = body.find("<section", start)
        return body[start:] if end == -1 else body[start:end]

    def test_every_undecided_fact_is_a_placeholder(self):
        with _undecided():
            body = self.body("/about/")
        for label in ("[Maintainer name]", "[Role]",
                      "[DATA LICENCE]", "[CODE LICENCE]", "[Postal address]",
                      "[Contact email]", "[retention period]"):
            with self.subTest(label=label):
                self.assertIn(label, body)
        self.assertIn("[Governance:", body)
        self.assertIn("[Terms for fields derived from licensed source lists", body)

    def test_every_fact_on_the_page_is_decided(self):
        """#200's "done when" for About: no amber chip left in either
        theme, because no fact behind one is open."""
        body = self.body("/about/")
        for decided in ("ODbL-1.0", "AGPL-3.0-or-later",
                        "Dorfsteig 8, 5223 Riniken, Switzerland",
                        "flows@brightway-lca.com", "14 days",
                        "in the public domain", "Chris Mutel",
                        "João Gonçalves", "David Turner"):
            with self.subTest(decided=decided):
                self.assertIn(decided, body)
        for gone in ("[DATA LICENCE]", "[CODE LICENCE]", "[Postal address]",
                     "[Contact email]", "[retention period]", "[Maintainer name]",
                     "[Terms for fields derived from licensed source lists"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, body)
        self.assertIn("made by the maintainers", body)
        self.assertNotIn('class="placeholder"', body)
        self.assertNotIn("[Governance:", body)

    def test_three_maintainers_are_maintainers_not_a_maintainer(self):
        body = self.body("/about/")
        self.assertIn(">Maintainers</h3>", body)
        self.assertNotIn(">Maintainer</h3>", body)

    def test_the_funding_line_is_gone(self):
        """How the work is funded is not a fact this page states (#200)."""
        body = self.body("/about/")
        self.assertNotIn("Funding", body)
        self.assertNotIn("[How the work is funded]", body)

    def test_the_address_names_the_country_once(self):
        body = self.body("/about/")
        self.assertEqual(body.count("Switzerland"), 1)

    def test_the_footer_anchors_exist(self):
        """The footer links to `/about/#licence`, `#privacy` and `#contact`."""
        body = self.body("/about/")
        for anchor in ("why", "who", "decisions", "contribute", "licence",
                       "contact", "privacy"):
            with self.subTest(anchor=anchor):
                self.assertIn(f'id="{anchor}"', body)
                self.assertIn(f'href="#{anchor}"', body)

    def test_why_and_who_are_separate_sections(self):
        body = self.body("/about/")
        self.assertIn(">Why we built it</h2>", body)
        self.assertIn(">Who builds it</h2>", body)
        self.assertIn('href="/docs/concepts/why"', self.section(body, "why"))
        self.assertNotIn('href="/docs/concepts/why"', self.section(body, "who"))

    def test_who_builds_it_links_to_brightway_labs(self):
        who = " ".join(self.section(self.body("/about/"), "who").split())
        for expected in ('href="https://brightway-lca.com"',
                         "brand/brightway-labs.svg",
                         "brand/brightway-labs-inverted.svg",
                         "co-founded by Chris Mutel",
                         "Brightway Cloud, a collaborative tool for LCA"):
            with self.subTest(expected=expected):
                self.assertIn(expected, who)

    def test_the_names_section_is_gone(self):
        body = self.body("/about/")
        for gone in ("Brightway, Brightway Labs and Brightway Cloud",
                     "Commercial product", "about-names"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, body)

    def test_the_report_buttons_open_the_issue_templates(self):
        """About sends a reader to the chooser rather than to one named form.
        There are nine forms now, and which one a reader wants depends on what
        they were looking at -- the pre-filled links for that are on the flow
        and substance pages, where the identifier is already known."""
        body = self.body("/about/")
        self.assertIn("/issues/new/choose", body)
        self.assertIn("/issues/new?template=answer-an-open-question.yml", body)
        self.assertIn("/blob/main/CONTRIBUTING.md", body)

    def test_decided_maintainers_and_contact_replace_their_placeholders(self):
        with _decided():
            body = self.body("/about/")
        self.assertIn("Ada Example", body)
        self.assertNotIn("[Maintainer name]", body)
        self.assertIn('href="mailto:list@example.org"', body)
        self.assertIn("CC-BY-4.0", body)


class DatabaseDownloadTestCase(_AppTestCase):
    """Plan §8 question 1 as decision 8 settled it (#200): the database may
    be published, so nothing gates it."""

    def test_the_run_page_links_the_database(self):
        client = self.client()
        self.assertIn("/run/download/database", client.get("/run/").get_data(as_text=True))

    def test_the_route_sends_the_file(self):
        response = self.client().get("/run/download/database")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)

    def test_no_variable_takes_it_off_the_site(self):
        app = create_app(self.path)
        app.config["TESTING"] = True
        self.assertNotIn("CONSENSUS_PUBLISH_DATABASE", app.config)
        client = app.test_client()
        self.assertIn("/run/download/database", client.get("/run/").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
