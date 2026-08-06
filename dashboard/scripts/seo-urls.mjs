// Put the real hostname into the built files, or take the placeholders out.
//
// index.html, robots.txt and sitemap.xml all ship with a `SITE_URL` token. A plain token
// rather than Vite's `%VAR%` substitution because Vite runs those through decodeURI: an
// unset variable fails the build with "URI malformed" instead of degrading, which would
// break a deploy over an optional setting.
//
// With no SITE_URL we remove the tags that need one rather than shipping them broken. A
// canonical link pointing at `SITE_URL/welcome` tells a crawler the real page lives at a
// URL that does not resolve, which is worse than saying nothing.
//
// **The variable is `SITE_URL`, not `VITE_SITE_URL`.** The `VITE_` prefix is Vite's marker
// for "expose this to browser code through `import.meta.env`", and nothing here does that
// — the substitution happens in this file, in a plain Node process, after `vite build`
// has already finished. The prefix promised a mechanism that was not in use, and named
// the token in the HTML differently from the variable that fills it.
import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";

// Where the value comes from, in order. The environment first, so CI and
// `scripts/deploy.sh` (which exports it) keep overriding everything.
//
// Then the files — and reading them here is a fix, not a flourish. This script runs as a
// separate process from `vite build`, so Vite loading `dashboard/.env` did nothing for it:
// `process.env` never saw the value. Setting it in a file was silently a no-op, while this
// script's own warning and docs/UPGRADE.md both told you to do exactly that. Now the
// instruction is true.
function fromEnvFile(path) {
  if (!existsSync(path)) return "";
  for (const line of readFileSync(path, "utf8").split("\n")) {
    const match = /^\s*(?:export\s+)?SITE_URL\s*=\s*(.*)$/.exec(line);
    if (match) return match[1].trim().replace(/^["']|["']$/g, "");
  }
  return "";
}

const site = (
  process.env.SITE_URL
  || fromEnvFile(".env")        // dashboard/.env — cwd is dashboard/ during npm run build
  || fromEnvFile("../.env")     // the repo root .env, which is what the VM actually uses
  || ""
).replace(/\/+$/, "");

const html = "dist/index.html";
if (existsSync(html)) {
  let out = readFileSync(html, "utf8");
  if (site) {
    out = out.replaceAll("SITE_URL", site);
  } else {
    // Drop the canonical and og:url lines; everything else in the head stands alone.
    out = out
      .split("\n")
      .filter((line) => !/SITE_URL/.test(line) || /<!--|-->/.test(line))
      .join("\n");
  }
  writeFileSync(html, out);
}

for (const file of ["dist/robots.txt", "dist/sitemap.xml"]) {
  if (!existsSync(file)) continue;
  if (!site) {
    // A sitemap full of unresolvable URLs is a search-console error. No file is fine.
    rmSync(file);
    continue;
  }
  writeFileSync(file, readFileSync(file, "utf8").replaceAll("SITE_URL", site));
}

console.log(site
  ? `[seo] canonical, robots and sitemap -> ${site}`
  : "[seo] SITE_URL not set — canonical/sitemap omitted. Set it in dashboard/.env " +
    "(see .env.example) so search engines can index this deployment.");
