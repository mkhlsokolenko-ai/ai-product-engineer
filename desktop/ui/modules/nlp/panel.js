// Модуль «Текст» (NLP): извлечение сущностей (локально) + классификация/тональность/саммари (self-host).
const N = "/api/modules/nlp";
const esc = (s) => (s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const LBL = "font-family:var(--mono);font-size:9.5px;letter-spacing:.8px;text-transform:uppercase;color:var(--ink-3)";
const CARD = "padding:20px;border-radius:16px;background:var(--panel);border:1px solid var(--line);display:flex;flex-direction:column;gap:14px";
const ENT_RU = { email: "Email", phone: "Телефоны", money: "Суммы", date: "Даты", inn: "ИНН", percent: "Проценты", url: "Ссылки", org: "Организации" };
const OPS = [["entities", "Сущности", "локально"], ["classify", "Категория", "модель"], ["sentiment", "Тональность", "модель"], ["summary", "Саммари + задачи", "модель"]];

export async function mount(root, ctx) {
  const { api, mascot } = ctx;
  root.innerHTML = `<div style="flex:1;min-width:0;overflow-y:auto;padding:26px 30px">
    <div style="max-width:900px;margin:0 auto;display:flex;flex-direction:column;gap:20px;animation:ape-in .35s ease-out">
      <div style="display:flex;flex-direction:column;gap:6px">
        <h1 style="margin:0;font-size:26px;font-weight:800;letter-spacing:-.7px">Обработка текста</h1>
        <p style="margin:0;font-size:13px;color:var(--ink-2)">Вставьте письмо, отзыв или заметку. Сущности извлекаются локально; категория/тональность/саммари — self-host Qwen.</p>
      </div>
      <div style="${CARD}">
        <textarea id="nText" rows="8" placeholder="Вставьте текст для анализа…" style="padding:12px 14px;border-radius:11px;border:1px solid var(--line);background:var(--field);color:var(--ink);font-size:13px;line-height:1.55"></textarea>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          ${OPS.map((o) => `<button class="op" data-op="${o[0]}" style="padding:9px 15px;border:1px solid var(--line);border-radius:9999px;background:var(--panel);color:var(--ink);font-size:12.5px;font-weight:600;cursor:pointer">${o[1]} <span style="color:var(--ink-3);font-size:10.5px">· ${o[2]}</span></button>`).join("")}
        </div>
      </div>
      <div id="nRes"></div>
    </div></div>`;
  const $ = (id) => root.querySelector("#" + id);

  function renderEntities(ents) {
    const keys = Object.keys(ents || {});
    if (!keys.length) return `<div style="color:var(--ink-3);font-size:13px">Сущности не найдены.</div>`;
    return keys.map((k) => `<div style="display:flex;gap:12px;align-items:flex-start;margin-bottom:8px">
      <span style="${LBL};width:110px;flex:none;padding-top:3px">${ENT_RU[k] || k}</span>
      <span style="display:flex;gap:6px;flex-wrap:wrap">${ents[k].map((v) => `<span class="chip">${esc(v)}</span>`).join("")}</span></div>`).join("");
  }

  async function runOp(op) {
    const text = $("nText").value.trim();
    if (!text) { $("nRes").innerHTML = `<div style="${CARD};color:var(--ink-3)">Вставьте текст.</div>`; return; }
    $("nRes").innerHTML = `<div style="${CARD}"><span style="display:inline-flex;gap:12px;align-items:center">${mascot("thinking", 26)}<span style="color:var(--ink-2)">обрабатываю…</span></span></div>`;
    const r = await api(N + "/run", { method: "POST", body: JSON.stringify({ text, op }) });
    if (!r.ok) { $("nRes").innerHTML = `<div style="${CARD};color:var(--danger-ink)">${esc(r.error === "auth_required" ? "Нужен вход через GitHub (для модельных операций)" : r.error)}</div>`; return; }
    let body = "";
    if (op === "entities") body = `<span style="${LBL}">сущности · ${esc(r.note || "")}</span><div style="margin-top:10px">${renderEntities(r.entities)}</div>`;
    else if (op === "classify") body = `<span style="${LBL}">категория обращения</span><div style="margin-top:8px"><span class="chip on" style="font-size:14px;padding:6px 14px">${esc(r.label)}</span></div>`;
    else if (op === "sentiment") { const col = /негатив/.test(r.tone || "") ? "var(--danger-ink)" : /позитив/.test(r.tone || "") ? "var(--ok-ink)" : "var(--ink)"; body = `<span style="${LBL}">тональность</span><div style="margin-top:8px;display:flex;align-items:center;gap:12px"><span style="font-size:18px;font-weight:700;color:${col}">${esc(r.tone || "—")}</span><span class="chip">score ${r.score ?? "—"}</span></div>${r.why ? `<div style="margin-top:8px;font-size:13px;color:var(--ink-2)">${esc(r.why)}</div>` : ""}`; }
    else if (op === "summary") body = `<span style="${LBL}">саммари и задачи</span><div style="margin-top:10px;white-space:pre-wrap;font-size:13.5px;line-height:1.6">${esc(r.text)}</div>`;
    $("nRes").innerHTML = `<div style="${CARD}">${body}</div>`;
  }

  root.querySelectorAll(".op").forEach((b) => b.onclick = () => runOp(b.dataset.op));
}
