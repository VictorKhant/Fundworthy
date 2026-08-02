import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

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
  plugins: [react(), mountApi()],
  build: { outDir: "dist", sourcemap: false },
  server: { port: 5173 },
});
