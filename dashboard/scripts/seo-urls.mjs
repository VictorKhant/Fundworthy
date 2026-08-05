// Put the real hostname into the built files, or take the placeholders out.
//
// index.html, robots.txt and sitemap.xml all ship with a `SITE_URL` token. A plain token
// rather than Vite's `%VAR%` substitution because Vite runs those through decodeURI: an
// unset variable fails the build with "URI malformed" instead of degrading, which would
// break a deploy over an optional setting.
//
// With no VITE_SITE_URL we remove the tags that need one rather than shipping them
// broken. A canonical link pointing at `SITE_URL/welcome` tells a crawler the real page
// lives at a URL that does not resolve, which is worse than saying nothing.
import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";

const site = (process.env.VITE_SITE_URL || "").replace(/\/+$/, "");

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
  : "[seo] VITE_SITE_URL not set — canonical/sitemap omitted. Set it in dashboard/.env " +
    "(see .env.example) so search engines can index this deployment.");
