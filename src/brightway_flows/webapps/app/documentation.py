"""The documentation, read from `docs/` and rendered per request.

The pages were readable in two places and neither was the review application:
on GitHub, and under `mkdocs serve` on a developer's laptop.  A curator working
through the queues had the answer to "what is a flow object, and why is this
one deprecated?" written down and nowhere they could reach it.

Rendered here rather than served as a built site.  `mkdocs build` produces a
directory of HTML with its own navigation bar, its own stylesheet and its own
search index, and it is exactly as fresh as the last time somebody ran it --
which is the failure mode a deployed copy has and nobody notices, because a
stale page looks like a page.  Reading the markdown at request time means one
navigation, one stylesheet, no build step, and a checkout that serves whatever
its `docs/` currently says.  It costs Material's search box.

Mermaid fences are drawn, by a copy of `mermaid.min.js` checked in beside the
stylesheet -- the same rule that keeps Pico out of a CDN, applied to the one
page kind that needs a second script.  It is loaded only for a page that has a
fence, and a page whose diagram will not draw falls back to the source, labelled
as source, which is what every page did before.

Nothing is cached: 53 files, the largest of them 2,263 lines, and a page that
renders in single-digit milliseconds is not worth a cache that can go stale
while somebody is editing the file it holds.  Search reads the same files per
request too, but as source rather than rendered (see `search`).

Flask-free, like `queries/`, so the tree can be walked and a page rendered in a
test without an application context.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import markdown
import yaml
from markdown.treeprocessors import Treeprocessor
from pymdownx.superfences import fence_code_format

#: The documentation tree and its configuration, relative to the project root.
DOCS_DIRNAME = "docs"
CONFIG_FILENAME = "mkdocs.yml"

#: The URL prefix the pages are served under.  Here rather than read from the
#: blueprint because the link rewriting below runs outside a request.
URL_PREFIX = "/docs"

#: The extensions `mkdocs.yml` configures.  The same list, so a page reads the
#: same in both places: an admonition that renders as a note under `mkdocs
#: serve` and as a stray `!!! note` here would be a second dialect of the
#: documentation, maintained by nobody.
_EXTENSIONS = (
    "admonition",
    "attr_list",
    "def_list",
    "footnotes",
    "tables",
    "toc",
    "pymdownx.details",
    "pymdownx.superfences",
)

_EXTENSION_CONFIGS: dict[str, Any] = {
    # Matching `mkdocs.yml`: the fence is custom so that Material draws the
    # diagram rather than printing its source.  It is what marks the block
    # `class="mermaid"`, which is both what `docs-mermaid.js` looks for here
    # and what stops the superfence parser swallowing it.
    "pymdownx.superfences": {
        "custom_fences": [
            {"name": "mermaid", "class": "mermaid", "format": fence_code_format}
        ]
    },
}


@dataclass
class DocLink:
    """One page in the navigation."""

    title: str
    slug: str


@dataclass
class DocSection:
    """A group of pages, as `mkdocs.yml` groups them.

    A page listed at the top level -- `Home` -- is a section with no title and
    one page, so the template renders one shape rather than two.
    """

    title: str = ""
    pages: list[DocLink] = field(default_factory=list)


@dataclass
class DocPage:
    """One rendered page, and its own table of contents.

    The contents come from the `toc` extension rather than from a second pass
    over the headings, so they are the headings the page actually has, with the
    same anchors the links between pages point at.
    """

    slug: str
    title: str
    html: str
    contents: str = ""
    has_diagrams: bool = False
    """Whether the page holds a mermaid fence.

    The template asks, because `mermaid.min.js` is three and a half megabytes
    and four pages of thirty-six have a diagram on them.  Read off the rendered
    HTML rather than the markdown: the fence is what `pymdownx` turned into
    `<pre class="mermaid">`, so this is true of exactly the pages the script
    would have something to draw on.
    """


class DocumentationMissingError(FileNotFoundError):
    """There is no `docs/` where the application was told to look.

    Raised rather than returned, like a missing database: an installed wheel
    carries the package and not the documentation tree, so this is a state the
    application can be in, and the view turns it into a page that names the
    path it looked in.
    """


def default_root(app_directory: Path) -> Path:
    """`docs/` beside the project, found from `webapps/app`.

    The application is run from a checkout -- `gunicorn wsgi.app:application`,
    from the project root or with `--chdir` -- so the tree is four directories
    up: `webapps`, `brightway_flows`, `src`, the project.  Resolved from
    the package rather than from the working directory, because a worker's
    working directory is a deployment detail and the documentation's location
    is not.
    """
    return app_directory.resolve().parents[3] / DOCS_DIRNAME


def _yaml_loader() -> type[yaml.SafeLoader]:
    """A loader that reads `mkdocs.yml` without executing any of it.

    The file carries `!!python/name:pymdownx.superfences.fence_code_format`,
    which `yaml.safe_load` refuses and `yaml.unsafe_load` would import.  Only
    the `nav` block is wanted here, so unknown tags become `None` and the
    configuration is read without a loader that can call anything.
    """

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor(None, lambda loader, node: None)
    return Loader


def _config(root: Path) -> dict[str, Any]:
    path = root.parent / CONFIG_FILENAME
    if not path.is_file():
        return {}
    loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=_yaml_loader())
    return loaded if isinstance(loaded, dict) else {}


def _slug(target: str) -> str:
    """A `nav` entry's file as the slug it is served under.

    `concepts/why.md` is `concepts/why`: the extension is how the file is
    stored, not part of what the page is called.
    """
    text = str(target).strip().lstrip("/")
    return text.removesuffix(".md")


def _walk(entries: Any, into: list[DocSection], current: DocSection) -> None:
    """One `nav` level.

    `nav` is a list of either `Title: file.md` or `Title: [more entries]`, and
    the second form nests.  Two levels is what `mkdocs.yml` uses and what the
    sidebar renders, so a deeper tree is flattened into its section rather than
    dropped -- a page nobody can reach is worse than one listed a level up.
    """
    if not isinstance(entries, list):
        return
    for entry in entries:
        if isinstance(entry, str):
            current.pages.append(DocLink(title=_slug(entry), slug=_slug(entry)))
            continue
        if not isinstance(entry, dict):
            continue
        for title, target in entry.items():
            if isinstance(target, str):
                current.pages.append(DocLink(title=str(title), slug=_slug(target)))
            elif isinstance(target, list):
                section = DocSection(title=str(title))
                into.append(section)
                _walk(target, into, section)


def navigation(root: Path) -> list[DocSection]:
    """The sidebar, from `mkdocs.yml` if it is there and the tree if it is not.

    Falling back to the tree rather than to nothing: a page that exists and is
    not listed is still a page, and a checkout without the configuration file
    is a checkout whose documentation should still be readable.
    """
    nav = _config(root).get("nav")
    if isinstance(nav, list) and nav:
        top = DocSection()
        sections = [top]
        _walk(nav, sections, top)
        return [section for section in sections if section.pages]

    by_directory: dict[str, DocSection] = {}
    for path in sorted(root.rglob("*.md")):
        slug = path.relative_to(root).with_suffix("").as_posix()
        directory = posixpath.dirname(slug)
        section = by_directory.setdefault(directory, DocSection(title=directory))
        section.pages.append(DocLink(title=_title_of(path) or slug, slug=slug))
    return list(by_directory.values())


def titles(root: Path) -> dict[str, str]:
    """Slug to the title the navigation gives it."""
    return {
        page.slug: page.title
        for section in navigation(root)
        for page in section.pages
    }


def group_of(sections: list[DocSection], slug: str) -> DocSection | None:
    """The titled group *slug* is listed under, or `None`.

    `None` covers two cases the caller treats alike: a top-level page such as
    the index, and a page `mkdocs.yml` does not list at all (`plans/public-
    site.md` §4). Either way there is no group to open in the sidebar or to
    name in the breadcrumb.
    """
    for section in sections:
        if section.title and any(link.slug == slug for link in section.pages):
            return section
    return None


def neighbours(
    sections: list[DocSection], slug: str
) -> tuple[DocLink | None, DocLink | None]:
    """The page before and after *slug*, in `navigation()`'s own order.

    Across group boundaries, because that is the order a reader who clicks
    "Next" through the sidebar actually walks. `(None, None)` on the first or
    last page, and on a page the navigation does not list at all.
    """
    pages = [link for section in sections for link in section.pages]
    for index, link in enumerate(pages):
        if link.slug != slug:
            continue
        before = pages[index - 1] if index > 0 else None
        after = pages[index + 1] if index + 1 < len(pages) else None
        return before, after
    return None, None


def _title_of(path: Path) -> str:
    """A page's first heading, which is its title on the page itself."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def resolve(root: Path, slug: str) -> tuple[str, Path] | None:
    """What *slug* names: a page, a file beside the pages, or nothing.

    The kind comes back with the path because both are served by one route.
    `../` and an absolute path are refused here rather than by the route: a
    reader cannot type a path that leaves the tree, and neither can a link in a
    page that was written wrongly.
    """
    cleaned = posixpath.normpath("/" + str(slug or "index")).lstrip("/")
    if not cleaned or cleaned == ".":
        cleaned = "index"

    candidate = (root / cleaned).resolve()
    if not candidate.is_relative_to(root.resolve()):
        return None

    page = candidate.with_suffix(candidate.suffix + ".md")
    if candidate.suffix != ".md" and page.is_file():
        return ("page", page)
    if candidate.is_file():
        return ("page" if candidate.suffix == ".md" else "asset", candidate)
    index = candidate / "index.md"
    if index.is_file():
        return ("page", index)
    return None


class _Links(Treeprocessor):
    """Rewrites the links a page carries so they work under `/docs`.

    The documentation is written for GitHub and `mkdocs serve`, where a link
    between pages is a relative path to a `.md` file. Left alone, every one of
    them 404s here. They are rewritten in the tree rather than in the rendered
    HTML because the tree is what the parser produced and a regular expression
    over HTML is a second, worse parser.

    Tables are wrapped as they go past, for the same reason every other table
    in the application is: `harmonisation-steps.md` has columns that do not fit
    a phone, and without the wrapper it is the page that scrolls sideways.
    """

    def __init__(self, md: markdown.Markdown, slug: str) -> None:
        super().__init__(md)
        self.directory = posixpath.dirname(slug)

    def run(self, root: ElementTree.Element) -> None:
        for element in root.iter("a"):
            href = element.get("href")
            if href:
                element.set("href", self._rewrite(href))
        for element in root.iter("img"):
            source = element.get("src")
            if source:
                element.set("src", self._rewrite(source))
        self._wrap_tables(root)

    def _rewrite(self, href: str) -> str:
        # An anchor, an absolute path or another site: all three already point
        # where they mean to.
        if href.startswith(("#", "/", "http://", "https://", "mailto:")):
            return href
        target, _, anchor = href.partition("#")
        if not target:
            return href
        resolved = posixpath.normpath(posixpath.join(self.directory, target))
        resolved = resolved.removesuffix(".md")
        link = f"{URL_PREFIX}/{resolved.lstrip('/')}"
        return f"{link}#{anchor}" if anchor else link

    @staticmethod
    def _wrap_tables(root: ElementTree.Element) -> None:
        parents = {child: parent for parent in root.iter() for child in parent}
        for table in list(root.iter("table")):
            parent = parents.get(table)
            if parent is None:
                continue
            wrapper = ElementTree.Element("div")
            wrapper.set("class", "table-scroll")
            position = list(parent).index(table)
            parent.remove(table)
            wrapper.append(table)
            parent.insert(position, wrapper)


class _LinkExtension(markdown.extensions.Extension):
    def __init__(self, slug: str) -> None:
        super().__init__()
        self.slug = slug

    def extendMarkdown(self, md: markdown.Markdown) -> None:
        # After `toc`, so heading ids exist before anything links to them.
        md.treeprocessors.register(_Links(md, self.slug), "bwf_links", 4)


def render(text: str, slug: str) -> tuple[str, str]:
    """*text* as HTML and its contents, with links pointing into this app.

    A parser per page rather than one reset between pages: the link rewriting
    is configured with the slug it is rewriting relative to, and a shared
    parser carrying per-page state is a bug that only shows up under two
    requests at once.
    """
    parser = markdown.Markdown(
        extensions=[*_EXTENSIONS, _LinkExtension(slug)],
        extension_configs=_EXTENSION_CONFIGS,
    )
    html = parser.convert(text)
    return html, getattr(parser, "toc", "")


def load_page(
    root: Path, slug: str, *, known_titles: dict[str, str] | None = None
) -> DocPage | None:
    """The page *slug* names, rendered, or `None` if there is no such page.

    *known_titles* is the navigation's titles, passed in by a caller that has
    already built the sidebar, so one request parses `mkdocs.yml` once.
    """
    found = resolve(root, slug)
    if found is None or found[0] != "page":
        return None
    _, path = found
    canonical = path.relative_to(root.resolve()).with_suffix("").as_posix()
    named = titles(root) if known_titles is None else known_titles
    html, contents = render(path.read_text(encoding="utf-8"), canonical)
    return DocPage(
        slug=canonical,
        title=named.get(canonical) or _title_of(path) or canonical,
        html=html,
        contents=contents,
        has_diagrams='<pre class="mermaid">' in html,
    )


#: The longest snippet a search result shows, not counting the ellipses.
SNIPPET_LENGTH = 120

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
#: `{#anchor}`, `{: .class}` and the rest of `attr_list`.
_ATTRIBUTES = re.compile(r"\{[:#.][^}]*\}")
_IMAGE_OR_LINK = re.compile(r"!?\[([^\]]*)\](?:\([^)]*\)|\[[^\]]*\])")
_FOOTNOTE_REFERENCE = re.compile(r"\[\^[^\]]+\]")
_TAG = re.compile(r"<[^>]+>")
#: A line's own markup: a list marker, a quote, a definition, an admonition.
_LINE_PREFIX = re.compile(r"^\s*(?:[-*+]\s+|\d+\.\s+|>\s?|:\s+|(?:!!!|\?\?\?\+?)\s+\w+\s*)")


@dataclass
class DocHit:
    """One page a search matched, and the line of it a result shows.

    `rank` is where the match was: 0 the title, 1 a heading, 2 the text.
    `snippet` is plain text -- the template marks the match and escapes the
    rest -- and is "Section: <heading>" for a match in a heading.
    """

    slug: str
    title: str
    group: str
    snippet: str
    rank: int


def _plain(text: str) -> str:
    """One line of Markdown as the words a reader sees."""
    text = _LINE_PREFIX.sub("", text)
    text = _FOOTNOTE_REFERENCE.sub("", text)
    text = _IMAGE_OR_LINK.sub(r"\1", text)
    text = _ATTRIBUTES.sub("", text)
    text = _TAG.sub("", text)
    for mark in ("**", "__", "`", "*"):
        text = text.replace(mark, "")
    text = text.replace("|", " ").strip('"')
    return " ".join(text.split())


def _read_source(path: Path) -> tuple[str, list[str], str]:
    """A page's first heading, its other headings, and its text, as plain text.

    Read from the Markdown rather than from `render`: rendering all 53 pages
    takes 538ms, and reading them 4ms, which is the difference between a
    search that answers and one that waits.  The cost is that the text is the
    source with its markup stripped by `_plain` rather than by the parser, so
    a construct it does not know leaves a stray character in a snippet -- and
    nothing worse, because the template escapes the snippet.

    A mermaid fence is skipped: it is a diagram's source, not words on the
    page.  Other code is kept, because an identifier a reader searches for is
    as likely to be in a code sample as in a sentence.
    """
    title = ""
    headings: list[str] = []
    words: list[str] = []
    fence = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        opened = _FENCE.match(line)
        if fence:
            if opened and opened.group(1) == fence:
                fence = ""
            elif fence != "mermaid":
                words.append(line.strip())
            continue
        if opened:
            fence = "mermaid" if "mermaid" in line else opened.group(1)
            continue
        heading = _HEADING.match(line)
        if heading:
            text = _plain(heading.group(2))
            if heading.group(1) == "#" and not title:
                title = text
            else:
                headings.append(text)
            continue
        if line.strip() in ("---", "***"):
            continue
        plain = _plain(line)
        if plain:
            words.append(plain)
    return title, headings, " ".join(" ".join(words).split())


def _snippet(text: str, at: int, length: int) -> str:
    """Up to `SNIPPET_LENGTH` characters of *text* around a match at *at*.

    Widened evenly either side of the match and then pulled in to whole
    words, with an ellipsis wherever the text was cut.
    """
    room = max(SNIPPET_LENGTH - length, 0)
    start = max(at - room // 2, 0)
    end = min(start + SNIPPET_LENGTH, len(text))
    start = max(end - SNIPPET_LENGTH, 0)
    if start > 0:
        space = text.find(" ", start, at)
        start = space + 1 if space != -1 else start
    if end < len(text):
        space = text.rfind(" ", at + length, end)
        end = space if space != -1 else end
    return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")


def search(root: Path, query: str) -> list[DocHit]:
    """Every page whose title, headings or text holds *query*, best first.

    A case-insensitive match of the whole query, not of its words: somebody
    searching the documentation for "carbon dioxide" is not asking for every
    page that says "carbon" (`plans/public-site.md` §3, Search).  Ranked by
    where it matched -- title, then heading, then text -- and within a rank in
    the navigation's order, with pages the navigation does not list after it.

    Per request, like the pages themselves, with no index file to go stale.
    """
    needle = " ".join(query.split()).lower()
    if not needle or not root.is_dir():
        return []

    sections = navigation(root)
    order = {link.slug: index for index, link in
             enumerate(link for section in sections for link in section.pages)}
    named = {link.slug: link.title for section in sections for link in section.pages}

    hits: list[DocHit] = []
    for path in sorted(root.rglob("*.md")):
        slug = path.relative_to(root).with_suffix("").as_posix()
        first_heading, headings, text = _read_source(path)
        title = named.get(slug) or first_heading or slug
        at = text.lower().find(needle)
        in_heading = next((heading for heading in headings if needle in heading.lower()), None)

        if needle in title.lower() or needle in first_heading.lower():
            rank = 0
        elif in_heading is not None:
            rank = 1
        elif at != -1:
            rank = 2
        else:
            continue

        if rank == 1 or (rank == 0 and at == -1 and in_heading is not None):
            snippet = f"Section: {in_heading}"
        elif at != -1:
            snippet = _snippet(text, at, len(needle))
        else:
            snippet = ""
        group = group_of(sections, slug)
        hits.append(DocHit(slug=slug, title=title, group=group.title if group else "",
                           snippet=snippet, rank=rank))

    hits.sort(key=lambda hit: (hit.rank, order.get(hit.slug, len(order)), hit.slug))
    return hits
