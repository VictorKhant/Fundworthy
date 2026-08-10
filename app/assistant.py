"""The program-card assistant: paste a link, get a draft card. (CLAUDE.md)

The problem this solves is a design problem, not a technical one. The user has to tell
the agent what each program is looking for, and CLAUDE.md is unambiguous:

    "The user never writes a prompt. If any workflow requires them to phrase a request
     to an AI, that workflow is wrong."

A blank "describe what this program funds in funder-facing language" textarea is exactly
that wrong workflow. So the interaction is inverted: the user pastes the program's own
page from the org's website, Sonnet reads it, and the card comes back **filled
in and editable**. Their job is to correct a draft, which is a job they already do every
day — not to compose an instruction for a model.

That inversion is also what makes the output trustworthy. They are reviewing concrete
sentences about their own programme, so a wrong one is obvious to them. A prompt written
blind would produce output they have no basis to check.

Two guarantees the code enforces rather than hopes for:

  - **Nothing is saved automatically.** `draft_program_card` returns a draft. Creating
    the card is a separate call the dashboard makes only after they click save, and the
    card is stamped `drafted_by_ai` until they do.
  - **It only reads the page they gave it.** No search, no recall, no filling gaps from
    what the model happens to know about the org. A field the page does not
    support comes back empty, and the response says which fields those were.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

ASSISTANT_MODEL = "claude-sonnet-4-6"
ASSISTANT_MAX_TOKENS = 4_000
PAGE_TEXT_CAP = 14_000

# One page read plus one Sonnet call. Bounded so a stuck loop cannot become a bill.
ASSISTANT_COST_CEILING_USD = 0.10

def _system(org_name: str = "", org_location: str = "") -> str:
    """Who the COO works for, in the org's own words — or in none, if they have not
    said.

    This was a literal string: "a nonprofit in San Diego and Imperial Counties," sent to
    every tenant regardless of who actually pasted the link. Exactly the bug class
    `agent/score.py: _preamble` was fixed for — that fix never reached here, so the
    "answer to the user never writes a prompt" (CLAUDE.md) was itself leaking the pilot
    org's own region into every other nonprofit's program card. An empty field is passed
    through as an empty field, the same rule `_preamble` follows: a guessed region is the
    thing that broke this, not a missing one.
    """
    who = f"{org_name.strip()}, a nonprofit" if org_name.strip() else "a nonprofit"
    if org_location.strip():
        who += f" working in {org_location.strip()}"

    return f"""\
You are helping the COO of {who}, set up a search for grant funding for one of the \
org's own programs.

You will be given the text of a page from the org's own website describing one program.
Turn it into a card that a grant-search agent can use.

Write for FUNDERS, not for the org. The keywords and search queries you produce are used
to match against foundation and government funding pages, so they must use the language
those funders use to describe what they fund — "BIPOC leadership development",
"creative placemaking", "behavioral health workforce" — not the org's internal names for
things.

Rules:
- Use only what is on the page you are given. You are not being asked what you know
  about the organization; you are being asked what this page says.
- If the page does not support a field, leave it empty and name that field in
  `fields_missing`. An empty field the COO can fill in is useful. An invented one is
  worse than useless, because they have no way to tell it apart from a real one.
- `summary` is one or two plain sentences they would recognise as their own program.
- `keywords` are the phrases a matching funder would use. 5-10 of them.
- `search_queries` are 3-5 complete searches, each one specific enough to return
  funders rather than articles. Vary the ANGLE of each query rather than restating the
  same phrase with a different verb — one aimed at government or public funding
  databases, one at named foundations or funder networks, one using a practice term
  unique to THIS program (not one that would fit equally well on this organisation's
  other programs), and one using a geography or funder-size qualifier if the page
  states one. Two queries that would return the same ten results are one query, not two.
- `funder_types` are the kinds of organisation that fund this sort of work.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "The program's name, as the page gives it."},
        "summary": {"type": "string", "description": "One or two plain sentences."},
        "what_it_funds": {
            "type": "string",
            "description": "What money for this program would actually pay for.",
        },
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "5-10 funder-facing phrases.",
        },
        "funder_types": {
            "type": "array",
            "items": {"type": "string",
                      "enum": ["private_foundation", "corporate", "community",
                               "government", "public_agency", "other"]},
        },
        "search_queries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-5 complete searches aimed at funders.",
        },
        "fields_missing": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Fields the page did not support. Be honest and specific.",
        },
        "page_confidence": {
            "type": "integer",
            "description": "0-100: how much this page actually described the program. "
                           "A nav page or a stub should score low.",
        },
    },
    "required": ["name", "summary", "what_it_funds", "keywords", "funder_types",
                 "search_queries", "fields_missing", "page_confidence"],
    "additionalProperties": False,
}


class AssistantError(RuntimeError):
    """Something the dashboard should show to the user in plain language."""


async def fetch_page_text(url: str) -> tuple[str, str]:
    """(title, text) for a URL, using the pipeline's own fetcher and parser.

    Reusing them rather than writing a second fetch path means the assistant obeys the
    same robots.txt, timeouts and politeness delays the crawl does. The org's own site is
    still someone's website.
    """
    from agent.fetch import Fetcher
    from agent.parse import parse_page

    async with Fetcher() as fetcher:
        result = await fetcher.get(url)

    if not result.ok:
        # A blocked address is a different conversation from a broken link, and the
        # person on the other end is a nonprofit administrator, not an attacker: say
        # plainly what the rule is instead of echoing "blocked_url: ... link-local ...".
        if (result.error or "").startswith(("blocked_url", "blocked_redirect")):
            raise AssistantError(
                "That link does not point at a public website, so Fundworthy will not "
                "open it. Paste the address of a page you can reach in your own browser."
            )
        raise AssistantError(
            f"Could not read that page ({result.error or result.status}). "
            "Check the link and try again."
        )
    page = parse_page(result.final_url or url, result.html or "")
    if len(page.text) < 200:
        raise AssistantError(
            "That page had almost no readable text — it may be built with JavaScript. "
            "Try a different link, or fill the card in by hand."
        )
    return page.title, page.text


async def draft_program_card(url: str, api_key: str | None = None, *,
                             org_name: str = "", org_location: str = "") -> dict:
    """Read `url` and return a DRAFT card. Never saves anything."""
    if not url.startswith(("http://", "https://")):
        raise AssistantError("That does not look like a web address.")
    if not api_key:
        raise AssistantError(
            "No Claude API key is saved yet. Add one on the Settings page and the "
            "assistant will be able to read the page for you."
        )

    title, text = await fetch_page_text(url)

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    body = (f"Page title: {title}\nURL: {url}\n\n{text[:PAGE_TEXT_CAP]}")

    try:
        resp = client.messages.create(
            model=ASSISTANT_MODEL,
            max_tokens=ASSISTANT_MAX_TOKENS,
            system=_system(org_name, org_location),
            messages=[{"role": "user", "content": body}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        )
    except anthropic.AuthenticationError as exc:
        raise AssistantError("That API key was rejected. Check it on the Settings page.") from exc
    except anthropic.APIStatusError as exc:
        raise AssistantError(f"Claude could not be reached ({exc.status_code}).") from exc

    data = _first_json(resp)
    cost = _cost(resp.usage.input_tokens, resp.usage.output_tokens)

    draft = {
        "name": str(data.get("name") or title)[:200],
        "summary": str(data.get("summary", "")),
        "what_it_funds": str(data.get("what_it_funds", "")),
        "keywords": [str(k)[:80] for k in (data.get("keywords") or [])][:12],
        "funder_types": list(data.get("funder_types") or []),
        "search_queries": [str(q)[:200] for q in (data.get("search_queries") or [])][:6],
        "source_url": url,
        "drafted_by_ai": True,
        "reviewed_by_human": False,
        # Surfaced in the UI so the draft arrives with its own caveats attached rather
        # than looking uniformly confident.
        "fields_missing": list(data.get("fields_missing") or []),
        "page_confidence": int(data.get("page_confidence") or 0),
        "usd_spent": round(cost, 5),
    }
    log.info("assistant drafted %r from %s ($%.5f, confidence %s)",
             draft["name"], url, cost, draft["page_confidence"])
    return draft


def _first_json(response) -> dict:
    for block in response.content:
        if block.type == "text":
            return json.loads(block.text)
    raise AssistantError("Claude returned an unreadable response. Try again.")


def _cost(in_tok: int, out_tok: int) -> float:
    """Sonnet 4.6 standard rates — $3/M in, $15/M out."""
    return (in_tok * 3.00 + out_tok * 15.00) / 1_000_000
