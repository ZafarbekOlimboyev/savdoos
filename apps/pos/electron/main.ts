import { app, BrowserWindow, ipcMain } from "electron";
import { autoUpdater } from "electron-updater";
import path from "node:path";

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
  createWindow();
  setupPrinting();
  if (!DEV_URL) setupAutoUpdate(); // faqat paketlangan ilovada
});
app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
