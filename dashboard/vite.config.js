import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Static build. The dashboard talks to the local FastAPI app in `app/` (see
// src/api.js), which serves this build from `dist/` in production, so there is
// nothing to configure beyond the dev port.
//
// Two plugins used to live here and are deliberately gone:
//
//   mountApi()           mounted `api/runs.js` — a Vercel serverless function that
//                        read the Google Sheet — into the dev server. Decision A6
//                        retired that reader in favour of the agent emitting data
//                        directly, and v2 replaced it entirely with the FastAPI
//                        backend. The file it mounted has been deleted.
//
//   devEnvFromRepoRoot() bridged the repo-root .env into process.env, and converted
//                        GOOGLE_APPLICATION_CREDENTIALS (a path) into
//                        GOOGLE_SHEETS_CREDENTIALS (the JSON) for that same
//                        function. The Python half of that problem is solved better
//                        and in one place by agent/__init__.py, which loads .env at
//                        package import for every entrypoint. Nothing in the front
//                        end reads a credential any more — it calls localhost:8000
//                        and the server holds the secrets.
//
// In dev this runs on :5173 and calls the API on :8000 cross-origin; app/main.py
// allows exactly those two localhost origins. In production both come from :8000
// and requests are same-origin.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false },
  server: { port: 5173 },
});
