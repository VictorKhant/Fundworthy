"""The local control surface: FastAPI backend + SQLite store.

CLAUDE.md §3 made "editing configuration in the dashboard" a non-goal and §4 made the
Google Sheet the product. Both are deliberately reversed here — see docs/PLAN.md §0.
The short version: a spreadsheet cell cannot express "search these three programs, with
these terms, at this floor, this week", and that is what the stakeholder asked for.
"""
