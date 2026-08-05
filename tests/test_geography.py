"""The `org_location` setting has to actually filter.

Before this, `SERVICE_AREA_GEOGRAPHY` and `GEOGRAPHY_EXCLUSIVE` were hardcoded to San
Diego and California. A Chicago nonprofit could type "Chicago, Illinois" into Settings,
watch it save, and still have every Illinois-only grant rejected for free — in the
deterministic tier, which never explains itself to the user. The setting was fully
plumbed through the UI and the API and changed nothing.

The rule these tests hold to: the vocabulary of *places* is universal and lives in code;
which of those places is **yours** is configuration.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.filters import geography_ok, service_area_terms  # noqa: E402


# --- reading the setting ------------------------------------------------------

def test_a_city_and_state_both_count_as_ours():
    terms = service_area_terms("San Diego County, California")
    assert "california" in terms
    assert "san diego county" in terms
    assert "san diego" in terms          # "County" stripped


def test_a_city_alone_still_picks_up_its_state():
    """A page saying "Illinois organizations only" is about a Chicago nonprofit even
    though it never says Chicago."""
    assert "illinois" in service_area_terms("Chicago")


def test_an_unset_location_yields_nothing():
    assert service_area_terms("") == frozenset()
    assert service_area_terms("   ") == frozenset()


# --- the filter ---------------------------------------------------------------

CHICAGO = service_area_terms("Chicago, Illinois")
SAN_DIEGO = service_area_terms("San Diego County, California")


def test_the_chicago_org_keeps_illinois_grants():
    """The reported bug, directly: this was rejected for free before."""
    ok, _ = geography_ok("Open only to organizations in Illinois.", CHICAGO)
    assert ok is True


def test_the_chicago_org_still_drops_texas_only_grants():
    ok, detail = geography_ok("Limited to nonprofits in Texas.", CHICAGO)
    assert ok is False
    assert "texas" in detail.lower()


def test_the_same_page_is_judged_differently_for_two_orgs():
    """The whole point. One page, two orgs, opposite answers."""
    page = "Grants are restricted to organizations in California."
    assert geography_ok(page, SAN_DIEGO)[0] is True
    assert geography_ok(page, CHICAGO)[0] is False


def test_an_org_that_has_not_said_where_it_works_rejects_nothing():
    """Empty settings must disable the filter, not fall back to somebody else's region.
    Guessing is exactly what the hardcoded pattern did."""
    ok, _ = geography_ok("Limited to nonprofits in Texas.", frozenset())
    assert ok is True


@pytest.mark.parametrize("text", [
    "This program is national in scope.",
    "Open to nonprofits across the country.",
    "Available in all 50 states.",
])
def test_national_funders_are_never_a_geographic_reject(text):
    assert geography_ok(text, CHICAGO)[0] is True


def test_silence_about_geography_is_eligible():
    """Rejecting on silence would drop most national funders."""
    ok, _ = geography_ok("A grant for arts education programs.", CHICAGO)
    assert ok is True


def test_a_national_page_that_also_names_a_state_is_kept():
    """"National, with a focus on Texas" is not a Texas-only restriction."""
    page = "A national program. Priority given to applicants in Texas."
    assert geography_ok(page, CHICAGO)[0] is True


def test_the_pilots_own_region_still_works():
    """The behaviour the hardcoded version had, now reached through configuration."""
    assert geography_ok("Serving only organizations in New York.", SAN_DIEGO)[0] is False
    assert geography_ok("Open only to applicants in San Diego.", SAN_DIEGO)[0] is True
