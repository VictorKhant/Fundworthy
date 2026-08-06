"""Is a shared funder's page real, reachable, and plausibly about grants.

Runs before a hand-added funder is offered to another nonprofit. Three deliberate
limits, because the gap between what this can establish and what somebody reading the
result will assume is where the harm lives:

  1. **No model is involved and nothing is spent.** This is the existing polite fetcher
     and the existing parser. Asking Sonnet "is this a real funder?" would cost the
     contributing org money to answer a question it cannot actually answer.
  2. **It produces evidence, never a verdict.** "Reached on 5 August; the page mentions
     award amounts and a deadline" is a fact. "Verified funder" is a claim about whether
     somebody should spend a week writing to them, and nothing here knows that. The
     Discover page shows the sentence and the link, not a tick.
  3. **Failing is disqualifying; passing is not qualifying.** A page that will not load
     is kept out of the pool, because a dead link wastes the next person's time for
     certain. A page that loads is merely allowed to be offered, clearly labelled as
     somebody else's suggestion.

The strongest signal available is not here: a funder that a *real weekly crawl* fetched
successfully has been proven live by an actual search rather than a one-off ping. That
lives in `runs.source_health` and would be a good second source for this field later.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# Words a grants page has and a homepage generally does not. Deliberately coarse — this
# is one input to "plausibly about grants", not a classifier, and a funder whose page is
# unusually worded should fail into "we could not tell", not into "fake".
_GRANTY = re.compile(
    r"\b(grant|grants|funding|fund|apply|application|applicant|eligib\w+|award|"
    r"proposal|rfp|solicitation|deadline|letter of inquiry|loi)\b", re.IGNORECASE)

MIN_TEXT = 400        # below this there is no page to judge, only a shell

# How much evidence before we will call it a grants page.
PASS_MARK = 3


def _stem(word: str) -> str:
    """grant/grants, award/awards, application/applications → one term.

    The first version counted distinct *surface forms* and wanted three of them, which
    rejected the MacArthur Foundation's grant-search page: 3,116 characters of text whose
    grant vocabulary was "grant" and "grants". Two strings, one word, and a page titled
    "Grant Search" was told it did not look like it was about grants. Counting plurals as
    separate concepts also rewarded rambling pages over focused ones, which is backwards.
    """
    return word.lower().rstrip("s") if len(word) > 3 else word.lower()


def _grant_evidence(page, url: str) -> tuple[int, bool]:
    """(how strongly this reads as a grants page, is it plausibly a homepage).

    A weighted read rather than a word count, because the three strongest signals are
    not in the body text at all — the page title, the address, and whether the parser
    could pull a real award amount or deadline off it. A page called "Grant Search" at
    `/grants` that states a figure is a grants page whatever its prose does.
    """
    title = (page.title or "").lower()
    terms = {_stem(m.group(0)) for m in _GRANTY.finditer(page.text)}
    hits = len(_GRANTY.findall(page.text))

    score = 0
    if _GRANTY.search(title):
        score += 2                       # they named the page after it
    if re.search(r"grant|funding|apply|rfp|solicitation", url, re.IGNORECASE):
        score += 2                       # and the address agrees
    score += min(len(terms), 3)          # vocabulary breadth, capped
    if hits >= 5:
        score += 1                       # and it keeps coming up
    if page.award_max is not None or page.earliest_deadline is not None:
        score += 2                       # the parser found a real figure or date

    # A funder's front door: their name in the title, little grant vocabulary, no
    # numbers. Worth its own message — the fix is to link the grants page, not to give up.
    homepage = score < PASS_MARK and bool(terms) and not re.search(
        r"grant|funding|apply|rfp|solicitation", url, re.IGNORECASE)
    return score, homepage


def _why_it_failed(error: str | None, status: int | None) -> str:
    """A reason a nonprofit administrator can act on.

    This sentence is shown to the person who added the funder, and its whole job is to
    tell them what to do next. The raw value is a Python exception repr — the first draft
    of this feature printed *"That page did not load (ConnectError: [SSL:
    CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired
    (_ssl.c:1006))"*, which is accurate, actionable by nobody, and exactly the register
    CLAUDE.md's binding constraint rules out.

    Unrecognised failures keep the raw text rather than being flattened into "something
    went wrong": a reason we have not seen before is more useful ugly than absent, and it
    is how the next case gets added to this list.
    """
    text = (error or "").lower()

    if "robots_disallowed" in text:
        return "That site asks not to be read automatically, so we cannot check it."
    if "certificate" in text or "ssl" in text:
        return ("That page's security certificate has expired or is invalid — a browser "
                "would warn about it too. It is the site's problem to fix, not yours.")
    if "could not look up" in text or "nodename" in text or "name or service" in text:
        return "That web address does not exist. Check it for a typo."
    if "timeout" in text or "timed out" in text:
        return "That page took too long to answer. It may be temporarily down."
    if "connect" in text or "refused" in text:
        return "Nothing answered at that address."
    if "too_many_redirects" in text:
        return "That address keeps redirecting and never arrives anywhere."
    if "unreadable_content_type" in text:
        return "That link is a file rather than a web page — link to the page instead."
    if "blocked_url" in text or "blocked_redirect" in text:
        return "That address is not a public website, so we will not open it."
    if status == 404 or "http_404" in text:
        return "That page is not there any more. The funder may have moved it."
    if status == 403 or "http_403" in text:
        return "That site refused to let us read the page."
    if status and 500 <= status < 600:
        return "That site returned an error. It may be temporarily broken."

    return f"That page did not load when we last looked ({error or status})."


async def check_page(url: str | None) -> tuple[bool, str]:
    """(is it usable, one sentence saying why) for a funder's grants page.

    Never raises. Every failure is a reason string, because this runs in the background
    over somebody else's website and a transient DNS blip must not become an exception
    in a request handler.
    """
    if not url or not url.strip():
        return False, "No web address on file, so there is nothing for anyone to open."

    from agent.fetch import Fetcher
    from agent.parse import parse_page

    try:
        async with Fetcher() as fetcher:
            result = await fetcher.get(url.strip())
    except Exception as exc:  # noqa: BLE001 — a broken host is a result, not a crash
        log.debug("funder check could not fetch %s: %r", url, exc)
        return False, "That page could not be opened when we last looked."

    if not result.ok:
        return False, _why_it_failed(result.error, result.status)

    try:
        page = parse_page(result.final_url or url, result.html or "")
    except Exception:  # noqa: BLE001
        return False, "That page loaded but could not be read."

    if len(page.text) < MIN_TEXT:
        return False, "That page has almost nothing on it."

    score, looks_like_a_homepage = _grant_evidence(page, result.final_url or url)
    if score < PASS_MARK:
        if looks_like_a_homepage:
            return False, ("That looks like the funder's front page rather than their "
                           "grants page. Link the page that lists what they fund.")
        return False, "That page does not look like it is about grants."

    # What we can honestly say, in the order somebody would want to hear it.
    facts = []
    if page.award_max:
        facts.append("names an award amount")
    if page.earliest_deadline:
        facts.append("names a deadline")
    detail = ", and ".join(facts) if facts else "mentions grants and how to apply"
    return True, f"The page opened and {detail}."


async def recheck_shared(conn_factory, org_id: str, limit: int = 25) -> int:
    """Check this org's unchecked hand-added funders. Returns how many were looked at.

    Bounded, because it walks other people's websites one request at a time. Takes a
    connection *factory* rather than a connection: it is called from a background thread
    and each write should be its own short transaction, not one held open across a series
    of network calls.
    """
    with conn_factory() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, name, url FROM funders "
            "WHERE org_id=? AND added_by='user' AND checked_at IS NULL LIMIT ?",
            (org_id, limit))]

    from .db import now_iso

    for row in rows:
        ok, note = await check_page(row["url"])
        with conn_factory() as conn:
            conn.execute(
                "UPDATE funders SET check_ok=?, check_note=?, checked_at=? "
                "WHERE org_id=? AND id=?",
                (1 if ok else 0, note, now_iso(), org_id, row["id"]))
        log.info("funder check %s (%s): %s", row["name"], "ok" if ok else "no", note)
    return len(rows)
