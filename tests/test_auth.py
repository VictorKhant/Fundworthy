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
    assert me == {"signed_in": True, "auth_required": True,
                  "email": ALLOWED, "name": "Test Admin"}


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
    """Google sign-in always verifies. If a future deployment ever switches on Firebase's
    email/password provider, anyone could register the allow-listed address without ever
    proving they own it."""
    r = signed_in.get("/api/state",
                      headers=auth_header(token_for(email_verified=False)))
    assert r.status_code == 403


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
