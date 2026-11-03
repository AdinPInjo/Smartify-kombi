import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { readFileSync } from "node:fs";

const pkg = JSON.parse(readFileSync(path.resolve(__dirname, "package.json"), "utf-8")) as { version: string };

// During development the dashboard talks to a backend on localhost:8000
// (`python -m smartify` in backend/, mock hardware by default).
export default defineConfig({
  // Relative asset URLs: the same build works at the root (the Pi) and in a
  // subfolder of a website (the remote dashboard), together with <base href>.
  base: "./",
  plugins: [react()],
  // Shown bottom-left in the menu; the changelog comes from ../CHANGELOG.md.
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    proxy: { "/api": "http://localhost:8000" },
    fs: { allow: [".."] }, // CHANGELOG.md lives in the project root
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 700 },
});
