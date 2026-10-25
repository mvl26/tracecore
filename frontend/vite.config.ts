import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  base: "/assets/tracecore/admin/",
  build: {
    outDir: "../tracecore/public/admin",
    emptyOutDir: true,
    manifest: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/assets/tracecore/css": "http://localhost:8000",
    },
  },
});
