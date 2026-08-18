import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("savdoos", {
  app: "pos",
  platform: process.platform,
});

// Ilova ichidagi yangilanish banneri uchun xavfsiz ko'prik
contextBridge.exposeInMainWorld("savdoosUpdate", {
  onStatus: (cb: (data: unknown) => void) => {
    ipcRenderer.on("savdoos:update", (_e, data) => cb(data));
  },
  install: () => ipcRenderer.send("savdoos:install-update"),
});
