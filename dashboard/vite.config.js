import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const REPO_ROOT = fileURLToPath(new URL("..", import.meta.url));

// Dev only. On Vercel these two are project environment variables and this never
// runs; locally they live in the repo-root .env that the Python agent already reads,
// so `npm run dev` shows real data instead of the not-connected state.
//
// The shapes differ on purpose and this is the only place that reconciles them:
// the agent takes GOOGLE_APPLICATION_CREDENTIALS as a *path* (gspread opens the
// file), while api/runs.js takes GOOGLE_SHEETS_CREDENTIALS as the JSON *itself*
// (Vercel has no filesystem to put a key file on). One .env feeds both.
function devEnvFromRepoRoot() {
  return {
    name: "rise-dev-env",
    apply: "serve",
    config(_, { mode }) {
      const env = loadEnv(mode, REPO_ROOT, "");
      for (const [key, value] of Object.entries(env)) {
        process.env[key] ??= value;
      }
      if (!process.env.GOOGLE_SHEETS_CREDENTIALS && process.env.GOOGLE_APPLICATION_CREDENTIALS) {
        try {
          process.env.GOOGLE_SHEETS_CREDENTIALS = readFileSync(
            new URL(process.env.GOOGLE_APPLICATION_CREDENTIALS, new URL("file://" + REPO_ROOT)),
            "utf8",
          );
        } catch (err) {
          // Not fatal: api/runs.js already renders an honest not-connected page.
          console.warn(`[rise] could not read the service-account file: ${err.message}`);
        }
      }
    },
  };
}

// Static build. There is no backend here — /api/runs is a Vercel serverless
// function (see api/runs.js), which exists so the Sheet can stay unpublished.
//
// Vite's dev server does not know about Vercel functions, so `npm run dev` would
// otherwise fail its fetch on every load. This mounts the *same* handler in dev, so
// what you see locally is what deploys — including the honest not-yet-connected
// state when no credentials are set.
function mountApi() {
  return {
    name: "rise-mount-api",
    configureServer(server) {
      server.middlewares.use("/api/runs", async (req, res) => {
        try {
          const { default: handler } = await server.ssrLoadModule("/api/runs.js");
          await handler(req, {
            setHeader: (k, v) => res.setHeader(k, v),
            status(code) {
              res.statusCode = code;
              return this;
            },
            json(body) {
              res.setHeader("Content-Type", "application/json");
              res.end(JSON.stringify(body));
            },
          });
        } catch (err) {
          res.statusCode = 500;
          res.end(JSON.stringify({ error: String(err) }));
        }
      });
    },
  };
}

export default defineConfig({
  plugins: [devEnvFromRepoRoot(), react(), mountApi()],
  build: { outDir: "dist", sourcemap: false },
  server: { port: 5173 },
});
