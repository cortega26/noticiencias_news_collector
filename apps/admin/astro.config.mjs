// @ts-check
import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  output: "static",
  site: "http://localhost:4322",
  vite: {
    plugins: [tailwindcss()],
  },
});
