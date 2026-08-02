"""API-key storage. (docs/PLAN.md §3, deliverable 5)

CLAUDE.md §2 says "Mauri never sees a terminal, a repo, a config file, or an API key."
The second half of that has changed: she now pastes a key into a Settings page, because
she is the one who owns the bill (§11 Q6) and there is no other honest place to put it.
The rule that survives is the one that matters — she should never have to *handle* a key
outside that single box.

Three properties, each of which is tested:

  1. The key is never written to disk in plaintext. It is encrypted with Fernet
     (AES-128-CBC + HMAC) under a key file created at 0600 next to the database.
  2. The key is never returned to the browser. Every read path yields a masked hint
     ("sk-ant-…4f2a") and a boolean. There is no endpoint that returns the secret.
  3. The key never reaches a log line. Errors report the failure, not the value.

Honest about the threat model: the key file sits next to the database, so anyone with
read access to `data/` has both. This defends against the realistic cases — the DB
getting copied into a shared folder, attached to a bug report, or committed by accident
— not against an attacker who already owns the machine. Full key management is a
deployment concern and is written up in HANDOFF.md rather than pretended at here.
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

log = logging.getLogger(__name__)

KEYFILE_NAME = ".fernet-key"
SETTING_NAME = "anthropic_api_key"


def _keyfile_path() -> Path:
    from .db import db_path

    override = os.environ.get("RISE_KEYFILE")
    if override:
        return Path(override)
    return db_path().parent / KEYFILE_NAME


def _fernet():
    from cryptography.fernet import Fernet

    path = _keyfile_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write at 0600 from the start rather than chmod-ing after — no window in
        # which the material exists world-readable.
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, Fernet.generate_key())
        finally:
            os.close(fd)
    else:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return Fernet(path.read_bytes())


def encrypt(secret: str) -> str:
    return _fernet().encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str | None:
    """Returns None rather than raising: a key file rotated out from under a stored
    token is a "please paste it again", not a crash on every request."""
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        log.warning("stored API key could not be decrypted (%s) — treating as unset",
                    type(exc).__name__)
        return None


def mask(secret: str | None) -> str | None:
    """What the browser is allowed to see. Enough to recognise which key is stored,
    not enough to use it."""
    if not secret:
        return None
    if len(secret) <= 12:
        return "…" + secret[-4:]
    return f"{secret[:7]}…{secret[-4:]}"


# --- stored-key access --------------------------------------------------------

def store_api_key(conn, secret: str) -> None:
    from .db import now_iso

    conn.execute(
        "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (SETTING_NAME, encrypt(secret), now_iso()),
    )


def clear_api_key(conn) -> None:
    from .db import now_iso

    conn.execute(
        "INSERT INTO settings(key, value, updated_at) VALUES(?,NULL,?) "
        "ON CONFLICT(key) DO UPDATE SET value=NULL, updated_at=excluded.updated_at",
        (SETTING_NAME, now_iso()),
    )


def read_api_key(conn) -> str | None:
    """The plaintext key, for server-side use only. Never send this to a client."""
    row = conn.execute(
        "SELECT value FROM settings WHERE key=?", (SETTING_NAME,)
    ).fetchone()
    if row is None or not row["value"]:
        return None
    return decrypt(row["value"])


def effective_api_key(conn=None) -> str | None:
    """The key the pipeline should use.

    Settings wins over the environment: the point of the Settings page is that RISE can
    change the key without anyone touching a file. `ANTHROPIC_API_KEY` stays as the
    fallback so the CLI, the tests, and the GitHub Actions run all keep working.
    """
    if conn is not None:
        stored = read_api_key(conn)
        if stored:
            return stored
    else:
        from .db import session

        try:
            with session() as c:
                stored = read_api_key(c)
            if stored:
                return stored
        except Exception as exc:  # noqa: BLE001 — no DB yet is a normal CLI state
            log.debug("no settings database available (%s)", exc)
    return os.environ.get("ANTHROPIC_API_KEY") or None
