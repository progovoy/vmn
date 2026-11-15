/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const VENDOR = /\/node_modules\/(react|react-dom|react-router|react-router-dom|@remix-run\/router|scheduler|@tanstack\/[^/]+)\//;

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    globals: true,
    // Stylesheets stay empty in tests, except `?raw` imports (the CSS guards read them).
    css: { include: [/\.css\?raw$/] },
  },
  build: {
    outDir: "../src/vmn_exp/ui/static",
    emptyOutDir: true,
    // Name chunks after themselves, not their content hash: index.html and the
    // server's routes stay stable across builds. The server revalidates
    // /assets instead of caching it forever (see static_files.py).
    rollupOptions: {
      output: {
        entryFileNames: "assets/[name].js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name].[ext]",
        // Library code changes only on a dependency bump, so vendor.js stays
        // byte-identical across app releases and revalidates to a 304.
        manualChunks: (id) => (VENDOR.test(id) ? "vendor" : undefined),
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8265",
    },
  },
});
