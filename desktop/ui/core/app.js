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
// Approve/deny-гейт (из макета Overlays «Подтверждение действия»). Governance-слой:
// действие наружу (письмо/тикет/коммит) требует явного разрешения. Promise<bool>.
// Сейчас — визуально; при подключении RBAC/коннекторов станет обязательным барьером.
export function apeGate(action) {
  return new Promise((resolve) => {
    const a = action || {};
    const rows = (a.fields || []).map((f) => `<div style="display:flex;gap:10px;font-size:13px;margin-bottom:6px"><span class="faint" style="width:90px;flex:none">${esc(f[0])}</span><span>${esc(f[1])}</span></div>`).join("");
    const ov = document.createElement("div");
    ov.style = "position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:120;backdrop-filter:blur(2px)";
    ov.innerHTML = `<div class="ape-card" style="width:min(520px,92vw);gap:0;padding:20px;animation:ape-drop .18s ease">
      <div class="ape-label" style="margin-bottom:6px">Требуется подтверждение · governance</div>
      <div style="font-size:16px;font-weight:700;letter-spacing:-.3px;margin-bottom:12px">${esc(a.title || "Подтверждение действия")}</div>
      ${rows}
      ${a.body ? `<div style="background:var(--field);border:1px solid var(--line);border-radius:11px;padding:11px 13px;font-size:12.5px;line-height:1.5;margin:8px 0;white-space:pre-wrap">${esc(a.body)}</div>` : ""}
      <div class="faint" style="font-size:11.5px;margin:6px 0 2px">Наружу ничего не уйдёт без вашего решения. Маска ПДн применена.</div>
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px">
        <button class="btn" id="gDeny">Отклонить</button><button class="btn primary" id="gAllow">${esc(a.allowLabel || "Разрешить")}</button></div></div>`;
    document.body.appendChild(ov);
    const done = (v) => { ov.remove(); resolve(v); };
    ov.querySelector("#gAllow").onclick = () => done(true);
    ov.querySelector("#gDeny").onclick = () => done(false);
    ov.onclick = (e) => { if (e.target === ov) done(false); };
  });
}
function esc(s) { return (s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

export const ctx = { api, base: API, user: null, gate: apeGate };

const $ = (id) => document.getElementById(id);
let MODULES = [];
let active = null;

function icon(name) {
  // минимальные глиф-иконки рейла (без внешних зависимостей)
  return { chat: "💬", agents: "🤖", graphlens: "🕸", opslens: "🗺", security: "🛡", cabinet: "👤", ocr: "🔎", ml: "🧠", abop: "🕸" }[name] || "▦";
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

// Быстрые функции в рейле (настраиваемые, persist localStorage) — из макета.
const QF_DEFAULT = ["new", "palette", "theme"];
function quickActions() {
  const a = [
    { id: "new", label: "Новый чат", icon: "➕", run: async () => { await loadModule("chat"); const b = document.querySelector("#newTh"); if (b) b.click(); } },
    { id: "palette", label: "Команды", icon: "⌘", run: openPalette },
    { id: "theme", label: "Тема", icon: "🌓", run: toggleTheme },
  ];
  MODULES.forEach((m) => a.push({ id: "mod:" + m.id, label: m.title, icon: icon(m.icon), run: () => loadModule(m.id) }));
  return a;
}
function getPins() { try { return JSON.parse(localStorage.getItem("ape_quickfns")) || QF_DEFAULT; } catch { return QF_DEFAULT; } }
function renderQuick() {
  const el = document.getElementById("railQuick"); if (!el) return;
  const acts = quickActions(), pins = getPins();
  el.innerHTML = pins.map((id) => { const a = acts.find((x) => x.id === id); return a ? `<button class="railbtn qf" data-id="${a.id}" title="${a.label}"><div style="font-size:18px">${a.icon}</div></button>` : ""; }).join("")
    + `<button class="railbtn" id="qfAdd" title="Настроить быстрые функции"><div style="font-size:16px">＋</div></button>`;
  el.querySelectorAll(".qf").forEach((b) => b.onclick = () => { const a = acts.find((x) => x.id === b.dataset.id); if (a) a.run(); });
  document.getElementById("qfAdd").onclick = openQuickManage;
}
function openQuickManage() {
  const acts = quickActions(), pins = getPins();
  const ov = document.createElement("div");
  ov.style = "position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:100;backdrop-filter:blur(2px)";
  ov.innerHTML = `<div style="width:min(420px,92vw);background:var(--panel);backdrop-filter:blur(20px);border:1px solid var(--b1);border-radius:14px;padding:18px">
    <div style="font-weight:600;margin-bottom:12px">Быстрые функции в меню</div>
    ${acts.map((a) => `<label style="display:flex;gap:8px;align-items:center;padding:6px 0;font-size:13px"><input type="checkbox" class="qfc" value="${a.id}" ${pins.includes(a.id) ? "checked" : ""}/> ${a.icon} ${a.label}</label>`).join("")}
    <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px"><button class="btn" id="qfCancel">Закрыть</button><button class="btn primary" id="qfSave">Сохранить</button></div></div>`;
  document.body.appendChild(ov);
  ov.querySelector("#qfCancel").onclick = () => ov.remove();
  ov.onclick = (e) => { if (e.target === ov) ov.remove(); };
  ov.querySelector("#qfSave").onclick = () => { localStorage.setItem("ape_quickfns", JSON.stringify([...ov.querySelectorAll(".qfc:checked")].map((x) => x.value))); ov.remove(); renderQuick(); };
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
function toggleTheme() {
  const t = (localStorage.getItem("ape_theme") || "dark") === "dark" ? "light" : "dark";
  localStorage.setItem("ape_theme", t); applyTheme(t);
}
function initTheme() {
  applyTheme(localStorage.getItem("ape_theme") || "dark");
  const b = document.getElementById("themeBtn");
  if (b) b.onclick = toggleTheme;
}

// Командная палитра (Ctrl+K) — из макета «Поиск и команды».
function buildCommands() {
  const cmds = MODULES.map((m) => ({ label: "Открыть: " + m.title, run: () => loadModule(m.id) }));
  cmds.push({ label: "Новый чат", run: async () => { await loadModule("chat"); const b = document.querySelector("#newTh"); if (b) b.click(); } });
  cmds.push({ label: "Тема: светлая / тёмная", run: toggleTheme });
  if (window.ape && window.ape.updater) cmds.push({ label: "Проверить обновления", run: () => window.ape.updater.check() });
  return cmds;
}
function openPalette() {
  if (document.getElementById("cmdPalette")) return;
  const all = buildCommands();
  const ov = document.createElement("div");
  ov.id = "cmdPalette";
  ov.style = "position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:flex-start;justify-content:center;padding-top:12vh;z-index:100;backdrop-filter:blur(2px)";
  ov.innerHTML = `<div style="width:min(560px,92vw);background:var(--panel);backdrop-filter:blur(20px);border:1px solid var(--b1);border-radius:14px;box-shadow:0 24px 70px rgba(0,0,0,.45);overflow:hidden">
    <input id="cmdInp" placeholder="Команда…" autocomplete="off" style="width:100%;border:0;border-bottom:1px solid var(--b1);border-radius:0;padding:14px 16px;font-size:14px;background:transparent"/>
    <div id="cmdList" style="max-height:52vh;overflow:auto;padding:6px"></div></div>`;
  document.body.appendChild(ov);
  let items = all, sel = 0;
  const list = ov.querySelector("#cmdList");
  const close = () => ov.remove();
  const runSel = () => { const c = items[sel]; close(); if (c) c.run(); };
  const paint = () => {
    list.innerHTML = items.map((c, i) => `<div class="cmd" data-i="${i}" style="padding:9px 12px;border-radius:9px;cursor:pointer;font-size:13px;background:${i === sel ? "var(--accent-bg)" : "transparent"};color:${i === sel ? "var(--accent-2)" : "var(--ink1)"}">${c.label}</div>`).join("") || `<div class="faint" style="padding:10px">Ничего не найдено</div>`;
    list.querySelectorAll(".cmd").forEach((e) => { e.onmouseenter = () => { sel = +e.dataset.i; paint(); }; e.onclick = runSel; });
  };
  const inp = ov.querySelector("#cmdInp");
  inp.oninput = () => { const q = inp.value.toLowerCase(); items = all.filter((c) => c.label.toLowerCase().includes(q)); sel = 0; paint(); };
  ov.onkeydown = (e) => {
    if (e.key === "Escape") close();
    else if (e.key === "ArrowDown") { sel = Math.min(sel + 1, items.length - 1); paint(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(sel - 1, 0); paint(); e.preventDefault(); }
    else if (e.key === "Enter") runSel();
  };
  ov.onclick = (e) => { if (e.target === ov) close(); };
  paint(); inp.focus();
}

async function boot() {
  initTheme();
  try { const h = await api("/api/health"); const v = document.getElementById("verChip"); if (v) v.textContent = "v" + (h.version || "?"); } catch {}
  if (window.ape && window.ape.updater) window.ape.updater.onStatus(renderUpdate);
  await renderAuth();
  try { MODULES = await api("/api/modules"); } catch { MODULES = []; }
  renderNav();
  renderQuick();
  if (MODULES.length) loadModule(MODULES[0].id);
  else $("panel").innerHTML = `<div class="faint" style="padding:24px">Модули не найдены. Проверь сайдкар.</div>`;
  // командная палитра: Ctrl+K + кнопка в топбаре
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && (e.key === "k" || e.key === "K")) { e.preventDefault(); openPalette(); }
  });
  const pb = document.getElementById("cmdBtn");
  if (pb) pb.onclick = openPalette;
}

boot();
