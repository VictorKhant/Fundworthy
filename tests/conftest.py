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

import pytest


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
