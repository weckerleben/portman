import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The portman daemon listens on 127.0.0.1:7878 by default.
// In dev we proxy API + WebSocket traffic to it; in production FastAPI
// serves the built SPA directly from frontend/dist.
const DAEMON = "http://127.0.0.1:7878";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: DAEMON, changeOrigin: true },
      "/ws": { target: DAEMON, ws: true, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
