"""The documentation has to point at things that exist.

Prose goes stale silently. Nothing fails when a page describes an application
that was deleted, a command that was removed, or a file the pipeline stopped
writing -- the reader finds out, some time later, by following the instructions
and watching them not work.

These are the checks that can be made mechanically:

- **Every relative link resolves.** Renaming a page updates its own heading and
  leaves eight links pointing at the old name.
- **Every `#section` a link asks for is a heading that is there.** A fragment
  that matches nothing is not an error anywhere: the page opens at the top and
  the reader is left to find the section. Renaming a heading is what does it
  (#373: two links kept asking for a heading renamed in #318), and so is typing
  a fragment out by hand (#373 again: three links kept a hyphen the em dash in
  the heading does not produce).
- **Every page is in the navigation.** A page mkdocs does not build is a page
  nobody reads and nobody notices is wrong.
- **No command that was removed is still being recommended.** The four
  `webapp-*` commands went with the applications they started.
- **The commands the docs name exist.** Checked against the CLI itself rather
  than against a list, so a renamed command fails here.
- **The context list on the page is the context list in the data.** It is a
  transcription of `consensus-flows-as-strings.json`, and a transcription
  drifts: the page listed fifty entries and claimed forty-nine while the file
  held sixty, missing every `Resource / Water` intake place added in #262.
- **The harmonisation steps on the page are the chain in the code.** Four
  numbered inventories of one list, in one page, all of which renumber when a
  step is inserted -- and one of which is the classification #88 is about.

The pages checked are every `.md` under `docs/`, `README.md`, `CONTRIBUTING.md`,
`expectations/README.md` and the skills in `.claude/skills/`. The last three are
not built by mkdocs, and are checked anyway: they link to repository paths and
invoke the CLI, which is all it takes to go stale. `CONTRIBUTING.md` is read by
somebody who has never opened this repository before, so a link in it that does
not resolve is worse there than on a page for people who could find the file
anyway.

What cannot be checked mechanically -- whether the prose is *true* -- is why the
list is short.
"""

import ast
import functools
import json
import re
import unittest
from pathlib import Path

import typer

from brightway_flows.application.cli import app
from brightway_flows.filesystem import PACKAGE_DATA_DIR
from brightway_flows.transformers import DEFAULT_TRANSFORMERS
from brightway_flows.webapps.app import documentation

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

#: Every page of checked-in prose, not only the ones mkdocs builds. The skills
#: and `expectations/README.md` name repository paths and invoke the CLI exactly
#: as a page in `docs/` does, and go stale the same way; the skill is worse,
#: because it is read while somebody is changing the thing it describes. They
#: are not in the navigation and must not be -- `test_every_page_is_in_the_
#: navigation` walks `docs/` for that reason.
PAGES = (
    sorted(DOCS.rglob("*.md"))
    + sorted((ROOT / ".claude" / "skills").rglob("*.md"))
    + [
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "expectations" / "README.md",
    ]
)

#: `[text](target)` with a relative target.
_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

#: A `brightway-flows <command>` invocation in a fenced block or inline.
_INVOCATION = re.compile(r"brightway-flows\s+([a-z][a-z0-9-]*)")

#: One entry of a rendered table of contents: `<a href="#the-anchor">`.
_TOC_ANCHOR = re.compile(r'href="#([^"]+)"')


@functools.cache
def anchors_of(path: Path) -> frozenset[str]:
    """The `#fragment`s *path* answers to.

    Read off the table of contents the review application's own renderer
    produces, rather than derived from the heading text a second time here: the
    anchor a heading gets is whatever `markdown`'s `toc` extension made of its
    punctuation, and a second implementation of that would be the thing being
    tested. The extensions are `mkdocs.yml`'s, so the anchors are the same ones
    the built site uses.
    """
    _, contents = documentation.render(path.read_text(), path.stem)
    return frozenset(_TOC_ANCHOR.findall(contents))

#: A number claiming to count contexts: the digits, and up to three words
#: between them and the word `contexts`.
_CONTEXT_COUNT = re.compile(r"(\d+)((?:\s+\S+){0,3}?)\s+contexts\b")

#: A row of the ordered step table: ``| 14 | **Consensus matching** | ... |``.
_STEP_ROW = re.compile(r"^\| (\d+) \| (.+?) \| (.+?) \|$", re.MULTILINE)

#: A row of the whole-list table, whose first cell is the step number and the
#: step name together: ``| 14 Consensus matching | ... |``.
_WHOLE_LIST_ROW = re.compile(r"^\| (\d+) (.+?) \| (.+?) \|$", re.MULTILINE)

#: A ``### Steps 9-13:`` heading in the phase-by-phase walkthrough. The dash is
#: an en dash, and a single-step phase has no second number at all.
_PHASE_HEADING = re.compile(r"^### Steps? (\d+)(?:\u2013(\d+))?:", re.MULTILINE)

#: A number claiming to count harmonisation steps, written either way round:
#: ``twenty-two processing steps``, ``Eighteen of the twenty-two steps``.
_STEP_COUNT = re.compile(r"([A-Za-z-]+|\d+)\s+(?:of the\s+([A-Za-z-]+|\d+)\s+)?"
                         r"(?:processing )?steps\b")

#: The number words in order, so that the index is the value. Enough of them to
#: read the counts the page states: it is prose for an engineer, so it spells a
#: number out (conventions section 11), while the code it describes counts in
#: digits.
_UNITS = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
)
_NUMBER_WORDS = {word: value for value, word in enumerate(_UNITS)}
_NUMBER_WORDS["twenty"] = 20
_NUMBER_WORDS.update(
    {f"twenty-{word}": 20 + value for value, word in enumerate(_UNITS) if value}
)


def as_number(token: str) -> int | None:
    """The integer a count token states, or None if it is not a count."""
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token.lower())


#: One bullet of the flat context list: ``* ['Environmental', 'Air']``, with an
#: optional trailing note such as ``— _deprecated_``.  The opening quote is part
#: of the pattern: the page has ordinary bullets that begin with a markdown
#: link, and ``* [Confined aquifer …](https://…)`` is not a context.
_CONTEXT_BULLET = re.compile(r"^\* (\['[^\]]*\])(.*)$", re.MULTILINE)

#: Commands that went with the four applications they started. Named rather
#: than derived, because the point is that they must not come back into the
#: docs by way of a copied example.
REMOVED_COMMANDS = frozenset({
    "webapp-inputs", "webapp-consensus", "webapp-run-report", "webapp-etl",
    "migrate-layered", "generate-ecoinvent-additional-inputs",
    # Wrote a `transform-sources.json` selecting which files became consensus
    # flows -- the input half of the input/source split (#210).
    "generate-sources-config",
})


def command_names() -> set[str]:
    return set(typer.main.get_command(app).commands)


def page_id(page: Path) -> str:
    """How a page is named in a subtest. The path, not the filename: `README.md`
    is now three different files and a bare name would not say which failed."""
    return page.relative_to(ROOT).as_posix()


class AgentsRuleReferenceTestCase(unittest.TestCase):
    """A citation of `AGENTS.md <n>` still points at the rule it meant.

    The rules are numbered, and code and curated data cite them by number.
    Inserting a rule renumbers every one below it, and nothing was checking
    that the citations moved with them: #89's title rule went in at 34 and
    pushed the naming rule to 35, leaving three comments in
    `ef-3.1-manual-fixes.json` citing 34 for a rule that had become "an issue
    or pull request title says plainly what changed".

    A dangling number cannot be caught by parsing alone -- the renumbered rule
    still exists -- so each citation is pinned to a word its rule contains. A
    renumber then fails here, and whoever does it updates both.
    """

    #: The word a cited rule has to still contain.  One entry per rule number
    #: any file cites; add to it when a new citation is written.
    EXPECTED = {
        3: "extra",           # merge/additions.py, merge/datastores.py
        17: "provenance",     # tests/test_curated_object_names.py
        22: "bounded",        # tools/verify_run.py
        32: "branch",         # tests/test_architecture_structure.py
        35: "names",          # data/ef-3.1-manual-fixes.json, three citations
    }

    def _rules(self) -> dict[int, str]:
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        rules: dict[int, str] = {}
        current: int | None = None
        for line in text.splitlines():
            started = re.match(r"^(\d+)\.\s+(.*)$", line)
            if started:
                current = int(started.group(1))
                rules[current] = started.group(2)
            elif current is not None and line[:1] == " " and line.strip():
                # Continuations are indented to clear the number, so a
                # single-digit rule wraps at three spaces and a two-digit one
                # at four.  Matching on four missed every rule below ten.
                rules[current] += " " + line.strip()
            elif not line.strip():
                continue
            else:
                current = None
        return rules

    def _citations(self) -> set[int]:
        pattern = re.compile(r"AGENTS(?:\.md)?\s+(?:rule\s+)?(\d+)\b")
        found: set[int] = set()
        for path in ROOT.rglob("*"):
            if path.suffix not in {".py", ".json", ".md"} or not path.is_file():
                continue
            if ".git" in path.parts or path.name == "AGENTS.md":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            found.update(int(m) for m in pattern.findall(text))
        return found

    def test_every_cited_rule_number_exists(self):
        rules = self._rules()
        self.assertTrue(rules, "no rules parsed out of AGENTS.md")
        for number in sorted(self._citations()):
            with self.subTest(rule=number):
                self.assertIn(number, rules, f"AGENTS.md has no rule {number}")

    def test_every_cited_rule_is_still_about_what_cited_it(self):
        rules = self._rules()
        for number, word in self.EXPECTED.items():
            with self.subTest(rule=number):
                self.assertIn(number, rules)
                self.assertIn(
                    word, rules[number].lower(),
                    f"AGENTS.md {number} no longer mentions {word!r}; a renumber "
                    f"has moved it out from under the files citing it",
                )

    def test_the_citations_this_pins_are_the_ones_that_exist(self):
        """`EXPECTED` going stale is the failure mode this whole class has."""
        self.assertEqual(self._citations(), set(self.EXPECTED))


class LinkTestCase(unittest.TestCase):
    def test_every_relative_link_resolves(self):
        for page in PAGES:
            for target in _LINK.findall(page.read_text()):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                path = target.split("#", 1)[0]
                if not path:
                    continue
                with self.subTest(page=page_id(page), target=target):
                    self.assertTrue(
                        (page.parent / path).resolve().exists(),
                        f"{page.relative_to(ROOT)} links to {target}",
                    )

    def test_every_link_to_a_section_names_a_heading_that_is_there(self):
        """A fragment matching no heading opens the page at the top (#373).

        Nothing else says so: the page is real and the link works, it simply
        does not land, and the reader is left to find the section themselves.
        Same-page fragments are checked too -- `[the box below](#...)` goes
        stale exactly as a link to another page does.
        """
        for page in PAGES:
            for target in _LINK.findall(page.read_text()):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                path, _, fragment = target.partition("#")
                if not fragment:
                    continue
                other = page if not path else (page.parent / path).resolve()
                # A target that is not there at all is the test above's.
                if other.suffix != ".md" or not other.is_file():
                    continue
                with self.subTest(page=page_id(page), target=target):
                    self.assertIn(
                        fragment,
                        anchors_of(other),
                        f"{page.relative_to(ROOT)} links to {target}, and "
                        f"{other.relative_to(ROOT)} has no heading with that "
                        f"anchor",
                    )

    def test_every_page_is_in_the_navigation(self):
        """A page mkdocs does not build is a page nobody reads."""
        nav = (ROOT / "mkdocs.yml").read_text()
        for page in sorted(DOCS.rglob("*.md")):
            relative = page.relative_to(DOCS).as_posix()
            with self.subTest(page=relative):
                self.assertIn(relative, nav)


class CommandTestCase(unittest.TestCase):
    def test_no_removed_command_is_still_recommended(self):
        for page in PAGES:
            text = page.read_text()
            for name in sorted(REMOVED_COMMANDS):
                # A line explaining that the command is *gone* is the one place
                # its name belongs, so only invocations count.
                for match in re.finditer(rf"brightway-flows\s+{re.escape(name)}\b", text):
                    with self.subTest(page=page_id(page), command=name):
                        self.fail(
                            f"{page.relative_to(ROOT)} invokes the removed "
                            f"command `{name}`: ...{text[max(0, match.start() - 60):match.end()]}"
                        )

    def test_every_command_the_docs_invoke_exists(self):
        """Checked against the CLI, so renaming a command fails here."""
        known = command_names()
        for page in PAGES:
            for name in set(_INVOCATION.findall(page.read_text())):
                with self.subTest(page=page_id(page), command=name):
                    self.assertIn(
                        name, known,
                        f"{page.relative_to(ROOT)} invokes `{name}`, which the "
                        "CLI does not have",
                    )

    def test_the_review_application_is_one_command(self):
        """Five commands started five applications; one starts the one."""
        webapp_commands = {name for name in command_names() if "webapp" in name}
        self.assertEqual(webapp_commands, {"webapp"})


class ArtifactTestCase(unittest.TestCase):
    """Files the pipeline stopped writing must not be described as outputs.

    `elementary-flows.json`, `flow-objects.json` and `harmonised-flows.json`
    stopped being written before the review application was consolidated, and
    three pages went on telling readers to open them. The record shapes are
    still real -- they are JSON columns in the database -- so the names still
    appear, in sections that say so.
    """

    UNWRITTEN = ("elementary-flows.json", "flow-objects.json",
                 "harmonised-flows.json")

    def test_nothing_writes_them(self):
        """The premise. If one comes back, this test is what to delete."""
        source = "\n".join(
            path.read_text()
            for path in (ROOT / "src").rglob("*.py")
            if path.name != "filesystem.py"
        )
        for constant in ("ELEMENTARY_FLOWS_FILEPATH", "FLOW_OBJECTS_FILEPATH"):
            with self.subTest(constant):
                self.assertNotIn(constant, source)

    def test_the_harmonised_flows_path_is_gone_entirely(self):
        """#5: this one has no reader either, so it kept no constant.

        Its two siblings are still named in `filesystem.py`, because
        `tests/test_schemas.py` opens them when an old data directory has them.
        `harmonised-flows.json` had no such reader, so excluding `filesystem.py`
        the way the test above does would have made the assertion vacuous.
        """
        source = "\n".join(
            path.read_text() for path in (ROOT / "src").rglob("*.py")
        )
        self.assertNotIn("HARMONISED_FLOWS_FILEPATH", source)

    def test_the_outputs_page_says_they_are_not_written(self):
        """The page a reader consults to choose an output has to say so."""
        text = (DOCS / "using" / "outputs.md").read_text()
        self.assertIn("are not written", text)
        for name in self.UNWRITTEN[:2]:
            with self.subTest(name):
                self.assertIn(name, text)


class ContextListTestCase(unittest.TestCase):
    """`concepts/contexts.md` prints the whole context vocabulary.

    A reader placing a compartment reads that list and nothing else -- it is the
    only page that states the vocabulary in full. It is a transcription, so it
    drifts, and it did: fifty bullets against sixty entries in the data,
    including all six places a water withdrawal can be taken from (#262). This
    is the check that would have caught it.
    """

    @staticmethod
    def _from_the_data() -> dict[tuple[str, ...], bool]:
        """Every context, mapped to whether it is deprecated."""
        strings = json.loads(
            (PACKAGE_DATA_DIR / "consensus-flows-as-strings.json").read_text()
        )
        records = json.loads(
            (PACKAGE_DATA_DIR / "consensus-flow-contexts.json").read_text()
        )
        retired = {r["context_iri"] for r in records if r.get("deprecated")}
        return {tuple(value): iri in retired for iri, value in strings.items()}

    @staticmethod
    def _from_the_page() -> dict[tuple[str, ...], bool]:
        text = (DOCS / "concepts" / "contexts.md").read_text()
        listed: dict[tuple[str, ...], bool] = {}
        for value, note in _CONTEXT_BULLET.findall(text):
            listed[tuple(ast.literal_eval(value))] = "deprecated" in note
        return listed

    def test_the_page_lists_every_context_and_no_others(self):
        data = self._from_the_data()
        page = self._from_the_page()
        self.assertEqual(
            sorted(data),
            sorted(page),
            "docs/concepts/contexts.md and consensus-flows-as-strings.json "
            "disagree about which contexts exist",
        )

    def test_the_page_marks_the_deprecated_ones(self):
        """A deprecated context stays on the page: a reader meeting one in an
        old artifact needs to be able to look it up and find out that it is
        retired, which a page that simply dropped it cannot tell them."""
        data = self._from_the_data()
        page = self._from_the_page()
        for value, retired in sorted(data.items()):
            with self.subTest(context=value):
                self.assertEqual(retired, page.get(value), value)

    #: Phrases that count contexts and are *not* claims about today's
    #: vocabulary. Listed one by one, with the reason, because the alternative
    #: is a looser pattern that would stop catching the claims that matter.
    NOT_A_CURRENT_COUNT = {
        # How wrong a merge bug was, measured against the vocabulary as it stood
        # when the bug was found. A historical measurement, not a claim.
        "37 of 49** registered contexts",
        # A row number in the semantic-typing rules table, followed by the word.
        "9 | its contexts",
    }

    def test_no_page_states_a_stale_count(self):
        """Four pages state the number, and correcting three of them is a fix
        that lasts until the next person corrects three of them.

        `concepts/contexts.md`, `concepts/why.md` and `reference/limitations.md`
        were corrected together while `concepts/glossary.md` went on saying
        forty-nine, which is why this is asked of every page rather than of the
        page the list happens to be on.
        """
        live = sum(1 for retired in self._from_the_data().values() if not retired)
        for page in PAGES:
            for match in _CONTEXT_COUNT.finditer(page.read_text()):
                phrase = match.group(0)
                if phrase in self.NOT_A_CURRENT_COUNT:
                    continue
                with self.subTest(page=page_id(page), phrase=phrase):
                    self.assertEqual(
                        int(match.group(1)),
                        live,
                        f"{page.name} says {phrase!r}; the data has {live} live "
                        f"contexts. If this is a historical figure rather than a "
                        f"claim about today, add it to NOT_A_CURRENT_COUNT with "
                        f"the reason.",
                    )

    def test_the_context_page_states_the_count(self):
        """Not only that no page is wrong: the page has to say it at all."""
        text = (DOCS / "concepts" / "contexts.md").read_text()
        live = sum(1 for retired in self._from_the_data().values() if not retired)
        self.assertIn(f"**{live} allowed contexts**", text)


class HarmonisationStepsTestCase(unittest.TestCase):
    """`reference/harmonisation-steps.md` is the ordered inventory of the chain.

    It states the same list four times -- a count in the opening sentence, a
    table of every step, a table of the four that are shown every flow, and a
    run of phase headings covering the numbers -- and inserting a step at
    position 12 renumbers three of them. None of that is checked by running the
    pipeline, because the pipeline never reads the page.

    The whole-list table is the one worth a test on its own. It is a
    transcription of `answers_per_flow`, the flag whose whole documented
    hazard is that getting it wrong is silent (#88, conventions section 4). A
    page that says a step is shown every flow, when the code stopped showing it
    every flow, is the same wrong answer one level out.
    """

    PAGE = DOCS / "reference" / "harmonisation-steps.md"

    @staticmethod
    def _section(text: str, heading: str) -> str:
        """The page from *heading* up to the next one at the same level.

        Bounded rather than read to the end of the page, because the layering
        section further down has a table of thirteen numbered passes and an
        unbounded read matches those as steps 1 to 13 a second time.
        """
        body = text.split(f"## {heading}", 1)[1]
        return body.split("\n## ", 1)[0]

    @classmethod
    def setUpClass(cls):
        cls.text = cls.PAGE.read_text()
        cls.order = cls._section(cls.text, "The order")
        cls.shown = cls._section(cls.text, "What each step is shown")

    def _order_table(self) -> list[tuple[int, str]]:
        """The numbered steps, in page order, names stripped of emphasis."""
        return [
            (int(number), name.strip().strip("*"))
            for number, name, _ in _STEP_ROW.findall(self.order)
        ]

    def test_the_order_table_is_the_default_chain(self):
        """One row per registered transformer, numbered from one without a gap.

        Not a check that the names match -- the page names a step the way an
        engineer would say it, `Strip element-symbol synonyms` against
        `strip_element_symbol_altlabels`, and it should keep doing that. The
        count and the numbering are the part a transcription gets wrong.
        """
        rows = self._order_table()
        self.assertEqual(
            [number for number, _ in rows],
            list(range(1, len(DEFAULT_TRANSFORMERS) + 1)),
            f"the order table in {self.PAGE.name} is numbered "
            f"{[n for n, _ in rows]}; DEFAULT_TRANSFORMERS has "
            f"{len(DEFAULT_TRANSFORMERS)} steps, numbered 1 upwards",
        )

    def test_the_whole_list_table_is_the_whole_list_transformers(self):
        """The steps the page says are shown every flow are exactly the steps
        that declare `answers_per_flow = False`, at the right numbers."""
        expected = [
            position
            for position, cls in enumerate(DEFAULT_TRANSFORMERS, start=1)
            if not cls.answers_per_flow
        ]
        listed = [int(number) for number, _, _ in _WHOLE_LIST_ROW.findall(self.shown)]
        self.assertEqual(
            expected,
            listed,
            f"{self.PAGE.name} says steps {listed} ask a question about the set; "
            f"the transformers declaring answers_per_flow = False are at "
            f"positions {expected} "
            f"({[DEFAULT_TRANSFORMERS[p - 1].name for p in expected]})",
        )

    def test_the_two_tables_name_a_step_the_same_way(self):
        """A step renamed in one table and not the other reads as two steps."""
        names = dict(self._order_table())
        for number, name, _ in _WHOLE_LIST_ROW.findall(self.shown):
            with self.subTest(step=int(number)):
                self.assertEqual(
                    names.get(int(number)),
                    name.strip().strip("*"),
                    f"step {number} is named differently in the two tables",
                )

    def test_no_page_states_a_stale_step_count(self):
        """Both counts, wherever they are written.

        `Eighteen of the twenty-two steps` states them together, so a step added
        without touching the sentence leaves both halves wrong at once.
        """
        total = len(DEFAULT_TRANSFORMERS)
        per_flow = sum(1 for cls in DEFAULT_TRANSFORMERS if cls.answers_per_flow)
        for page in PAGES:
            for match in _STEP_COUNT.finditer(page.read_text()):
                phrase = match.group(0)
                # `N steps` puts the total first; `N of the M steps` puts the
                # per-flow count first and the total second.
                subset, whole = match.groups()
                if whole is None:
                    subset, whole = None, subset
                if subset is not None:
                    with self.subTest(page=page_id(page), phrase=phrase, half="per flow"):
                        self.assertEqual(
                            as_number(subset),
                            per_flow,
                            f"{page.name} says {phrase!r}; {per_flow} of the "
                            f"registered transformers declare answers_per_flow",
                        )
                if as_number(whole) is None:
                    continue  # "these steps", "the steps" -- not a count at all
                with self.subTest(page=page_id(page), phrase=phrase):
                    self.assertEqual(
                        as_number(whole),
                        total,
                        f"{page.name} says {phrase!r}; DEFAULT_TRANSFORMERS has "
                        f"{total} steps in all",
                    )

    def test_the_phase_headings_cover_every_step(self):
        """`## Phase by phase` walks the chain in ranges, and a step that falls
        between two of them is in the table and described nowhere."""
        covered: list[int] = []
        for first, last in _PHASE_HEADING.findall(self.text):
            covered.extend(range(int(first), int(last or first) + 1))
        self.assertEqual(
            covered,
            list(range(1, len(DEFAULT_TRANSFORMERS) + 1)),
            f"the phase headings in {self.PAGE.name} cover steps {covered}; "
            f"the chain has {len(DEFAULT_TRANSFORMERS)}",
        )


class RenumberedCorrectionCountsTestCase(unittest.TestCase):
    """`sources.md` counts the corrections each renumbering answer covers.

    Three counts, all read out of `ecoinvent-match-overrides.json`, and all of
    them the kind that moves when somebody adds a row: thirteen vanadium
    corrections say the decision does not carry across the renumbering, nine
    chromium and five copper oxychloride ones say it does.  The page names them
    to make the two answers concrete, and a page that says "nine" beside a file
    holding ten is worse than one that says nothing.
    """

    PAGE = DOCS / "operating" / "sources.md"
    OVERRIDES = PACKAGE_DATA_DIR / "ecoinvent-match-overrides.json"

    #: The number word the page uses, against how the row is counted.
    WORDS = {13: "thirteen", 9: "nine", 5: "five", 1: "one"}

    def setUp(self):
        self.rows = json.loads(self.OVERRIDES.read_text())["overrides"]
        # Lower-cased: a count that opens a sentence is capitalised, and which
        # of the three does is not a fact worth pinning.
        self.text = self.PAGE.read_text().lower()

    def _count(self, field, substance):
        return sum(
            1
            for row in self.rows
            if row.get(field) and row.get("source_name") == substance
        )

    def test_the_page_counts_the_guarded_and_the_checked_rows(self):
        for field, substance, phrase in (
            ("only_when_named", "Vanadium V", "{word} vanadium rows"),
            ("carries_when_registered_as", "Chromium III", "{word} `Chromium III` rows"),
            # Copper oxychloride's five recorded declines were spent when #141
            # retired the tables; lutetium's typo pair is the entry that
            # remains beside chromium's.
            (
                "carries_when_registered_as",
                "Lutetium, In Ground",
                "{word} `Lutetium, in ground` row",
            ),
        ):
            count = self._count(field, substance)
            with self.subTest(substance=substance):
                self.assertIn(count, self.WORDS, f"{substance}: {count} rows")
                self.assertIn(
                    phrase.format(word=self.WORDS[count]).lower(),
                    self.text,
                    f"{self.PAGE.name} does not say there are {count} rows with "
                    f"{field!r} for {substance}.",
                )


class ELINCSCheckDigitCountsTestCase(unittest.TestCase):
    """`harmonisation-steps.md` counts the EC numbers the check-digit exception covers.

    Two numbers, both transcribed out of `ec-inventory.json.gz`: how many
    substances the inventory holds, and how many of them carry a check digit
    the ordinary mod-11 rule refuses.  They are the whole argument for reading
    remainder 10 as a 1 rather than as a typing error, which is #120 -- so a
    page that says 181 beside a file that has come to hold a different number
    is stating the evidence wrongly, not merely going stale.

    Re-downloading the inventory is what would move them.  The counts are
    recomputed here rather than stored, so the page is checked against the file
    the pipeline actually reads.
    """

    PAGE = DOCS / "reference" / "harmonisation-steps.md"

    @classmethod
    def setUpClass(cls) -> None:
        from brightway_flows.integrations.ec_inventory import load_ec_inventory

        cls.numbers = [
            record["ec_number"]
            for record in load_ec_inventory()["records"]
            if record.get("ec_number")
        ]
        # Line breaks are the author's, not the claim's, so the page is read as
        # one run of words: rewrapping a paragraph must not fail this.
        cls.text = " ".join(cls.PAGE.read_text().split())

    @staticmethod
    def _remainder(ec: str) -> int:
        digits = ec.replace("-", "")
        return sum(int(d) * (i + 1) for i, d in enumerate(digits[:6])) % 11

    def test_the_page_counts_the_inventory_and_its_exceptions(self):
        exceptional = sum(1 for ec in self.numbers if self._remainder(ec) == 10)
        phrase = f"{exceptional} of the {len(self.numbers):,} substances in the inventory"
        self.assertIn(
            phrase,
            self.text,
            f"{self.PAGE.name} does not say there are {exceptional} such "
            f"numbers among {len(self.numbers):,}.",
        )


class RecognisedCompartmentCountsTestCase(unittest.TestCase):
    """`matching-your-own-list.md` tells a reader how many compartments are
    recognised, and where they came from.

    Six numbers, all read out of `context-manual-mapping.json`: 26 from BAFU,
    26 from ecoinvent across its five releases, 37 from EF 3.1, 21 from
    GreenDelta's openLCA package, 11 from Stepwise 2006, and 119 in total.

    They used to add up exactly, because the vendors shared no compartment
    spelling.  Stepwise is a SimaPro method file and two of its eleven are
    ecoinvent's spellings exactly, so the total is now the sum less the two
    that are written twice -- and the page says so rather than leaving a reader
    to find that the arithmetic does not work.  What is still checked is that
    the page's total is the number of distinct compartments, which is what a
    reader is being promised.

    The page is the only place a reader is *promised* a number here, and it is
    the number that says whether their own list will be understood. A curator
    adding a compartment rule moves it.
    """

    PAGE = DOCS / "using" / "matching-your-own-list.md"

    @staticmethod
    def _vendor(source: str) -> str:
        return "ecoinvent" if source.startswith("ecoinvent") else source

    def setUp(self):
        from brightway_flows.context_mapping import context_mapping_index

        by_vendor: dict[str, set] = {}
        for source, compartment in context_mapping_index():
            by_vendor.setdefault(self._vendor(source), set()).add(compartment)
        self.by_vendor = {vendor: len(keys) for vendor, keys in by_vendor.items()}
        self.total = len({compartment for _s, compartment in context_mapping_index()})
        # Whitespace collapsed, because the page is hard-wrapped prose and which
        # side of a line break a number falls on is not a fact worth pinning.
        self.text = " ".join(self.PAGE.read_text().split())

    def test_the_five_vocabularies_are_counted_correctly(self):
        for vendor, phrase in (
            ("bafu-2026-v1", "BAFU has already written down what those {n} compartments"),
            ("ecoinvent", "So has ecoinvent for its {n}"),
            ("ef 3.1", "EF 3.1 for its {n}"),
            # Not a list that gets merged: GreenDelta's rows say what the
            # compartments of an LCIA package mean, so a factor of theirs can
            # reach a flow of ours by substance (#165).
            ("greendelta", "openLCA method package for its {n}"),
            ("stepwise-2006-1.09", "and Stepwise 2006 for its {n}"),
            ("agribalyse-3.2", "AGRIBALYSE 3.2 for its {n}"),
        ):
            count = self.by_vendor[vendor]
            with self.subTest(vendor=vendor, count=count):
                self.assertIn(phrase.format(n=count), self.text)

    #: Compartment strings two vendors write.  Two are ecoinvent's, which
    #: Stepwise writes because a SimaPro method file's vocabulary is close to
    #: ecoinvent's; the other eighteen are BAFU's, which AGRIBALYSE writes
    #: because both are SimaPro's export vocabulary.
    #: `test_generic_context_resolution` is where they are pinned with the
    #: contexts they agree on.
    SHARED = 20

    def test_the_total_is_the_sum_less_what_two_vendors_both_write(self):
        self.assertEqual(sum(self.by_vendor.values()) - self.SHARED, self.total)
        self.assertIn(
            f"{self.total} compartment names are recognised", self.text
        )
        self.assertIn("are ecoinvent's spellings exactly", self.text)


class SimaproCompartmentCountTestCase(unittest.TestCase):
    """`matching-your-own-list.md` also counts SimaPro's own spellings (#328).

    The same argument as the case above, for the section beside it: the page
    promises a reader that their compartments will be understood, and the number
    is what says how far that goes. A curator adding a SimaPro compartment moves
    it, and nothing else would notice.
    """

    PAGE = DOCS / "using" / "matching-your-own-list.md"

    def setUp(self):
        from brightway_flows.context_mapping import simapro_context_rules

        self.count = len(simapro_context_rules())
        self.text = " ".join(self.PAGE.read_text().split())

    def test_the_page_counts_the_spellings_the_file_holds(self):
        self.assertIn(f"Another {self.count} spellings are read", self.text)


class ParticulateFlowClassCountTestCase(unittest.TestCase):
    """`deciding/merging.md` says how many rows the size-class table holds.

    The point that sentence is making is that *not one* of them carries a
    registry number, which is why the merge looks the window up instead of
    reading a name.  A curator adding rows moves the number and nothing else
    would notice, so it is held against the file it came from.
    """

    PAGE = DOCS / "deciding" / "merging.md"

    def setUp(self):
        from brightway_flows.domain.particulate_size import (
            particulate_class_by_source_flow,
        )

        self.count = len(particulate_class_by_source_flow())
        self.text = " ".join(self.PAGE.read_text().split())

    def test_the_page_counts_the_rows_the_file_holds(self):
        self.assertIn(f"the {self.count} rows in the size-class table", self.text)


class PlacementTableTestCase(unittest.TestCase):
    """`assessing.md` prints a sample of the placement table, and it goes stale.

    A number copied out of `data/` can be checked against the file it came from,
    which is what the cases above do.  A number copied out of a *build* had
    nothing checking it, and that is not hypothetical: while this case was being
    written, a branch's copy of this table said 64 unplaced BAFU rows and 85.0%
    on an existing flow, while its own `expectations/baseline.json` -- recorded
    from a later build of the same branch -- said 14 and 86.9%.  A reader has no
    way to tell which of the two is the build they would get.

    `baseline.json` is the one build figure the repository does keep, rewritten
    by `assess --record`, so it is what the sample is held against.  Only the
    numbers the baseline carries are checked: the sample is illustrative and may
    show a list the baseline was not recorded over, which is not drift.
    """

    PAGE = DOCS / "operating" / "assessing.md"
    BASELINE = ROOT / "expectations" / "baseline.json"

    #: ``  bafu-2026-v1   2,679   16   2,312   0   337   14   1,270   178   86.9%``
    ROW = re.compile(
        r"^\s{2}([a-z][a-z0-9.-]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)"
        r"\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d.]+)%\s*$",
        re.MULTILINE,
    )
    #: The sample's columns, in order, against the measure each one prints.
    COLUMNS = (
        "prepared",
        "algorithm",
        "manual_addition",
        "created",
        "unmatched",
        "on_characterised_flow",
        "unit_mismatch",
    )

    def setUp(self):
        self.measures = json.loads(self.BASELINE.read_text())["measures"]

    def test_the_sample_placement_table_matches_the_baseline(self):
        rows = self.ROW.findall(self.PAGE.read_text())
        self.assertTrue(rows, f"no placement table found in {self.PAGE.name}")
        checked = 0
        for row in rows:
            source, printed = row[0], row[2:9]
            for column, value in zip(self.COLUMNS, printed, strict=True):
                key = f"merge.{source}.{column}"
                if key not in self.measures:
                    continue
                checked += 1
                with self.subTest(measure=key):
                    self.assertEqual(
                        int(value.replace(",", "")),
                        self.measures[key],
                        f"{self.PAGE.name} prints {value} for {key}; "
                        "`assess --record` last wrote "
                        f"{self.measures[key]}. Re-copy the table from a build, "
                        "or record the baseline from the build it came from.",
                    )
        self.assertTrue(checked, "no column of the sample table reached a measure")


class PublishedCategoryCountTestCase(unittest.TestCase):
    """The number of impact categories is arithmetic over the method files.

    A count out of `data/` rather than out of a build (rule 30), so it is
    checkable without one: every method file states its categories and its
    implementations, and the published set is the sum of one times the other.
    It moved from 100 to 138 when Stepwise 2006 was added, and the pages that
    quote it are not the pages anybody edits when adding a method.
    """

    #: `138 categories`, `the 138 `ImpactCategory` objects`.  A page wraps, so
    #: the number and the word are separated by whitespace of any kind and the
    #: phrase is normalised before it is compared.
    COUNT = re.compile(
        r"\b(\d{2,4})\s+(?:published\s+)?(?:`?ImpactCategory`?\s+objects|categories\b)"
    )

    #: Phrases that are about one method rather than the published set.  Compared
    #: against the match with its whitespace collapsed, so a wrapped line reads
    #: the same as an unwrapped one.
    NOT_THE_PUBLISHED_SET = {
        "25 categories",  # EF 3.1's own, times four implementations
        "19 categories",  # Stepwise 2006's own, times two
        "100 categories",  # EF 3.1's four implementations, in `using/outputs.md`
    }

    def _expected(self) -> int:
        from brightway_flows.domain.lcia.crosswalk import lcia_methods

        return sum(
            len(method.categories) * len(method.implementations)
            for method in lcia_methods()
        )

    def test_the_arithmetic_is_what_the_method_files_say(self):
        # 25 x 4 + 19 x 2. Stated here so that a method file gaining an
        # implementation is a number this test moves rather than one it accepts.
        self.assertEqual(self._expected(), 138)

    def test_no_page_states_a_stale_category_count(self):
        expected = self._expected()
        for page in PAGES:
            for match in self.COUNT.finditer(page.read_text()):
                phrase = " ".join(match.group(0).split())
                if phrase in self.NOT_THE_PUBLISHED_SET:
                    continue
                with self.subTest(page=page_id(page), phrase=phrase):
                    self.assertEqual(
                        int(match.group(1)),
                        expected,
                        f"{page.name} says {phrase!r}; the method files state "
                        f"{expected} published categories. If this is about one "
                        f"method rather than the published set, add it to "
                        f"NOT_THE_PUBLISHED_SET with the reason.",
                    )


class LandTaxonomyCountsTestCase(unittest.TestCase):
    """`land-taxonomy-overview.md` counts the rows and classes of `data/`.

    Both numbers come straight out of `land-flow-classes.json`, which is
    regenerated whenever a list is added to `tools/build_land_flow_classes.py`,
    and nothing was holding the page against it: #174 added Stepwise 2006 and
    moved 1,288 to 1,316 and 336 to 339, in a page, two tests and two source
    comments that a curator adding the next list would have to remember. Rule
    30, applied to the page that had been missed.
    """

    PAGE = ROOT / "land-taxonomy-overview.md"

    def setUp(self):
        from brightway_flows.domain.land_flow_classes import (
            land_class_by_source_flow,
        )

        rows = land_class_by_source_flow()
        self.rows = len(rows)
        self.classes = len({row.land_use.key for row in rows.values()})
        self.text = " ".join(self.PAGE.read_text().split())

    def test_the_page_counts_the_classes_the_file_reaches(self):
        self.assertIn(f"**{self.classes} land classes**", self.text)

    def test_the_page_counts_the_rows_the_file_holds(self):
        self.assertIn(f"**{self.rows:,} source flows**", self.text)
        self.assertIn(f"holds all {self.rows:,},", self.text)


class CuratedNameCountsTestCase(unittest.TestCase):
    """`matching-your-own-list.md` copies the land table's row and name counts.

    The sentence is the page's argument for why the name-keyed join can answer
    a land row with no readable compartment at all, and both numbers come out
    of `land-flow-classes.json` exactly as `LandTaxonomyCountsTestCase`'s do.
    Rule 30, applied to the copy #358 added.
    """

    PAGE = DOCS / "using" / "matching-your-own-list.md"

    def setUp(self):
        from brightway_flows.domain.land_flow_classes import (
            land_class_by_source_flow,
        )

        rows = land_class_by_source_flow()
        self.rows = len(rows)
        self.names = len({row.source_name for row in rows.values()})
        self.text = " ".join(self.PAGE.read_text().split())

    def test_the_page_counts_the_rows_and_names_of_the_land_table(self):
        self.assertIn(
            f"no two of the land table's {self.rows:,} rows disagree about "
            f"any of its {self.names} names",
            self.text,
        )


class ConversionMultiplierTableTestCase(unittest.TestCase):
    """`reference/schemas.md` prints the conversion multipliers out of `data/`.

    One table per source list, transcribed from that list's
    `*-match-overrides.json` -- and a transcription drifts in both directions.
    The ecoinvent table went on printing a `Gas, mine, off-gas` row at 36.0
    long after the redirection that removed it, and it gained none of Stepwise
    2006's twelve energy carriers on the day that list arrived with its own
    heating values. Rule 30.
    """

    PAGE = DOCS / "reference" / "schemas.md"

    #: The sentence each list's crossing table is counted in. A crossing is a
    #: mapping whose two ends are measured in different units; the ore
    #: conversions, where both ends are kilograms, are `ORE_PHRASES` below,
    #: because they are a different table and a different reason.
    CROSSING_PHRASES = {
        "ecoinvent-match-overrides.json": "Six ecoinvent flows",
        "bafu-2026-v1-match-overrides.json": "BAFU's eight",
        "stepwise-2006-match-overrides.json": "Twelve rows, every one taken from",
        # Absent until the #354 work landed with the table untranscribed --
        # exactly the drift this class exists to catch, and it caught it: nine
        # subfailures on `main` until the page printed the water conversions.
        "agribalyse-3.2-match-overrides.json": "AGRIBALYSE's eight",
    }

    #: The same, for the mappings whose two ends share a unit and still need a
    #: factor, because what is measured changed: the ore against the metal.
    ORE_PHRASES = {
        "ecoinvent-match-overrides.json": "so its three appear in 3.8 and 3.9.1 only",
        "bafu-2026-v1-match-overrides.json": "BAFU ships two of the same three ores",
    }

    def setUp(self):
        self.text = self.PAGE.read_text()
        self.flat = " ".join(self.text.split())
        self.files = {
            path.name: json.loads(path.read_text())["overrides"]
            for path in sorted(PACKAGE_DATA_DIR.glob("*-match-overrides.json"))
        }

    @staticmethod
    def _conversions(overrides):
        """Every (source flow, factor) a file states, releases included."""
        for row in overrides:
            factors = []
            if "conversion_factor" in row:
                factors.append(row["conversion_factor"])
            factors.extend(row.get("conversion_by_release", {}).values())
            for factor in factors:
                yield row["source_name"], float(factor)

    @staticmethod
    def _units(value):
        """A row's unit as a set: one list ships a flow under two spellings."""
        return frozenset(value) if isinstance(value, list) else frozenset({value})

    @classmethod
    def _crossings(cls, overrides):
        """The source flows whose mapping changes what is measured, and the
        ones whose two ends are one unit and still carry a factor."""
        crossing, ore = set(), set()
        for row in overrides:
            if "conversion_factor" not in row and "conversion_by_release" not in row:
                continue
            same = cls._units(row.get("source_unit")) == cls._units(
                row.get("target_unit")
            )
            (ore if same else crossing).add(row["source_name"])
        return crossing, ore

    @staticmethod
    def _stated(phrase):
        """The count a phrase spells out: `BAFU's eight` is 8."""
        for word in phrase.split():
            value = as_number(word.lower().rstrip(",:").removesuffix("'s"))
            if value is not None:
                return value
        return None

    def test_every_curated_conversion_is_printed_with_its_factor(self):
        checked = 0
        lines = self.text.splitlines()
        for name, overrides in self.files.items():
            for source, factor in self._conversions(overrides):
                checked += 1
                with self.subTest(file=name, flow=source, factor=factor):
                    self.assertTrue(
                        any(
                            f"`{source}`" in line and str(factor) in line
                            for line in lines
                        ),
                        f"{self.PAGE.name} prints no row for {source!r} at "
                        f"{factor}, which {name} states. A conversion nobody "
                        f"can read is a kilogram characterised as a megajoule.",
                    )
        self.assertTrue(checked, "no conversion rows found in data/")

    def test_the_page_counts_each_table(self):
        for phrases, index in ((self.CROSSING_PHRASES, 0), (self.ORE_PHRASES, 1)):
            for name, phrase in phrases.items():
                expected = len(self._crossings(self.files[name])[index])
                with self.subTest(file=name, phrase=phrase):
                    self.assertIn(phrase, self.flat)
                    self.assertEqual(
                        self._stated(phrase),
                        expected,
                        f"{self.PAGE.name} says {phrase!r}; {name} states "
                        f"{expected} of those conversions",
                    )


class QueueIndexTestCase(unittest.TestCase):
    """`operating/review-app.md` describes the queues the application renders.

    A queue with no row on the page is a decision nobody is told they can make:
    `substance-label-conflict` was rendered by the application and absent from
    the page, and the page went on saying there were seventeen queues while the
    application had nineteen. Both halves are read off `queries.queue` here.
    """

    PAGE = DOCS / "operating" / "review-app.md"

    #: The word for a count, so that the page may spell it out as prose does.
    WORDS = {value: word for word, value in _NUMBER_WORDS.items()}

    def setUp(self):
        from brightway_flows.webapps.app.queries import queue

        self.queue = queue
        self.definitions = queue.DEFINITIONS
        self.custom = {
            queue.ELEMENTS,
            queue.COLLISIONS,
            queue.PLACES,
            *queue.FACTOR_QUEUES,
        }
        self.flat = " ".join(self.PAGE.read_text().split())

    def test_the_table_names_every_queue(self):
        for definition in self.definitions:
            with self.subTest(queue=definition.name):
                self.assertIn(
                    f"| `{definition.name}` |",
                    self.flat,
                    f"the review application renders {definition.name!r} and "
                    f"{self.PAGE.name} has no row for it",
                )

    def test_the_page_counts_them(self):
        word = self.WORDS[len(self.definitions)].capitalize()
        self.assertIn(f"{word} queues", self.flat)

    def test_the_page_counts_the_ones_the_shared_template_renders(self):
        shared = [d for d in self.definitions if d.name not in self.custom]
        word = self.WORDS[len(shared)].capitalize()
        self.assertIn(
            f"{word} of them are rows in `review_queue` rendered by one template",
            self.flat,
        )

    def test_the_page_counts_the_factor_queues(self):
        word = self.WORDS[len(self.queue.FACTOR_QUEUES)]
        self.assertIn(f"The {word} factor queues are `review_queue` rows", self.flat)


if __name__ == "__main__":
    unittest.main()


class SourceChangePagesTestCase(unittest.TestCase):
    """`changes/` has one page per input list, and each prints the registry
    numbers that list's fix file corrects.

    A correction is written once, in `<list>-manual-fixes.json`, with the
    number it takes off a row and the number it writes there. The page for the
    list repeats both so that a reader who knows the source can find the row.
    A repeat drifts: a fix added to the file after the page was written is a
    correction nobody is told about, and a number the page prints after the
    file stopped stating it is a claim about a correction that no longer
    happens. Rule 30: the two are held equal here.

    The SimaPro-lineage file applies to every list whose manifest says
    `simapro_origin`, so its numbers are expected on each of those pages.
    """

    PAGES = DOCS / "changes"

    #: Each page, and the fix files whose registry-number entries it prints.
    FIX_FILES = {
        "ef-3.1.md": ("ef-3.1-manual-fixes.json",),
        "ecoinvent-3.8.md": ("ecoinvent-3.8-manual-fixes.json",),
        "ecoinvent-3.9.1.md": ("ecoinvent-3.9.1-manual-fixes.json",),
        "ecoinvent-3.10.1.md": ("ecoinvent-3.10.1-manual-fixes.json",),
        "ecoinvent-3.11.md": ("ecoinvent-3.11-manual-fixes.json",),
        "ecoinvent-3.12.md": ("ecoinvent-3.12-manual-fixes.json",),
        "bafu-2026-v1.md": (
            "bafu-2026-v1-manual-fixes.json",
            "simapro-lineage-manual-fixes.json",
        ),
        "stepwise-2006.md": (
            "stepwise-2006-manual-fixes.json",
            "simapro-lineage-manual-fixes.json",
        ),
    }

    #: The four kinds of change every page reports, in this order.
    HEADINGS = (
        "## One name, two substances",
        "## An ionic charge was added or corrected",
        "## Rows merged into one flow",
        "## Registry numbers corrected",
    )

    REGISTRY_FIELDS = {"cas_number", "cas_numbers", "ec_numbers"}

    @staticmethod
    def _numbers(value):
        """The registry numbers a fix value states, whether one or a list."""
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        return [str(value)]

    def _registry_fixes(self, name):
        payload = json.loads((PACKAGE_DATA_DIR / name).read_text())
        for fix in payload["fixes"]:
            if fix["field"] not in self.REGISTRY_FIELDS:
                continue
            numbers = []
            for key in ("original_value", "new_value", "remove_value"):
                numbers.extend(self._numbers(fix.get(key)))
            yield fix, numbers

    def test_every_page_has_the_four_sections(self):
        for page in self.FIX_FILES:
            text = (self.PAGES / page).read_text()
            for heading in self.HEADINGS:
                with self.subTest(page=page, heading=heading):
                    self.assertIn(heading, text)

    def test_every_registry_number_correction_is_on_its_page(self):
        checked = 0
        for page, files in self.FIX_FILES.items():
            text = (self.PAGES / page).read_text()
            for name in files:
                for fix, numbers in self._registry_fixes(name):
                    checked += 1
                    for number in numbers:
                        with self.subTest(page=page, file=name, number=number):
                            self.assertIn(
                                number,
                                text,
                                f"{name} corrects {number} on "
                                f"{fix.get('uuid') or fix.get('match')}, and "
                                f"changes/{page} does not mention it.",
                            )
        self.assertTrue(checked, "no registry-number fixes found in data/")

    def test_every_source_manifest_has_a_page(self):
        manifests = sorted(
            path.stem for path in (PACKAGE_DATA_DIR / "sources").glob("*.json")
        )
        pages = sorted(
            path.stem for path in self.PAGES.glob("*.md") if path.stem != "index"
        )
        # Stepwise's manifest carries its patch version and its page does not.
        expected = sorted(stem.removesuffix("-1.09") for stem in manifests)
        self.assertEqual(expected, pages)
