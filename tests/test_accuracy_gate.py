"""Unit tests for the accuracy gate (agent/verify.py). (CLAUDE.md §6, §10)

Runs with NO API key and NO network — this is what proves the "never state a number
that wasn't on the page" guarantee without paying to score anything. Run it:

    python3 tests/test_accuracy_gate.py          # plain, no deps
    python3 -m pytest tests/test_accuracy_gate.py # if pytest is installed
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.verify import quote_on_page, year_in_quote  # noqa: E402

PAGE = (
    "About the Foundation. We support leaders across San Diego and Imperial County.\n"
    "The Resilience Fund awards grants of up to $75,000 per organization each year.\n"
    "Applications are due March 15, 2027. Since inception we have distributed over "
    "$4,500,000 to the community."
)


# --- quote_on_page ------------------------------------------------------------

def test_exact_sentence_matches():
    assert quote_on_page("The Resilience Fund awards grants of up to $75,000 per organization each year.", PAGE)


def test_whitespace_and_newlines_normalized():
    assert quote_on_page("awards grants of up to $75,000\n   per organization", PAGE)


def test_case_insensitive():
    assert quote_on_page("APPLICATIONS ARE DUE MARCH 15, 2027", PAGE)


def test_fabricated_amount_rejected():
    # The model hallucinated a bigger number; that sentence is not on the page.
    assert not quote_on_page("awards grants of up to $750,000 per organization", PAGE)


def test_total_since_inception_is_not_an_award():
    # This sentence IS on the page, but it's a lifetime total — the gate only proves the
    # quote is real; the prompt + parse.py disqualifier keep it out of the award field.
    # Here we just confirm a made-up per-award sentence using that number is rejected.
    assert not quote_on_page("awards grants of up to $4,500,000 per organization", PAGE)


def test_none_quote_rejected():
    assert not quote_on_page(None, PAGE)


def test_empty_quote_rejected():
    assert not quote_on_page("", PAGE)


def test_too_short_quote_rejected():
    # A bare number would substring-match by accident; require a real sentence.
    assert not quote_on_page("$75,000", PAGE)


# --- year_in_quote ------------------------------------------------------------

def test_year_present_in_quote():
    assert year_in_quote("2027-03-15", "Applications are due March 15, 2027.")


def test_invented_year_rejected():
    # Real sentence, but no year in it — the model invented 2027.
    assert not year_in_quote("2027-03-15", "Applications are due March 15.")


def test_year_none_inputs_rejected():
    assert not year_in_quote(None, "March 15, 2027")
    assert not year_in_quote("2027-03-15", None)


def test_wrong_year_rejected():
    assert not year_in_quote("2028-03-15", "Applications are due March 15, 2027.")


# --- end-to-end shape the gate enforces ---------------------------------------

def test_gate_combination_deadline_trusted_only_with_quote_and_year():
    dl = "2027-03-15"
    good = "Applications are due March 15, 2027."
    bad_paraphrase = "The deadline is in mid-March next year."
    assert quote_on_page(good, PAGE) and year_in_quote(dl, good)          # trusted
    assert not (quote_on_page(bad_paraphrase, PAGE) and year_in_quote(dl, bad_paraphrase))  # dropped


def _run() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}  {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())


# --- regression: values split across elements (found on the first scored run) ---
#
# The Prebys "2026 Rooted and Rising" page renders "Up to $150,000" with each digit
# group in its own element, so the extracted text is "Up to $\n150\n,\n000". On the
# first real scoring run this cost us a genuine $150,000 opportunity twice over: the
# free tier found no amount at all, and the gate then discarded Sonnet's correct
# reading because the quote was not a literal substring of our mangled text.

SPLIT_PAGE = (
    "Guidelines\nGrant Term:\nJuly\n2026\n– December\n2027\n,\n\n18\nmonths\n"
    "Anticipated Grant Awards:\nUp to $\n150\n,\n000\nTotal Funds for the Initiative:\n"
    "$\n2\n.\n5\nM\nin funding\n"
)


def test_split_amount_is_repaired_by_the_parser():
    from agent.parse import _clean, extract_amounts

    cleaned = _clean(SPLIT_PAGE)
    assert "$150,000" in cleaned, "the split figure was not rejoined"
    assert "$2.5" in cleaned

    amounts = [e.value for e in extract_amounts(cleaned)]
    assert 150_000 in amounts, "the free tier still cannot see the award"


def test_quote_matches_across_a_split_value():
    from agent.parse import _clean

    assert quote_on_page("Anticipated Grant Awards: Up to $150,000", _clean(SPLIT_PAGE))


def test_whitespace_insensitive_pass_still_rejects_a_fabrication():
    """The second pass may only forgive layout. An invented number must still fail."""
    from agent.parse import _clean

    page = _clean(SPLIT_PAGE)
    assert not quote_on_page("Anticipated Grant Awards: Up to $500,000", page)
    assert not quote_on_page("Awards of up to $150,000 are made annually", page)


def test_repair_does_not_join_unrelated_numbers():
    from agent.parse import _clean

    assert _clean("We gave $5 million. 2024 was a strong year.") == \
        "We gave $5 million. 2024 was a strong year."
    assert _clean("Applications cost $25 to submit") == "Applications cost $25 to submit"


# --- regression: unreadable files must never reach a model --------------------
#
# On a real scored run, three results had a raw URL as their title because the crawl
# followed links to PDFs. A PDF fetched as HTML decodes to its byte stream —
# "%PDF-1.6 ... FlateDecode ..." — the title falls back to the URL, and Sonnet scored
# one of them 55 out of 100. A confident number derived from binary noise, at full
# token cost, is the worst possible combination.

def test_pdf_and_office_links_are_not_followed():
    from agent.parse import find_grant_links

    links = [
        ("/grants/application-instructions.pdf", "Application instructions"),
        ("/grants/FY27-GAP-Program-Guidelines.PDF", "Program guidelines"),
        ("/grants/budget-template.xlsx", "Budget template"),
        ("/grants/apply", "Apply for funding"),
    ]
    out = find_grant_links("https://example.invalid/grants", links)
    assert out == ["https://example.invalid/grants/apply"], \
        "only the readable page should be followed"


def test_a_non_html_content_type_is_refused():
    """The extension check catches most of it; a URL with no extension that still
    serves a PDF is caught here, where the server has told us what it sent."""
    from agent.fetch import _READABLE_TYPE

    for ok in ("text/html", "text/plain", "application/xhtml+xml", "application/json"):
        assert _READABLE_TYPE.match(ok), ok
    for bad in ("application/pdf", "image/png", "application/zip",
                "application/octet-stream", "application/msword"):
        assert not _READABLE_TYPE.match(bad), bad


# --- regression: the rationale is prose and never passed the quote gate --------
#
# Found on a real scored run. The Andy Warhol Foundation result correctly had
# award_max = None — the model had no quote to back an amount. Its rationale then read
# "solid average awards (~$80k inferred from public announcements)". The field was
# honest and the sentence was not, which is worse than either alone: the number reads
# as sourced because everything around it is. And the sentence is the part Mauri reads.

PAGE_WITH_AMOUNTS = (
    "Grants of up to $25,000 are awarded annually. "
    "Since inception the foundation has distributed 250,000 dollars in total."
)


def test_an_invented_figure_in_the_rationale_is_caught():
    from agent.verify import unsourced_figures

    assert unsourced_figures(
        "solid average awards (~$80k inferred from public announcements)",
        PAGE_WITH_AMOUNTS,
    ) == ["$80k"]


def test_a_figure_that_is_on_the_page_is_not_flagged():
    from agent.verify import unsourced_figures

    assert unsourced_figures("Awards up to $25,000, which clears the floor",
                             PAGE_WITH_AMOUNTS) == []


def test_formatting_differences_are_not_treated_as_invention():
    """We are catching invention, not formatting — '$250k' and '250,000' are the
    same claim, and flagging the second would train everyone to ignore the flag."""
    from agent.verify import unsourced_figures

    assert unsourced_figures("about $250k distributed", PAGE_WITH_AMOUNTS) == []


def test_prose_without_figures_is_left_alone():
    from agent.verify import unsourced_figures

    assert unsourced_figures("A strong fit for the arts program with real runway.",
                             PAGE_WITH_AMOUNTS) == []
    assert unsourced_figures("", PAGE_WITH_AMOUNTS) == []
    assert unsourced_figures(None, PAGE_WITH_AMOUNTS) == []
