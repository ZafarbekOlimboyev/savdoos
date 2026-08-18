// Faqat brauzerda ko'rish uchun (Electron'siz) — dizayn tekshiruvi/preview.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import path from "node:path";

export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(__dirname, "../../packages/shared/src") },
    dedupe: ["react", "react-dom", "react-router-dom", "zustand"],
  },
  plugins: [react()],
  server: { port: 5198 },
});
