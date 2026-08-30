// @ts-check
import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  output: "static",
  site: "http://localhost:4322",
  vite: {
    plugins: [tailwindcss()],
    server: {
      // Dev-only: proxy the admin API through this origin so the browser
      // talks to a single host — no CORS, no PUBLIC_ADMIN_API_BASE needed
      // for local work. Applies to `astro dev` only (not `preview`/`dist`).
      // Override the target when the serving API runs elsewhere:
      //   ADMIN_API_TARGET=http://127.0.0.1:9000 npm run dev
      proxy: {
        "/v1": {
          target: process.env.ADMIN_API_TARGET ?? "http://localhost:8000",
          changeOrigin: true,
        },
      },
    },
  },
});
