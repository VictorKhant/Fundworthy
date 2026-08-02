"""Deterministic accuracy gate. (CLAUDE.md §6)

The scoring model may report an award amount or a deadline. Before either reaches
Mauri marked as fact, we confirm it was actually on the page we fetched: the model must
return the *verbatim sentence* it read the value from, and we check that sentence is a
literal substring of the fetched text. A value whose quote is missing, paraphrased, or
absent from the page is discarded and flagged for a human — never shown as a number.

This is the one guarantee §6 calls non-negotiable ("A wrong deadline in the demo is
fatal"). `source_url` only proves a page was fetched; this proves the number came from
*that* page. Everything here is pure and deterministic so it can be unit-tested without
an API key or a network.
"""

from __future__ import annotations

import re

# A real sourced sentence is longer than this. Below it, a "quote" is a bare number or
# fragment that would substring-match by accident (e.g. "$5,000" appearing anywhere).
_MIN_QUOTE_LEN = 12


def _normalize(text: str | None) -> str:
    """Collapse all runs of whitespace to a single space and casefold, so a quote that
    differs from the page only in spacing, newlines, or case still matches."""
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def _squeeze(text: str) -> str:
    """Normalized, with whitespace removed entirely rather than collapsed."""
    return re.sub(r"\s+", "", text or "").casefold()


def quote_on_page(quote: str | None, page_text: str) -> bool:
    """True only if `quote` is a non-trivial, verbatim substring of `page_text`.

    Whitespace- and case-insensitive (the page text is cleaned before the model sees
    it), but otherwise exact — a paraphrase or a fabricated number will not match.

    Two passes. The first collapses runs of whitespace to a single space, which handles
    the ordinary case. The second removes whitespace altogether, which handles pages
    that break a value across elements: the Prebys grant page renders "Up to $150,000"
    as "$\\n150\\n,\\n000", so the model's (correct) quote of "Up to $150,000" is not a
    substring of our extracted text under the first pass alone. That cost us a real
    opportunity on the first scored run.

    The second pass cannot launder a fabrication. Removing whitespace makes matching
    more permissive about *layout* only — every other character still has to appear in
    the same order, so an invented number or a paraphrase fails exactly as before.
    """
    q = _normalize(quote)
    if len(q) < _MIN_QUOTE_LEN:
        return False
    if q in _normalize(page_text):
        return True
    return _squeeze(quote) in _squeeze(page_text)


_MONEY_IN_PROSE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s*[kKmM]?\b")


def unsourced_figures(prose: str | None, page_text: str) -> list[str]:
    """Dollar figures in `prose` that do not appear anywhere in `page_text`.

    The quote gate protects the structured fields. It does not protect the one-sentence
    rationale — and that is the part Mauri actually reads.

    Found on a real run: the Andy Warhol Foundation result correctly had `award_max =
    None`, because the model had no quote to back an amount. Its rationale then said
    "solid average awards (~$80k inferred from public announcements)". The field was
    honest and the sentence was not, which is worse than either alone: it reads as
    sourced because everything around it is.

    Comparison is on digits only, so "$80k" written as "80,000" on the page still
    counts as sourced — we are catching invention, not formatting.
    """
    if not prose:
        return []
    page_digits = re.sub(r"[^0-9]", "", page_text or "")
    bad: list[str] = []
    for match in _MONEY_IN_PROSE.finditer(prose):
        token = match.group(0)
        digits = re.sub(r"[^0-9]", "", token)
        if not digits:
            continue
        # "$80k" -> also try the expanded form, since pages write it either way.
        expanded = digits + "000" if token.rstrip().lower().endswith("k") else None
        if digits in page_digits or (expanded and expanded in page_digits):
            continue
        bad.append(token.strip())
    return bad


def year_in_quote(deadline_iso: str | None, quote: str | None) -> bool:
    """True if the deadline's 4-digit year literally appears in its quote.

    Guards the classic failure where the model reads a real but year-less sentence
    ("Applications are due March 15") and confidently emits a full date with a year it
    invented. If the year isn't in the sentence, we don't trust the year.
    """
    if not deadline_iso or not quote:
        return False
    year = deadline_iso[:4]
    if not re.fullmatch(r"\d{4}", year):
        return False
    return year in quote
