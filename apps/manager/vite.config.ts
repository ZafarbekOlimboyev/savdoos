import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import electron from "vite-plugin-electron/simple";
import path from "node:path";
import pkg from "./package.json";

export default defineConfig({
  // Build vaqtida versiya quyiladi — qurilma telemetriyasi (fleet.ts) serverga AYNAN
  // shu build raqamini xabar qiladi. Ilgari server qaysi build ishlayotganini bilmasdi.
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
    __APP_NAME__: JSON.stringify("manager"),
  },
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
