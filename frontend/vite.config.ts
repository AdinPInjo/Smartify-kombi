import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// During development the dashboard talks to a backend on localhost:8000
// (`python -m smartify` in backend/, mock hardware by default).
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    proxy: { "/api": "http://localhost:8000" },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 700 },
});
