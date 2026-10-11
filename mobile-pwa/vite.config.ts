import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, proxy API + WebSocket to the PC1 orchestrator on localhost:8000.
const api = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/command": api,
      "/jobs": api,
      "/confirm": api,
      "/stop": api,
      "/status": api,
      "/health": api,
      "/events": { target: api.replace("http", "ws"), ws: true },
    },
  },
  test: { environment: "node" },
} as never);
