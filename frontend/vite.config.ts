import { defineConfig } from "vitest/config";

export default defineConfig({
  base: "/assets/tracecore/home/",
  build: {
    outDir: "../tracecore/public/home",
    emptyOutDir: true,
    cssCodeSplit: false,
    rollupOptions: {
      input: "src/main.tsx",
      output: {
        entryFileNames: "home.js",
        assetFileNames: (asset) =>
          asset.name?.endsWith(".css") ? "home.css" : "[name]-[hash][extname]",
      },
    },
  },
  test: {
    environment: "jsdom",
  },
});
