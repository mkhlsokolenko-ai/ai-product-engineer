// Модуль «Чат» (фронт). Треды (переименование/избранное/авто-тема), история, профиль,
// скиллы из UI, вложения→RAG с видимым списком файлов, кнопки инструментов (RAG/OCR/NLP),
// мультиагенты с выбором ролей (in-app модалка — в Electron native prompt() не работает!).

const M = "/api/modules/chat";
const esc = (s) => (s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

// ── универсальная модалка (замена native prompt/confirm, которых в Electron нет) ──
function modal(title, bodyHTML, onOk) {
  const ov = document.createElement("div");
  ov.style = "position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:50";
  ov.innerHTML = `<div style="background:var(--panel);border:1px solid var(--b1);border-radius:14px;width:min(560px,92vw);max-height:86vh;overflow:auto;padding:20px">
    <div style="font-weight:600;font-size:15px;margin-bottom:14px">${esc(title)}</div>
    <div id="mBody">${bodyHTML}</div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:18px">
      <button class="btn" id="mCancel">Отмена</button><button class="btn primary" id="mOk">Готово</button></div></div>`;
  document.body.appendChild(ov);
  const close = () => ov.remove();
  ov.querySelector("#mCancel").onclick = close;
  ov.querySelector("#mOk").onclick = () => { if (onOk(ov.querySelector("#mBody")) !== false) close(); };
  ov.onclick = (e) => { if (e.target === ov) close(); };
  return ov;
}

export async function mount(root, ctx) {
  const { api } = ctx;
  let threads = [], cur = null, messages = [], skills = [], roles = [];
  try { skills = await api(M + "/skills"); } catch {}
  try { roles = await api(M + "/agent-roles"); } catch {}

  root.innerHTML = `
    <div style="display:flex;height:100%">
      <div style="width:270px;flex-shrink:0;border-right:1px solid var(--b1);display:flex;flex-direction:column">
        <div style="padding:12px"><button class="btn primary" id="newTh" style="width:100%">+ Новый чат</button></div>
        <div id="thList" style="flex:1;overflow:auto;padding:0 8px"></div>
      </div>
      <div style="flex:1;min-width:0;display:flex;flex-direction:column">
        <div id="msgs" style="flex:1;overflow:auto;padding:20px;display:flex;flex-direction:column;gap:14px"></div>
        <div id="files" style="padding:0 16px"></div>
        <div id="composer" style="border-top:1px solid var(--b1);padding:12px 16px"></div>
      </div>
    </div>`;
  const $ = (id) => root.querySelector("#" + id);

  function renderThreads() {
    $("thList").innerHTML = threads.map((t) => `
      <div class="th" data-id="${t.id}" style="display:flex;align-items:center;gap:6px;padding:9px 8px;border-radius:9px;cursor:pointer;margin-bottom:3px;background:${cur && t.id === cur.id ? "var(--accent-bg)" : "transparent"}">
        <span class="star" data-id="${t.id}" title="В избранное" style="cursor:pointer">${t.favorite ? "★" : "☆"}</span>
        <div style="flex:1;min-width:0">
          <div style="font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(t.title)}</div>
          <div class="faint mono" style="font-size:10px">${t.profile}${t.skills && t.skills.length ? " · " + t.skills.length + " ск." : ""}</div>
        </div>
        <span class="ren" data-id="${t.id}" title="Переименовать" style="cursor:pointer;color:var(--ink3)">✎</span>
        <span class="del" data-id="${t.id}" title="Удалить" style="cursor:pointer;color:var(--ink3)">×</span>
      </div>`).join("") || `<div class="faint" style="padding:10px;font-size:12.5px">Чатов пока нет</div>`;
    $("thList").querySelectorAll(".th").forEach((el) => {
      el.onclick = (e) => { if (e.target.closest(".star,.ren,.del")) return; openThread(threads.find((x) => x.id == el.dataset.id)); };
    });
    $("thList").querySelectorAll(".star").forEach((s) => s.onclick = async () => {
      const t = threads.find((x) => x.id == s.dataset.id); t.favorite = t.favorite ? 0 : 1;
      await api(M + "/threads/" + t.id, { method: "PATCH", body: JSON.stringify({ title: t.title, profile: t.profile, skills: t.skills, favorite: t.favorite }) });
      await loadThreads();
    });
    $("thList").querySelectorAll(".ren").forEach((s) => s.onclick = () => renameThread(threads.find((x) => x.id == s.dataset.id)));
    $("thList").querySelectorAll(".del").forEach((s) => s.onclick = async () => {
      if (confirm("Удалить чат?")) { await api(M + "/threads/" + s.dataset.id, { method: "DELETE" }); if (cur && cur.id == s.dataset.id) cur = null; await loadThreads(); if (!cur) { messages = []; renderMessages(); renderFiles(); renderComposer(); } }
    });
  }

  function renameThread(t) {
    modal("Название чата", `<input id="tt" value="${esc(t.title)}" style="width:100%" />
      <div class="faint" style="font-size:12px;margin-top:8px">Оставь пустым и нажми «Авто» — тему определит ИИ.</div>
      <button class="btn sm" id="autoT" style="margin-top:8px">✨ Авто-тема</button>`, (b) => {
      const v = b.querySelector("#tt").value.trim(); if (!v) return false;
      t.title = v;
      api(M + "/threads/" + t.id, { method: "PATCH", body: JSON.stringify({ title: t.title, profile: t.profile, skills: t.skills, favorite: t.favorite }) }).then(loadThreads);
    });
    root.ownerDocument.querySelector("#autoT").onclick = async () => {
      const r = await api(M + "/threads/" + t.id + "/autotitle", { method: "POST" });
      if (r.ok) { document.querySelector("#tt").value = r.title; }
    };
  }

  function bubble(m) {
    const mine = m.role === "user";
    const meta = m.meta && m.meta.model
      ? `<div class="faint mono" style="font-size:10px;margin-top:4px">${m.meta.model} · ${m.meta.cost_rub ?? 0} ₽ · ${m.meta.output_tokens ?? 0} tok</div>` : "";
    return `<div class="bubble" style="max-width:80%;align-self:${mine ? "flex-end" : "flex-start"}">
      <div class="bcontent" style="background:${mine ? "var(--accent-bg)" : "var(--panel)"};border:1px solid var(--b1);border-radius:12px;padding:10px 13px;white-space:pre-wrap;font-size:13.5px;line-height:1.5">${esc(m.content)}</div>${meta}</div>`;
  }
  function renderMessages() {
    $("msgs").innerHTML = messages.map(bubble).join("") ||
      `<div class="faint" style="margin:auto;text-align:center">Напиши сообщение ниже.<br>Профиль, скиллы и инструменты — в панели ввода.</div>`;
    $("msgs").scrollTop = $("msgs").scrollHeight;
  }

  async function renderFiles() {
    if (!cur) { $("files").innerHTML = ""; return; }
    let fs = [];
    try { fs = await api(M + "/threads/" + cur.id + "/files"); } catch {}
    if (!fs.length) { $("files").innerHTML = ""; return; }
    $("files").innerHTML = `<div class="faint" style="font-size:11px;margin:6px 0 4px">База знаний чата (${fs.length}):</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px">${fs.map((f) =>
        `<span class="chip" title="${f.chunks} фрагм., ${f.chars} симв.">📄 ${esc(f.name)} <span class="fdel" data-id="${f.id}" style="cursor:pointer;color:var(--crit)">×</span></span>`).join("")}</div>`;
    $("files").querySelectorAll(".fdel").forEach((x) => x.onclick = async () => {
      await api(M + "/threads/" + cur.id + "/files/" + x.dataset.id, { method: "DELETE" }); renderFiles();
    });
  }

  function renderComposer() {
    if (!cur) { $("composer").innerHTML = `<div class="faint" style="font-size:12.5px">Создай или выбери чат слева.</div>`; return; }
    const skillChips = skills.map((s) =>
      `<span class="chip skc ${cur.skills.includes(s.id) ? "on" : ""}" data-id="${s.id}" title="${esc(s.hint)}" style="cursor:pointer">${s.id}</span>`).join(" ");
    $("composer").innerHTML = `
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap">
        <select id="prof" style="width:auto">
          <option value="standard"${cur.profile === "standard" ? " selected" : ""}>standard · 30B</option>
          <option value="code"${cur.profile === "code" ? " selected" : ""}>code</option>
          <option value="research"${cur.profile === "research" ? " selected" : ""}>ask</option>
        </select>
        <div style="display:flex;gap:5px;flex-wrap:wrap;flex:1">${skillChips}</div>
        <button class="btn sm" id="tRag" title="Приложить файл в базу знаний (RAG)">📎 RAG</button>
        <button class="btn sm" id="tOcr" title="Распознать текст с изображения/скана">🔎 OCR</button>
        <button class="btn sm" id="tNlp" title="NLP: извлечение сущностей/классификация">🧠 NLP</button>
        <button class="btn sm" id="agentsBtn" title="Собрать команду агентов под задачу">🕸 Агенты</button>
        <input type="file" id="fileIn" accept=".txt,.md,.csv,.json" style="display:none" />
      </div>
      <div style="display:flex;gap:8px">
        <textarea id="inp" rows="2" placeholder="Сообщение…  (Enter — отправить, Shift+Enter — перенос)" style="flex:1;resize:none"></textarea>
        <button class="btn primary" id="sendBtn">Отправить</button>
      </div>`;
    $("prof").onchange = async (e) => { cur.profile = e.target.value; await saveThread(); };
    $("composer").querySelectorAll(".skc").forEach((c) => c.onclick = async () => {
      const id = c.dataset.id; const i = cur.skills.indexOf(id);
      if (i >= 0) cur.skills.splice(i, 1); else cur.skills.push(id);
      await saveThread(); renderComposer();
    });
    $("sendBtn").onclick = send;
    $("inp").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
    $("tRag").onclick = () => $("fileIn").click();
    $("fileIn").onchange = attach;
    $("tOcr").onclick = () => alert("OCR: модуль ocr-tesseract в разработке (см. roadmap). Пока прикладывай текстовые файлы через RAG.");
    $("tNlp").onclick = () => alert("NLP: модуль извлечения сущностей/классификации в разработке (см. roadmap).");
    $("agentsBtn").onclick = openAgents;
    $("inp").focus();
  }

  async function saveThread() {
    await api(M + "/threads/" + cur.id, { method: "PATCH", body: JSON.stringify({ title: cur.title, profile: cur.profile, skills: cur.skills, favorite: cur.favorite || 0 }) });
  }
  async function loadThreads() { threads = await api(M + "/threads"); renderThreads(); }

  async function openThread(t) {
    cur = { ...t, skills: t.skills || [] };
    renderThreads(); renderComposer(); renderFiles();
    messages = await api(M + "/threads/" + t.id + "/messages");
    renderMessages();
  }

  async function send() {
    const inp = $("inp"); const text = inp.value.trim(); if (!text || !cur) return;
    inp.value = "";
    const wasNew = messages.length === 0;
    messages.push({ role: "user", content: text, meta: {} });
    const asst = { role: "assistant", content: "", meta: {} };
    messages.push(asst); renderMessages();
    const el = $("msgs").querySelector(".bubble:last-child .bcontent");
    const setTxt = (t) => { if (el) { el.textContent = t; $("msgs").scrollTop = $("msgs").scrollHeight; } };
    setTxt("…");
    try {
      const resp = await fetch(ctx.base + M + "/threads/" + cur.id + "/send-stream",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: text }) });
      if (!resp.ok || !resp.body) throw new Error("HTTP " + resp.status);
      const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf = "";
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const block = buf.slice(0, i); buf = buf.slice(i + 2);
          const dl = block.split("\n").find((l) => l.startsWith("data:")); if (!dl) continue;
          let d; try { d = JSON.parse(dl.slice(5).trim()); } catch { continue; }
          if (d.delta) { asst.content += d.delta; setTxt(asst.content); }
          else if (d.error) { asst.content = asst.content || ("Ошибка: " + (d.error === "auth_required" ? "нужен вход через GitHub (кнопка вверху)" : d.error)); setTxt(asst.content); }
          else if (d.done && d.meta) { asst.meta = d.meta; }
        }
      }
    } catch (e) { asst.content = asst.content || ("Сбой: " + e.message); }
    renderMessages(); // финальный рендер (с meta: модель/стоимость/токены)
    if (wasNew && (cur.title === "Новый чат")) { try { const a = await api(M + "/threads/" + cur.id + "/autotitle", { method: "POST" }); if (a.ok) cur.title = a.title; } catch {} }
    loadThreads();
  }

  async function attach(e) {
    const f = e.target.files[0]; if (!f || !cur) return;
    const text = await f.text();
    const r = await api(M + "/threads/" + cur.id + "/attach", { method: "POST", body: JSON.stringify({ name: f.name, documents: [text] }) });
    messages.push({ role: "assistant", content: r.ok ? `Файл «${f.name}» в базе знаний (${r.indexed} фрагм.) — спрашивай по нему.` : "Не удалось приложить: " + r.error, meta: {} });
    renderMessages(); renderFiles(); e.target.value = "";
  }

  function openAgents() {
    if (!cur) return;
    const rolesHTML = roles.map((r) =>
      `<label style="display:flex;gap:8px;align-items:flex-start;padding:6px 0"><input type="checkbox" class="rl" value="${r.id}" ${r.default ? "checked" : ""} style="margin-top:3px" />
        <span><b>${esc(r.name)}</b><div class="faint" style="font-size:12px">${esc(r.brief)}</div></span></label>`).join("");
    modal("Команда агентов под задачу", `
      <textarea id="atask" rows="3" placeholder="Опиши задачу для команды…" style="width:100%;resize:vertical"></textarea>
      <div class="faint" style="font-size:12px;margin:12px 0 4px">Выбери роли (выполняются цепочкой, передавая наработки):</div>
      ${rolesHTML}`, async (b) => {
      const task = b.querySelector("#atask").value.trim();
      const sel = [...b.querySelectorAll(".rl:checked")].map((x) => x.value);
      if (!task || !sel.length) { alert("Укажи задачу и хотя бы одну роль"); return false; }
      messages.push({ role: "user", content: "[агенты] " + task, meta: {} });
      messages.push({ role: "assistant", content: "Агенты работают…", meta: {} }); renderMessages();
      const r = await api(M + "/threads/" + cur.id + "/agents", { method: "POST", body: JSON.stringify({ task, roles: sel }) });
      messages.pop();
      messages.push({ role: "assistant", content: r.ok ? r.content : "Ошибка: " + r.error, meta: {} });
      renderMessages();
    });
  }

  $("newTh").onclick = async () => {
    const t = await api(M + "/threads", { method: "POST", body: JSON.stringify({ title: "Новый чат", profile: "standard", skills: [] }) });
    await loadThreads(); openThread(t);
  };

  await loadThreads();
  if (threads.length) openThread(threads[0]); else { renderComposer(); renderFiles(); }
}
