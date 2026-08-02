"""Reads the Config tab of the Sheet. (CLAUDE.md §4, §9)

Closes a hole in the spec: §4 requires the run to read config from the Sheet and to
check the kill switch at step 0, but §10's file list gave that job to nobody —
sinks/sheets.py is described as a write path. This module owns the read.

Config lives in the Sheet and nowhere else (§3: editing config in the dashboard is a
non-goal). Every key here is plain English so that the tab stays editable by someone
who has never seen a config file.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from .models import Program
from .sources import Tier

log = logging.getLogger(__name__)

CONFIG_TAB = "Config"

# MIN_AWARD is the primary filter and the whole point of the product (§11 Q1).
# CLAUDE.md is explicit: do not guess at it. This placeholder exists so the pipeline
# runs before Mauri answers; it is not an answer, and the run says so out loud.
MIN_AWARD_PLACEHOLDER = 25_000
MIN_AWARD_IS_PLACEHOLDER = True  # TODO(Mauri, §11 Q1): set the real floor, flip to False


@dataclass
class Config:
    """Runtime settings. Defaults match the Config tab's shipped values."""

    enabled: bool = True                     # ENABLED — the kill switch (§8)
    min_award: int = MIN_AWARD_PLACEHOLDER   # MIN_AWARD (§11 Q1 — placeholder)
    min_award_is_placeholder: bool = MIN_AWARD_IS_PLACEHOLDER
    max_opportunities: int = 12              # sized for a 1-hour review (§9)
    programs_active: list[Program] = field(
        default_factory=lambda: [Program.RULFP, Program.RESILIENCE, Program.ARTS]
    )
    run_day: str = "Wednesday"
    run_time: str = "23:00"
    max_tier: Tier = Tier.WARM               # crawl scope; tier 1 for Block 1
    weekly_budget_usd: float = 1.00          # hard ceiling (§8)
    min_deadline_runway_days: int = 14       # reject inside this window (§7)

    @property
    def warnings(self) -> list[str]:
        out: list[str] = []
        if self.min_award_is_placeholder:
            out.append(
                f"MIN_AWARD is a PLACEHOLDER (${self.min_award:,}). CLAUDE.md §11 Q1 is "
                "unanswered — the award floor has not been set by Mauri. Every count "
                "below is provisional until it is."
            )
        return out


# --- Sheet reader -------------------------------------------------------------

_TRUE = {"true", "yes", "y", "1", "on", "enabled"}
_FALSE = {"false", "no", "n", "0", "off", "disabled"}


def _as_bool(value: str, default: bool) -> bool:
    v = str(value).strip().casefold()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return default


def _as_int(value: str, default: int) -> int:
    """Tolerant of what a person actually types: '$25,000', '25k', '25 000'."""
    v = str(value).strip().casefold().replace("$", "").replace(",", "").replace(" ", "")
    if not v:
        return default
    mult = 1
    if v.endswith("k"):
        v, mult = v[:-1], 1_000
    elif v.endswith("m"):
        v, mult = v[:-1], 1_000_000
    try:
        return int(float(v) * mult)
    except ValueError:
        log.warning("Config: could not read %r as a number, using %s", value, default)
        return default


class ConfigUnavailable(RuntimeError):
    """The Config tab could not be read while running in strict mode."""


def load_config(sheet_id: str | None = None, credentials_path: str | None = None,
                strict: bool | None = None) -> Config:
    """Read the Config tab.

    Without credentials, falls back to shipped defaults — the agent has to be
    runnable before the Sheet exists.

    With `strict` (set `RISE_STRICT_CONFIG=1`, which the scheduled job does), an
    unreadable Config tab raises instead of falling back. This matters more than it
    looks: `ENABLED` is Mauri's kill switch, and a silent fall back to defaults means
    `enabled=True`. She would set `ENABLED` to `FALSE`, a transient Sheets outage
    would swallow it, and the agent would run anyway — the one failure the kill
    switch exists to prevent. Refusing to run on an unreadable config is the correct
    direction to fail.
    """
    sheet_id = sheet_id or os.environ.get("RISE_SHEET_ID")
    credentials_path = credentials_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if strict is None:
        strict = os.environ.get("RISE_STRICT_CONFIG", "").strip() in _TRUE

    if not sheet_id or not credentials_path:
        if strict:
            raise ConfigUnavailable(
                "RISE_STRICT_CONFIG is on but RISE_SHEET_ID / "
                "GOOGLE_APPLICATION_CREDENTIALS are not set. Refusing to run without "
                "reading the kill switch."
            )
        log.info("No Sheet credentials — using shipped defaults.")
        return Config()

    try:
        import gspread  # imported lazily so the agent runs without Sheets installed

        gc = gspread.service_account(filename=credentials_path)
        tab = gc.open_by_key(sheet_id).worksheet(CONFIG_TAB)
        raw = {
            str(row[0]).strip().upper(): str(row[1]).strip()
            for row in tab.get_all_values()
            if len(row) >= 2 and row[0]
        }
    except Exception as exc:  # noqa: BLE001
        if strict:
            raise ConfigUnavailable(
                f"Could not read the {CONFIG_TAB} tab ({exc}). Refusing to run: the "
                "ENABLED kill switch lives there and we cannot confirm it is on."
            ) from exc
        log.warning("Could not read the Config tab (%s) — using shipped defaults.", exc)
        return Config()

    cfg = Config()
    cfg.enabled = _as_bool(raw.get("ENABLED", ""), cfg.enabled)
    if "MIN_AWARD" in raw and raw["MIN_AWARD"]:
        cfg.min_award = _as_int(raw["MIN_AWARD"], cfg.min_award)
        # A human typed a number into the tab, so it is no longer our placeholder.
        cfg.min_award_is_placeholder = False
    cfg.max_opportunities = _as_int(raw.get("MAX_OPPORTUNITIES", ""), cfg.max_opportunities)
    cfg.run_day = raw.get("RUN_DAY") or cfg.run_day
    cfg.run_time = raw.get("RUN_TIME") or cfg.run_time

    if raw.get("PROGRAMS_ACTIVE"):
        wanted = {p.strip().upper() for p in raw["PROGRAMS_ACTIVE"].split(",")}
        chosen = [p for p in Program if p.value in wanted]
        if chosen:
            cfg.programs_active = chosen
        else:
            log.warning("PROGRAMS_ACTIVE=%r matched no program — keeping all three.",
                        raw["PROGRAMS_ACTIVE"])
    return cfg
