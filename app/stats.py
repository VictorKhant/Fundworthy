"""How the whole install is doing, from a terminal.

    .venv/bin/python -m app.stats            # readable
    .venv/bin/python -m app.stats --json     # for a script

The same numbers as `GET /api/admin/stats`, without the Firebase ID token that endpoint
needs. That is the point: getting a bearer token means opening the browser's dev tools,
finding the request, and copying a JWT that expires in an hour — a miserable way to
answer "how many orgs signed up this week", and one you will do wrong at 2am.

**Its authentication is the SSH session.** Anyone who can run this can already read
`data/rise.db` directly, so requiring a token here would guard nothing while making the
ordinary case painful. The HTTP endpoint has a real gate because it is reachable from the
internet; this is not.
"""

from __future__ import annotations

import argparse
import json

from . import repo
from .db import session


def _bar(value: int, total: int, width: int = 24) -> str:
    if total <= 0:
        return ""
    filled = round(width * value / total)
    return "█" * filled + "·" * (width - filled)


def render(s: dict) -> str:
    lines = [
        "",
        "  Fundworthy — how it is going",
        "  " + "─" * 46,
        "",
        f"  Organizations          {s['orgs']:>6}",
        f"  People                 {s['users']:>6}",
        f"  Active in last 7 days  {s['orgs_active_7d']:>6}   "
        f"{_bar(s['orgs_active_7d'], s['orgs'])}",
        "",
        # The number that separates a product from a demo. Everything before it is
        # somebody looking; this is somebody committing their own money.
        f"  With their own API key {s['orgs_with_own_key']:>6}   "
        f"{_bar(s['orgs_with_own_key'], s['orgs'])}",
        "",
        f"  Searches (30 days)     {s['runs_30d']:>6}",
    ]
    for status, n in sorted(s["runs_by_status_30d"].items()):
        lines.append(f"    {status:<20} {n:>6}")
    lines += [
        f"  Spent (30 days)      ${s['spend_30d_usd']:>8.2f}   (their credit, not ours)",
        "",
        f"  Findings in {s['month']}     {s['findings_this_month']:>6}",
        f"    needing a human check {s['findings_needing_check']:>6}   "
        f"{_bar(s['findings_needing_check'], s['findings_this_month'])}",
    ]
    if s["findings_this_month"]:
        share = s["findings_needing_check"] / s["findings_this_month"]
        if share > 0.5:
            # Worth flagging out loud: this is the accuracy gate nulling fields it could
            # not verify, and a rising share is the product getting less trustworthy —
            # which no single org's dashboard would ever show you.
            lines.append(
                f"    ⚠ {share:.0%} unverified — check whether funder pages changed shape")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Platform statistics for this install.")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args()

    with session() as conn:
        stats = repo.platform_stats(conn)

    print(json.dumps(stats, indent=2) if args.json else render(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
