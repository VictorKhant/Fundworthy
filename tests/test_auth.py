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


def _client(tmp_path, monkeypatch, keypair, **env):
    monkeypatch.setenv("FUNDWORTHY_DB_PATH", str(tmp_path / "rise.db"))
    monkeypatch.setenv("FUNDWORTHY_KEYFILE", str(tmp_path / ".fernet-key"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    init_db()

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

def test_a_project_without_an_allow_list_refuses_to_boot(tmp_path, monkeypatch, keypair):
    """The dangerous middle state: sign-in on, allow-list empty. Firebase would
    authenticate every Google account on earth and let all of them in. The app must not
    start rather than start open."""
    monkeypatch.setenv("ALLOWED_EMAILS", "")
    with pytest.raises(RuntimeError, match="ALLOWED_EMAILS"):
        _client(tmp_path, monkeypatch, keypair, FIREBASE_PROJECT_ID=PROJECT)


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
                 FIREBASE_WEB_API_KEY="AIza-not-a-secret",
                 FUNDWORTHY_OPEN_SIGNUP="1") as c:
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
                 FIREBASE_WEB_API_KEY="AIza-not-a-secret",
                 FUNDWORTHY_OPEN_SIGNUP="1") as c:
        token = jwt.encode(
            {"iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT,
             "sub": "uid-x", "iat": int(time.time()), "exp": int(time.time()) + 3600,
             "email": "unverified@example.org", "email_verified": False},
            keypair[0], algorithm="RS256")
        res = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 403


def test_a_deployment_must_choose_private_or_open(tmp_path, monkeypatch, keypair):
    """Neither set is a refusal to start, not a permissive default. The two are opposite
    products and guessing between them is how an install ends up open by accident."""
    monkeypatch.delenv("ALLOWED_EMAILS", raising=False)
    monkeypatch.delenv("FUNDWORTHY_OPEN_SIGNUP", raising=False)
    with pytest.raises(RuntimeError, match="ALLOWED_EMAILS nor"):
        _client(tmp_path, monkeypatch, keypair, FIREBASE_PROJECT_ID=PROJECT,
                FIREBASE_WEB_API_KEY="AIza-not-a-secret")


def test_the_sign_in_page_is_told_which_mode_it_is_in(tmp_path, monkeypatch, keypair):
    with _client(tmp_path, monkeypatch, keypair,
                 FIREBASE_PROJECT_ID=PROJECT,
                 FIREBASE_WEB_API_KEY="AIza-not-a-secret",
                 FUNDWORTHY_OPEN_SIGNUP="1") as c:
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
