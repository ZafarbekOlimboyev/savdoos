import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("savdoos", {
  app: "manager",
  platform: process.platform,
  version: "0.1.0",
});
