"""Sign-in: the gate, and the ways round it that must not work. (app/auth.py)

Offline. No Firebase project, no network: the tests mint their own RSA key, sign their
own tokens with it, and hand the verifier a stand-in for Google's key endpoint. That is
worth the setup, because it exercises the real `jwt.decode` path — audience, issuer,
expiry, algorithm — rather than a mock that agrees with whatever the code does.

Almost everything here is a negative test. An endpoint that works when you are signed in
gets noticed the first time anyone clicks it. An endpoint that also works when you are
*not* signed in does not get noticed at all, and this app is one Re-run button away from
spending somebody's money.

    .venv/bin/python -m pytest tests/test_auth.py -q
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.helpers import (seed_starter_funders,  # noqa: E402
                           seed_starter_programs)

from app import auth
from app.db import init_db

PROJECT = "fundworthy-test"
ALLOWED = "admin@example.org"


# --- a stand-in for Google's signing keys --------------------------------------

@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return private, key.public_key()


@pytest.fixture()
def token_for(keypair):
    """Mint an ID token the way Firebase would, with any claim overridden."""
    private, _ = keypair

    def make(**overrides):
        now = int(time.time())
        claims = {
            "iss": f"https://securetoken.google.com/{PROJECT}",
            "aud": PROJECT,
            "sub": "uid-123",
            "iat": now,
            "exp": now + 3600,
            "email": ALLOWED,
            "email_verified": True,
            "name": "Test Admin",
        }
        claims.update(overrides)
        return jwt.encode(claims, private, algorithm="RS256")

    return make


def token_for_(keypair, **overrides):
    """`token_for` is a fixture bound to the default client; this is the same token for
    tests that build their own."""
    now = int(time.time())
    claims = {
        "iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT,
        "sub": "uid-123", "iat": now, "exp": now + 3600,
        "email": ALLOWED, "email_verified": True, "name": "Test Admin",
    }
    claims.update(overrides)
    return jwt.encode(claims, keypair[0], algorithm="RS256")


def _client(tmp_path, monkeypatch, keypair, **env):
    monkeypatch.setenv("FUNDWORTHY_DB_PATH", str(tmp_path / "rise.db"))
    monkeypatch.setenv("FUNDWORTHY_KEYFILE", str(tmp_path / ".fernet-key"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    init_db()
    seed_starter_funders()
    seed_starter_programs()

    from app.main import create_app

    app = create_app()

    # Stand in for the JWKS fetch. Set after create_app so a misconfiguration test still
    # fails where it should.
    _, public = keypair
    monkeypatch.setattr(
        auth, "_jwks_client",
        SimpleNamespace(get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=public)),
    )
    return TestClient(app)


@pytest.fixture()
def signed_in(tmp_path, monkeypatch, keypair):
    """An install with sign-in switched on."""
    with _client(tmp_path, monkeypatch, keypair,
                 FIREBASE_PROJECT_ID=PROJECT,
                 FIREBASE_WEB_API_KEY="AIza-not-a-secret",
                 ALLOWED_EMAILS=f"{ALLOWED}, Someone.Else@example.org") as c:
        yield c


@pytest.fixture()
def local(tmp_path, monkeypatch, keypair):
    """A localhost install: no sign-in at all."""
    monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
    with _client(tmp_path, monkeypatch, keypair) as c:
        yield c


# --- off by default -------------------------------------------------------------

def test_local_install_needs_no_sign_in(local):
    """CLAUDE.md §6: ./start.sh opens straight onto the dashboard. A localhost-bound app
    with nobody to authenticate must not grow a login wall."""
    assert local.get("/api/state").status_code == 200
    assert local.get("/api/auth/config").json() == {"enabled": False}
    assert local.get("/api/auth/me").json()["auth_required"] is False


def test_local_install_keeps_the_api_docs(local):
    assert local.get("/api/docs").status_code == 200


# --- misconfiguration is a refusal to start -------------------------------------

def test_an_empty_allow_list_means_open_not_broken(tmp_path, monkeypatch, keypair):
    """This used to be a refusal to start, and the reasoning was sound at the time: one
    shared Anthropic key meant "anyone may sign in" was "anyone may spend the pilot's
    money". Per-org keys removed that, so an empty allow-list is now simply the open
    product rather than a dangerous middle state."""
    monkeypatch.setenv("ALLOWED_EMAILS", "")
    with _client(tmp_path, monkeypatch, keypair, FIREBASE_PROJECT_ID=PROJECT,
                 FIREBASE_WEB_API_KEY="AIza-not-a-secret") as c:
        assert c.get("/api/auth/config").json()["open_signup"] is True


def test_a_project_without_a_web_key_refuses_to_boot(tmp_path, monkeypatch, keypair):
    with pytest.raises(RuntimeError, match="FIREBASE_WEB_API_KEY"):
        _client(tmp_path, monkeypatch, keypair,
                FIREBASE_PROJECT_ID=PROJECT, ALLOWED_EMAILS=ALLOWED)


# --- the gate --------------------------------------------------------------------

ROUTES = [
    ("get", "/api/state"),
    ("get", "/api/settings"),
    ("get", "/api/programs"),
    ("get", "/api/funders"),
    ("get", "/api/opportunities"),
    ("get", "/api/opportunities/export.csv"),
    ("get", "/api/archive"),
    ("get", "/api/runs"),
    ("get", "/api/runs/current"),
]


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_every_read_route_is_closed_without_a_token(signed_in, method, path):
    assert getattr(signed_in, method)(path).status_code == 401


def test_the_expensive_routes_are_closed_without_a_token(signed_in):
    """The two that cost money if left open: starting a run spends the API key, and the
    assistant is a Sonnet call per request."""
    assert signed_in.post("/api/runs", json={}).status_code == 401
    assert signed_in.post("/api/programs/draft",
                          json={"url": "https://example.org"}).status_code == 401


def test_the_api_key_routes_are_closed_without_a_token(signed_in):
    assert signed_in.post("/api/settings/api-key",
                          json={"api_key": "sk-ant-nope-0000"}).status_code == 401
    assert signed_in.delete("/api/settings/api-key").status_code == 401
    assert signed_in.post("/api/settings/api-key/test", json={}).status_code == 401


def test_health_stays_open(signed_in):
    """It has to be, to be useful — nginx, a monitor, or the ping that stops Oracle
    reclaiming an idle free VM. Which is why it must never report anything."""
    r = signed_in.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_the_config_endpoint_gives_away_nothing_secret(signed_in):
    body = signed_in.get("/api/auth/config").json()
    assert body["enabled"] is True
    assert body["project_id"] == PROJECT
    assert body["api_key"] == "AIza-not-a-secret"   # Firebase's public web key
    # Who is allowed in is nobody's business but the server's.
    assert "allowed_emails" not in body
    assert ALLOWED not in str(body)


def test_the_api_docs_are_not_published_on_a_public_install(signed_in):
    """Harmless on a localhost install, an unnecessary map of the building on a public
    one. Both paths fall through to the SPA — what matters is that neither one hands out
    a schema of every route and body shape."""
    assert "swagger" not in signed_in.get("/api/docs").text.lower()

    schema = signed_in.get("/openapi.json")
    assert "paths" not in schema.text
    assert "/api/settings/api-key" not in schema.text


# --- tokens that must not work ---------------------------------------------------

def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_a_valid_allow_listed_token_gets_in(signed_in, token_for):
    r = signed_in.get("/api/state", headers=auth_header(token_for()))
    assert r.status_code == 200
    assert r.json()["settings"]["min_award"] == 10_000

    me = signed_in.get("/api/auth/me", headers=auth_header(token_for())).json()
    assert me["signed_in"] is True
    assert me["auth_required"] is True
    assert me["email"] == ALLOWED
    assert me["name"] == "Test Admin"
    # On a fresh install the first person in gets the default org — shipped seed content
    # is not somebody else's work. It is only withheld once that org has accumulated
    # findings or a saved API key. See app/db.py: _claims_default_org.
    assert me["org_id"] == "default"


def test_the_allow_list_is_case_insensitive(signed_in, token_for):
    """Nobody types their own address the same way twice, and locking an admin out of
    their own dashboard over a capital letter is not a security win."""
    token = token_for(email="SOMEONE.ELSE@Example.ORG")
    assert signed_in.get("/api/state", headers=auth_header(token)).status_code == 200


def test_a_real_google_account_that_is_not_on_the_list_is_refused(signed_in, token_for):
    """The whole point of the allow-list. This token is genuine, correctly signed, and
    from the right project — Firebase authenticated a real person. It is still a no."""
    r = signed_in.get("/api/state", headers=auth_header(token_for(email="stranger@gmail.com")))
    assert r.status_code == 403
    assert "allow-list" in r.json()["detail"]


def test_an_unverified_email_cannot_clear_the_allow_list(signed_in, token_for):
    """The check that carries email/password sign-in.

    Under Google-only this never fired — Google verifies before handing us anything. With
    the password provider enabled, Firebase will create an account for any address a
    stranger can type, so this is the only thing standing between the allow-list and
    someone registering `admin@the-org.org` with a password of their choosing.
    """
    r = signed_in.get("/api/state",
                      headers=auth_header(token_for(email_verified=False)))
    assert r.status_code == 403


def test_the_unverified_refusal_says_what_to_do_about_it(signed_in, token_for):
    """Unlike the other refusals, this one is entirely the user's to fix — so it names the
    address and points at the inbox instead of stating a fact about the token."""
    r = signed_in.get("/api/state",
                      headers=auth_header(token_for(email_verified=False)))
    detail = r.json()["detail"]
    assert ALLOWED in detail
    assert "inbox" in detail.lower()


def test_a_token_for_another_firebase_project_is_refused(signed_in, token_for):
    """Anyone can create a Firebase project and mint themselves a valid ID token. The
    audience check is what makes that token useless here."""
    token = token_for(aud="somebody-elses-project")
    assert signed_in.get("/api/state", headers=auth_header(token)).status_code == 401


def test_a_token_from_the_wrong_issuer_is_refused(signed_in, token_for):
    token = token_for(iss="https://securetoken.google.com/attacker")
    assert signed_in.get("/api/state", headers=auth_header(token)).status_code == 401


def test_an_expired_token_is_refused(signed_in, token_for):
    token = token_for(exp=int(time.time()) - 60)
    r = signed_in.get("/api/state", headers=auth_header(token))
    assert r.status_code == 401
    assert "expired" in r.json()["detail"].lower()


def test_an_unsigned_token_is_refused(signed_in, keypair, token_for):
    """The alg=none attack: same claims, no signature. Pinning algorithms=["RS256"] in
    the decode call is what stops the token's own header choosing how it gets checked."""
    now = int(time.time())
    token = jwt.encode(
        {"iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT,
         "sub": "uid-123", "iat": now, "exp": now + 3600,
         "email": ALLOWED, "email_verified": True},
        key="", algorithm="none",
    )
    assert signed_in.get("/api/state", headers=auth_header(token)).status_code == 401


def test_a_token_signed_with_the_public_key_is_refused(signed_in, keypair):
    """The RS256→HS256 confusion attack: Google's signing key is public, so sign with it
    as an HMAC secret and hope the verifier trusts the token's own `alg` header.

    Assembled by hand rather than with `jwt.encode`, which refuses to use a PEM as an
    HMAC secret. An attacker is not calling PyJWT.
    """
    _, public = keypair
    pem = public.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    now = int(time.time())
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=")  # noqa: E731
    signed = b".".join((
        b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()),
        b64(json.dumps({
            "iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT,
            "sub": "uid-123", "iat": now, "exp": now + 3600,
            "email": ALLOWED, "email_verified": True,
        }).encode()),
    ))
    token = b".".join(
        (signed, b64(hmac.new(pem, signed, hashlib.sha256).digest()))).decode()

    assert signed_in.get("/api/state", headers=auth_header(token)).status_code == 401


@pytest.mark.parametrize("header", [
    {"Authorization": "Bearer"},
    {"Authorization": "Bearer "},
    {"Authorization": "Basic YWRtaW46aHVudGVyMg=="},
    {"Authorization": ""},
])
def test_junk_in_the_authorization_header_is_refused(signed_in, header):
    assert signed_in.get("/api/state", headers=header).status_code == 401


# --- failures on the way to the key, before the token is ever decoded --------------
#
# These use the real PyJWKClient rather than the fixture's stand-in, because the bug they
# cover lived in exactly the gap the stand-in papers over: it answers every call with a
# key, so nothing above ever exercised what happens when looking the key *up* fails.
# `Bearer garbage` used to come back 500 with a stack trace.

@pytest.fixture()
def unmocked(tmp_path, monkeypatch, keypair):
    """Sign-in on, with the JWKS client left as it really is."""
    with _client(tmp_path, monkeypatch, keypair,
                 FIREBASE_PROJECT_ID=PROJECT,
                 FIREBASE_WEB_API_KEY="AIza-not-a-secret",
                 ALLOWED_EMAILS=ALLOWED) as c:
        monkeypatch.setattr(auth, "_jwks_client", None)
        yield c


@pytest.mark.parametrize("token", [
    "garbage",              # not a JWT at all
    "a.b.c",                # three segments of nonsense
    "eyJhbGciOiJSUzI1NiJ9", # a lone header, no payload or signature
    "....",
])
def test_a_bearer_token_that_is_not_a_jwt_is_a_clean_401(unmocked, token):
    """No network is reached: the token cannot be parsed far enough to look a key up.

    A 500 here would be wrong twice over — the caller is refused either way, but an
    unauthenticated stranger should not be able to write stack traces into the log.
    """
    r = unmocked.get("/api/state", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Sign in to use Fundworthy."


def test_a_token_whose_kid_google_does_not_publish_is_a_401(unmocked, monkeypatch, token_for):
    """A well-formed token signed by a key Google never issued."""
    import jwt as pyjwt

    def no_such_key(_token):
        raise pyjwt.exceptions.PyJWKClientError("Unable to find a signing key that matches")

    monkeypatch.setattr(auth, "_jwks_client",
                        SimpleNamespace(get_signing_key_from_jwt=no_such_key))
    assert unmocked.get("/api/state",
                        headers=auth_header(token_for())).status_code == 401


def test_being_unable_to_reach_google_is_a_503_not_a_401(unmocked, monkeypatch, token_for):
    """The one failure that is ours, not the user's. Answering 401 would send a valid
    person round the sign-in loop forever chasing a problem on our end."""
    import jwt as pyjwt

    def offline(_token):
        raise pyjwt.exceptions.PyJWKClientConnectionError("connection refused")

    monkeypatch.setattr(auth, "_jwks_client",
                        SimpleNamespace(get_signing_key_from_jwt=offline))
    r = unmocked.get("/api/state", headers=auth_header(token_for()))
    assert r.status_code == 503
    assert "Could not reach Google" in r.json()["detail"]


# --- the one thing the mocks cannot check ----------------------------------------

@pytest.mark.network
def test_googles_key_endpoint_is_the_real_one():
    """Everything above stands in for the JWKS fetch, which means a typo in JWKS_URL
    would pass the entire suite and then fail for a real person at the sign-in button.
    It has happened once already: the path is `/jwk/`, and `/jwks/` is a 404.

    Opt in with `pytest -m network`. Skipped by default — the rest of this suite is
    offline on purpose.
    """
    import httpx

    r = httpx.get(auth.JWKS_URL, timeout=15)
    assert r.status_code == 200, f"{auth.JWKS_URL} returned {r.status_code}"
    keys = r.json()["keys"]

    assert keys, "Google returned no signing keys"
    assert all(k["alg"] == "RS256" for k in keys)
    assert all("kid" in k for k in keys)


# --- two orgs, over HTTP --------------------------------------------------------
#
# The repo-level isolation tests live in tests/test_tenancy.py. These check the seam that
# actually faces the internet: that the org a request is scoped to comes from the *token*,
# and that nothing a client can type changes it.

def test_two_signed_in_people_do_not_share_data(signed_in, token_for):
    """The reported bug, end to end: a teammate signs in at the same URL and must not
    land in the first user's dashboard, findings, or API key."""
    first = {"Authorization": f"Bearer {token_for()}"}
    second = {"Authorization": "Bearer " + token_for(
        sub="uid-999", email="someone.else@example.org", name="Someone Else")}

    a_org = signed_in.get("/api/auth/me", headers=first).json()["org_id"]
    b_org = signed_in.get("/api/auth/me", headers=second).json()["org_id"]
    assert a_org != b_org

    # A program card created by one is invisible to the other.
    made = signed_in.post("/api/programs", headers=first,
                          json={"name": "Confidential Strategy"})
    assert made.status_code == 201
    b_programs = signed_in.get("/api/programs", headers=second).json()["programs"]
    assert "Confidential Strategy" not in [p["name"] for p in b_programs]

    # A settings change by one does not move the other's floor.
    signed_in.put("/api/settings", headers=first, json={"min_award": 99_000})
    b_settings = signed_in.get("/api/settings", headers=second).json()["settings"]
    assert b_settings["min_award"] == 10_000


def test_a_saved_key_is_not_visible_to_another_org(signed_in, token_for):
    first = {"Authorization": f"Bearer {token_for()}"}
    second = {"Authorization": "Bearer " + token_for(
        sub="uid-999", email="someone.else@example.org")}

    saved = signed_in.post("/api/settings/api-key", headers=first,
                           json={"api_key": "sk-ant-FIRST-USERS-KEY"})
    assert saved.status_code == 200
    assert saved.json()["has_api_key"] is True

    theirs = signed_in.get("/api/settings", headers=second).json()
    assert theirs["has_api_key"] is False
    assert theirs["api_key_hint"] is None
    assert theirs["key_available"] is False       # and no fallback to anyone else's

    # The first org still has its key: saving nothing did not clear it.
    assert signed_in.get("/api/settings", headers=first).json()["has_api_key"] is True


def test_the_org_cannot_be_chosen_by_the_caller(signed_in, token_for):
    """Nothing a client sends may select the tenant — no query parameter, no body field,
    no header. The org comes from the verified token and nowhere else."""
    first = {"Authorization": f"Bearer {token_for()}"}
    second = {"Authorization": "Bearer " + token_for(
        sub="uid-999", email="someone.else@example.org")}

    signed_in.post("/api/programs", headers=first, json={"name": "Private Card"})
    a_org = signed_in.get("/api/auth/me", headers=first).json()["org_id"]

    # Try to borrow the other org's id every way the API exposes.
    sneaky = signed_in.get(f"/api/programs?org_id={a_org}", headers=second).json()
    assert "Private Card" not in [p["name"] for p in sneaky["programs"]]

    posted = signed_in.post("/api/programs", headers=second,
                            json={"name": "Injected", "org_id": a_org})
    assert posted.status_code == 201
    a_programs = signed_in.get("/api/programs", headers=first).json()["programs"]
    assert "Injected" not in [p["name"] for p in a_programs]


def test_one_org_cannot_stop_anothers_run(signed_in, token_for, monkeypatch):
    """Stop used to terminate whatever the singleton held, with no check on who asked."""
    from app.runner import MANAGER

    second = {"Authorization": "Bearer " + token_for(
        sub="uid-999", email="someone.else@example.org")}

    monkeypatch.setattr(type(MANAGER), "is_running", property(lambda self: True))
    monkeypatch.setattr(MANAGER, "_org_id", "org_someone_elses", raising=False)
    monkeypatch.setattr(MANAGER, "_proc", object(), raising=False)

    assert signed_in.post("/api/runs/stop", headers=second).json()["stopped"] is False


# --- the invite flow, over HTTP -------------------------------------------------

def test_a_colleague_joins_by_code_and_sees_the_same_dashboard(signed_in, token_for):
    """The whole point of invites: two staff at one nonprofit, one set of findings."""
    owner = {"Authorization": f"Bearer {token_for()}"}
    joiner = {"Authorization": "Bearer " + token_for(
        sub="uid-999", email="someone.else@example.org")}

    signed_in.post("/api/programs", headers=owner, json={"name": "Shared Program"})
    owner_org = signed_in.get("/api/auth/me", headers=owner).json()["org_id"]

    # Before joining, the colleague is in their own empty org.
    assert signed_in.get("/api/auth/me", headers=joiner).json()["org_id"] != owner_org
    assert signed_in.get("/api/programs", headers=joiner).json()["programs"] == []

    made = signed_in.post("/api/org/invites", headers=owner)
    assert made.status_code == 201
    code = made.json()["invite"]["code"]

    joined = signed_in.post("/api/org/join", headers=joiner, json={"code": code})
    assert joined.status_code == 200
    assert joined.json()["org_id"] == owner_org

    names = [p["name"] for p in
             signed_in.get("/api/programs", headers=joiner).json()["programs"]]
    assert "Shared Program" in names


def test_a_stranger_cannot_join_with_a_guessed_code(signed_in, token_for):
    joiner = {"Authorization": "Bearer " + token_for(
        sub="uid-999", email="someone.else@example.org")}
    refused = signed_in.post("/api/org/join", headers=joiner,
                             json={"code": "ZZZZ-ZZZZ-ZZZZ"})
    assert refused.status_code == 400
    assert "not valid" in refused.json()["detail"]


def test_one_org_cannot_see_or_revoke_anothers_invites(signed_in, token_for):
    owner = {"Authorization": f"Bearer {token_for()}"}
    other = {"Authorization": "Bearer " + token_for(
        sub="uid-999", email="someone.else@example.org")}

    code = signed_in.post("/api/org/invites", headers=owner).json()["invite"]["code"]

    theirs = signed_in.get("/api/org", headers=other).json()
    assert code not in [i["code"] for i in theirs["invites"]]
    assert signed_in.delete(f"/api/org/invites/{code}", headers=other).status_code == 404


def test_the_member_list_is_scoped_to_your_own_org(signed_in, token_for):
    owner = {"Authorization": f"Bearer {token_for()}"}
    other = {"Authorization": "Bearer " + token_for(
        sub="uid-999", email="someone.else@example.org")}

    signed_in.get("/api/auth/me", headers=other)      # provision their org
    mine = signed_in.get("/api/org", headers=owner).json()

    assert [m["email"] for m in mine["members"]] == [ALLOWED]


def test_security_headers_are_present(signed_in):
    res = signed_in.get("/api/health")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in res.headers["Content-Security-Policy"]
    # HSTS belongs on nginx — sending it from the app would pin a developer's
    # http://127.0.0.1:8000 to HTTPS for a year.
    assert "Strict-Transport-Security" not in res.headers


# --- open sign-up ---------------------------------------------------------------
#
# The allow-list existed for one reason: a single shared Anthropic key meant anyone who
# found the URL could spend the pilot org's money. Per-org keys removed that, so a
# deployment can now let any nonprofit sign up — but it has to say which product it is.

def test_open_signup_lets_any_verified_google_account_in(tmp_path, monkeypatch, keypair):
    with _client(tmp_path, monkeypatch, keypair,
                 FIREBASE_PROJECT_ID=PROJECT,
                 FIREBASE_WEB_API_KEY="AIza-not-a-secret") as c:
        _, public = keypair
        token = jwt.encode(
            {"iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT,
             "sub": "uid-stranger", "iat": int(time.time()),
             "exp": int(time.time()) + 3600,
             "email": "brand.new@somenonprofit.org", "email_verified": True,
             "name": "A Stranger"},
            keypair[0], algorithm="RS256")
        me = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["signed_in"] is True


def test_open_signup_still_requires_a_verified_address(tmp_path, monkeypatch, keypair):
    """The worst case for the password provider, and the reason verification is not
    optional: under open sign-up there is no allow-list to fall back on, so an unverified
    address would let a stranger claim an organization keyed on an address they do not
    own — and then be the account a colleague's invitation gets sent to."""
    with _client(tmp_path, monkeypatch, keypair,
                 FIREBASE_PROJECT_ID=PROJECT,
                 FIREBASE_WEB_API_KEY="AIza-not-a-secret") as c:
        token = jwt.encode(
            {"iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT,
             "sub": "uid-x", "iat": int(time.time()), "exp": int(time.time()) + 3600,
             "email": "unverified@example.org", "email_verified": False},
            keypair[0], algorithm="RS256")
        res = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 403


def test_no_allow_list_means_open_sign_up(tmp_path, monkeypatch, keypair):
    """Open is the default, not an opt-in. Fundworthy is a product any nonprofit can
    use; the allow-list is the unusual configuration, so it is the one you set."""
    monkeypatch.delenv("ALLOWED_EMAILS", raising=False)
    with _client(tmp_path, monkeypatch, keypair, FIREBASE_PROJECT_ID=PROJECT,
                 FIREBASE_WEB_API_KEY="AIza-not-a-secret") as c:
        assert c.get("/api/auth/config").json()["open_signup"] is True


def test_the_sign_in_page_is_told_which_mode_it_is_in(tmp_path, monkeypatch, keypair):
    with _client(tmp_path, monkeypatch, keypair,
                 FIREBASE_PROJECT_ID=PROJECT,
                 FIREBASE_WEB_API_KEY="AIza-not-a-secret") as c:
        assert c.get("/api/auth/config").json()["open_signup"] is True


# --- which ways in to offer -------------------------------------------------------

def test_the_password_form_is_off_unless_the_project_has_the_provider(signed_in):
    """The server cannot ask Firebase which providers are enabled, so it is declared.
    Rendering a password form against a project with the provider switched off fails with
    `auth/operation-not-allowed`, which reads as a broken app rather than a setting
    nobody turned on."""
    assert signed_in.get("/api/auth/config").json()["password_auth"] is False


def test_the_password_form_appears_when_the_deployment_says_so(tmp_path, monkeypatch, keypair):
    with _client(tmp_path, monkeypatch, keypair,
                 FIREBASE_PROJECT_ID=PROJECT,
                 FIREBASE_WEB_API_KEY="AIza-not-a-secret",
                 ALLOWED_EMAILS=ALLOWED,
                 FIREBASE_PASSWORD_AUTH="1") as c:
        assert c.get("/api/auth/config").json()["password_auth"] is True


def test_turning_on_passwords_does_not_weaken_the_gate(tmp_path, monkeypatch, keypair,
                                                       token_for):
    """Enabling the provider changes what the sign-in page offers and nothing about who
    gets in. Same allow-list, same verified-address requirement."""
    with _client(tmp_path, monkeypatch, keypair,
                 FIREBASE_PROJECT_ID=PROJECT,
                 FIREBASE_WEB_API_KEY="AIza-not-a-secret",
                 ALLOWED_EMAILS=ALLOWED,
                 FIREBASE_PASSWORD_AUTH="1") as c:
        assert c.get("/api/state").status_code == 401
        assert c.get("/api/state", headers=auth_header(
            token_for(email="stranger@example.org"))).status_code == 403
        assert c.get("/api/state", headers=auth_header(
            token_for(email_verified=False))).status_code == 403
        assert c.get("/api/state", headers=auth_header(token_for())).status_code == 200


def test_a_private_install_is_unchanged(signed_in, token_for):
    """The allow-list still works exactly as before when it is the chosen mode."""
    assert signed_in.get("/api/auth/config").json()["open_signup"] is False
    refused = signed_in.get("/api/auth/me", headers={
        "Authorization": "Bearer " + token_for(email="nobody@example.org")})
    assert refused.status_code == 403


# --- the one endpoint that ignores the tenant boundary --------------------------

def test_platform_stats_are_invisible_without_being_named_an_admin(signed_in, token_for):
    """`FUNDWORTHY_ADMIN_EMAILS` is its own list, not ALLOWED_EMAILS and not a role. With
    open sign-up the allow-list is empty, so hanging admin off "are you signed in" would
    publish the platform's numbers to anybody who made an account."""
    ok = {"Authorization": f"Bearer {token_for()}"}
    res = signed_in.get("/api/admin/stats", headers=ok)
    # 404, not 403: saying "you are not an admin" confirms the endpoint exists and that
    # being one is a thing to become.
    assert res.status_code == 404


def test_an_admin_sees_counts_and_no_names(tmp_path, monkeypatch, keypair):
    with _client(tmp_path, monkeypatch, keypair,
                 FIREBASE_PROJECT_ID=PROJECT,
                 FIREBASE_WEB_API_KEY="AIza-not-a-secret",
                 ALLOWED_EMAILS=ALLOWED,
                 FUNDWORTHY_ADMIN_EMAILS=ALLOWED) as c:
        body = c.get("/api/admin/stats",
                     headers={"Authorization": f"Bearer {token_for_(keypair)}"}).json()

    assert {"orgs", "users", "runs_30d", "spend_30d_usd"} <= set(body)
    # It answers "is the product working", so it must not carry anything that identifies
    # an organization or leaks one org's research to whoever is reading.
    blob = str(body).lower()
    for leak in ("@", "foundation", "grant", "email"):
        assert leak not in blob


def test_an_empty_admin_list_means_nobody(signed_in, token_for):
    """A missing variable must not be a permissive default on the only endpoint that
    reads across every organization."""
    res = signed_in.get("/api/admin/stats",
                        headers={"Authorization": f"Bearer {token_for()}"})
    assert res.status_code == 404


# --- who administers an organization ------------------------------------------
#
# Removing a colleague cuts them off from the funders, the findings and the API key in
# one request, and none of it is undoable. The dashboard hides Manage from everyone but
# the admin; these tests are about the half that actually decides, because a hidden
# button is not a permission check.

SECOND = "someone.else@example.org"


def _sign_in(client, token_for, **claims):
    """Sign somebody in for the first time, which is what provisions their org."""
    return client.get("/api/state", headers=auth_header(token_for(**claims)))


def test_whoever_creates_an_org_administers_it(signed_in, token_for):
    _sign_in(signed_in, token_for)
    body = signed_in.get("/api/org", headers=auth_header(token_for())).json()

    assert body["you_are_admin"] is True
    assert [m["is_admin"] for m in body["members"]] == [True]


def test_a_colleague_who_joins_is_not_an_admin(signed_in, token_for):
    _sign_in(signed_in, token_for)
    code = signed_in.post("/api/org/invites",
                          headers=auth_header(token_for())).json()["invite"]["code"]

    joiner = auth_header(token_for(sub="uid-999", email=SECOND))
    assert signed_in.post("/api/org/join", json={"code": code},
                          headers=joiner).status_code == 200

    seen_by_joiner = signed_in.get("/api/org", headers=joiner).json()
    assert seen_by_joiner["you_are_admin"] is False
    admins = {m["email"]: m["is_admin"] for m in seen_by_joiner["members"]}
    assert admins == {ALLOWED: True, SECOND: False}


def test_only_the_admin_may_remove_anybody(signed_in, token_for):
    """The check that matters. A member who can remove the admin can take the
    organization, its funders and its saved API key from the people who built it."""
    _sign_in(signed_in, token_for)
    code = signed_in.post("/api/org/invites",
                          headers=auth_header(token_for())).json()["invite"]["code"]
    joiner = auth_header(token_for(sub="uid-999", email=SECOND))
    signed_in.post("/api/org/join", json={"code": code}, headers=joiner)

    r = signed_in.delete("/api/org/members/uid-123", headers=joiner)
    assert r.status_code == 403
    assert "admin" in r.json()["detail"]

    # And the admin is still there.
    members = signed_in.get("/api/org", headers=joiner).json()["members"]
    assert ALLOWED in {m["email"] for m in members}


def test_only_the_admin_may_hand_the_organization_on(signed_in, token_for):
    _sign_in(signed_in, token_for)
    code = signed_in.post("/api/org/invites",
                          headers=auth_header(token_for())).json()["invite"]["code"]
    joiner = auth_header(token_for(sub="uid-999", email=SECOND))
    signed_in.post("/api/org/join", json={"code": code}, headers=joiner)

    grab = signed_in.post("/api/org/transfer", json={"uid": "uid-999"}, headers=joiner)
    assert grab.status_code == 403, "a member must not be able to promote themselves"


def test_the_admin_can_remove_a_colleague_and_they_land_somewhere_new(signed_in, token_for):
    _sign_in(signed_in, token_for)
    code = signed_in.post("/api/org/invites",
                          headers=auth_header(token_for())).json()["invite"]["code"]
    joiner = auth_header(token_for(sub="uid-999", email=SECOND))
    signed_in.post("/api/org/join", json={"code": code}, headers=joiner)
    signed_in.post("/api/settings/api-key", json={"api_key": "sk-ant-" + "x" * 20},
                   headers=auth_header(token_for()))

    r = signed_in.delete("/api/org/members/uid-999", headers=auth_header(token_for()))
    assert r.status_code == 200 and r.json()["removed"] == SECOND

    # They can still sign in — they simply are not here any more, and arrive somewhere
    # with no key and the walkthrough waiting, exactly like a new account.
    after = signed_in.get("/api/state", headers=joiner).json()
    assert after["has_api_key"] is False
    assert after["settings"]["onboarding_done"] is False


def test_transferring_hands_over_the_controls_both_ways(signed_in, token_for):
    _sign_in(signed_in, token_for)
    code = signed_in.post("/api/org/invites",
                          headers=auth_header(token_for())).json()["invite"]["code"]
    joiner = auth_header(token_for(sub="uid-999", email=SECOND))
    signed_in.post("/api/org/join", json={"code": code}, headers=joiner)

    handed = signed_in.post("/api/org/transfer", json={"uid": "uid-999"},
                            headers=auth_header(token_for()))
    assert handed.status_code == 200 and handed.json()["admin"] == SECOND

    assert signed_in.get("/api/org", headers=joiner).json()["you_are_admin"] is True
    assert signed_in.get("/api/org",
                         headers=auth_header(token_for())).json()["you_are_admin"] is False
    # The old admin stays a member — transferring is not leaving.
    assert ALLOWED in {m["email"] for m in
                       signed_in.get("/api/org", headers=joiner).json()["members"]}


def test_an_admin_cannot_remove_themselves_by_the_back_door(signed_in, token_for):
    _sign_in(signed_in, token_for)
    r = signed_in.delete("/api/org/members/uid-123", headers=auth_header(token_for()))
    assert r.status_code == 400
    assert "cannot remove yourself" in r.json()["detail"]


def test_an_admin_with_colleagues_must_hand_over_before_deleting_their_account(
        signed_in, token_for):
    """Otherwise the last admin walks out and nobody left can invite or remove anyone."""
    _sign_in(signed_in, token_for)
    code = signed_in.post("/api/org/invites",
                          headers=auth_header(token_for())).json()["invite"]["code"]
    signed_in.post("/api/org/join", json={"code": code},
                   headers=auth_header(token_for(sub="uid-999", email=SECOND)))

    r = signed_in.delete("/api/account", headers=auth_header(token_for()))
    assert r.status_code == 409
    assert "Hand the organization" in r.json()["detail"]


def test_the_only_member_may_delete_their_account(signed_in, token_for):
    """Nobody to strand, so no hand-over to demand."""
    _sign_in(signed_in, token_for)
    r = signed_in.delete("/api/account", headers=auth_header(token_for()))
    assert r.status_code == 200 and r.json()["deleted"] == ALLOWED
    assert r.json()["funders_kept"] is True


def test_deleting_an_account_is_refused_on_an_install_with_no_accounts(local):
    r = local.delete("/api/account")
    assert r.status_code == 400
    assert "no accounts" in r.json()["detail"]


def test_the_member_routes_are_closed_without_a_token(signed_in):
    assert signed_in.delete("/api/org/members/uid-123").status_code == 401
    assert signed_in.post("/api/org/transfer", json={"uid": "x"}).status_code == 401
    assert signed_in.delete("/api/account").status_code == 401


# --- the shared funder pool and its moderation --------------------------------

def test_the_sharing_routes_are_closed_without_a_token(signed_in):
    assert signed_in.get("/api/directory/shared").status_code == 401
    assert signed_in.post("/api/directory/shared/report",
                          json={"from_org": "x", "funder_id": "y"}).status_code == 401


def test_moderation_is_hidden_from_ordinary_accounts(signed_in, token_for, monkeypatch):
    """`FUNDWORTHY_ADMIN_EMAILS` is unset here, and unset must mean nobody — the queue
    crosses every tenant boundary, so a missing variable cannot be a permissive default.

    404 rather than 403, matching `/api/admin/stats`: an endpoint that says "you are not
    an admin" has confirmed both that it exists and that being one is a thing to become.
    """
    _sign_in(signed_in, token_for)
    me = auth_header(token_for())

    assert signed_in.get("/api/admin/reports", headers=me).status_code == 404
    assert signed_in.post(
        "/api/admin/reports/resolve",
        json={"uphold": True, "funder_org": "x", "funder_id": "y"},
        headers=me).status_code == 404
    assert signed_in.get("/api/org", headers=me).json()["platform_admin"] is False


def test_the_named_operator_can_moderate(signed_in, token_for, monkeypatch):
    monkeypatch.setenv("FUNDWORTHY_ADMIN_EMAILS", f"someone.else@x.org, {ALLOWED}")
    _sign_in(signed_in, token_for)
    me = auth_header(token_for())

    assert signed_in.get("/api/admin/reports", headers=me).status_code == 200
    assert signed_in.get("/api/org", headers=me).json()["platform_admin"] is True
    # A funder with no open report is a 404 from the handler, not from the gate.
    assert signed_in.post(
        "/api/admin/reports/resolve",
        json={"uphold": True, "funder_org": "x", "funder_id": "nope"},
        headers=me).status_code == 404


def test_a_report_names_the_funder_it_is_given_not_the_org_asking(signed_in, token_for,
                                                                  monkeypatch):
    """The reporting org is recorded server-side from the session and never accepted from
    the body — the same rule as `current_org`. Who objected to whom is exactly the kind of
    thing a small nonprofit sector would gossip about."""
    monkeypatch.setenv("FUNDWORTHY_ADMIN_EMAILS", ALLOWED)
    _sign_in(signed_in, token_for)
    me = auth_header(token_for())

    r = signed_in.post("/api/directory/shared/report",
                       json={"from_org": "org_somebody", "funder_id": "f1",
                             "reason": "not real"}, headers=me)
    assert r.status_code == 201

    queued = signed_in.get("/api/admin/reports", headers=me).json()["reports"]
    assert len(queued) == 1
    assert queued[0]["reason"] == "not real"
    assert "reported_by" not in queued[0], "the objector is not part of the queue view"


# --- deleting the sign-in, not just the data ----------------------------------
#
# "Delete my account" must not quietly mean "delete your data and keep your email
# address on file". These are offline: `httpx.post` is stubbed, because the thing under
# test is which outcome each Firebase answer maps to and what we do with it — not
# whether Google's endpoint works.

class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _firebase_says(monkeypatch, response):
    calls = {}

    def fake_post(url, **kw):
        calls["url"] = url
        calls["params"] = kw.get("params")
        calls["json"] = kw.get("json")
        if isinstance(response, Exception):
            raise response
        return response

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


def _configured(monkeypatch):
    from app import auth
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT)
    monkeypatch.setenv("FIREBASE_WEB_API_KEY", "AIza-not-a-secret")
    auth.configure()
    return auth


def test_a_successful_delete_reports_the_sign_in_as_removed(monkeypatch):
    auth = _configured(monkeypatch)
    calls = _firebase_says(monkeypatch, _Response(200))

    assert auth.delete_firebase_account("tok") is auth.DeletionOutcome.REMOVED
    assert calls["json"] == {"idToken": "tok"}
    assert calls["params"] == {"key": "AIza-not-a-secret"}
    assert "identitytoolkit" in calls["url"], "the REST endpoint, not firebase-admin"


def test_a_stale_sign_in_is_reported_rather_than_papered_over(monkeypatch):
    """Firebase refuses this when you signed in a while ago. It is about `auth_time`, so
    refreshing the token does not help — the only honest answer is to say so, and the UI
    then tells them to sign in again rather than claiming the record is gone."""
    auth = _configured(monkeypatch)
    _firebase_says(monkeypatch, _Response(
        400, {"error": {"message": "CREDENTIAL_TOO_OLD_LOGIN_AGAIN"}}))

    assert auth.delete_firebase_account("tok") is auth.DeletionOutcome.NEEDS_RECENT_LOGIN


def test_an_account_already_gone_counts_as_removed(monkeypatch):
    """USER_NOT_FOUND is the outcome we wanted, reached by another route. Reporting it
    as a failure would send somebody chasing a record that does not exist."""
    auth = _configured(monkeypatch)
    _firebase_says(monkeypatch, _Response(400, {"error": {"message": "USER_NOT_FOUND"}}))

    assert auth.delete_firebase_account("tok") is auth.DeletionOutcome.REMOVED


def test_firebase_being_unreachable_is_a_failure_not_an_exception(monkeypatch):
    """This runs immediately after the person's data has already been deleted. An
    exception here would surface as a 500 on a request that half-succeeded."""
    import httpx
    auth = _configured(monkeypatch)
    _firebase_says(monkeypatch, httpx.ConnectError("no route to host"))

    assert auth.delete_firebase_account("tok") is auth.DeletionOutcome.FAILED


def test_a_local_install_has_no_sign_in_to_delete(monkeypatch):
    from app import auth
    monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
    auth.configure()

    assert auth.delete_firebase_account("tok") is auth.DeletionOutcome.NOT_APPLICABLE


def test_closing_an_account_deletes_the_data_before_the_sign_in(signed_in, token_for,
                                                                monkeypatch):
    """The ordering is the safety property. If the sign-in went first and the data
    delete then failed, somebody would be locked out of an account whose data is still
    on the box; this way round a failure is harmless and retryable."""
    from app import auth as auth_mod

    order = []

    import app.main as main
    real_remove = main.remove_member
    monkeypatch.setattr(main, "remove_member",
                        lambda *a, **k: (order.append("data"), real_remove(*a, **k))[1])
    monkeypatch.setattr(auth_mod, "delete_firebase_account",
                        lambda tok: (order.append("sign-in"),
                                     auth_mod.DeletionOutcome.REMOVED)[1])

    _sign_in(signed_in, token_for)
    r = signed_in.delete("/api/account", headers=auth_header(token_for()))

    assert r.status_code == 200
    assert order == ["data", "sign-in"]
    assert r.json()["sign_in"] == "removed"


def test_the_response_says_when_the_sign_in_survived(signed_in, token_for, monkeypatch):
    from app import auth as auth_mod

    monkeypatch.setattr(auth_mod, "delete_firebase_account",
                        lambda tok: auth_mod.DeletionOutcome.NEEDS_RECENT_LOGIN)
    _sign_in(signed_in, token_for)
    body = signed_in.delete("/api/account", headers=auth_header(token_for())).json()

    assert body["deleted"] == ALLOWED
    assert body["sign_in"] == "stale", "the data went; say so about the rest"


def test_the_token_never_leaves_the_server(signed_in, token_for):
    """`User` carries the raw bearer token so the delete can use it. No endpoint may
    hand it back — the same rule the Anthropic key has."""
    _sign_in(signed_in, token_for)
    raw = token_for()

    for path in ("/api/auth/me", "/api/org", "/api/state", "/api/settings"):
        body = signed_in.get(path, headers=auth_header(raw)).text
        assert raw not in body, f"{path} echoed the caller's ID token back"
