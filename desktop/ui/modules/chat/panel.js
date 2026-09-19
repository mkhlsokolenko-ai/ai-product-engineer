// Модуль «Чат» (фронт). Треды (переименование/избранное/авто-тема), история, профиль,
// скиллы из UI, вложения→RAG с видимым списком файлов, кнопки инструментов (RAG/OCR/NLP),
// мультиагенты с выбором ролей (in-app модалка — в Electron native prompt() не работает!).

const M = "/api/modules/chat";
const esc = (s) => (s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

// Минимальный безопасный markdown → HTML (сначала escape, потом свои теги).
function md(t) {
  let h = esc(t);
  h = h.replace(/```([\s\S]*?)```/g, (_m, c) =>
    `<div style="position:relative;margin:6px 0"><button class="codecopy" style="position:absolute;top:6px;right:6px;font-size:10.5px;padding:2px 7px;border:1px solid var(--b1);background:var(--panel);color:var(--ink2);border-radius:6px;cursor:pointer">копир.</button><pre style="background:var(--bg0);border:1px solid var(--b1);border-radius:8px;padding:10px;overflow:auto"><code>${c.replace(/^\n/, "")}</code></pre></div>`);
  h = h.replace(/`([^`\n]+)`/g, '<code style="background:var(--raised);padding:1px 5px;border-radius:5px">$1</code>');
  h = h.replace(/^\s*#{1,4}\s+(.*)$/gm, "<b>$1</b>");
  h = h.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  h = h.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2">$1</a>');
  h = h.replace(/^\s*[-*]\s+(.*)$/gm, "• $1");
  return h;
}

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

// Шаблоны под менеджера для пустого экрана: заголовок · промпт · опц. скилл.
const TEMPLATES = [
  ["📝 Письмо клиенту", "Напиши деловое письмо клиенту: <опиши ситуацию и цель>", "email-draft"],
  ["🗂 Саммари встречи", "Сделай саммари встречи и список задач с ответственными по тексту:\n<вставь заметки>", ""],
  ["💬 Разобрать отзывы", "Из отзывов ниже вытащи главные боли и 3 действия на неделю:\n<вставь отзывы>", ""],
  ["🎯 Проверить идею", "Проверь мою идею как скептик-инвестор, без похвал, с аргументами:\n<опиши идею>", "devils-advocate"],
  ["⚖️ Сравнить варианты", "Сравни варианты по критериям и порекомендуй один:\n<перечисли варианты>", ""],
  ["📅 План на неделю", "Составь план на неделю по цели с приоритетами и рисками:\n<опиши цель>", ""],
];

export async function mount(root, ctx) {
  const { api } = ctx;
  let threads = [], cur = null, messages = [], skills = [], roles = [], threadFilter = "";
  try { skills = await api(M + "/skills"); } catch {}
  try { roles = await api(M + "/agent-roles"); } catch {}

  root.innerHTML = `
    <div style="display:flex;height:100%">
      <div style="width:270px;flex-shrink:0;border-right:1px solid var(--b1);display:flex;flex-direction:column">
        <div style="padding:12px 12px 6px"><button class="btn primary" id="newTh" style="width:100%">+ Новый чат</button></div>
        <div style="padding:0 12px 8px"><input id="thSearch" placeholder="Поиск по чатам…" style="width:100%" /></div>
        <div id="thList" style="flex:1;overflow:auto;padding:0 8px"></div>
      </div>
      <div id="rightPane" style="flex:1;min-width:0;display:flex;flex-direction:column;position:relative">
        <div id="dropHint" style="display:none;position:absolute;inset:0;z-index:5;background:var(--accent-bg);border:2px dashed var(--accent);align-items:center;justify-content:center;font-weight:600;color:var(--accent)">Отпусти файл — добавлю в базу знаний</div>
        <div id="msgs" style="flex:1;overflow:auto;padding:20px;display:flex;flex-direction:column;gap:14px"></div>
        <div id="files" style="padding:0 16px"></div>
        <div id="composer" style="border-top:1px solid var(--b1);padding:12px 16px"></div>
        <div id="drawer" style="position:absolute;top:0;right:0;height:100%;width:390px;max-width:88%;transform:translateX(100%);transition:transform .2s ease;background:var(--panel);border-left:1px solid var(--b1);z-index:6;display:flex;flex-direction:column;box-shadow:-10px 0 28px rgba(0,0,0,.28)">
          <div style="display:flex;align-items:center;gap:8px;padding:14px 16px;border-bottom:1px solid var(--b1)">
            <b style="flex:1">🤖 Агенты · вызов в чат</b><span id="drClose" style="cursor:pointer;color:var(--ink3);font-size:16px">✕</span>
          </div>
          <div id="drBody" style="flex:1;overflow:auto;padding:14px"></div>
        </div>
      </div>
    </div>`;
  const $ = (id) => root.querySelector("#" + id);
  $("thSearch").oninput = (e) => { threadFilter = e.target.value.toLowerCase(); renderThreads(); };
  $("drClose").onclick = () => closeDrawer();
  // drag-drop файлов в правую панель
  const rp = $("rightPane");
  rp.addEventListener("dragover", (e) => { e.preventDefault(); if (cur) $("dropHint").style.display = "flex"; });
  rp.addEventListener("dragleave", (e) => { if (e.relatedTarget === null || !rp.contains(e.relatedTarget)) $("dropHint").style.display = "none"; });
  rp.addEventListener("drop", async (e) => {
    e.preventDefault(); $("dropHint").style.display = "none";
    if (!cur) return;
    for (const f of [...(e.dataTransfer.files || [])]) { if (/\.(txt|md|csv|json)$/i.test(f.name)) await attachFile(f); }
  });
  // горячие клавиши: Ctrl+N — новый чат, Esc — стоп генерации
  if (window.__apeKeyHandler) document.removeEventListener("keydown", window.__apeKeyHandler);
  window.__apeKeyHandler = (e) => {
    if (!root.isConnected) return;
    if (e.ctrlKey && (e.key === "n" || e.key === "N")) { e.preventDefault(); $("newTh").click(); }
    else if (e.key === "Escape") { if ($("drawer") && $("drawer").style.transform === "translateX(0px)") closeDrawer(); else if (curAbort) curAbort.abort(); }
  };
  document.addEventListener("keydown", window.__apeKeyHandler);

  function renderThreads() {
    const list = threads.filter((t) => !threadFilter || (t.title || "").toLowerCase().includes(threadFilter));
    $("thList").innerHTML = list.map((t) => `
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

  function bubble(m, idx) {
    const mine = m.role === "user";
    const meta = m.meta && m.meta.model
      ? `<div class="faint mono" style="font-size:10px;margin-top:4px">${m.meta.model} · ${m.meta.cost_rub ?? 0} ₽ · ${m.meta.output_tokens ?? 0} tok</div>` : "";
    const body = mine ? esc(m.content) : md(m.content);
    const acts = mine
      ? `<div style="display:flex;gap:12px;margin-top:5px;justify-content:flex-end"><span data-edit="${idx}" style="cursor:pointer;color:var(--ink3);font-size:11.5px">✎ изменить</span></div>`
      : `<div style="display:flex;gap:12px;margin-top:5px">
      <span data-copy="${idx}" style="cursor:pointer;color:var(--ink3);font-size:11.5px">⧉ копировать</span>
      <span data-regen="${idx}" style="cursor:pointer;color:var(--ink3);font-size:11.5px">↻ ещё раз</span></div>`;
    return `<div class="bubble" style="max-width:80%;align-self:${mine ? "flex-end" : "flex-start"}">
      <div class="bcontent" style="background:${mine ? "var(--accent-bg)" : "var(--panel)"};border:1px solid var(--b1);border-radius:12px;padding:10px 13px;white-space:pre-wrap;font-size:13.5px;line-height:1.5">${body}</div>${meta}${acts}</div>`;
  }
  function renderMessages() {
    if (!messages.length) {
      const cards = TEMPLATES.map((t, i) =>
        `<div data-tpl="${i}" style="cursor:pointer;border:1px solid var(--b1);background:var(--panel);border-radius:12px;padding:12px 14px;font-size:13px;font-weight:600">${t[0]}</div>`).join("");
      $("msgs").innerHTML = `<div style="margin:auto;max-width:640px;text-align:center">
        <div class="faint" style="margin-bottom:14px">С чего начать? Выбери шаблон или просто напиши сообщение.</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">${cards}</div></div>`;
      $("msgs").querySelectorAll("[data-tpl]").forEach((e) => e.onclick = async () => {
        const [, prompt, skill] = TEMPLATES[+e.dataset.tpl];
        if (skill && cur && !cur.skills.includes(skill)) { cur.skills.push(skill); await saveThread(); renderComposer(); }
        const inp = $("inp"); if (inp) { inp.value = prompt; inp.focus(); }
      });
      return;
    }
    $("msgs").innerHTML = messages.map(bubble).join("");
    $("msgs").querySelectorAll("[data-copy]").forEach((e) => e.onclick = () => {
      navigator.clipboard.writeText(messages[+e.dataset.copy].content);
      const o = e.textContent; e.textContent = "✓ скопировано"; setTimeout(() => { e.textContent = o; }, 1500);
    });
    $("msgs").querySelectorAll("[data-regen]").forEach((e) => e.onclick = () => {
      const prev = messages[+e.dataset.regen - 1];
      if (prev && prev.role === "user") sendPrompt(prev.content);
    });
    $("msgs").querySelectorAll("[data-edit]").forEach((e) => e.onclick = () => {
      const inp = $("inp"); if (inp) { inp.value = messages[+e.dataset.edit].content; inp.focus(); }
    });
    $("msgs").querySelectorAll(".codecopy").forEach((b) => b.onclick = () => {
      const pre = b.parentElement.querySelector("code");
      navigator.clipboard.writeText(pre ? pre.textContent : "");
      const o = b.textContent; b.textContent = "✓"; setTimeout(() => { b.textContent = o; }, 1200);
    });
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
        <button class="btn sm" id="expBtn" title="Сохранить чат в Загрузки">📥 Экспорт</button>
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
    $("expBtn").onclick = () => {
      const ov = modal("Экспорт чата в «Загрузки»", `<div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn" data-f="md">Markdown (.md)</button>
        <button class="btn" data-f="pdf">PDF (.pdf)</button>
        <button class="btn" data-f="docx" disabled title="в v0.1.3">Word (.docx)</button>
        <button class="btn" data-f="xlsx" disabled title="в v0.1.3">Excel (.xlsx)</button>
      </div>`, () => true);
      ov.querySelectorAll("[data-f]").forEach((b) => b.onclick = () => { if (!b.disabled) { exportThread(b.dataset.f); ov.remove(); } });
    };
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

  let curAbort = null;
  function setSending(on) {
    const b = $("sendBtn"); if (!b) return;
    b.textContent = on ? "⏹ Стоп" : "Отправить";
    b.classList.toggle("primary", !on);
    b.onclick = on ? () => { if (curAbort) curAbort.abort(); } : send;
  }
  function send() { const inp = $("inp"); const t = inp.value; inp.value = ""; sendPrompt(t); }

  async function sendPrompt(text) {
    text = (text || "").trim(); if (!text || !cur) return;
    const wasNew = messages.length === 0;
    messages.push({ role: "user", content: text, meta: {} });
    const asst = { role: "assistant", content: "", meta: {} };
    messages.push(asst); renderMessages();
    const el = $("msgs").querySelector(".bubble:last-child .bcontent");
    const setTxt = (t2) => { if (el) { el.textContent = t2; $("msgs").scrollTop = $("msgs").scrollHeight; } };
    setTxt("▍ думает…");
    curAbort = new AbortController(); setSending(true);
    try {
      const resp = await fetch(ctx.base + M + "/threads/" + cur.id + "/send-stream",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: text }), signal: curAbort.signal });
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
    } catch (e) {
      if (e.name === "AbortError") asst.content += "\n\n⏹ остановлено";
      else asst.content = asst.content || ("Сбой: " + e.message);
    }
    curAbort = null; setSending(false);
    renderMessages();
    if (wasNew && (cur.title === "Новый чат")) { try { const a = await api(M + "/threads/" + cur.id + "/autotitle", { method: "POST" }); if (a.ok) cur.title = a.title; } catch {} }
    loadThreads();
  }

  async function exportThread(fmt) {
    if (!cur) return;
    if (fmt === "pdf") {
      if (!(window.ape && window.ape.exportPdf)) { alert("PDF доступен только в установленном приложении."); return; }
      const html = `<html><head><meta charset="utf-8"><style>body{font-family:sans-serif;padding:24px;color:#111}h1{font-size:20px}h2{margin:16px 0 4px;font-size:14px}pre{background:#f4f4f4;padding:8px;border-radius:6px;white-space:pre-wrap}</style></head><body><h1>${esc(cur.title)}</h1>` +
        messages.map((m) => `<h2>${m.role === "user" ? "Вы" : "Ассистент"}</h2><div style="white-space:pre-wrap">${esc(m.content)}</div>`).join("") + `</body></html>`;
      const r = await window.ape.exportPdf(html, (cur.title || "chat").replace(/[^\w\-. ]/g, "_").slice(0, 60) + ".pdf");
      alert(r.ok ? "Сохранено в Загрузки:\n" + r.path : "Ошибка PDF: " + r.error);
      return;
    }
    const r = await api(M + "/threads/" + cur.id + "/export", { method: "POST", body: JSON.stringify({ format: fmt }) });
    alert(r.ok ? "Сохранено в Загрузки:\n" + r.path : "Не удалось: " + r.error);
  }

  async function attachFile(f) {
    if (!f || !cur) return;
    messages.push({ role: "assistant", content: `📎 индексирую «${f.name}»…`, meta: {} }); renderMessages();
    const text = await f.text();
    const r = await api(M + "/threads/" + cur.id + "/attach", { method: "POST", body: JSON.stringify({ name: f.name, documents: [text] }) });
    messages.pop();
    messages.push({ role: "assistant", content: r.ok ? `Файл «${f.name}» в базе знаний (${r.indexed} фрагм.) — спрашивай по нему.` : "Не удалось приложить: " + r.error, meta: {} });
    renderMessages(); renderFiles();
  }
  async function attach(e) { const f = e.target.files[0]; await attachFile(f); e.target.value = ""; }

  function openAgents() {
    if (!cur) { alert("Сначала создай или выбери чат."); return; }
    $("drawer").style.transform = "translateX(0)";
    renderDrawer();
  }
  function closeDrawer() { $("drawer").style.transform = "translateX(100%)"; }
  async function renderDrawer() {
    const body = $("drBody");
    body.innerHTML = `<div class="faint">Загрузка каталога…</div>`;
    let cat = []; try { cat = await api("/api/modules/agents/catalog"); } catch {}
    const catHTML = cat.map((a) => `<label style="display:flex;gap:8px;align-items:flex-start;border:1px solid var(--b1);border-radius:10px;padding:10px;margin-bottom:8px;cursor:pointer">
        <input type="checkbox" class="da" value="${a.id}" style="margin-top:3px"/>
        <span style="min-width:0"><b style="font-size:13px">${esc(a.name)}</b><div class="faint" style="font-size:12px">${esc(a.description || "")}</div>
        <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:3px">${(a.skills || []).map((s) => `<span class="chip" style="font-size:10px">${esc(s)}</span>`).join("")}</div></span></label>`).join("")
      || `<div class="faint" style="font-size:12.5px">Каталог пуст. Открой вкладку 🤖 Агенты слева → «Создать агента».</div>`;
    const rolesHTML = roles.map((r) => `<label style="display:flex;gap:8px;align-items:flex-start;padding:5px 0"><input type="checkbox" class="rl" value="${r.id}" style="margin-top:3px"/><span style="font-size:12.5px"><b>${esc(r.name)}</b> <span class="faint">${esc(r.brief)}</span></span></label>`).join("");
    body.innerHTML = `
      <div class="faint" style="font-size:12px;margin-bottom:8px">Выбери агента или несколько (цепочка), задай задачу — выполнится в этот чат.</div>
      <textarea id="drTask" rows="3" style="width:100%;margin-bottom:10px" placeholder="Задача для агента(ов)…"></textarea>
      <div class="faint" style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px">Мои агенты (каталог)</div>
      ${catHTML}
      <details style="margin-top:8px"><summary class="faint" style="cursor:pointer;font-size:12px">Быстрые роли (без настройки)</summary><div style="margin-top:6px">${rolesHTML}</div></details>
      <button class="btn primary" id="drRun" style="width:100%;margin-top:12px">▶ Запустить в чат</button>`;
    const inp = $("inp"); if (inp && inp.value.trim()) body.querySelector("#drTask").value = inp.value.trim();
    body.querySelector("#drRun").onclick = async () => {
      const task = body.querySelector("#drTask").value.trim();
      const ids = [...body.querySelectorAll(".da:checked")].map((x) => +x.value);
      const rl = [...body.querySelectorAll(".rl:checked")].map((x) => x.value);
      if (!task || (!ids.length && !rl.length)) { alert("Укажи задачу и хотя бы одного агента/роль"); return; }
      closeDrawer();
      messages.push({ role: "user", content: "[агенты] " + task, meta: {} });
      messages.push({ role: "assistant", content: "▍ агенты работают…", meta: {} }); renderMessages();
      const r = await api(M + "/threads/" + cur.id + "/agents", { method: "POST", body: JSON.stringify(ids.length ? { task, agent_ids: ids } : { task, roles: rl }) });
      messages.pop();
      messages.push({ role: "assistant", content: r.ok ? r.content : ("Ошибка: " + (r.error === "auth_required" ? "нужен вход через GitHub" : r.error)), meta: {} });
      renderMessages(); loadThreads();
    };
  }

  $("newTh").onclick = async () => {
    const t = await api(M + "/threads", { method: "POST", body: JSON.stringify({ title: "Новый чат", profile: "standard", skills: [] }) });
    await loadThreads(); openThread(t);
  };

  await loadThreads();
  if (threads.length) openThread(threads[0]); else { renderComposer(); renderFiles(); }
}
