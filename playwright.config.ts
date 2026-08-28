import { defineConfig } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

// E2E: robot-foydalanuvchi Manager (5198) va POS (5199) ni haqiqiy brauzerda bosib chiqadi.
// Backend — e2e/start_backend.py (har ishga tushishda TOZA SQLite + demo seed).
// Lokal: `npm run e2e` (E2E_PY venv python'ga ko'rsatadi). CI: PATH'dagi `python`.

// Python: E2E_PY > lokal venv (apps/server/.venv) > PATH'dagi python (CI)
const venvPy = path.join(__dirname, "apps", "server", ".venv", "Scripts", "python.exe");
const PY = process.env.E2E_PY || (fs.existsSync(venvPy) ? `"${venvPy}"` : "python");
const CI = !!process.env.CI;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  retries: CI ? 1 : 0,
  workers: 1, // bitta umumiy backend holati — testlar ketma-ket
  reporter: CI ? "github" : "list",
  use: {
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `${PY} e2e/start_backend.py`,
      url: "http://127.0.0.1:8000/api/v1/health",
      reuseExistingServer: false, // har run TOZA baza
      timeout: 60_000,
    },
    {
      command: "npx vite --config vite.preview.config.ts --port 5199 --strictPort",
      cwd: "apps/pos",
      url: "http://localhost:5199",
      reuseExistingServer: !CI,
      timeout: 90_000,
    },
    {
      command: "npx vite --config vite.preview.config.ts --port 5198 --strictPort",
      cwd: "apps/manager",
      url: "http://localhost:5198",
      reuseExistingServer: !CI,
      timeout: 90_000,
    },
  ],
});
