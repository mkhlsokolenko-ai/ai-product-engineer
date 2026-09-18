// Electron main: спавнит Python-сайдкар (движок) и рендерит модульный UI поверх него.
// Оболочка тонкая — вся логика в сайдкаре; окно можно заменить, не трогая движок.
const { app, BrowserWindow, shell } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const net = require("net");
const http = require("http");

// Удалённый UI: если задан APE_UI_URL — грузим фронт с сервера (правки без релиза),
// с фоллбеком на локальную копию из asar (офлайн/недоступность). Пусто → всегда локально.
const REMOTE_UI = process.env.APE_UI_URL || "";

let sidecar = null;
let win = null;

function freePort() {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => {
      const p = s.address().port;
      s.close(() => resolve(p));
    });
  });
}

function pyCmd() {
  // dev: системный Python. В упакованной сборке позже подменим на bundled sidecar (PyInstaller).
  return process.platform === "win32" ? "py" : "python3";
}

function startSidecar(port) {
  const env = Object.assign({}, process.env, { APE_SIDECAR_PORT: String(port) });
  let proc;
  if (app.isPackaged) {
    // прод: автономный бинарь сайдкара из extraResources (Python пользователю не нужен)
    const exe = process.platform === "win32" ? "ape-sidecar.exe" : "ape-sidecar";
    const bin = path.join(process.resourcesPath, "ape-sidecar", exe);
    proc = spawn(bin, [], { env });
  } else {
    // dev: системный Python из репозитория
    proc = spawn(pyCmd(), ["-m", "sidecar.app"], { cwd: path.join(__dirname, ".."), env });
  }
  proc.stdout.on("data", (d) => console.log("[sidecar]", d.toString().trim()));
  proc.stderr.on("data", (d) => console.error("[sidecar]", d.toString().trim()));
  proc.on("exit", (code) => console.log("[sidecar] exit", code));
  return proc;
}

function waitHealth(port, tries = 80) {
  return new Promise((resolve, reject) => {
    const timer = setInterval(() => {
      const req = http.get(
        { host: "127.0.0.1", port, path: "/api/health", timeout: 1000 },
        (r) => {
          if (r.statusCode === 200) {
            clearInterval(timer);
            resolve();
          }
          r.resume();
        }
      );
      req.on("error", () => {
        if (--tries <= 0) {
          clearInterval(timer);
          reject(new Error("sidecar не поднялся"));
        }
      });
      req.on("timeout", () => req.destroy());
    }, 400);
  });
}

async function createWindow() {
  const port = await freePort();
  sidecar = startSidecar(port);
  try {
    await waitHealth(port);
  } catch (e) {
    console.error(e);
  }
  win = new BrowserWindow({
    width: 1240,
    height: 820,
    minWidth: 900,
    backgroundColor: "#0B0F14",
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  // внешние ссылки — в системный браузер (например, окно логина при необходимости)
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
  const apiBase = `http://127.0.0.1:${port}`;
  const localIndex = path.join(__dirname, "..", "ui", "index.html");
  if (REMOTE_UI) {
    // грузим удалённый UI; при сбое сети — откат на локальную копию
    win.webContents.once("did-fail-load", () => win.loadFile(localIndex, { query: { api: apiBase } }));
    win.loadURL(REMOTE_UI + (REMOTE_UI.includes("?") ? "&" : "?") + "api=" + encodeURIComponent(apiBase));
  } else {
    win.loadFile(localIndex, { query: { api: apiBase } });
  }
}

// Тихий авто-апдейт всего приложения (сайдкар+оболочка+UI-fallback) с GitHub Releases.
// Ставится на перезапуск; пользователю не нужно переустанавливать вручную.
function checkUpdates() {
  if (!app.isPackaged) return;
  try {
    const { autoUpdater } = require("electron-updater");
    autoUpdater.autoDownload = true;
    autoUpdater.on("error", (e) => console.error("[updater]", e && e.message));
    autoUpdater.on("update-downloaded", (i) => console.log("[updater] downloaded", i && i.version));
    autoUpdater.checkForUpdatesAndNotify();
  } catch (e) {
    console.error("[updater] недоступен:", e && e.message);
  }
}

app.whenReady().then(createWindow).then(checkUpdates);
app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
function stop() {
  if (sidecar) {
    sidecar.kill();
    sidecar = null;
  }
}
app.on("window-all-closed", () => {
  stop();
  if (process.platform !== "darwin") app.quit();
});
app.on("before-quit", stop);
