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
    title: "SavdoOS Manager",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
    },
  });

  if (DEV_URL) win.loadURL(DEV_URL);
  else win.loadFile(path.join(__dirname, "../dist/index.html"));
}

// Avto-yangilanish: fonda yuklab oladi, holatni ILOVA ICHIDAGI banner'ga yuboradi (IPC).
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

app.whenReady().then(() => {
  createWindow();
  if (!DEV_URL) setupAutoUpdate(); // faqat paketlangan ilovada
});
app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
