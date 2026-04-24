const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("paloraDesktop", {
  getConfig: () => ipcRenderer.invoke("palora:get-config"),
  pickFile: () => ipcRenderer.invoke("palora:pick-file"),
});
