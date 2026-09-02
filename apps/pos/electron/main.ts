import { app, BrowserWindow, ipcMain, safeStorage } from "electron";
import { autoUpdater } from "electron-updater";
import fs from "node:fs";
import path from "node:path";

// ── Xavfsiz saqlash (auth token) ── OS darajasida shifrlangan (Windows DPAPI). Token ochiq
// localStorage'da turmasin — umumiy POS kompyuterida istalgan lokal jarayon o'qiy olardi.
// sendSync: kichik payload, startup'da bir marta o'qiladi — renderer hydration sinxron qoladi.
function secPath(key: string): string {
  return path.join(app.getPath("userData"), `sec-${key.replace(/[^a-z0-9-]/gi, "_")}.bin`);
}
function setupSecureStore() {
  ipcMain.on("savdoos:sec-get", (e, key: string) => {
    try {
      const p = secPath(key);
      if (fs.existsSync(p) && safeStorage.isEncryptionAvailable()) {
        e.returnValue = safeStorage.decryptString(fs.readFileSync(p));
        return;
      }
    } catch { /* buzilgan/o'qib bo'lmadi — bo'sh */ }
    e.returnValue = null;
  });
  ipcMain.on("savdoos:sec-set", (e, key: string, val: string) => {
    try {
      if (safeStorage.isEncryptionAvailable()) fs.writeFileSync(secPath(key), safeStorage.encryptString(val));
    } catch { /* diskka yozilmasa — sessiya xotirada davom etadi */ }
    e.returnValue = true;
  });
  ipcMain.on("savdoos:sec-del", (e, key: string) => {
    try { fs.rmSync(secPath(key), { force: true }); } catch { /* ignore */ }
    e.returnValue = true;
  });
}

const DEV_URL = process.env.VITE_DEV_SERVER_URL;

let win: BrowserWindow | null = null;

function createWindow() {
  win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    autoHideMenuBar: true,
    backgroundColor: "#eceef4",
    title: "SavdoOS POS",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
    },
  });

  if (DEV_URL) win.loadURL(DEV_URL);
  else win.loadFile(path.join(__dirname, "../dist/index.html"));

  // UI ni ekranga sig'dirish uchun ~10% kichraytirish (kichik ekranlarda ham to'liq ko'rinadi)
  win.webContents.on("did-finish-load", () => win?.webContents.setZoomFactor(0.9));
}

// Avto-yangilanish: fonda yuklab oladi, holatni ILOVA ICHIDAGI banner'ga yuboradi (IPC).
// Kassa kun bo'yi ochiq turadi — shuning uchun har 4 soatda ham tekshiramiz.
function sendUpdate(data: unknown) {
  BrowserWindow.getAllWindows().forEach((w) => w.webContents.send("savdoos:update", data));
}

function setupAutoUpdate() {
  autoUpdater.autoDownload = false; // AVTO yuklab OLINMAYDI — foydalanuvchi "Yangilanish"ni bosganda yuklanadi
  autoUpdater.autoInstallOnAppQuit = false; // AVTO-o'rnatilmaydi — faqat foydalanuvchi "Yangilanish" tugmasini bosganda o'rnatiladi

  autoUpdater.on("update-available", (info) => {
    sendUpdate({ state: "available", version: info.version }); // tugma chiqadi (hali yuklanmagan)
  });
  autoUpdater.on("download-progress", (p) => {
    sendUpdate({ state: "downloading", percent: Math.round(p.percent) });
  });
  autoUpdater.on("update-downloaded", (info) => {
    sendUpdate({ state: "ready", version: info.version });
  });
  autoUpdater.on("error", () => {
    sendUpdate({ state: "idle" });
  });

  ipcMain.on("savdoos:download-update", () => {          // tugma: yuklab olishni boshlaydi
    autoUpdater.downloadUpdate().catch(() => sendUpdate({ state: "idle" }));
  });
  ipcMain.on("savdoos:install-update", () => {           // tugma: yuklab bo'lingach o'rnatadi (qayta ishga tushadi)
    autoUpdater.quitAndInstall();
  });

  const check = () => autoUpdater.checkForUpdates().catch(() => { /* offline/publish yo'q — jim */ });
  check();
  setInterval(check, 4 * 60 * 60 * 1000);
}

function setupPrinting() {
  ipcMain.handle("savdoos:list-printers", async (e) => {
    try { return await e.sender.getPrintersAsync(); } catch { return []; }
  });
  ipcMain.handle("savdoos:print", async (_e, { html, deviceName }) => {
    const w = new BrowserWindow({ show: false, webPreferences: { contextIsolation: true } });
    try {
      await w.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(html));
      await new Promise<void>((resolve) => {
        w.webContents.print(
          { silent: true, deviceName: deviceName || undefined, margins: { marginType: "none" }, printBackground: true },
          () => resolve()
        );
      });
      return { ok: true };
    } catch (err) {
      return { ok: false, error: String(err) };
    } finally {
      if (!w.isDestroyed()) w.close();
    }
  });
}

app.whenReady().then(() => {
  setupSecureStore();  // renderer hydration'idan OLDIN tayyor bo'lsin
  createWindow();
  setupPrinting();
  if (!DEV_URL) setupAutoUpdate(); // faqat paketlangan ilovada
});
app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
