import { useEffect, useState } from "react";

// Light / Dark, at the bottom of the sidebar.
//
// Two deliberate choices, both about not surprising anybody:
//
//   1. The default is light, NOT `prefers-color-scheme`. The light palette is the
//      researched one and the one every screenshot and support conversation assumes.
//      Reading the OS preference would flip the app to dark for a large share of people
//      who never asked for it, on their first visit, before they have any idea what it
//      is meant to look like. Dark is a choice you make here.
//   2. Two labelled buttons rather than a switch. A switch has to be read as "on = which
//      one?", and the answer is never written down; two buttons say what they do.
//
// Written to <body> rather than <html> because that is what styles.css scopes on, and
// applied in an effect so the DOM and the stored value cannot drift apart.

const KEY = "fw.theme";
const THEMES = ["light", "dark"];

export function storedTheme() {
  try {
    const saved = localStorage.getItem(KEY);
    return THEMES.includes(saved) ? saved : "light";
  } catch {
    // Private browsing, or storage disabled. A theme is not worth an exception.
    return "light";
  }
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState(storedTheme);

  useEffect(() => {
    document.body.setAttribute("data-fw-theme", theme);
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* see storedTheme */
    }
  }, [theme]);

  return (
    <div className="themetoggle" role="group" aria-label="Colour theme">
      <button
        type="button"
        aria-pressed={theme === "light"}
        onClick={() => setTheme("light")}
      >
        <SunIcon />
        Light
      </button>
      <button
        type="button"
        aria-pressed={theme === "dark"}
        onClick={() => setTheme("dark")}
      >
        <MoonIcon />
        Dark
      </button>
    </div>
  );
}

/* Inline strokes rather than an icon package: styles.css notes there is no image asset
   anywhere in this app, and that is worth keeping true. */

function SunIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"
         strokeLinecap="round" aria-hidden="true">
      <circle cx="8" cy="8" r="3.1" />
      <path d="M8 1v1.6M8 13.4V15M15 8h-1.6M2.6 8H1M12.95 3.05l-1.13 1.13M4.18 11.82l-1.13 1.13M12.95 12.95l-1.13-1.13M4.18 4.18L3.05 3.05" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M13.5 9.6A5.9 5.9 0 0 1 6.4 2.5a5.9 5.9 0 1 0 7.1 7.1z" />
    </svg>
  );
}
