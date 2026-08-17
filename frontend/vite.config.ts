import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy: SPA on :5173, API proxied to a local uvicorn instance.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../backend/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
