"""page -> raw candidate. (CLAUDE.md)

Everything extracted here carries the snippet it came from. That is not decoration:
§6 forbids stating an amount or a deadline that was not on a page we fetched, and the
only way to keep that promise is to be able to point at the sentence. A number without
evidence is discarded rather than reported.

selectolax first (fast), BeautifulSoup as fallback (§5).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from urllib.parse import urljoin, urlparse

from .models import Program, RawCandidate

log = logging.getLogger(__name__)

_STRIP_TAGS = ("script", "style", "noscript", "svg", "nav", "footer", "header", "form")

# $50,000 · $50,000-$75,000 · up to $1 million · $1.5M
_MONEY = re.compile(
    r"\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(million|billion|thousand|m\b|k\b)?",
    re.IGNORECASE,
)

# The sentence must present the money as something an applicant receives.
_AWARD_CONTEXT = re.compile(
    r"(award(?:s|ed|ing)?\s+(?:of|up\s+to|range|between|amount)|"
    r"grants?\s+(?:of|up\s+to|range|between|from)|"
    r"(?:up\s+to|as\s+much\s+as|maximum\s+of|minimum\s+of|no\s+more\s+than)\s*\$|"
    r"request\s+(?:up\s+to|between|of)|"
    r"funding\s+(?:of|up\s+to|range|between|level)|"
    r"\baward\s+(?:size|amount|range)|grant\s+(?:size|amount|range)|"
    r"per\s+(?:grant|award|grantee|organization|project)|"
    r"rang(?:e|es|ing)\s+(?:from|between)|"
    r"\$[\d,]+\s*(?:-|–|to)\s*\$[\d,]+)",
    re.IGNORECASE,
)

# ...and must not be talking about totals, history, or the funder's own balance sheet.
_AWARD_DISQUALIFIER = re.compile(
    r"(since\s+(?:its\s+)?(?:inception|founding|\d{4})|"
    r"(?:to|thus\s+far|so\s+far)\s+date|"
    r"total(?:ing|ling|ed)?\s+(?:more\s+than\s+)?\$|"
    r"(?:has|have|had)\s+(?:award|grant|distribut|invest|provid|given)\w*\s+(?:more\s+than\s+|over\s+|nearly\s+)?\$|"
    r"\b(?:endowment|assets\s+under|net\s+assets|annual\s+budget|operating\s+budget|"
    r"revenue|portfolio|market\s+value)\b|"
    r"(?:in|over)\s+(?:the\s+)?(?:past|last)\s+\w+\s+years?|"
    r"budget\s+of\s+\$|program\s+budget|total\s+(?:funding|available|pool|allocation))",
    re.IGNORECASE,
)

# Widened after the calibration test caught "must be submitted by <date>" slipping
# through a `submit by` cue — a 5-day deadline passed the 14-day runway filter
# because the sentence never matched. Deadline phrasing is the highest-risk part of
# this parser: a missed cue means a too-soon grant reaches the user as if it had runway.
_DEADLINE_CUE = re.compile(
    r"(deadline|due\s+(?:by|date|on)?|"
    r"applications?\s+(?:close|closing|are\s+due|due|must\s+be|period\s+ends)|"
    r"submitt?(?:ed|ing)?\s+by|apply\s+by|appl(?:y|ications?)\s+no\s+later\s+than|"
    r"no\s+later\s+than|postmarked\s+by|received\s+by|"
    r"closes?\s+(?:on|at)|closing\s+date|last\s+day\s+to\s+apply|"
    r"letters?\s+of\s+(?:intent|inquiry)\s+(?:are\s+)?due|loi\s+due|"
    r"nominations?\s+(?:are\s+)?due|proposals?\s+(?:are\s+)?due|rfp\s+closes?)",
    re.IGNORECASE,
)

# Only formats a funder would actually publish. Deliberately narrow — a loose date
# regex produces confident garbage, which is the one outcome §6 forbids.
_DATE_PATTERNS = [
    re.compile(
        r"\b(january|february|march|april|may|june|july|august|september|october|"
        r"november|december)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+"
        r"\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
]

_GRANT_LINK_HINT = re.compile(
    r"(grant|funding|fund|rfp|apply|application|opportunit|award|fellowship|"
    r"scholarship|solicitation|nofa|nofo)",
    re.IGNORECASE,
)

# Files we cannot read. This is not a nicety: a PDF fetched as HTML yields its raw
# byte stream ("%PDF-1.6 ... FlateDecode ..."), the title falls back to the URL, and on
# a real run Sonnet scored one of those 55 out of 100 — a confident number derived from
# binary noise, at full token cost. Decision A2 deferred PDF support; until it lands,
# not following these is the honest behaviour.
_UNREADABLE_SUFFIX = re.compile(
    r"\.(pdf|docx?|xlsx?|pptx?|zip|rar|csv|jpe?g|png|gif|svg|mp4|mov|mp3)$",
    re.IGNORECASE,
)

_MULTIPLIERS = {
    "million": 1_000_000, "m": 1_000_000,
    "billion": 1_000_000_000,
    "thousand": 1_000, "k": 1_000,
}

# Below this, a "$" on a grants page is a membership fee, a ticket price, or a
# footnote — not an award. Filtering here keeps noise out of the award fields.
_MIN_PLAUSIBLE_AWARD = 500


@dataclass
class Evidence:
    """A value plus the sentence it was read from."""

    value: object
    snippet: str
    kind: str  # "amount" | "deadline"


@dataclass
class ParsedPage:
    url: str
    title: str
    text: str
    amounts: list[Evidence] = field(default_factory=list)
    deadlines: list[Evidence] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def award_min(self) -> int | None:
        vals = [e.value for e in self.amounts if isinstance(e.value, int)]
        return min(vals) if vals else None

    @property
    def award_max(self) -> int | None:
        vals = [e.value for e in self.amounts if isinstance(e.value, int)]
        return max(vals) if vals else None

    @property
    def earliest_deadline(self) -> date | None:
        """Nearest future deadline. Past dates are last year's cycle, not this one."""
        today = date.today()
        future = [e.value for e in self.deadlines
                  if isinstance(e.value, date) and e.value >= today]
        return min(future) if future else None


# --- HTML -> text -------------------------------------------------------------

def html_to_text(html: str) -> tuple[str, str, list[tuple[str, str]]]:
    """Returns (title, text, links). selectolax first, bs4 fallback."""
    try:
        from selectolax.parser import HTMLParser

        tree = HTMLParser(html)
        for tag in _STRIP_TAGS:
            for node in tree.css(tag):
                node.decompose()
        title = tree.css_first("title")
        title_text = title.text(strip=True) if title else ""
        if not title_text:
            h1 = tree.css_first("h1")
            title_text = h1.text(strip=True) if h1 else ""
        body = tree.body or tree.root
        text = body.text(separator="\n", strip=True) if body else ""
        links = [
            (a.attributes.get("href", ""), a.text(strip=True))
            for a in tree.css("a")
            if a.attributes.get("href")
        ]
        return title_text, text, links

    except ImportError:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(list(_STRIP_TAGS)):
            tag.decompose()
        title_text = soup.title.get_text(strip=True) if soup.title else ""
        if not title_text and soup.h1:
            title_text = soup.h1.get_text(strip=True)
        text = soup.get_text(separator="\n", strip=True)
        links = [(a["href"], a.get_text(strip=True)) for a in soup.find_all("a", href=True)]
        return title_text, text, links


# A dollar sign followed by a run of digits, commas, periods and whitespace, ending on
# a digit. Deliberately anchored to `$` so the repair below can only ever touch the
# inside of a money figure.
_SPLIT_MONEY = re.compile(r"\$\s*(\d[\d\s,.]*\d|\d)")


def _repair_split_amounts(text: str) -> str:
    """Rejoin dollar figures that the page broke across elements.

    Found on the Prebys "2026 Rooted and Rising" page during the first real scoring run.
    It reads "Anticipated Grant Awards: Up to $150,000", but each digit group sits in
    its own element, so the extracted text is:

        Up to $\\n150\\n,\\n000

    Two things went wrong because of it, and they pull in opposite directions:

      - the free tier found NO amount on the page, because `_MONEY` cannot match across
        those newlines. A real $150,000 opportunity had no award figure at all;
      - Sonnet read it correctly as $150,000 — it can see through the line breaks — but
        the verbatim sentence it quoted could not be a literal substring of our mangled
        text, so the §6 accuracy gate discarded a TRUE value.

    The gate failing that way is the safe direction (we showed "amount not stated"
    rather than a wrong number) but it is still a loss: this is exactly the kind of
    opportunity the whole product exists to surface. Repairing the text at the source
    fixes both halves at once.
    """
    return _SPLIT_MONEY.sub(
        lambda m: "$" + re.sub(r"\s+", "", m.group(1)), text
    )


def _clean(text: str) -> str:
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = _repair_split_amounts(text)
    return text.strip()


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;:])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


# --- extraction ---------------------------------------------------------------

def extract_amounts(text: str, limit: int = 40) -> list[Evidence]:
    """Only amounts a sentence actually presents as a per-award figure.

    The first run of this agent reported "$440,000–$4,500,000" for the Alliance
    Healthcare i2 Challenge. Neither number was an award size — they were the total
    program budget and the cumulative amount granted since inception. A grants page is
    full of dollar figures that are not awards: endowment size, annual giving, revenue
    floors, past totals. Taking min/max over all of them produces a confident wrong
    number, which §6 forbids outright.

    So an amount counts only when its own sentence says it is what an applicant can
    receive, and never when the sentence is talking about totals or history.
    """
    out: list[Evidence] = []
    for sentence in _sentences(text):
        if _AWARD_DISQUALIFIER.search(sentence):
            continue
        if not _AWARD_CONTEXT.search(sentence):
            continue
        for m in _MONEY.finditer(sentence):
            raw, suffix = m.group(1), (m.group(2) or "").lower().strip()
            try:
                value = float(raw.replace(",", ""))
            except ValueError:
                continue
            value *= _MULTIPLIERS.get(suffix, 1)
            amount = int(value)
            if amount < _MIN_PLAUSIBLE_AWARD:
                continue
            out.append(Evidence(value=amount, snippet=sentence[:300], kind="amount"))
            if len(out) >= limit:
                return out
    return out


def _parse_date(raw: str) -> date | None:
    """dateparser when available (§5 — funder formats are chaotic), stdlib otherwise."""
    try:
        import dateparser

        parsed = dateparser.parse(
            raw,
            settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False},
        )
        return parsed.date() if parsed else None
    except ImportError:
        for fmt in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y",
                    "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw.replace("  ", " ").strip(), fmt).date()
            except ValueError:
                continue
        return None


def extract_deadlines(text: str, limit: int = 20) -> list[Evidence]:
    """Dates are only taken when a deadline cue sits in the same sentence. A date
    with no cue is a board meeting or a press release, not a due date."""
    out: list[Evidence] = []
    for sentence in _sentences(text):
        if not _DEADLINE_CUE.search(sentence):
            continue
        for pattern in _DATE_PATTERNS:
            for m in pattern.finditer(sentence):
                parsed = _parse_date(m.group(0))
                if parsed is None:
                    continue
                out.append(Evidence(value=parsed, snippet=sentence[:300], kind="deadline"))
                if len(out) >= limit:
                    return out
    return out


def find_grant_links(base_url: str, links: list[tuple[str, str]], limit: int = 25) -> list[str]:
    """Same-domain links whose URL or anchor text suggests a grant program page.
    Staying on-domain is what keeps source_url pointing at the funder (§6)."""
    base_host = urlparse(base_url).netloc
    seen: set[str] = set()
    out: list[str] = []
    for href, anchor in links:
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https") or parsed.netloc != base_host:
            continue
        if _UNREADABLE_SUFFIX.search(parsed.path):
            continue
        if not (_GRANT_LINK_HINT.search(parsed.path) or _GRANT_LINK_HINT.search(anchor)):
            continue
        normalized = absolute.split("#")[0].rstrip("/")
        if normalized in seen or normalized.rstrip("/") == base_url.rstrip("/"):
            continue
        seen.add(normalized)
        out.append(normalized)
        if len(out) >= limit:
            break
    return out


def parse_page(url: str, html: str) -> ParsedPage:
    title, raw_text, links = html_to_text(html)
    text = _clean(raw_text)
    page = ParsedPage(
        url=url,
        title=_clean(title) or url,
        text=text,
        amounts=extract_amounts(text),
        deadlines=extract_deadlines(text),
        links=find_grant_links(url, links),
    )
    if len(text) < 400:
        page.notes.append("very little text — likely JS-rendered; needs a human look")
    if not page.amounts:
        page.notes.append("no award amount stated on this page")
    if not page.deadlines:
        page.notes.append("no deadline stated on this page")
    return page


def to_candidate(page: ParsedPage, funder: str, tier: int,
                 programs_hint: list[Program] | None = None,
                 http_status: int | None = None) -> RawCandidate:
    return RawCandidate(
        source_url=page.url,
        funder=funder,
        title=page.title,
        text=page.text,
        tier=tier,
        programs_hint=programs_hint or [],
        http_status=http_status,
        fetched_at=datetime.now(timezone.utc),
        parse_notes=list(page.notes),
    )
