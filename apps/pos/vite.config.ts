import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import electron from "vite-plugin-electron/simple";
import path from "node:path";

export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(__dirname, "../../packages/shared/src") },
    dedupe: ["react", "react-dom", "react-router-dom", "zustand"],
  },
  plugins: [
    react(),
    electron({
      main: { entry: "electron/main.ts" },
      preload: { input: path.join(__dirname, "electron/preload.ts") },
      renderer: {},
    }),
  ],
});
