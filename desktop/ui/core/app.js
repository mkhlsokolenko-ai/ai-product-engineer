// Ядро фронта: загрузчик модулей + маршрутизация + API-клиент к сайдкару.
// Модули НЕ хардкодятся: берём список из /api/modules и динамически импортируем панель.
// Добавить фичу = новый backend-модуль + ui/modules/<id>/panel.js. Ядро не меняется.

const API = new URLSearchParams(location.search).get("api") || "http://127.0.0.1:8799";

export async function api(path, opts = {}) {
  const r = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}
export const ctx = { api, base: API, user: null };

const $ = (id) => document.getElementById(id);
let MODULES = [];
let active = null;

function icon(name) {
  // минимальные глиф-иконки рейла (без внешних зависимостей)
  return { chat: "💬", cabinet: "👤", ocr: "🔎", ml: "🧠", abop: "🕸" }[name] || "▦";
}

async function renderAuth() {
  const box = $("authBox");
  let me = { authed: false };
  try { me = await api("/api/auth/me"); } catch {}
  ctx.user = me.user || null;
  if (me.authed) {
    box.innerHTML = `<span class="sub" style="font-size:12.5px">${me.user || ""}</span>
      <button class="btn sm" id="logoutBtn" style="margin-left:10px">Выйти</button>`;
    $("logoutBtn").onclick = async () => { await api("/api/auth/logout", { method: "POST" }); renderAuth(); };
  } else {
    box.innerHTML = `<button class="btn primary sm" id="loginBtn">Войти через GitHub</button>`;
    $("loginBtn").onclick = async () => {
      $("loginBtn").textContent = "Открываю браузер…";
      try {
        const res = await api("/api/auth/login", { method: "POST" });
        if (!res.ok) alert(res.error || "Вход не удался");
      } catch (e) { alert("Ошибка входа: " + e.message); }
      renderAuth();
      if (active) loadModule(active); // перерисуем панель уже авторизованным
    };
  }
}

function renderNav() {
  $("railNav").innerHTML = MODULES.map(
    (m) => `<button class="railbtn ${m.id === active ? "on" : ""}" data-id="${m.id}">
      <div style="font-size:18px">${icon(m.icon)}</div><div>${m.title}</div></button>`
  ).join("");
  $("railNav").querySelectorAll(".railbtn").forEach((b) => {
    b.onclick = () => loadModule(b.dataset.id);
  });
}

async function loadModule(id) {
  active = id;
  renderNav();
  const m = MODULES.find((x) => x.id === id);
  $("topTitle").textContent = m ? m.title : "APE Desktop";
  const root = $("panel");
  root.innerHTML = `<div class="faint" style="padding:24px">Загрузка модуля «${m ? m.title : id}»…</div>`;
  try {
    const mod = await import(`../modules/${m.ui}/panel.js`);
    root.innerHTML = "";
    await mod.mount(root, ctx);
  } catch (e) {
    root.innerHTML = `<div style="padding:24px;color:var(--crit)">Модуль не загрузился: ${e.message}</div>`;
    console.error(e);
  }
}

function renderUpdate(s) {
  const bar = document.getElementById("updateBar");
  if (!bar) return;
  const show = (html, bg) => {
    bar.style.display = "flex";
    bar.style.cssText += ";align-items:center;gap:12px;padding:8px 16px;border-bottom:1px solid var(--b1);font-size:13px;" + (bg ? "background:var(--accent-bg)" : "background:var(--panel)");
    bar.innerHTML = html;
  };
  if (s.state === "downloading") show(`⬇ Обновление ${s.version ? "v" + s.version : ""} — скачивается ${s.percent || 0}%`);
  else if (s.state === "available") show(`⬇ Найдено обновление v${s.version} — скачиваю…`);
  else if (s.state === "ready") {
    show(`<span style="flex:1">✓ Обновление <b>v${s.version}</b> готово к установке</span>
      <button class="btn primary sm" id="updNow">Перезапустить и обновить</button>`, true);
    const b = document.getElementById("updNow");
    if (b) b.onclick = () => window.ape.updater.install();
  } else if (s.state === "error") show(`<span class="faint">Апдейтер: ${(s.message || "").slice(0, 120)}</span>`);
  else bar.style.display = "none"; // checking / none
}

function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  const b = document.getElementById("themeBtn");
  if (b) b.textContent = t === "light" ? "☀️" : "🌙";
}
function initTheme() {
  applyTheme(localStorage.getItem("ape_theme") || "dark");
  const b = document.getElementById("themeBtn");
  if (b) b.onclick = () => {
    const t = (localStorage.getItem("ape_theme") || "dark") === "dark" ? "light" : "dark";
    localStorage.setItem("ape_theme", t); applyTheme(t);
  };
}

async function boot() {
  initTheme();
  try { const h = await api("/api/health"); const v = document.getElementById("verChip"); if (v) v.textContent = "v" + (h.version || "?"); } catch {}
  if (window.ape && window.ape.updater) window.ape.updater.onStatus(renderUpdate);
  await renderAuth();
  try { MODULES = await api("/api/modules"); } catch { MODULES = []; }
  renderNav();
  if (MODULES.length) loadModule(MODULES[0].id);
  else $("panel").innerHTML = `<div class="faint" style="padding:24px">Модули не найдены. Проверь сайдкар.</div>`;
}

boot();
