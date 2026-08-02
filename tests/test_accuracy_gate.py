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
