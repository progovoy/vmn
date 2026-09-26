/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    globals: true,
  },
  build: {
    outDir: "../version_stamp/ui/static",
    emptyOutDir: true,
    // Name chunks after themselves, not their content hash. The bundle is
    // committed, and a hash cascades: one edit rewrites every chunk importing
    // the one that changed, so a rebuild churned the whole bundle. The server
    // revalidates /assets instead of caching it forever (see static_files.py).
    rollupOptions: {
      output: {
        entryFileNames: "assets/[name].js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name].[ext]",
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8265",
    },
  },
});
