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
#
# `awarded?\s+date|date\s+awarded` was added after a real page (Hilton Foundation's
# housing priorities page) turned out to be a case-study record of a grant already
# given — "Grant Amount:\n$2400000\n\nAwarded Date:\nAugust, 2022" — not an open call's
# award size. Narrow on purpose: it matches the LABEL that marks a past-grant record,
# not the word "award" alone, so "grants are typically awarded up to $50,000" — future
# tense, describing an open call — is untouched.
_AWARD_DISQUALIFIER = re.compile(
    r"(since\s+(?:its\s+)?(?:inception|founding|\d{4})|"
    r"(?:to|thus\s+far|so\s+far)\s+date|"
    r"total(?:ing|ling|ed)?\s+(?:more\s+than\s+)?\$|"
    r"(?:has|have|had)\s+(?:award|grant|distribut|invest|provid|given)\w*\s+(?:more\s+than\s+|over\s+|nearly\s+)?\$|"
    r"\b(?:endowment|assets\s+under|net\s+assets|annual\s+budget|operating\s+budget|"
    r"revenue|portfolio|market\s+value)\b|"
    r"(?:in|over)\s+(?:the\s+)?(?:past|last)\s+\w+\s+years?|"
    r"budget\s+of\s+\$|program\s+budget|total\s+(?:funding|available|pool|allocation)|"
    r"awarded?\s+date|date\s+awarded|grant(?:ee)?\s+(?:profile|record|history))",
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

# Found on the San Diego Pride grants page: "Applications open: October 6, 2025
# Deadline to apply: November 3, 2025" with no sentence break between them, because a
# key-dates block on the page renders as one run of text with no punctuation to split
# on. Both dates land in the same sentence, `_DEADLINE_CUE` matches ("Deadline to
# apply"), and without this, extract_deadlines took EVERY date in that sentence —
# reporting the OPEN date as a deadline alongside the real one. That is not a harmless
# extra: `ParsedPage.earliest_deadline` takes the MIN of what it is given, and an open
# date is always earlier than the deadline that follows it, so the open date would win
# every time and the runway filter would judge the application against a date that was
# never the deadline at all. `_nearest_cue_wins` below keeps a date only when a deadline
# cue is textually closer to it than any open cue — the fix is proximity, not exclusion,
# because a page can legitimately state both and the deadline cue is usually right next
# to its own date even when an open cue appears earlier in the same run-on sentence.
_OPEN_CUE = re.compile(
    r"(applications?\s+open|opens?\s+(?:on|for|to)|now\s+accepting|"
    r"application\s+window\s+opens|submissions?\s+open|opening\s+date)",
    re.IGNORECASE,
)


def _nearest_cue_wins(sentence: str, date_start: int) -> bool:
    """True unless an OPEN cue is the label immediately before this date, closer than
    any DEADLINE cue's closest occurrence before it.

    Only cues that come BEFORE the date count, because every real instance of this
    pattern puts the label first — "Deadline to apply: <date>", "Applications open:
    <date>" — never the reverse. That is what makes this precise rather than a coin
    flip: on the San Diego Pride page, "Key Deadlines" is a section heading at the very
    start of the block, "Applications open:" sits directly in front of the open date,
    and "Deadline to apply:" sits directly in front of the real one. Scanning the whole
    sentence for the nearest cue in EITHER direction let the distant, generic heading
    outrank the specific label two words before the open date. Restricting to what
    precedes the date fixes that without needing to special-case headings at all.
    """
    deadline_before = [m.start() for m in _DEADLINE_CUE.finditer(sentence)
                       if m.end() <= date_start]
    if not deadline_before:
        return False  # no deadline cue leads into this date at all
    nearest_deadline = date_start - max(deadline_before)

    open_before = [m.start() for m in _OPEN_CUE.finditer(sentence)
                  if m.end() <= date_start]
    if not open_before:
        return True
    nearest_open = date_start - max(open_before)
    return nearest_deadline <= nearest_open

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

# The link a human would actually click to start applying — CLAUDE.md §6 requires
# `source_url` to stay the funder's OWN page, so this is deliberately a second, separate
# fact rather than a replacement. It never needs a model: an href that literally exists
# in the fetched HTML is self-evidencing the same way a quoted sentence is, so this can
# be found for free, in the tier that costs nothing to be wrong in.
#
# Anchor text that says, in so many words, "click here to apply". Distinct from
# `_GRANT_LINK_HINT`, which is broad on purpose (it also has to catch "Priorities" and
# "Guidelines" pages worth following) — this is narrow on purpose, because it decides
# which ONE link is shown as *the* apply link, not which pages are worth a second look.
_APPLY_ANCHOR = re.compile(
    r"\b(apply\s*(?:now|here|online)?|start\s+(?:your\s+)?application|"
    r"submit\s+(?:your\s+|an?\s+)?(?:application|proposal|loi|"
    r"letter\s+of\s+(?:inquiry|intent))|begin\s+(?:your\s+)?application|"
    r"application\s+form|register(?:\s+(?:here|now|for\s+an?\s+account))?|"
    r"create\s+an?\s+account|log\s*in\s+to\s+apply|grant\s+application|"
    r"online\s+application|access\s+the\s+application)\b",
    re.IGNORECASE,
)

# A funder that outsources applications to a dedicated grants-management vendor is
# telling you, in the URL alone, that its real "Apply" link is off its own domain — the
# exact case `find_grant_links`'s same-domain rule (correctly, for `source_url`) cannot
# reach. Measured against 62 real pages from the shipped funder registry, 8 of them
# — 13% — had their actual apply link on one of these hosts.
_KNOWN_PORTAL_HOST = re.compile(
    r"(\bfluxx\.io\b|\bsubmittable\.com\b|\bsmapply\.(?:io|org)\b|"
    r"\bgrantrequest\.com\b|\bfoundant\.com\b|\bgrantinterface\.com\b|"
    r"\bproposalcentral\.com\b|\bgrants\.gov\b|\bwizehive\.com\b|"
    r"\bcommunityforce\.com\b|\bapplyfor\.[a-z]+\b)",
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
    # True when the sentence states this figure as a FLOOR ("minimum grant size is
    # $100,000") with no ceiling anywhere in the same sentence. Only `extract_amounts`
    # sets this; deadlines never do. See `_FLOOR_ONLY_CUE` for why it exists.
    floor_only: bool = False


@dataclass
class ParsedPage:
    url: str
    title: str
    text: str
    amounts: list[Evidence] = field(default_factory=list)
    deadlines: list[Evidence] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Distinct from `url` (which becomes `source_url`, and by §6 must be the funder's
    # own page): this is the link a human would actually click to start applying, which
    # may be off the funder's domain entirely — see `find_apply_link`.
    apply_url: str | None = None

    @property
    def award_min(self) -> int | None:
        vals = [e.value for e in self.amounts if isinstance(e.value, int)]
        return min(vals) if vals else None

    @property
    def award_max(self) -> int | None:
        """The highest amount the page states as a CEILING — never a lone floor.

        A sentence that only says "minimum grant size is $100,000", with nothing else
        on the page, is evidence of what an applicant gets AT LEAST — it says nothing
        about the ceiling, and reporting it as one is the same mistake §6 forbids for a
        past grant amount: a true figure, attached to the wrong claim. Found on the
        Hearst Foundations health page, whose only dollar figure is exactly that
        sentence — `award_min` and `award_max` used to both resolve to the same
        `min()`/`max()` over one evidence value, so the stated floor was reported as the
        cap. A sentence naming both a floor and a ceiling (a range, or "up to $X") is
        unaffected: only a bare floor with no ceiling anywhere on the page loses its
        claim to this property.
        """
        vals = [e.value for e in self.amounts
                if isinstance(e.value, int) and not e.floor_only]
        return max(vals) if vals else None

    @property
    def earliest_deadline(self) -> date | None:
        """Nearest future deadline. Past dates are last year's cycle, not this one."""
        today = date.today()
        future = [e.value for e in self.deadlines
                  if isinstance(e.value, date) and e.value >= today]
        return min(future) if future else None

    @property
    def most_recent_past_deadline(self) -> date | None:
        """The latest deadline evidence that has already passed, if the page states
        one and states no future one alongside it.

        Exists to keep two very different facts apart: "this page states no deadline"
        and "this page's only stated deadline has already passed" both used to collapse
        to `earliest_deadline is None`, so a closed grant read identically to one that
        simply never mentioned a date — flagged `deadline_not_stated` and shown, rather
        than rejected as closed. `apply_filters` checks this only when
        `earliest_deadline` is None, so a page describing both a closed round and an
        upcoming one is unaffected — the future date wins there, as it should.
        """
        today = date.today()
        past = [e.value for e in self.deadlines
                if isinstance(e.value, date) and e.value < today]
        return max(past) if past else None


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
    """True sentence boundaries, plus any newline — but no longer a bare `:` or `;`.

    It used to split on those too, and "Deadline to apply: May 1, 2027 - 5:00 p.m." —
    one fact, one line, just a label and its value separated by a colon — came apart
    into "Deadline to apply:" and "May 1, 2027…" as two different "sentences".
    `extract_amounts`/`extract_deadlines` require the cue and the value in the SAME
    piece, so that single punctuation mark silently dropped the deadline. Measured
    against a real sample of the funder registry, `label: value` on one line is a common
    way funders publish this, not an edge case.

    The newline split stays exactly as strict as before — every line breaks a chunk —
    on purpose. A funder's timeline table renders several DIFFERENT milestones (opens,
    submission deadline, notification date) as consecutive single-newline-separated
    rows, and loosening this to a paragraph-level break was tried and reverted: it let
    one "sentence" span the whole table, so a single cue anywhere in it pulled in every
    date in every row — the open date and the notification date along with the real
    deadline. `_paired_with_nearby_value` below is what reaches across a SINGLE newline
    safely instead, because it pairs one cue with the very next bare-value line only,
    never with a later row two milestones down.
    """
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def _dedupe_evidence(items: list[Evidence]) -> list[Evidence]:
    """Same value, same neighbourhood of text — one real fact, reported once.

    Needed because May's abbreviation IS its full name: "May 9, 2026" matches both the
    full-month and the abbreviated-month pattern in `_DATE_PATTERNS`, so every May
    deadline was recorded twice. Deduping on the value is enough — two genuinely
    different sentences stating the same date is rare, and showing the fact once more
    isn't the failure mode this guards against; showing it as two competing pieces of
    evidence for what is one date is.
    """
    seen: set = set()
    out: list[Evidence] = []
    for e in items:
        if e.value in seen:
            continue
        seen.add(e.value)
        out.append(e)
    return out


# A label:value or label\nvalue pair the sentence splitter cannot see, because the two
# halves land in different chunks. Deliberately narrow: the wrong direction to be wrong
# in here is pairing a cue with a date or amount from somewhere else on the page — a
# CONFIDENT WRONG fact, which is worse than the miss this exists to fix. So a candidate
# "value line" only counts when almost nothing besides the value is on it: a real
# label:value pair is short on both sides. A date buried inside an unrelated sentence,
# or a cue sitting in the middle of a paragraph two lines above an unrelated fact, never
# qualifies — those still go through the ordinary same-sentence path above, unaffected.
_MAX_CUE_LINE = 70   # a label, not a paragraph that happens to contain a cue word
_MAX_VALUE_LOOKAHEAD = 2   # how many lines past the cue we will look
_MAX_VALUE_REMAINDER = 20  # how much non-value text a "bare value" line may still carry
_DISQUALIFIER_TRAILING_LINES = 2  # how far past the value a disqualifier still counts


def _paired_with_nearby_value(text: str, cue_re: "re.Pattern[str]",
                              value_re: "re.Pattern[str]",
                              disqualifier_re: "re.Pattern[str] | None" = None
                              ) -> list[tuple[str, str]]:
    """(combined_snippet, value_line) for every short cue line immediately followed by a
    bare value line. Stops at the first non-empty line after the cue that is NOT a bare
    value — it never skips past an unrelated line hunting for one further down, which is
    what would let an "Application opens: <date>" cue reach past its own line and grab
    the closing date meant for a different label two lines later.

    The disqualifier is checked over the value line AND a few lines after it, not the
    value line alone. Found on a real page: "Grant Amount:\\n$2,400,000\\n\\nAwarded
    Date:\\nAugust, 2022" is a record of a grant already given, not an open call's award
    size — but "Awarded Date" trails the number by two lines, and a check that only
    looked at the bare "$2,400,000" line would never see it.
    """
    lines = [ln.strip() for ln in text.split("\n")]
    out: list[tuple[str, str]] = []
    for i, line in enumerate(lines):
        if not line or len(line) > _MAX_CUE_LINE:
            continue
        if not cue_re.search(line) or value_re.search(line):
            continue  # no cue here, or the cue line already carries its own value
        for j in range(i + 1, min(i + 1 + _MAX_VALUE_LOOKAHEAD, len(lines))):
            candidate = lines[j]
            if not candidate:
                continue
            m = value_re.search(candidate)
            if not m:
                break  # the next real content isn't a value — do not look further
            remainder = (candidate[:m.start()] + candidate[m.end():]).strip(" -–—:|.")
            if len(remainder) > _MAX_VALUE_REMAINDER:
                break  # not a bare value line — likely unrelated prose
            if disqualifier_re:
                trailing = " ".join(
                    lines[j:j + 1 + _DISQUALIFIER_TRAILING_LINES])
                if disqualifier_re.search(trailing):
                    break
            out.append((f"{line} {candidate}", candidate))
            break
    return out


# A sentence stating only a FLOOR ("minimum grant size is $100,000", "grants start at
# $5,000", "awards of at least $2,000") — see the docstring on `ParsedPage.award_max`
# for why this has to be kept apart from a ceiling.
_FLOOR_ONLY_CUE = re.compile(
    r"(minimum\s+(?:grant\s+|award\s+)?(?:size\s+|amount\s+)?(?:is|of)|"
    r"at\s+least\s*\$|no\s+less\s+than\s*\$|"
    r"(?:grants?|awards?)\s+(?:start(?:ing)?|begin(?:ning)?)\s+(?:at|from)\s*\$)",
    re.IGNORECASE,
)
# A sentence naming a ceiling — a range, or "up to $X" and its synonyms. Present, this
# cancels `_FLOOR_ONLY_CUE`: "grants of $5,000 up to $50,000" states both ends and both
# numbers are real evidence for their own side, exactly as before this fix.
_CEILING_CUE = re.compile(
    r"((?:up\s+to|as\s+much\s+as|maximum\s+of|no\s+more\s+than|not\s+to\s+exceed)\s*\$|"
    r"\$[\d,]+\s*(?:-|–|to)\s*\$[\d,]+)",
    re.IGNORECASE,
)


def _floor_only(sentence: str) -> bool:
    return bool(_FLOOR_ONLY_CUE.search(sentence) and not _CEILING_CUE.search(sentence))


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
            out.append(Evidence(value=amount, snippet=sentence[:300], kind="amount",
                                floor_only=_floor_only(sentence)))
            if len(out) >= limit:
                return out

    # Second pass: "Award Amount:\n$50,000" and "Grant size: $25,000" — a bare dollar
    # figure has no context of its own to disqualify it the way a sentence does, so the
    # cue is required to be a genuine award phrase (`_AWARD_CONTEXT`), never just "$".
    if len(out) < limit:
        for snippet, value_line in _paired_with_nearby_value(
                text, _AWARD_CONTEXT, _MONEY, _AWARD_DISQUALIFIER):
            m = _MONEY.search(value_line)
            if not m:
                continue
            raw, suffix = m.group(1), (m.group(2) or "").lower().strip()
            try:
                value = float(raw.replace(",", ""))
            except ValueError:
                continue
            value *= _MULTIPLIERS.get(suffix, 1)
            amount = int(value)
            if amount < _MIN_PLAUSIBLE_AWARD:
                continue
            out.append(Evidence(value=amount, snippet=value_line[:300], kind="amount",
                                floor_only=_floor_only(snippet)))
            if len(out) >= limit:
                break
    return _dedupe_evidence(out)[:limit]


# Found on a real page (California Board of State and Community Corrections, CalVIP):
# "Proposals due 6/27/25" — a completely ordinary 2-digit-year date — parsed by
# `dateparser` under `PREFER_DATES_FROM: "future"` as **2125-06-27**, a century off, not
# 2025. The stdlib fallback below gets this right (`%y` uses the POSIX 00-68→20xx,
# 69-99→19xx convention, so "25" is unambiguously 2025) — it is specifically
# dateparser's future-preference heuristic that jumps a full century instead of
# correcting a two-digit year to the nearby one. Since `ParsedPage.earliest_deadline`
# only returns FUTURE dates and takes the MIN, a date wrongly parsed a century ahead
# would always look like "the deadline with unlimited runway" — the exact opposite of
# reality for a grant whose real deadline had already passed. A grants page fetched
# today writing a 2-digit year never means anything but this century, so it is expanded
# explicitly before either parser sees it — removing the ambiguity rather than trusting
# a library's guess about it.
_TWO_DIGIT_YEAR_SLASH_DATE = re.compile(r"^(\d{1,2}/\d{1,2}/)(\d{2})$")


def _parse_date(raw: str) -> date | None:
    """dateparser when available (§5 — funder formats are chaotic), stdlib otherwise."""
    raw = raw.strip()
    m = _TWO_DIGIT_YEAR_SLASH_DATE.match(raw)
    if m:
        raw = f"{m.group(1)}20{m.group(2)}"

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
    """Dates are only taken when a deadline cue sits in the same sentence, or is the
    label immediately above/before a bare date (`_paired_with_nearby_value`). A date
    with no cue is a board meeting or a press release, not a due date."""
    out: list[Evidence] = []
    for sentence in _sentences(text):
        if not _DEADLINE_CUE.search(sentence):
            continue
        # Consumed spans, so a date matched by one pattern is not matched AGAIN by a
        # different pattern over the same characters — May's abbreviation equals its
        # full name ("may" is both), so "May 9, 2026" satisfied the full-month AND the
        # abbreviated-month regex and was recorded twice for every May deadline.
        consumed: list[tuple[int, int]] = []
        for pattern in _DATE_PATTERNS:
            for m in pattern.finditer(sentence):
                if any(m.start() < e and s < m.end() for s, e in consumed):
                    continue
                if not _nearest_cue_wins(sentence, m.start()):
                    continue
                parsed = _parse_date(m.group(0))
                if parsed is None:
                    continue
                consumed.append((m.start(), m.end()))
                out.append(Evidence(value=parsed, snippet=sentence[:300], kind="deadline"))
                if len(out) >= limit:
                    return _dedupe_evidence(out)

    # Second pass: "Application Deadline\nOctober 15, 2026" — a table row or a
    # definition list renders the label and the date on adjacent lines, which is how
    # most funders actually publish this, not the edge case the same-sentence rule
    # above assumed.
    if len(out) < limit:
        for pattern in _DATE_PATTERNS:
            for _snippet, value_line in _paired_with_nearby_value(
                    text, _DEADLINE_CUE, pattern):
                m = pattern.search(value_line)
                if not m:
                    continue
                parsed = _parse_date(m.group(0))
                if parsed is None:
                    continue
                out.append(Evidence(value=parsed, snippet=value_line[:300], kind="deadline"))
                if len(out) >= limit:
                    break
    return _dedupe_evidence(out)[:limit]


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


def find_apply_link(base_url: str, links: list[tuple[str, str]]) -> str | None:
    """The single best candidate for "click here to apply", off-domain included.

    Unlike `find_grant_links`, this deliberately does NOT restrict the RESULT to the
    funder's own domain — that restriction is correct for `source_url` (§6: it must
    point at the funder's own page) and wrong here, because a great many funders run
    applications through a dedicated portal vendor (Fluxx, Submittable, SM Apply,
    GrantRequest…) on a completely different host. `base_url` is still used to resolve
    ordinary relative hrefs (`/apply`, `apply.html`) into absolute ones — most same-
    domain "Apply Now" buttons are written as relative links, so skipping resolution
    would miss the common case, not just the off-domain one. Every candidate is still a
    real href pulled straight out of the fetched HTML — nothing here is inferred or
    guessed, only chosen among what the page itself links to, so it costs nothing to be
    occasionally wrong about which of several real links is the best one, and it is
    never wrong about a link's existence.

    Scored, not just matched, because a real page can have several plausible candidates
    ("Apply Now" on the funder's own domain AND a portal link a few lines later) and the
    UI needs exactly one. A known portal host and matching anchor text together is the
    strongest signal available without a model; either alone still beats an ordinary
    `_GRANT_LINK_HINT` match, which exists only to break a tie honestly, not to invent
    a link nothing on the page actually offered.
    """
    best: tuple[int, str] | None = None
    for href, anchor in links:
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        if _UNREADABLE_SUFFIX.search(parsed.path):
            continue

        score = 0
        if _KNOWN_PORTAL_HOST.search(absolute):
            score += 2
        if _APPLY_ANCHOR.search(anchor):
            score += 2
        if score == 0 and _GRANT_LINK_HINT.search(anchor):
            # The weak, generic tier only — a page names its "Grant Recipients" or
            # "Past Grantees" page with the same words a real apply link uses ("grant"),
            # and on The Parker Foundation's real page that link tied 1-1 with "Grant
            # Seekers" and only won by NOT being first in document order. A stronger
            # match (portal host or real apply anchor) always overrides this exclusion,
            # so a genuine "Apply Now" button that happens to sit on a page also linking
            # to past recipients is untouched.
            if re.search(r"recipient|grantee|past\s+grants?|awarded|portfolio|"
                        r"annual\s+report", anchor, re.IGNORECASE):
                continue
            score += 1
        if score == 0:
            continue

        normalized = absolute.split("#")[0].rstrip("/")
        if normalized == base_url.rstrip("/"):
            continue  # the page linking to itself, not an application starting point
        if best is None or score > best[0]:
            best = (score, normalized)
    return best[1] if best else None


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
        apply_url=find_apply_link(url, links),
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
        apply_url=page.apply_url,
    )
