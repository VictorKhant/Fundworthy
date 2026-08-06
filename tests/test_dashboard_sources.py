"""Static checks on the React source, run by the same pytest that gates the deploy.

There is no linter in front of the dashboard, and `vite build` is not one: it resolves
modules and bundles them, and an identifier that is never declared anywhere is not a
build error — it is a `ReferenceError` thrown at render time, in the browser, by
whichever component happens to use it.

That is not hypothetical. `<Busy>` was added to SearchSettings.jsx without its import.
The build passed, 300 tests passed, the deploy went green, and the first person to press
"Adjust search settings" on the live site got a white page. Nothing in the pipeline was
looking at the one thing that was wrong.

A real ESLint setup would be better and is worth doing. This is the cheap version that
catches the specific class of mistake that has actually happened, costs no dependency,
and runs offline in milliseconds — the same shape as
`test_no_env_var_escapes_the_scrub`, for the same reason.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "dashboard" / "src"

# Names that are legitimately in scope without an import or a declaration.
_AMBIENT = {"React", "Fragment"}

# <Foo …>, <Foo.Bar …> and </Foo>. Only capitalised tags: lowercase ones are HTML.
_JSX_TAG = re.compile(r"</?([A-Z][A-Za-z0-9_]*)")

# Anything the file brings into scope. Deliberately generous — the point is to find
# names with NO possible source, so a false negative is much cheaper than a false alarm
# that makes somebody delete this test.
_IMPORT = re.compile(r"^\s*import\s+(?:type\s+)?(.+?)\s+from\s+['\"]", re.MULTILINE)
_DECLARED = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class|const|let|var)\s+"
    r"([A-Za-z_$][\w$]*)", re.MULTILINE)
# `const { Component, title } = …` and `const [A, B] = …`, including renames and
# defaults, which is how Tutorial.jsx gets the component it renders.
_DESTRUCTURED = re.compile(r"^\s*(?:const|let|var)\s*[{\[]([^}\]]*)[}\]]\s*=", re.MULTILINE)


def _names_in_scope(source: str) -> set[str]:
    names: set[str] = set(_AMBIENT)

    for clause in _IMPORT.findall(source):
        # `Spinner, { Busy }` · `{ a as b, c }` · `* as ns` · `Default`
        for part in clause.replace("{", ",").replace("}", ",").split(","):
            token = part.strip()
            if not token:
                continue
            if " as " in token:
                token = token.split(" as ")[-1].strip()
            token = token.removeprefix("*").strip()
            if token:
                names.add(token)

    names.update(_DECLARED.findall(source))

    for group in _DESTRUCTURED.findall(source):
        for part in group.split(","):
            token = part.split("=")[0].strip()
            if ":" in token:
                token = token.split(":")[-1].strip()
            token = token.removeprefix("...").strip()
            if token:
                names.add(token)

    # Locally defined components, including `const Foo = (props) => …` — already covered
    # by _DECLARED, but function parameters can also supply one (`function Step({ n })`).
    for params in re.findall(r"function\s+[A-Za-z_$][\w$]*\s*\(([^)]*)\)", source):
        for part in params.replace("{", ",").replace("}", ",").split(","):
            token = part.split("=")[0].split(":")[0].strip().removeprefix("...").strip()
            if token:
                names.add(token)

    return names


def _sources() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.jsx"))


def test_there_are_jsx_files_to_check():
    """A path typo here would make every check below vacuously pass."""
    assert len(_sources()) > 10, f"expected the dashboard's components under {SRC}"


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.name)
def test_every_component_a_file_renders_is_actually_in_scope(path: Path):
    """The white-page check.

    `<Busy>` with no `import { Busy }` builds cleanly and throws when React renders it,
    so the failure lands on a user rather than in CI.
    """
    source = path.read_text(encoding="utf-8")
    in_scope = _names_in_scope(source)
    used = {tag.split(".")[0] for tag in _JSX_TAG.findall(source)}

    missing = sorted(used - in_scope)
    assert not missing, (
        f"{path.relative_to(SRC.parent.parent)} renders {', '.join(missing)} but nothing "
        "imports or defines it. This builds fine and throws a ReferenceError in the "
        "browser — a blank page for whoever opens that view."
    )
