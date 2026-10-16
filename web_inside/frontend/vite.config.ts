import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // A relative asset base lets the same internal build run at `/` when it is
  // selected alone and at `/inside/` when both frontends are enabled.
  base: "./",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/ws": {
        target: "ws://127.0.0.1:8000",
        ws: true,
      },
    },
  },
});
