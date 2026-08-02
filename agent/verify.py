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


def quote_on_page(quote: str | None, page_text: str) -> bool:
    """True only if `quote` is a non-trivial, verbatim substring of `page_text`.

    Whitespace- and case-insensitive (the page text is cleaned before the model sees
    it), but otherwise exact — a paraphrase or a fabricated number will not match.
    """
    q = _normalize(quote)
    if len(q) < _MIN_QUOTE_LEN:
        return False
    return q in _normalize(page_text)


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
