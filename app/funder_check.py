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
        # The distinction is worth keeping: "we are not allowed to read it" is not the
        # same as "it is not there", and only one of them suggests the link is wrong.
        if result.error == "robots_disallowed":
            return False, "That site asks not to be read automatically."
        return False, f"That page did not load when we last looked ({result.error or result.status})."

    try:
        page = parse_page(result.final_url or url, result.html or "")
    except Exception:  # noqa: BLE001
        return False, "That page loaded but could not be read."

    if len(page.text) < MIN_TEXT:
        return False, "That page has almost nothing on it."

    hits = len(set(m.group(0).lower() for m in _GRANTY.finditer(page.text)))
    if hits < 3:
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
