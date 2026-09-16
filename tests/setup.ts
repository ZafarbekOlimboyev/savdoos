import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

// Har sinovdan keyin DOM ham, tarmoq mock'i ham TOZA bo'ladi — aks holda
// sinovlar bir-birining holatiga suyanib "yashil" bo'lib qolardi.
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  try { localStorage.clear(); } catch { /* ignore */ }
});

// jsdom'da matchMedia yo'q — `useNarrow` uni o'qiydi.
if (!window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false, media: query, onchange: null,
      addEventListener: () => {}, removeEventListener: () => {},
      addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
    }),
  });
}
