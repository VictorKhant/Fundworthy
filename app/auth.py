"""Sign-in. Firebase Authentication in the browser, verified here. (FUTURE.md §2)

The moment this app is reachable from the internet it is a box holding somebody's
Anthropic key behind a Re-run button. Without a login, anyone who finds the URL can spend
the org's money. So: every `/api/*` route requires a signed-in, allow-listed person, and
the two routes that cannot require one (`/api/health`, and this module's own config
endpoint) hold nothing worth having.

**Two separate questions, and Firebase only answers the first.**

    Who is this?        Firebase. A Google or password sign-in, an ID token, a
                        verified email.
    Are they allowed?   ALLOWED_EMAILS. Ours, and ours alone.

**A verified address is the whole basis of both answers.** Google verifies before it
hands us anything, but Firebase's email/password provider will mint an account for any
address a stranger can type. So `verify()` refuses an unverified token outright — without
that, registering someone else's address with a password of your choosing walks through
the allow-list, and under open sign-up claims an organization keyed on an address you do
not own. Everything below treats "verified" as load-bearing, not cosmetic.

Firebase will happily authenticate any Google account on earth. It is an identity
provider, not a door policy — so the second question has to be answered here, and a
deployment answers it with `ALLOWED_EMAILS`: set it and only those addresses get in;
leave it out and any nonprofit may sign up, which is the default because that is what
this product is.

**Why open sign-up is safe now and was not before.** The allow-list originally existed
for one reason: the app held a single shared Anthropic key, so anyone who found the URL
could press Re-run and spend the pilot org's money. Per-org keys removed that — a new
sign-up gets an empty organization with no key, and cannot spend anything until it
supplies its own. What it can still do is make the server crawl on the free tier, which
is why `app/runner.py` caps runs per org per day.

One thing open sign-up made dangerous that private did not: `DEFAULT_ORG_ID` holds the
pilot's data and their key, and it used to be adopted by whoever signed in first. That is
now `FUNDWORTHY_PILOT_EMAILS` — see `app/db.py: _claims_default_org`.

**Why not firebase-admin.** A Firebase ID token is an ordinary RS256 JWT signed by
Google. Verifying it needs the public keys, the issuer, the audience, and an expiry
check — about forty lines. `firebase-admin` does the same thing, but drags in gRPC and
expects a service-account JSON on disk: one more secret to protect, back up and rotate on
a box whose whole appeal is that it holds almost nothing. The public keys below are
public.

**Off by default.** No `FIREBASE_PROJECT_ID` means no auth, which is what keeps the
promise in CLAUDE.md §6 that `./start.sh` opens straight onto the dashboard. That is safe
for exactly one reason: a local install binds to `127.0.0.1`. The deploy that changes the
binding is the deploy that sets these variables — see docs/DEPLOY-ORACLE.md §8.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from fastapi import Header, HTTPException

log = logging.getLogger(__name__)

# Google's public keys for Firebase ID tokens, in JWKS form. Public, unauthenticated,
# and rotated by Google every few hours — PyJWKClient re-fetches on a cache miss, so a
# rotation costs one request rather than a failed sign-in.
#
# `/jwk/`, singular. `/jwks/` is a 404, and since the tests stand in for this fetch
# rather than making it, the first thing that would notice is a real person unable to
# sign in. `tests/test_auth.py::test_googles_key_endpoint_is_the_real_one` is the
# opt-in network check that keeps this honest.
JWKS_URL = (
    "https://www.googleapis.com/service_accounts/v1/jwk/"
    "securetoken@system.gserviceaccount.com"
)


@dataclass(frozen=True)
class Config:
    project_id: str
    web_api_key: str
    auth_domain: str
    # Empty means **open sign-up**: any Google account with a verified address may sign
    # in. See `configure()` for why that is now a reasonable default rather than a hole.
    allowed_emails: frozenset[str]
    open_signup: bool = False
    # Whether Firebase's email/password provider is switched on for this project. The
    # server cannot detect it, so it is declared — showing a password form against a
    # project that has the provider disabled fails with `auth/operation-not-allowed`,
    # which reads as a broken app rather than a deployment that made a choice.
    password_auth: bool = False

    @property
    def issuer(self) -> str:
        return f"https://securetoken.google.com/{self.project_id}"


@dataclass(frozen=True)
class User:
    email: str
    name: str
    uid: str


_config: Config | None = None
_jwks_client = None


def _emails(raw: str) -> frozenset[str]:
    """Addresses compare casefolded, because nobody types their own email the same way
    twice and `Admin@Org.org` being locked out of their own dashboard is not a security
    win."""
    return frozenset(e.strip().casefold() for e in raw.split(",") if e.strip())


def configure() -> Config | None:
    """Read the environment once, at startup. Returns None when auth is off.

    A half-configured deployment is refused rather than started. The failure this guards
    against is quiet and total: `FIREBASE_PROJECT_ID` set but `ALLOWED_EMAILS` empty
    would authenticate every Google account in existence and let all of them in. An app
    that will not boot, with the reason in `journalctl`, is a far better outcome than an
    app that boots and is wide open.
    """
    global _config

    project_id = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    if not project_id:
        _config = None
        log.info("Sign-in is off (no FIREBASE_PROJECT_ID). Local, single-user mode.")
        return None

    # No allow-list means anyone may sign up, and that is the default rather than an
    # opt-in. There was a `FUNDWORTHY_OPEN_SIGNUP` flag here for one commit; it was
    # ceremony. Fundworthy is a product any nonprofit can use, so "open" is the shape,
    # and `ALLOWED_EMAILS` is the thing you set when you want the unusual one.
    allowed = _emails(os.getenv("ALLOWED_EMAILS", ""))

    web_api_key = os.getenv("FIREBASE_WEB_API_KEY", "").strip()
    if not web_api_key:
        raise RuntimeError(
            "FIREBASE_PROJECT_ID is set but FIREBASE_WEB_API_KEY is not. The browser "
            "needs it to reach Firebase. Copy it from Firebase console → Project "
            "settings → General → Your apps → SDK setup and configuration."
        )

    _config = Config(
        project_id=project_id,
        web_api_key=web_api_key,
        auth_domain=os.getenv("FIREBASE_AUTH_DOMAIN", "").strip()
            or f"{project_id}.firebaseapp.com",
        allowed_emails=allowed,
        open_signup=not allowed,
        password_auth=os.getenv("FIREBASE_PASSWORD_AUTH", "").strip().lower() in {
            "1", "true", "yes", "on"},
    )
    if allowed:
        log.info("Sign-in is on (private). Firebase project %s, %d address(es) allowed.",
                 project_id, len(allowed))
    else:
        log.info("Sign-in is on (open sign-up). Firebase project %s — any Google "
                 "account with a verified address may create an organization.",
                 project_id)
    return _config


def config() -> Config | None:
    return _config


def enabled() -> bool:
    return _config is not None


def browser_config() -> dict:
    """What the sign-in page needs, served rather than baked into the build.

    The alternative was `VITE_FIREBASE_*` variables at build time, which would make
    changing a hostname or moving projects a `npm run build` on the VM. This way `.env`
    plus a restart is the whole operation, and one dashboard bundle works identically
    with sign-in on or off.

    `api_key` here is Firebase's *web* API key, which is a public project identifier —
    it appears in every Firebase web app's page source by design, and grants nothing on
    its own (the allow-list and Firebase's own rules are what gate access). It is not
    remotely the same kind of thing as the Anthropic key, which has no endpoint at all.
    """
    if _config is None:
        return {"enabled": False}
    return {
        "enabled": True,
        "project_id": _config.project_id,
        "api_key": _config.web_api_key,
        "auth_domain": _config.auth_domain,
        # So the sign-in page can offer "create an account" rather than implying that
        # everyone arriving already has one.
        "open_signup": _config.open_signup,
        # Which ways in to offer. The page renders what the project actually has enabled
        # rather than a fixed set, so it can never show a form that Firebase will refuse.
        "password_auth": _config.password_auth,
    }


def verify(token: str) -> User:
    """A Firebase ID token → the person it belongs to, or an HTTPException.

    Three answers, and the difference matters to whoever is standing at the door:

        401  something is wrong with the token — sign in again
        403  the token is fine and you are still not coming in — signing in again
             will not help, ask to be added to the allow-list
        503  we could not check, because we could not reach Google — not your fault
    """
    import jwt  # imported here so a no-auth install never needs the dependency

    cfg = _config
    if cfg is None:  # pragma: no cover — the dependency checks this first
        raise HTTPException(500, "Sign-in is not configured.")

    global _jwks_client
    if _jwks_client is None:
        from jwt import PyJWKClient

        # Cache the key set for an hour. Without this every single API call — and the
        # dashboard polls every 1.5s during a run — would fetch Google's keys again.
        _jwks_client = PyJWKClient(JWKS_URL, cache_jwk_set=True, lifespan=3600)

    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
    except jwt.exceptions.PyJWKClientConnectionError as exc:
        # We could not fetch Google's signing keys — an outage, no egress, or a machine
        # with no CA store. That is our problem, not the user's, and answering 401 would
        # send a perfectly valid person round the sign-in loop forever.
        log.error("Could not fetch Firebase signing keys from %s: %s", JWKS_URL, exc)
        raise HTTPException(
            503, "Could not reach Google to check your sign-in. Try again in a moment."
        ) from exc
    except jwt.exceptions.PyJWTError as exc:
        # Everything else this call can raise is about the token, not about us: it is not
        # a JWT at all, or its `kid` matches no key Google publishes. Both are 401.
        #
        # This clause is here because it was missing: `Bearer garbage` reached the JWKS
        # client, raised DecodeError on the way to reading the header, escaped, and came
        # back as a 500 with a stack trace — an unauthenticated caller able to fill the
        # log with tracebacks, and the wrong answer besides.
        log.warning("Rejected an ID token before key lookup: %s", type(exc).__name__)
        raise HTTPException(401, "Sign in to use Fundworthy.") from exc

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],          # never trust the token's own alg header
            audience=cfg.project_id,       # a token minted for another project is not ours
            issuer=cfg.issuer,
            options={"require": ["exp", "iat", "aud", "iss", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        # Firebase ID tokens last an hour; the browser refreshes them silently, so this
        # is a tab that was asleep, not an attack.
        raise HTTPException(401, "Your sign-in expired. Reload the page.") from exc
    except Exception as exc:  # noqa: BLE001 — every other failure is one answer
        log.warning("Rejected an ID token: %s", type(exc).__name__)
        raise HTTPException(401, "Sign in to use Fundworthy.") from exc

    email = (claims.get("email") or "").strip()

    if not email:
        raise HTTPException(403, "That account has no email address.")

    # **The load-bearing check for password sign-in.** Google always verifies the address
    # it hands us, so under Google-only this never fired. With the email/password provider
    # enabled it fires constantly and on purpose: Firebase will create an account for any
    # address anyone can type, so without this, registering `admin@the-org.org` with a
    # password of your choosing would walk you straight through the allow-list — and under
    # open sign-up, into an org keyed on an address you do not own.
    #
    # Clicking the link in the email is what closes that gap. So the message names the
    # address and says what to do, because unlike the refusals below this one is entirely
    # the user's to fix, and "no verified email address" told them nothing.
    if not claims.get("email_verified"):
        log.info("Refused sign-in for %s — address not verified yet.", email)
        raise HTTPException(
            403,
            f"Check your inbox — {email} has not been verified yet. Open the link in "
            "the email from Fundworthy, then sign in again.",
        )

    # An empty allow-list is open sign-up, not a misconfiguration: leaving `ALLOWED_EMAILS`
    # out is how a deployment says "any nonprofit may sign up", which is the default.
    if cfg.allowed_emails and email.casefold() not in cfg.allowed_emails:
        log.warning("Refused sign-in for %s — not on the allow-list.", email)
        raise HTTPException(
            403, f"{email} is not on this install's allow-list. Ask whoever set "
                 "Fundworthy up to add you.")

    return User(email=email, name=(claims.get("name") or email), uid=claims["sub"])


def require_user(authorization: str | None = Header(default=None)) -> User | None:
    """The dependency on every `/api/*` route. A no-op when sign-in is off.

    Declared once, on the router (`app/main.py`), rather than route by route — a gate
    you have to remember to add to each new endpoint is a gate that will eventually be
    forgotten on the one that matters.
    """
    if _config is None:
        return None

    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            401, "Sign in to use Fundworthy.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify(token.strip())
