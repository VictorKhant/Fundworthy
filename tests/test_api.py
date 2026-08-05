"""The FastAPI control surface. Offline — no network, no API key, no model calls.

The tests that matter most here are the negative ones. A CRUD endpoint that works is
obvious the first time anyone clicks it; a settings page that quietly returns the API
key in a JSON blob is not, and that is exactly the kind of thing that only gets noticed
after it has been shared.

    .venv/bin/python -m pytest tests/test_api.py -q
"""

from __future__ import annotations

import os

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.helpers import (seed_starter_funders,  # noqa: E402
                           seed_starter_programs)

from app import secrets
from app.db import DEFAULT_ORG_ID, init_db, session

FAKE_KEY = "sk-ant-api03-THIS-IS-NOT-A-REAL-KEY-0000000000-4f2a"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FUNDWORTHY_DB_PATH", str(tmp_path / "rise.db"))
    monkeypatch.setenv("FUNDWORTHY_KEYFILE", str(tmp_path / ".fernet-key"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    init_db()
    seed_starter_funders()
    seed_starter_programs()

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


# --- the whole-dashboard call -------------------------------------------------

def test_state_returns_everything_the_dashboard_needs(client):
    body = client.get("/api/state").json()
    for key in ("settings", "programs", "funders", "clear", "needs_check",
                "sectors_available", "month", "has_api_key"):
        assert key in body, f"/api/state is missing {key}"
    assert body["settings"]["min_award"] == 10_000
    assert len(body["programs"]) == 7
    assert body["has_api_key"] is False


# --- settings -----------------------------------------------------------------

def test_settings_round_trip(client):
    r = client.put("/api/settings", json={
        "min_award": 15000, "max_opportunities": 8,
        "sectors_active": ["warm_partner", "government"],
    })
    assert r.status_code == 200
    s = r.json()["settings"]
    assert s["min_award"] == 15000
    assert s["max_opportunities"] == 8
    assert s["sectors_active"] == ["warm_partner", "government"]


def test_partial_update_leaves_other_settings_alone(client):
    client.put("/api/settings", json={"min_award": 15000})
    client.put("/api/settings", json={"max_opportunities": 5})
    s = client.get("/api/settings").json()["settings"]
    assert s["min_award"] == 15000, "editing one knob must not reset the others"
    assert s["max_opportunities"] == 5


def test_unknown_sector_is_rejected(client):
    r = client.put("/api/settings", json={"sectors_active": ["nonsense"]})
    assert r.status_code == 400
    assert "nonsense" in r.json()["detail"]


def test_out_of_range_settings_are_rejected(client):
    assert client.put("/api/settings", json={"run_budget_usd": 500}).status_code == 422
    assert client.put("/api/settings", json={"min_award": -5}).status_code == 422
    assert client.put("/api/settings", json={"max_opportunities": 0}).status_code == 422


# --- the API key: the tests that matter ---------------------------------------

def test_api_key_is_never_returned_by_any_endpoint(client):
    """The whole point of the write-only design. If this ever fails, the key is one
    screenshot or one shared JSON file away from being public."""
    client.post("/api/settings/api-key", json={"api_key": FAKE_KEY})

    for path in ("/api/settings", "/api/state", "/api/programs", "/api/funders",
                 "/api/runs", "/api/opportunities", "/api/archive"):
        raw = client.get(path).text
        assert FAKE_KEY not in raw, f"{path} leaked the API key"
        assert "THIS-IS-NOT-A-REAL-KEY" not in raw, f"{path} leaked part of the key"


def test_saving_a_key_returns_only_a_masked_hint(client):
    body = client.post("/api/settings/api-key", json={"api_key": FAKE_KEY}).json()
    assert body["has_api_key"] is True
    assert body["api_key_hint"] == "sk-ant-…4f2a"
    assert FAKE_KEY not in str(body)


def test_key_is_not_stored_in_plaintext_on_disk(client, tmp_path):
    client.post("/api/settings/api-key", json={"api_key": FAKE_KEY})

    blob = (tmp_path / "rise.db").read_bytes()
    assert FAKE_KEY.encode() not in blob, "the key is sitting in the database in plaintext"

    with session() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='anthropic_api_key'").fetchone()
    assert row["value"] and FAKE_KEY not in row["value"]


def test_key_round_trips_for_server_side_use(client):
    """Encrypted at rest, but the pipeline still has to be able to use it."""
    client.post("/api/settings/api-key", json={"api_key": FAKE_KEY})
    with session() as conn:
        assert secrets.read_api_key(conn, org_id=DEFAULT_ORG_ID) == FAKE_KEY


def test_deleting_the_key_clears_it(client):
    client.post("/api/settings/api-key", json={"api_key": FAKE_KEY})
    body = client.delete("/api/settings/api-key").json()
    assert body["has_api_key"] is False
    with session() as conn:
        assert secrets.read_api_key(conn, org_id=DEFAULT_ORG_ID) is None


def test_a_corrupt_stored_key_degrades_instead_of_crashing(client, tmp_path):
    """A rotated or truncated key file must mean 'please paste it again', not a 500 on
    every request the dashboard makes."""
    client.post("/api/settings/api-key", json={"api_key": FAKE_KEY})
    (tmp_path / ".fernet-key").unlink()

    r = client.get("/api/settings")
    assert r.status_code == 200
    assert r.json()["has_api_key"] is False


def test_test_endpoint_reports_no_key_without_calling_out(client):
    body = client.post("/api/settings/api-key/test").json()
    assert body["ok"] is False
    assert "No API key" in body["message"]


def test_test_endpoint_accepts_an_empty_body(client):
    """Regression: "check the key I already saved" sends `{}`, and declaring the body
    as `ApiKeyIn | None` still validated it against a required field — so the button
    422'd instead of testing the stored key."""
    r = client.post("/api/settings/api-key/test", json={})
    assert r.status_code == 200
    assert r.json()["ok"] is False  # nothing saved in this fixture


# --- programs -----------------------------------------------------------------

def test_program_crud_through_the_api(client):
    created = client.post("/api/programs", json={
        "name": "RISE Consult", "summary": "Advisory", "active": True,
        "keywords": ["capacity building"], "min_award": 5000,
    })
    assert created.status_code == 201
    pid = created.json()["program"]["id"]

    updated = client.put(f"/api/programs/{pid}", json={"summary": "Edited by the user"})
    assert updated.json()["program"]["summary"] == "Edited by the user"
    assert updated.json()["program"]["keywords"] == ["capacity building"], \
        "a partial edit must not wipe the rest of the card"

    assert client.delete(f"/api/programs/{pid}").status_code == 200
    assert client.put(f"/api/programs/{pid}", json={"summary": "x"}).status_code == 404


def test_program_without_a_name_is_rejected(client):
    assert client.post("/api/programs", json={"summary": "nameless"}).status_code == 400


def test_ticking_a_program_changes_what_the_run_would_search(client):
    """The tick is the whole activation mechanism, so it has to reach the config the
    pipeline reads — not just the row in the table."""
    from agent.config import load_from_db

    before = load_from_db()
    assert sorted(before.programs_active) == ["ARTS", "RESILIENCE", "RULFP"]

    ilia = next(p for p in client.get("/api/programs").json()["programs"]
                if p["slug"] == "ILIA")
    client.put(f"/api/programs/{ilia['id']}", json={"active": True})

    after = load_from_db()
    assert "ILIA" in after.programs_active


def test_per_program_floor_lowers_the_crawl_filter(client):
    """A program with a lower floor must not have its opportunities filtered out by
    the global one before program-aware scoring ever sees them."""
    from agent.config import load_from_db

    arts = next(p for p in client.get("/api/programs").json()["programs"]
                if p["slug"] == "ARTS")
    client.put(f"/api/programs/{arts['id']}", json={"min_award": 5000})

    cfg = load_from_db()
    assert cfg.min_award == 10_000
    assert cfg.effective_min_award == 5_000


def test_draft_without_a_key_says_so_in_plain_language(client):
    r = client.post("/api/programs/draft",
                    json={"url": "https://www.risesandiego.org/programs/ilia"})
    assert r.status_code == 400
    assert "API key" in r.json()["detail"]


def test_draft_rejects_a_non_url(client):
    r = client.post("/api/programs/draft", json={"url": "just some words"})
    assert r.status_code == 400


# --- funders ------------------------------------------------------------------

def test_funder_crud_and_deactivation(client):
    funders = client.get("/api/funders").json()["funders"]
    assert len(funders) >= 8

    target = next(f for f in funders if f["warm"])
    client.put(f"/api/funders/{target['id']}", json={"active": False})

    after = {f["id"]: f for f in client.get("/api/funders").json()["funders"]}
    assert after[target["id"]]["active"] is False, "deactivated"
    assert target["id"] in after, "but still on the list — the relationship is a record"


def test_adding_a_funder(client):
    r = client.post("/api/funders", json={
        "name": "Some New Foundation", "url": "https://example.invalid/grants",
        "sector": "foundation", "warm": False,
    })
    assert r.status_code == 201
    assert r.json()["funder"]["name"] == "Some New Foundation"


def test_deleting_a_missing_funder_is_404(client):
    assert client.delete("/api/funders/nope").status_code == 404


# --- runs ---------------------------------------------------------------------

def test_run_history_starts_empty(client):
    assert client.get("/api/runs").json()["runs"] == []


def test_current_run_reports_idle(client):
    body = client.get("/api/runs/current").json()
    assert body["running"] is False


def test_the_kill_switch_blocks_the_rerun_button(client):
    """§8's kill switch, enforced at the button as well as in the pipeline."""
    client.put("/api/settings", json={"enabled": False})
    r = client.post("/api/runs", json={"no_llm": True})
    assert r.status_code == 409
    assert "switched off" in r.json()["detail"]


def test_archive_endpoint_shape(client):
    body = client.get("/api/archive").json()
    assert "current_month" in body and "months_available" in body


# --- which key is actually in play -------------------------------------------
#
# A .env on the machine makes the pipeline score whether or not Settings holds
# anything, so "no key saved" and "no key anywhere" are different states that used to
# render identically. The page would say no key was saved while the run scored happily.

ENV_KEY = "sk-ant-api03-FROM-THE-ENVIRONMENT-NOT-REAL-1aAa"


def test_reports_settings_as_the_source_when_a_key_is_saved(client):
    client.post("/api/settings/api-key", json={"api_key": FAKE_KEY})
    body = client.get("/api/settings").json()
    assert body["has_api_key"] is True
    assert body["key_available"] is True
    assert body["api_key_source"] == "settings"
    assert body["env_key_hint"] is None


def test_reports_the_environment_when_nothing_is_saved(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", ENV_KEY)
    body = client.get("/api/settings").json()
    assert body["has_api_key"] is False, "nothing is saved in Settings"
    assert body["key_available"] is True, "but the pipeline can still score"
    assert body["api_key_source"] == "environment"
    assert body["env_key_hint"] == "sk-ant-…1aAa"
    assert ENV_KEY not in client.get("/api/settings").text


def test_settings_wins_over_the_environment(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", ENV_KEY)
    client.post("/api/settings/api-key", json={"api_key": FAKE_KEY})

    assert client.get("/api/settings").json()["api_key_source"] == "settings"
    with session() as conn:
        assert secrets.effective_api_key(conn) == FAKE_KEY


def test_no_key_anywhere_is_its_own_state(client):
    body = client.get("/api/state").json()
    assert body["has_api_key"] is False
    assert body["key_available"] is False
    assert body["api_key_source"] is None


def test_deleting_the_saved_key_admits_the_environment_still_scores(client, monkeypatch):
    """Otherwise Remove looks like it stopped the agent scoring when it did not."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", ENV_KEY)
    client.post("/api/settings/api-key", json={"api_key": FAKE_KEY})

    body = client.delete("/api/settings/api-key").json()
    assert body["has_api_key"] is False
    assert body["key_available"] is True
    assert body["api_key_source"] == "environment"


# --- the remove list ----------------------------------------------------------
#
# The stakeholder does not want opportunities from funders the organization already receives money
# from — they get the cheque without reapplying. So warmth stopped being a priority
# signal and became a reason to EXCLUDE, and the exclusion happens in the Python stage
# where it costs nothing.

def test_removing_a_funder_records_why(client):
    funders = client.get("/api/funders").json()["funders"]
    target = funders[0]
    client.put(f"/api/funders/{target['id']}",
               json={"active": False,
                     "exclude_reason": "We already receive funding from them"})

    after = {f["id"]: f for f in client.get("/api/funders").json()["funders"]}
    assert after[target["id"]]["active"] is False
    assert after[target["id"]]["exclude_reason"] == "We already receive funding from them"
    assert target["id"] in after, "removed from the search, not from the record"


def test_an_excluded_funder_is_never_fetched(client):
    """Cheap half of the remove list: it never enters the source registry at all."""
    from agent.sources import Tier, sources_from_db

    before, _ = sources_from_db(Tier.GOVERNMENT, [])
    target = next(f for f in client.get("/api/funders").json()["funders"] if f["url"])
    client.put(f"/api/funders/{target['id']}", json={"active": False})

    after, _ = sources_from_db(Tier.GOVERNMENT, [])
    assert len(after) == len(before) - 1
    assert target["name"] not in {s.funder for s in after}


def test_an_excluded_funder_is_also_dropped_from_indexed_results(client):
    """The other door. The public databases carry grants from every funder in the
    state, so an excluded funder can still arrive via Grants.gov or the CA portal
    unless we drop it on the way in."""
    from agent.run import excluded_funders

    target = client.get("/api/funders").json()["funders"][0]
    client.put(f"/api/funders/{target['id']}", json={"active": False})

    assert target["name"].casefold() in excluded_funders(DEFAULT_ORG_ID)


def test_warmth_no_longer_orders_the_funder_list(client):
    """'Partner first' was the ordering the stakeholder asked us to drop."""
    names = [f["name"] for f in client.get("/api/funders").json()["funders"]]
    assert names == sorted(names, key=str.casefold)


def test_stopping_a_run_is_not_recorded_as_a_failure():
    """Pressing Stop sends SIGTERM, so the child exits with a negative code. The pump
    thread reached _finalize before stop() could mark the row, and a run the user ended
    deliberately reported "failed (exit -15)". Decided from the exit code now, so there
    is no race to lose."""
    from app.db import init_db, session
    from app.runner import RunManager
    from app import repo

    init_db()
    seed_starter_funders()
    seed_starter_programs()
    with session() as conn:
        run_id = repo.create_run(conn, org_id=DEFAULT_ORG_ID)

    RunManager()._finalize(run_id, -15)          # SIGTERM
    with session() as conn:
        run = repo.get_run(conn, run_id)
    assert run["status"] == "stopped"
    assert run["stop_reason"] == "stopped_by_user"
    assert run["progress"]["message"] == "Stopped by you."


def test_a_real_crash_is_still_recorded_as_a_failure(client):
    from app.runner import RunManager
    from app import repo
    from app.db import session

    with session() as conn:
        run_id = repo.create_run(conn, org_id=DEFAULT_ORG_ID)
    RunManager()._finalize(run_id, 1)            # non-zero, not a signal
    with session() as conn:
        run = repo.get_run(conn, run_id)
    assert run["status"] == "failed"
    assert run["stop_reason"] == "exit_1"


# --- the suite must not inherit the machine it runs on --------------------------

def test_the_environment_is_hermetic():
    """A regression guard with a real deploy behind it.

    `agent/__init__.py` calls `load_dotenv()` at import time, so importing anything from
    `agent` pulls the box's own `.env` into `os.environ`. On the deployed VM that file
    sets FIREBASE_PROJECT_ID and ALLOWED_EMAILS — so sign-in switched on mid-test-run and
    37 API tests failed with 401s that had nothing to do with the code under test. The
    suite passed where it was written and failed where it mattered, which is the one
    thing a deploy gate must never do.

    `FUNDWORTHY_DB_PATH` is the sharp one: inherited from a real `.env`, a test calling
    `init_db()` before setting its own path would have migrated the live database.
    """
    import agent  # noqa: F401 — the import is the thing being tested

    for name in ("FIREBASE_PROJECT_ID", "FIREBASE_WEB_API_KEY", "ALLOWED_EMAILS",
                 "ANTHROPIC_API_KEY"):
        assert os.environ.get(name) is None, (
            f"{name} leaked in from the environment — see tests/conftest.py")

    # Pointed somewhere disposable, never at whatever `data/rise.db` resolves to.
    assert "rise.db" not in os.environ.get("FUNDWORTHY_DB_PATH", "")


def test_no_env_var_escapes_the_scrub():
    """Every variable the app reads must be in `conftest._LEAKY_ENV`.

    The list above is hand-maintained, and the failure mode when it falls behind is
    nasty: the suite keeps passing on a laptop, where none of those variables are set,
    and fails only on the VM, where `.env` sets them — which is to say it fails *as the
    deploy gate*, after a merge, on a change that was fine.

    That has now happened twice. `FIREBASE_PASSWORD_AUTH` was the second: a test
    asserting the password form is off by default passed everywhere except the one box
    that has it switched on. So rather than remember, read the source and compare.
    """
    import re
    from pathlib import Path

    from tests.conftest import _LEAKY_ENV

    root = Path(__file__).resolve().parents[1]
    pattern = re.compile(r'os\.(?:getenv|environ\.get)\(\s*"([A-Z][A-Z0-9_]+)"')

    read: set[str] = set()
    for package in ("app", "agent", "sinks"):
        for source in (root / package).rglob("*.py"):
            read |= set(pattern.findall(source.read_text()))

    missed = sorted(read - set(_LEAKY_ENV))
    assert not missed, (
        f"{', '.join(missed)} read by the app but not scrubbed in tests/conftest.py. "
        "Add them to _LEAKY_ENV, or the suite will pass here and fail on the VM."
    )


def test_sign_in_is_off_for_the_api_suite_whatever_the_box_thinks():
    from app import auth

    assert auth.enabled() is False


# --- the SPA catch-all must not answer for the API ------------------------------

def test_an_unknown_api_route_is_a_404_not_a_page_of_html(client):
    """The catch-all is registered last, so an API path that matches no route used to
    fall through to it and return 200 with index.html. Every failure mode of that is
    quiet: a caller cannot tell "gone" from "fine", curl reports success, and a stale
    deployment looks healthy — `GET /api/maintenance` answered 200 on a box that had
    never heard of that endpoint."""
    res = client.get("/api/definitely-not-a-real-route")
    assert res.status_code == 404
    assert "text/html" not in res.headers.get("content-type", "")


def test_a_real_page_route_still_serves_the_dashboard(client):
    """The fix must not break client-side routing, which is the reason the catch-all
    exists — /welcome and /signin are real URLs the SPA handles.

    Needs a built dashboard: `dist/` is gitignored and app/main.py only registers the
    catch-all when it exists, so in a fresh checkout /welcome is an honest 404 rather
    than a regression. CI builds the dashboard before running this, so a skip here means
    that build step is missing, not that the check is optional.
    """
    from app.main import DIST

    if not DIST.exists():
        pytest.skip("the dashboard has not been built in this checkout")
    res = client.get("/welcome")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")


def test_a_static_file_is_still_served_as_itself(client, tmp_path):
    """robots.txt and sitemap.xml live in dist/ and must come back as files rather than
    as the SPA fallback — a robots.txt that is secretly index.html is why the live site
    looked like it had been deployed when it had not."""
    from app.main import DIST

    if not DIST.exists():
        pytest.skip("the dashboard has not been built in this checkout")
    probe = DIST / "robots.txt"
    if not probe.exists():
        pytest.skip("no robots.txt in this build")
    res = client.get("/robots.txt")
    assert res.status_code == 200
    assert not res.text.lstrip().startswith("<!doctype")


def test_robots_lets_a_crawler_render_the_page_it_is_allowed_to_index():
    """`Disallow: /api/` blocked the app's own startup fetches, so the home page rendered
    as an error to Googlebot.

    A blocked XHR is not skipped, it fails: Google's renderer answers it with status 499,
    the app turns that into "Something went wrong (499)", and Search Console's live test
    showed that error screen as the home page while /welcome — which needs nothing from
    /api — rendered correctly. Allowing a page to be indexed while blocking what it needs
    to draw itself is the trap here.

    Resolved by Google's rule — the longest matching rule wins, ties go to Allow —
    and NOT with urllib.robotparser, which answers a different question. The stdlib
    parser takes the first matching rule, so `Allow: /` on the first line matches every
    path and it reports nothing as blocked: it called the old file's /api/auth/config
    crawlable, when Google was visibly blocking it. A test built on it would have passed
    both before and after the fix.
    """
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "dashboard" / "public" / "robots.txt"

    def google_allows(path: str) -> bool:
        longest_allow = longest_disallow = -1
        for line in source.read_text().splitlines():
            line = line.split("#")[0].strip()
            if ":" not in line:
                continue
            directive, _, value = line.partition(":")
            directive, value = directive.strip().lower(), value.strip()
            if not value or not path.startswith(value):
                continue
            if directive == "allow":
                longest_allow = max(longest_allow, len(value))
            elif directive == "disallow":
                longest_disallow = max(longest_disallow, len(value))
        return longest_allow >= longest_disallow

    for path in ("/", "/welcome", "/api/auth/config", "/api/maintenance"):
        assert google_allows(path), f"{path} must be crawlable — the page cannot render"

    # Still closed: these need a signed-in user, so a crawler gets 401 either way.
    for path in ("/api/state", "/api/settings", "/api/opportunities"):
        assert not google_allows(path), f"{path} must stay blocked"


def test_head_is_served_wherever_get_is(client):
    """HEAD is GET without the body, so a 405 where GET returns 200 is a protocol
    violation — and not a theoretical one. FastAPI does not add HEAD alongside GET the
    way a plain Starlette route does, so `HEAD /sitemap.xml` answered `405 Method Not
    Allowed` with `Allow: GET` on the live site, while `GET` returned the file.

    The clients that use HEAD are the ones this matters to: crawlers checking a file's
    type and size before downloading it, and uptime monitors, which read a 405 as an
    outage.
    """
    from app.main import DIST

    if not (DIST / "index.html").exists():
        pytest.skip("the dashboard has not been built in this checkout")

    for path in ("/", "/welcome", "/sitemap.xml", "/robots.txt"):
        if path not in ("/", "/welcome") and not (DIST / path.lstrip("/")).exists():
            continue
        head, get = client.head(path), client.get(path)
        assert head.status_code == 200, f"HEAD {path} -> {head.status_code}"
        assert head.status_code == get.status_code
        # Same headers as the GET, and no body: that is the whole definition of HEAD.
        assert head.headers.get("content-length") == get.headers.get("content-length")
        assert head.headers.get("content-type") == get.headers.get("content-type")
        assert head.content == b""


def test_head_on_an_unknown_api_route_is_still_a_404(client):
    """Adding HEAD to the catch-all must not reopen the hole it was narrowed to close:
    /api is still not the SPA's to answer, by either method."""
    assert client.head("/api/definitely-not-a-real-route").status_code == 404
    assert client.get("/api/definitely-not-a-real-route").status_code == 404


def _verification_files():
    """Every Search Console verification file in the repo.

    A glob rather than a list of hashes, because there is more than one: each Google
    account that verifies the property gets its own file, and they all have to stay.
    Removing one un-verifies that account. Pinning them by name meant the second file
    shipped untested, which is the failure the first of these tests exists to prevent.
    """
    from pathlib import Path

    public = Path(__file__).resolve().parents[1] / "dashboard" / "public"
    return sorted(public.glob("google*.html"))


def test_the_search_console_verification_files_are_served_verbatim(client):
    """Google fetches these exact paths and expects one line back. If the SPA catch-all
    answered instead, verification fails with "the file has the wrong content" — and the
    content it saw would be the dashboard's HTML, which is a confusing thing to be told.

    They live in dashboard/public/ rather than being uploaded to the VM by hand, because
    anything not in the repo is deleted by the next `npm run build` — and a site that
    silently loses its verification weeks later is worse than one that never had it.
    """
    from app.main import DIST

    if not (DIST / "index.html").exists():
        pytest.skip("the dashboard has not been built in this checkout")

    for source in _verification_files():
        assert (DIST / source.name).is_file(), (
            f"{source.name} is in dashboard/public/ but not in the build.")
        res = client.get(f"/{source.name}")
        assert res.status_code == 200
        assert res.text.strip() == f"google-site-verification: {source.name}"


def test_the_search_console_verification_files_are_in_the_repo():
    """The test above needs a built dashboard and skips without one. This one does not,
    so deleting a file is a red test in every checkout rather than a silent skip.

    Vite copies dashboard/public/ to the root of dist/ untouched, which is where Google
    looks. Anything not in the repo is erased by the next `npm run build`.
    """
    files = _verification_files()
    assert files, "No Search Console verification file in dashboard/public/."
    for source in files:
        # The name is the payload — Google checks the file it asked for contains its own
        # filename, so a copy-paste of the wrong hash reads as "wrong content" to them.
        assert source.read_text().strip() == f"google-site-verification: {source.name}"


def test_the_sitemap_declares_the_namespace_google_expects(client):
    """A sitemap in the wrong XML namespace is rejected at parse time, and the error in
    Search Console does not say which character is wrong.

    This shipped as `www.sitemap.org` — singular, one letter off the real
    `www.sitemaps.org` — which is invisible in review and fails only at submission.
    """
    from xml.etree import ElementTree

    from app.main import DIST

    source = (DIST / "sitemap.xml") if (DIST / "sitemap.xml").exists() else None
    if source is None:
        from pathlib import Path
        source = Path(__file__).resolve().parents[1] / "dashboard" / "public" / "sitemap.xml"

    root = ElementTree.fromstring(source.read_text())
    assert root.tag == "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset"
