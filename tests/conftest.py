"""Shared pytest configuration.

The suite is offline: no network, no API key, no model calls. That is what makes it safe
to run on every change and in CI without spending anything.

One test is an exception. `test_googles_key_endpoint_is_the_real_one` checks that the URL
we fetch Firebase's signing keys from is a URL that exists — the one fact about sign-in
that a mock cannot verify, and one that has already been wrong once. It is deselected by
default and runs on request:

    .venv/bin/python -m pytest tests/ -q            # offline, the default
    .venv/bin/python -m pytest tests/ -m network    # just the network check
"""

import os

import pytest

# Every variable that changes how the app behaves. Cleared before each test, so the suite
# gives the same answer on a laptop, in CI, and on the deployed VM.
#
# This is not hypothetical tidiness. `agent/__init__.py` calls `load_dotenv()` at import
# time, so importing anything from `agent` pulls the box's own `.env` into `os.environ`.
# On the VM that file sets FIREBASE_PROJECT_ID and ALLOWED_EMAILS — so `auth.configure()`
# switched sign-in ON during the test run and 37 API tests failed with 401s that had
# nothing to do with the code being tested. The suite passed on the machine it was
# written on and failed on the machine that mattered, which makes it worthless as the
# gate in front of a deploy.
#
# `FUNDWORTHY_DB_PATH` is the one to notice: inherited from a real `.env`, a test that
# calls `init_db()` before setting its own path would have run migrations against the
# live database.
#
# Adding a variable to the app and forgetting to add it here is a trap this list has
# already sprung twice: `FIREBASE_PASSWORD_AUTH` was missing, so a test asserting the
# password form is off passed on a laptop and failed on the VM, where `.env` switches it
# on — and it failed *as the deploy gate*, after the merge. `test_no_env_var_escapes_the_
# scrub` in tests/test_api.py now fails the moment the two drift apart, so the next one
# is caught here rather than in production.
_LEAKY_ENV = (
    "FIREBASE_PROJECT_ID", "FIREBASE_WEB_API_KEY", "FIREBASE_AUTH_DOMAIN",
    "FIREBASE_PASSWORD_AUTH",
    "ALLOWED_EMAILS", "FUNDWORTHY_PILOT_EMAILS",
    "ANTHROPIC_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS",
    "FUNDWORTHY_DB_PATH", "FUNDWORTHY_KEYFILE",
    "FUNDWORTHY_STRICT_CONFIG", "FUNDWORTHY_SHEET_ID",
    "FUNDWORTHY_MAX_RUNS_PER_DAY", "FUNDWORTHY_MAX_CONCURRENT_RUNS",
    "FUNDWORTHY_ADMIN_EMAILS",
)


@pytest.fixture(autouse=True)
def _hermetic_environment(monkeypatch, tmp_path):
    """No test inherits the deployment it happens to be running on."""
    for name in _LEAKY_ENV:
        monkeypatch.delenv(name, raising=False)

    # Somewhere harmless by default. A test that wants a real database sets its own path;
    # this only stops one that forgets from touching whatever `data/rise.db` resolves to
    # in the working directory.
    monkeypatch.setenv("FUNDWORTHY_DB_PATH", str(tmp_path / "default.db"))
    monkeypatch.setenv("FUNDWORTHY_KEYFILE", str(tmp_path / ".default-fernet-key"))

    # `auth.configure()` caches into a module global, so a test that switched sign-in on
    # would otherwise leave it on for everything that ran after it.
    from app import auth
    monkeypatch.setattr(auth, "_config", None, raising=False)
    monkeypatch.setattr(auth, "_jwks_client", None, raising=False)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "network: needs the internet; deselected unless you ask for it")


def pytest_collection_modifyitems(config, items):
    if config.getoption("-m"):
        return  # the caller said what they wanted; don't second-guess it
    skip = pytest.mark.skip(reason="needs the internet — run with `-m network`")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)

