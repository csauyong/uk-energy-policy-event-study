"""Read published policy chronologies, so discovery is auditable.

Populates the :mod:`taxonomy` grid from documents that are *written as
timelines*, rather than from a search ranking:

`House of Commons Library research briefings`
    Written precisely as policy chronologies, with citations. They list
    instruments a category sweep never surfaces, and -- more importantly --
    they are a **fixed, checkable reference**: a reader can open the same
    briefing and find what was missed.

`gov.uk document collections`
    Group every document for a policy under one parent. Enumerating a
    collection is a closed operation with a definite answer, unlike a search
    query, which has a ranking.

Both are used for **discovery only**. Timestamps still come from the gov.uk
content API via :func:`policy_event_study.events.govuk.first_publication`,
because a chronology says "October 2021" and an event study needs
"2021-10-19T12:05:00Z".

What this module deliberately will not do
-----------------------------------------
It does not infer an instrument that a source does not state. Every extracted
reference carries the document and page it came from, so a curator can check
it. An instrument recalled rather than read has no citation to check and is
therefore worse than one a search failed to rank -- the search failure is at
least visible as an empty grid cell.
"""

from __future__ import annotations

import html
import io
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pandas as pd

#: The Commons Library website rejects non-browser user agents with HTTP 403.
#: The research-briefing PDF host does not, but one header set is simpler.
BROWSER_UA: Final[str] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
LIBRARY_SEARCH: Final[str] = "https://commonslibrary.parliament.uk/"
BRIEFING_PDF: Final[str] = (
    "https://researchbriefings.files.parliament.uk/documents/{code}/{code}.pdf"
)
CONTENT_API: Final[str] = "https://www.gov.uk/api/content"

#: "March 2024", "September 2023" -- the granularity a chronology writes in.
MONTH_YEAR = re.compile(
    r"\b((?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(?:19|20)\d{2})"
)
BRIEFING_CODE = re.compile(r"/research-briefings/([a-z]+-?\d+)/")

#: Patterns that mark a line as apparatus rather than prose. PDF extraction
#: interleaves footnotes, contents pages and page furniture into the body
#: text, and every one of those carries dates and instrument words -- so
#: without this filter the extractor happily returns "Jim Pickard and Pilita
#: Clark, Green heating subsidies to be pruned, Financial Times, 2 September
#: 2015" as a policy instrument. Every one of these was observed in a real
#: shortlist run, not anticipated.
CITATION_PATTERNS: Final[tuple[str, ...]] = (
    r"\bPQ\s*\d",  # parliamentary question citation
    r"\bHC\s+Deb\b",  # Hansard
    r"\bHL\s+Deb\b",
    r"\bop\.?\s*cit\b",
    r"\bibid\b",
    r"https?://",
    r"\[subscription required\]",
    r"\bDeposited paper\b",
    r"^\s*\d{1,3}\s+[A-Z][a-z]+.{0,40},",  # "12 Smith, Title, date"
    r"\b(?:Financial Times|The Times|The Guardian|BBC News|Telegraph|Reuters)\b",
)

#: Contents-page and table furniture: runs of section numbers and page
#: numbers that survive extraction as one long pseudo-sentence.
CONTENTS_PATTERNS: Final[tuple[str, ...]] = (
    r"(?:\b\d{1,2}\.\d\b.*){3,}",  # "1.1 ... 1.2 ... 1.3"
    r"(?:\s\d{1,3}\s){4,}",  # a run of bare page numbers
    r"^\s*\d{1,3}\s+\d{1,2}\.\d",  # page number followed by a section number
    r"^\s*[A-Z][a-z]+ [A-Z][a-z]+ \d{1,3} Commons Library",  # running header
)

#: Phrases where an instrument word appears inside a proper noun and means
#: nothing. "Department for Business, Energy and Industrial Strategy" matched
#: the `strategy` lifecycle stage and put a machinery-of-government change at
#: the top of the shortlist.
FALSE_FRIENDS: Final[tuple[str, ...]] = (
    "industrial strategy",
    "department for business, energy",
    "energy and industrial",
)

#: A dated sentence is only an instrument reference if it also names an
#: instrument. Without this the extractor returns every date in the document,
#: most of which are citations to other documents.
INSTRUMENT_WORDS: Final[tuple[str, ...]] = (
    "consultation",
    "consulted",
    "regulations",
    "standard",
    "scheme",
    "strategy",
    "announced",
    "announcement",
    "laid before",
    "published",
    "response",
    "came into force",
    "launched",
    "closed",
    "extended",
    "amended",
    "uplift",
    "target",
    "commitment",
    "phase out",
    "phased out",
    "delayed",
    "scrapped",
)


@dataclass(frozen=True)
class Briefing:
    """One House of Commons Library research briefing."""

    code: str
    title: str
    url: str

    @property
    def pdf_url(self) -> str:
        """Direct PDF link on the research-briefings file host."""
        return BRIEFING_PDF.format(code=self.code.upper())


@dataclass(frozen=True)
class DatedReference:
    """A dated instrument reference extracted from a chronology.

    `month_year` is deliberately coarse. Chronologies write "October 2021" and
    the extractor does not invent a day -- the exact timestamp comes from the
    gov.uk content API, and a fabricated day would be indistinguishable from a
    sourced one downstream.
    """

    month_year: str
    sentence: str
    source_code: str
    source_title: str
    page: int

    @property
    def period(self) -> pd.Period:
        """The referenced month, for sorting and grouping."""
        return pd.Period(pd.Timestamp(self.month_year), freq="M")

    def matches_family(self, terms: Iterable[str]) -> bool:
        """Whether this reference plausibly belongs to a policy family.

        Matched against a family's `match_terms`, not its
        `chronology_queries`. The two differ on purpose: a query is a phrase
        chosen to rank a *document*, a match term is a token that occurs in
        running prose. Matching on the query silently empties the grid.

        **Known limitation: matching is sentence-local.** A chronology names
        its subject once and then writes "the scheme" or an acronym, so the
        most informative sentences are often the ones that do *not* repeat the
        family name -- "The Government announced on 27 March 2021 that the
        scheme was to close" carries the closure date and matches nothing.
        Acronyms are in `match_terms` for this reason, but pronoun reference
        is not solved and section-level context would be needed to solve it.
        The practical consequence is that a family's reference count
        understates its coverage, so a thin family should be checked against
        the briefing by hand before being called a gap.
        """
        lowered = self.sentence.lower()
        return any(term.lower() in lowered for term in terms)


@dataclass(frozen=True)
class CollectionDocument:
    """One document enumerated from a gov.uk collection page."""

    collection: str
    title: str
    url: str
    document_type: str
    public_updated_at: str | None


def _fetch(url: str, *, timeout: int = 60) -> bytes:
    """Fetch bytes with a browser user agent."""
    request = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload: bytes = response.read()
    return payload


def search_briefings(query: str, *, limit: int = 6) -> list[Briefing]:
    """Find Commons Library research briefings for a policy area.

    Source: https://commonslibrary.parliament.uk/
    Licence: Open Parliament Licence v3.0.
    Vintage: live site; briefings carry their own publication date, and the
        sweep records which vintage it read.
    Publication lag: briefings are updated periodically and the extractor
        records the code so a rerun can be compared against the same document.

    **Discovery only.** The query finds the *timeline document*; the timeline
    document enumerates the instruments. That separation is what makes the
    result auditable -- a reader checks the briefing, not the ranking.
    """
    # Quote multi-word queries. Unquoted, the site search returns loosely
    # related briefings -- an "energy efficiency private rented homes" query
    # ranks damp-and-mould and population-ageing briefings above the housing
    # chronology. Quoting is the difference between finding the timeline
    # document and finding the neighbourhood it lives in.
    phrase = f'"{query}"' if " " in query else query
    params = urllib.parse.urlencode({"s": phrase})
    try:
        body = _fetch(f"{LIBRARY_SEARCH}?{params}", timeout=30).decode(
            "utf-8", "ignore"
        )
    except (urllib.error.URLError, OSError):
        return []

    briefings: list[Briefing] = []
    seen: set[str] = set()
    for match in re.finditer(
        r'<a[^>]+href="(https://commonslibrary\.parliament\.uk/research-briefings/'
        r'([a-z]+-?\d+)/)"[^>]*>(.*?)</a>',
        body,
        re.DOTALL,
    ):
        url, code, raw_title = match.group(1), match.group(2), match.group(3)
        if code in seen:
            continue
        seen.add(code)
        title = re.sub(r"<[^>]+>", "", raw_title).strip()
        if not title:
            continue
        briefings.append(Briefing(code=code.upper(), title=title, url=url))
        if len(briefings) >= limit:
            break
    return briefings


def cache_path(briefing: Briefing) -> Path:
    """Where a briefing's extracted text is cached.

    Cached because the completeness audit reads the same corpus repeatedly and
    re-fetching 17 PDFs per pass is both slow and impolite to the host. The
    cache is keyed by briefing code only: briefings are revised in place, so a
    rerun after a revision should be a deliberate act -- delete the cache.
    """
    from policy_event_study.paths import EVENTS_DIR

    directory = EVENTS_DIR / "briefing_cache"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{briefing.code}.txt"


def briefing_pages(briefing: Briefing, *, use_cache: bool = True) -> list[str]:
    """Extract text from a briefing, per page where the source has pages.

    Tries the PDF first, because it paginates and a page number is what makes
    a citation checkable -- a citation to a 48-page document is not a citation.

    **Falls back to the HTML briefing page when no PDF exists**, and that
    fallback is not a nicety. Roughly a third of Commons Library briefings are
    HTML-only, and treating them as unreadable silently discarded some of the
    best chronologies in the corpus: CBP-10797 "Green Homes Grant" has no PDF
    and carries the scheme's entire lifecycle -- announced July 2020, opened
    September 2020, extended November 2020, funding cut February 2021, closed
    March 2021. Dropping it lost a launch/closure pair of opposite-signed
    shocks, which is the most valuable shape an event can have in this design.

    HTML has no pages, so those references cite page 0. The distinction is
    kept rather than faked: a fabricated page number is worse than an honest
    absence of one.
    """
    from pypdf import PdfReader

    cached = cache_path(briefing)
    if use_cache and cached.exists():
        return cached.read_text(encoding="utf-8").split("\x0c")

    try:
        raw = _fetch(briefing.pdf_url)
    except (urllib.error.URLError, OSError):
        pages = _briefing_html(briefing)
    else:
        try:
            reader = PdfReader(io.BytesIO(raw))
        except Exception:
            pages = _briefing_html(briefing)
        else:
            pages = [page.extract_text() or "" for page in reader.pages]

    if pages:
        # Form feed as the page separator: it cannot occur in extracted text.
        cached.write_text("\x0c".join(pages), encoding="utf-8")
    return pages


def _briefing_html(briefing: Briefing) -> list[str]:
    """Read a briefing's HTML page as a single unpaginated block.

    Returns a one-element list, so the caller's page numbering yields page 1
    for HTML sources. Markup is stripped crudely: the extractor only needs
    sentences, and a full parser would add a dependency for no gain.
    """
    if not briefing.url:
        return []
    try:
        body = _fetch(briefing.url, timeout=30).decode("utf-8", "ignore")
    except (urllib.error.URLError, OSError):
        return []
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", body, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", body)
    # Unescape entities before sentence splitting: `&pound;300 million` and
    # `&nbsp;` otherwise survive into the extracted quotation and make a
    # citation look mangled to whoever checks it.
    text = html.unescape(text)
    return [" ".join(text.split())]


def extract_dated_references(
    briefing: Briefing, pages: Sequence[str]
) -> list[DatedReference]:
    """Pull dated instrument references out of a chronology.

    A sentence qualifies when it carries **both** a month-year and an
    instrument word. The date alone is not enough: a briefing is dense with
    dates that are citations to other documents rather than policy events.
    """
    references: list[DatedReference] = []
    for number, text in enumerate(pages, start=1):
        flattened = " ".join(text.split())
        for sentence in re.split(r"(?<=[.!?])\s+", flattened):
            if not 40 < len(sentence) < 400:
                continue
            dates = MONTH_YEAR.findall(sentence)
            if not dates:
                continue
            lowered = sentence.lower()
            if not any(word in lowered for word in INSTRUMENT_WORDS):
                continue
            if is_apparatus(sentence):
                continue
            references.append(
                DatedReference(
                    month_year=dates[0],
                    sentence=sentence,
                    source_code=briefing.code,
                    source_title=briefing.title,
                    page=number,
                )
            )
    return references


def is_apparatus(sentence: str) -> bool:
    """Whether a sentence is document apparatus rather than policy prose.

    Footnotes, Hansard and PQ citations, press references, contents pages and
    page furniture all carry dates and instrument words, so the
    date-plus-instrument-word test passes them. They are not instruments, and
    a leak check spent on one is wasted.

    The `FALSE_FRIENDS` case is subtler and was the worst offender in
    practice: "Department for Business, Energy and Industrial **Strategy**"
    matched the `strategy` lifecycle stage, so a machinery-of-government
    change was ranked as a policy instrument in two separate families.
    """
    lowered = sentence.lower()
    if any(friend in lowered for friend in FALSE_FRIENDS):
        return True
    for pattern in CITATION_PATTERNS:
        if re.search(pattern, sentence, re.IGNORECASE | re.MULTILINE):
            return True
    for pattern in CONTENTS_PATTERNS:
        if re.search(pattern, sentence):
            return True
    # A sentence whose leading token is a bare number is a footnote body that
    # extraction has run together with the note marker.
    if re.match(r"^\s*\d{1,3}\s+[A-Z]", sentence):
        return True
    # Digit-dense text is a table, not prose.
    digits = sum(character.isdigit() for character in sentence)
    return digits / max(len(sentence), 1) > 0.12


def enumerate_collection(slug: str) -> list[CollectionDocument]:
    """List every document grouped under a gov.uk collection page.

    Source: https://www.gov.uk/api/content/government/collections/<slug>
    Licence: OGL v3.
    Vintage: live; the sweep records its read date.
    Publication lag: none for the listing. The `public_updated_at` shown here
        is a **last-updated** stamp and must not be used as an announcement
        date -- see `events.govuk.first_publication`.

    A closed operation with a definite answer, which is what a search query is
    not.
    """
    import json

    try:
        payload: dict[str, Any] = json.loads(
            _fetch(f"{CONTENT_API}/government/collections/{slug}", timeout=30)
        )
    except (urllib.error.URLError, OSError, ValueError):
        return []

    documents = payload.get("links", {}).get("documents", [])
    return [
        CollectionDocument(
            collection=slug,
            title=str(entry.get("title", "")).strip(),
            url=f"https://www.gov.uk{entry.get('base_path', '')}",
            document_type=str(entry.get("document_type", "")),
            public_updated_at=(
                str(entry["public_updated_at"])
                if entry.get("public_updated_at")
                else None
            ),
        )
        for entry in documents
    ]


def find_collections(query: str, *, limit: int = 8) -> list[str]:
    """Find gov.uk collection slugs for a policy area."""
    import json

    params = urllib.parse.urlencode(
        {
            "q": query,
            "count": str(limit),
            "filter_content_store_document_type": "document_collection",
            "fields": "title,link",
        }
    )
    try:
        payload = json.loads(
            _fetch(f"https://www.gov.uk/api/search.json?{params}", timeout=30)
        )
    except (urllib.error.URLError, OSError, ValueError):
        return []
    return [
        str(result["link"]).rsplit("/", 1)[-1]
        for result in payload.get("results", [])
        if str(result.get("link", "")).startswith("/government/collections/")
    ]


def references_frame(references: Sequence[DatedReference]) -> pd.DataFrame:
    """Dated references as a frame, oldest first."""
    if not references:
        return pd.DataFrame()
    frame = pd.DataFrame(
        [
            {
                "month_year": reference.month_year,
                "period": str(reference.period),
                "source": f"{reference.source_code} p.{reference.page}",
                "source_title": reference.source_title,
                "sentence": reference.sentence,
            }
            for reference in references
        ]
    )
    return frame.sort_values("period").reset_index(drop=True)
