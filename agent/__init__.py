"""RISE San Diego funding opportunity agent.

Loading `.env` here, at package import, is deliberate: every entrypoint (`agent.run`,
`tests.calibration`, `sinks.sheets`) goes through this package, so there is exactly
one place credentials get picked up and no entrypoint can forget to.

`override=False` is the important flag. In GitHub Actions the secrets arrive as real
environment variables and there is no `.env` file at all — this call is a silent
no-op there. Locally the file fills in what the shell has not already set, so an
exported variable still wins over a stale checked-out file.
"""

from dotenv import load_dotenv

load_dotenv(override=False)
