import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("savdoos", {
  app: "pos",
  platform: process.platform,
  version: "0.1.0",
});
