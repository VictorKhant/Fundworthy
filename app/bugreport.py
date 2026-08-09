"""Filing a bug report as a GitHub issue on the project's own repo. (CLAUDE.md)

This is an operational/support channel the deployer owns, not a per-org feature —
exactly the same shape as `FUNDWORTHY_SHEET_ID` or `FUNDWORTHY_ADMIN_EMAILS`. So the
GitHub credentials it uses live in the install's own environment, never in an org's
encrypted settings row: a nonprofit reporting that a page is broken has no business
supplying (or needing) a GitHub token, and letting one org's key file bugs against the
upstream repo would be the exact per-org-secret mistake the Anthropic key is careful
not to make.

Deliberately no default repo. A fork of this app that never set
`FUNDWORTHY_GITHUB_REPO` must never silently file issues against the upstream
project's tracker on somebody else's behalf.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Filing a real GitHub issue has a human cost — somebody has to read and triage it —
# unlike a metered API call whose only cost is money. So this is a hard cap, not a
# configurable setting the way run_budget_usd is.
MAX_REPORTS_PER_ORG_PER_DAY = 10


class BugReportError(Exception):
    """Something the dashboard should show to the user in plain language."""


async def file_github_issue(title: str, body: str) -> dict:
    """File one issue on the install's configured GitHub repo.

    Reads `FUNDWORTHY_GITHUB_TOKEN` and `FUNDWORTHY_GITHUB_REPO` fresh from the
    environment on every call rather than caching them at import time, so a token
    rotated or a repo reconfigured on a running install takes effect on the next
    report without a restart.
    """
    token = os.environ.get("FUNDWORTHY_GITHUB_TOKEN", "").strip()
    repo = os.environ.get("FUNDWORTHY_GITHUB_REPO", "").strip()
    if not token or not repo:
        raise BugReportError(
            "GitHub issue filing is not set up on this install. Ask whoever runs it "
            "to set FUNDWORTHY_GITHUB_TOKEN and FUNDWORTHY_GITHUB_REPO."
        )

    import httpx

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.github.com/repos/{repo}/issues",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={"title": title, "body": body, "labels": ["user-reported"]},
                timeout=10.0,
            )
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        raise BugReportError(
            "Could not reach GitHub — the network may be down, or GitHub may be "
            "having an outage."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise BugReportError(str(exc)) from exc

    if response.status_code == 201:
        # Parsing the "success" response can still fail — a malformed or truncated
        # body from a proxy glitch, or a shape GitHub's own docs don't lead you to
        # expect — and that must degrade the same way every other failure here does,
        # not escape as a raw exception that turns the graceful filed:false outcome
        # into an unhandled 500 on the one response branch nobody thought to guard.
        try:
            data = response.json()
            return {"issue_url": data["html_url"], "issue_number": data["number"]}
        except Exception as exc:  # noqa: BLE001
            raise BugReportError(
                "GitHub said the issue was created, but its response could not be "
                f"read ({type(exc).__name__})."
            ) from exc

    if response.status_code == 404:
        message = ("The configured GitHub repo could not be found. Check "
                   "FUNDWORTHY_GITHUB_REPO.")
    elif response.status_code in (401, 403):
        message = "The GitHub token was rejected. Check FUNDWORTHY_GITHUB_TOKEN."
    elif response.status_code == 422:
        message = ("GitHub rejected the request (validation failed, or the repo is "
                   "rate-limited).")
    elif response.status_code == 410:
        message = "Issues are disabled on the configured GitHub repo."
    else:
        message = f"GitHub returned {response.status_code}."
    raise BugReportError(message)


def format_issue_body(description: str, *, org_name: str, org_id: str, reporter: str,
                      page: str, user_agent: str) -> str:
    """The markdown body filed alongside the title.

    The user's own words come first, verbatim — a maintainer reading the issue reads
    their report before anything else. Everything after the rule is plain identifying
    context for follow-up: never anything from Settings or an API key, which have no
    business leaving the org's own database.
    """
    reporter_label = reporter if reporter and reporter != "local" \
        else "local install, no sign-in"
    return (
        f"{description}\n\n"
        "---\n\n"
        "**Reported from Fundworthy**\n\n"
        f"- Org: {org_name.strip() or '(unnamed)'} (`{org_id}`)\n"
        f"- Reported by: {reporter_label}\n"
        f"- Page: {page or '(not given)'}\n"
        f"- User agent: {user_agent or '(not given)'}\n"
        f"- Time (UTC): {datetime.now(timezone.utc).isoformat()}\n"
    )
