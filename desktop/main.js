const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const path = require("node:path");
const { spawn } = require("node:child_process");
const fs = require("node:fs");

let mainWindow;
let backendProcess;
let backendConfig;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1500,
    height: 980,
    minWidth: 1200,
    minHeight: 820,
    title: "Palora",
    backgroundColor: "#0E0B08",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.loadFile(path.join(__dirname, "index.html"));
}

function launchBackend() {
  return new Promise((resolve, reject) => {
    const backendCwd = path.join(__dirname, "..", "backend");
    const repoRoot = path.join(__dirname, "..");
    const preferredPython = path.join(repoRoot, ".venv", "bin", "python");
    const pythonBin = fs.existsSync(preferredPython) ? preferredPython : "python3";
    const env = {
      ...process.env,
      PALORA_REPO_ROOT: repoRoot,
      PALORA_DATA_DIR: path.join(repoRoot, ".palora-data"),
    };

    backendProcess = spawn(pythonBin, ["-m", "app.main"], {
      cwd: backendCwd,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdoutBuffer = "";
    let resolved = false;

    backendProcess.stdout.on("data", (chunk) => {
      stdoutBuffer += chunk.toString();
      const lines = stdoutBuffer.split(/\r?\n/);
      stdoutBuffer = lines.pop() || "";
      for (const line of lines) {
        if (line.startsWith("PALORA_BOOTSTRAP ")) {
          try {
            const payload = JSON.parse(line.slice("PALORA_BOOTSTRAP ".length));
            backendConfig = {
              baseUrl: `http://127.0.0.1:${payload.port}`,
              token: payload.token,
            };
            resolved = true;
            resolve(backendConfig);
          } catch (error) {
            reject(error);
          }
        } else if (line.trim()) {
          console.log("[palora-backend]", line);
        }
      }
    });

    backendProcess.stderr.on("data", (chunk) => {
      const text = chunk.toString();
      console.error("[palora-backend]", text.trim());
    });

    backendProcess.on("exit", (code) => {
      if (!resolved) {
        reject(new Error(`Backend exited before bootstrap: ${code}`));
      }
    });
  });
}

ipcMain.handle("palora:get-config", async () => {
  if (!backendConfig) {
    throw new Error("Backend not ready");
  }
  return backendConfig;
});

ipcMain.handle("palora:pick-file", async () => {
  const result = await dialog.showOpenDialog({
    properties: ["openFile"],
    filters: [
      { name: "Text files", extensions: ["txt", "md", "html", "json"] },
      { name: "All files", extensions: ["*"] },
    ],
  });
  if (result.canceled || result.filePaths.length === 0) {
    return null;
  }
  return result.filePaths[0];
});

app.whenReady().then(async () => {
  try {
    await launchBackend();
    createWindow();
  } catch (error) {
    dialog.showErrorBox("Palora boot failed", String(error));
    app.quit();
  }
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill("SIGTERM");
  }
});
