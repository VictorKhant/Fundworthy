"""The two palettes, checked against the rules that are correctness and not taste.

`styles.css` opens with four things that must survive any restyle — the sourced-vs-
inferred distinction above all. Dark mode doubles the surface those rules have to hold
on, and the failure is silent: a token defined only in `:root` does not error in the dark
theme, it just keeps its light value, so one wrong chip quietly starts asserting
something §6 says we may never assert.

No browser here. These are questions about the stylesheet that can be answered by
reading it, which means they run in CI with everything else instead of needing somebody
to remember to look.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS = Path(__file__).resolve().parents[1] / "dashboard" / "src" / "styles.css"
DARK_SELECTOR = 'body[data-fw-theme="dark"]'

# Tokens that are deliberately light-only: structural or type choices with no colour in
# them, plus the aliases that resolve through another token and therefore follow it.
THEME_NEUTRAL = {
    "sidebar", "display", "ui", "mono",     # layout + font stacks
    "ok", "warn", "off",                    # aliases: var(--accent) / var(--clay-deep)
    "invert", "on-invert",                  # light values are var(--fg) / var(--bg)
    "oauth-1", "oauth-2", "oauth-3", "oauth-4",  # mid-tones, legible on either ground
}


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _block(selector: str) -> dict[str, str]:
    css = _strip_comments(CSS.read_text())
    start = css.index(selector)
    end = css.index("}", start)
    return {k: v.strip()
            for k, v in re.findall(r"--([a-z0-9-]+):\s*([^;]+);", css[start:end])}


@pytest.fixture(scope="module")
def palettes() -> tuple[dict, dict]:
    light = _block(":root")
    dark = _block(DARK_SELECTOR)
    return light, dark


def _rgb(value: str) -> tuple[float, float, float]:
    h = value.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _luminance(value: str) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def test_dark_mode_overrides_every_colour_token(palettes):
    """The silent failure. A colour token added to `:root` and forgotten in the dark
    block keeps its LIGHT value on a dark ground — a paper-white chip on near-black,
    which nobody notices until a user reports it."""
    light, dark = palettes
    colourful = {k: v for k, v in light.items()
                 if k not in THEME_NEUTRAL and re.match(r"#|rgba?\(", v)}
    missing = sorted(set(colourful) - set(dark))
    assert missing == [], (
        f"{DARK_SELECTOR} does not override: {missing}. Add them there, or to "
        "THEME_NEUTRAL in this test if they genuinely read on both grounds."
    )


def test_no_hard_coded_colours_outside_the_palette_blocks():
    """Every colour lives in a token, or dark mode cannot reach it."""
    css = _strip_comments(CSS.read_text())
    body = css[css.index("* { box-sizing"):]
    body = body.replace(css[css.index(DARK_SELECTOR):css.index("}", css.index(DARK_SELECTOR))], "")

    stray = [m for m in re.findall(r"#[0-9A-Fa-f]{3,8}\b", body)]
    # Shadows are allowed to be literal rgba(0,0,0,…) — they are opacity, not palette.
    assert stray == [], f"hard-coded colours outside the palette blocks: {sorted(set(stray))}"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_an_ai_judgement_never_looks_like_a_sourced_value(palettes, theme):
    """`.chip.inferred` is a dashed --dash border with no fill; `.chip.strong` is a solid
    --accent-soft fill. If the dashed border stops reading, an AI guess starts looking
    like a quote off the funder's page, which is the §6 rule the whole app rests on.

    The specific dark-mode trap: --dash at roughly --line's value disappears entirely on
    a dark card. So the test is not "is --dash defined" but "is it clear of --line".
    """
    light, dark = palettes
    t = light if theme == "light" else {**light, **dark}

    dash_on_card = contrast(t["dash"], t["card"])
    line_on_card = contrast(t["line"], t["card"])

    assert dash_on_card > line_on_card * 1.2, (
        f"{theme}: --dash ({dash_on_card:.2f}) is not meaningfully stronger than the "
        f"ordinary --line ({line_on_card:.2f}) against a card, so the dashed AI border "
        "reads as a plain edge"
    )
    # And the sourced chip must be genuinely filled, not a tint of the card.
    assert contrast(t["accent-soft"], t["card"]) > 1.05, \
        f"{theme}: --accent-soft is indistinguishable from --card, so a sourced chip has no fill"


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("fg,bg,label", [
    ("fg", "bg", "body text on the page"),
    ("body", "card", "secondary text on a card"),
    ("on-accent", "accent", "a primary button's label"),
    ("accent-deep", "accent-soft", "a sourced chip"),
    ("notice-fg", "notice-bg", "a blocker message"),
    ("danger", "card", "a destructive action"),
])
def test_text_carries_on_its_own_background(palettes, theme, fg, bg, label):
    """WCAG AA for normal text, in both themes.

    `--muted` on `--card` is deliberately not in this list: it sits at 3.68 in the
    light palette, which predates dark mode and is the researched theme. Raising it is
    a visual change to every helper line in the app and belongs to its own decision,
    not to this one. The dark value is 4.87, so dark mode does not inherit the problem.
    """
    light, dark = palettes
    t = light if theme == "light" else {**light, **dark}
    ratio = contrast(t[fg], t[bg])
    assert ratio >= 4.5, f"{theme}: {label} is {ratio:.2f}:1, under the 4.5:1 floor"
