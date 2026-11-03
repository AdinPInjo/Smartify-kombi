import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// During development the dashboard talks to a backend on localhost:8000
// (`python -m smartify` in backend/, mock hardware by default).
export default defineConfig({
  // Relative asset URLs: the same build works at the root (the Pi) and in a
  // subfolder of a website (the remote dashboard), together with <base href>.
  base: "./",
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    proxy: { "/api": "http://localhost:8000" },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 700 },
});
