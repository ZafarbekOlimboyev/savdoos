import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("savdoos", {
  app: "manager",
  platform: process.platform,
});

// Ilova ichidagi yangilanish banneri uchun xavfsiz ko'prik
contextBridge.exposeInMainWorld("savdoosUpdate", {
  onStatus: (cb: (data: unknown) => void) => {
    ipcRenderer.on("savdoos:update", (_e, data) => cb(data));
  },
  download: () => ipcRenderer.send("savdoos:download-update"),
  install: () => ipcRenderer.send("savdoos:install-update"),
});

// Chek chop etish — jimjit termal (dialogsiz). Kanal nomlari `packages/shared/src/print/bridge.ts`
// PRINT_IPC bilan bir xil (sinov solishtiradi). ESC/POS uchun renderer BAYT emas, chek bloklarini
// yuboradi — baytlarni main tekshirib, o'zi yasaydi.
contextBridge.exposeInMainWorld("savdoosPrint", {
  listPrinters: () => ipcRenderer.invoke("savdoos:list-printers"),
  print: (html: string, deviceName?: string) => ipcRenderer.invoke("savdoos:print", { html, deviceName }),
  printHtml: (req: unknown) => ipcRenderer.invoke("savdoos:print-html", req),
  printEscPos: (req: unknown) => ipcRenderer.invoke("savdoos:print-escpos", req),
});

// Xavfsiz saqlash (auth token) — OS darajasida shifrlangan (safeStorage). Sinxron: hydration buzilmaydi.
contextBridge.exposeInMainWorld("savdoosSecure", {
  get: (key: string) => ipcRenderer.sendSync("savdoos:sec-get", key),
  set: (key: string, val: string) => ipcRenderer.sendSync("savdoos:sec-set", key, val),
  del: (key: string) => ipcRenderer.sendSync("savdoos:sec-del", key),
});
