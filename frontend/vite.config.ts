import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In docker compose the backend is reachable as "backend"; locally it's localhost.
const apiTarget = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
    },
  },
});
