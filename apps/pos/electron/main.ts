import { app, BrowserWindow, dialog } from "electron";
import { autoUpdater } from "electron-updater";
import path from "node:path";

const DEV_URL = process.env.VITE_DEV_SERVER_URL;

function createWindow() {
  const win = new BrowserWindow({
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
}

// Avto-yangilanish: fonda yuklab oladi, tayyor bo'lgach foydalanuvchidan so'raydi.
// Kassa kun bo'yi ochiq turadi — shuning uchun har 4 soatda ham tekshiramiz.
function setupAutoUpdate() {
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true; // "Keyinroq" deyilsa — ilova yopilganda o'rnatiladi

  autoUpdater.on("update-downloaded", (info) => {
    const win = BrowserWindow.getAllWindows()[0];
    void dialog
      .showMessageBox(win, {
        type: "info",
        title: "Yangilanish tayyor",
        message: `SavdoOS POS ${info.version} yuklab olindi`,
        detail: "Yangi versiyani o'rnatish uchun ilova qayta ishga tushadi. Keyinroq desangiz, ilova yopilganda avtomatik o'rnatiladi.",
        buttons: ["Hozir qayta ishga tushirish", "Keyinroq"],
        defaultId: 0,
        cancelId: 1,
      })
      .then(({ response }) => {
        if (response === 0) autoUpdater.quitAndInstall();
      });
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
