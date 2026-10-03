/// Separate build of the exported-report renderer (plan 13 §6): one IIFE
/// script plus one stylesheet that `vmn-exp report export` inlines into a
/// self-contained HTML file.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "../src/vmn_exp/ui/export_bundle",
    emptyOutDir: true,
    lib: {
      entry: "src/reports/export.tsx",
      formats: ["iife"],
      name: "VmnReportExport",
      fileName: () => "report-export.js",
    },
    rollupOptions: { output: { inlineDynamicImports: true, assetFileNames: "report-export.[ext]" } },
  },
});
