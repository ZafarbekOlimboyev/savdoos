import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import * as path from "path";

// Komponent sinovlari (jsdom). E2E — Playwright'da (`npm run e2e`), bu yerda EMAS:
// bu yerda tarmoq ham, backend ham yo'q, `fetch` sinovda almashtiriladi.
export default defineConfig({
  plugins: [react()],
  resolve: {
    // ⚠️  BITTA REACT NUSXASI. `apps/manager` va `apps/pos` ning O'Z
    //     `node_modules` i bor (electron-builder shuni talab qiladi). Manager
    //     komponentini sinovga import qilganda u o'sha nusxadagi React'ni
    //     tortadi va «Invalid hook call» bilan yiqiladi — shu bois ildizdagi
    //     nusxaga qat'iy bog'laymiz.
    dedupe: ["react", "react-dom", "react-router-dom"],
    alias: {
      "@": path.resolve(__dirname, "packages/shared/src"),
      react: path.resolve(__dirname, "node_modules/react"),
      "react-dom": path.resolve(__dirname, "node_modules/react-dom"),
      "react-router-dom": path.resolve(__dirname, "node_modules/react-router-dom"),
    },
  },
  // Ilova kodi vite `define` bilan yig'iladi (fleet.ts o'qiydi) — sinovda ham
  // bo'lmasa modul import paytida ReferenceError bilan yiqilardi.
  define: {
    __APP_VERSION__: JSON.stringify("0.0.0-test"),
    __APP_NAME__: JSON.stringify("manager"),
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.tsx", "tests/**/*.test.ts"],
    css: false,
  },
});
