import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The FastAPI backend serves the built app at /app and the API at the root.
// In dev, proxy every API prefix to it.
const API = "http://127.0.0.1:8000";
const apiPrefixes = [
  "/opportunities", "/company", "/prices", "/scanner", "/institutions", "/insiders",
  "/radar", "/radar-backtest", "/backtest", "/historical", "/universe", "/health",
  "/search", "/schedule",
];

export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(apiPrefixes.map((p) => [p, { target: API, changeOrigin: true }])),
  },
});
