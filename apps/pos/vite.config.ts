import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import electron from "vite-plugin-electron/simple";
import path from "node:path";
import { execSync } from "node:child_process";
import pkg from "./package.json";

// Build vaqtidagi commit — do'kondagi qabul sinovida "qaysi build o'rnatilgan?" savoliga
// ekranning O'ZI javob bersin. Git yo'q bo'lsa (arxivdan build) "unknown" qoladi.
const BUILD_SHA = (() => {
  try { return execSync("git rev-parse --short HEAD", { stdio: ["ignore", "pipe", "ignore"] }).toString().trim(); }
  catch { return "unknown"; }
})();

export default defineConfig({
  // Build vaqtida versiya quyiladi — qurilma telemetriyasi (fleet.ts) serverga AYNAN
  // shu build raqamini xabar qiladi. Ilgari server qaysi build ishlayotganini bilmasdi.
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
    __APP_NAME__: JSON.stringify("pos"),
    __BUILD_SHA__: JSON.stringify(BUILD_SHA),
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
