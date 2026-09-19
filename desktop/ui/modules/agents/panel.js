// Модуль «Агенты» (фронт): каталог + конструктор (скилл/шаги/DoD/анти) + запуск цепочек.
const A = "/api/modules/agents";
const esc = (s) => (s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

function modal(title, bodyHTML, onOk, okLabel) {
  const ov = document.createElement("div");
  ov.style = "position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:50";
  ov.innerHTML = `<div class="ape-card" style="width:min(620px,94vw);max-height:88vh;overflow:auto;padding:20px;gap:0">
    <div style="font-weight:600;font-size:15px;margin-bottom:14px">${esc(title)}</div>
    <div id="mBody">${bodyHTML}</div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:18px">
      <button class="btn" id="mCancel">Закрыть</button>${onOk ? `<button class="btn primary" id="mOk">${esc(okLabel || "Готово")}</button>` : ""}</div></div>`;
  document.body.appendChild(ov);
  const close = () => ov.remove();
  ov.querySelector("#mCancel").onclick = close;
  if (onOk) ov.querySelector("#mOk").onclick = () => { if (onOk(ov.querySelector("#mBody")) !== false) close(); };
  ov.onclick = (e) => { if (e.target === ov) close(); };
  return ov;
}

export async function mount(root, ctx) {
  const { api } = ctx;
  let agents = [], skills = [], chain = new Set();
  try { skills = await api(A + "/skills"); } catch {}

  root.innerHTML = `<div style="flex:1;min-width:0;height:100%;display:flex;flex-direction:column">
    <div style="display:flex;align-items:center;gap:12px;padding:16px 20px;border-bottom:1px solid var(--b1)">
      <h2 style="margin:0;flex:1;font-size:17px">Каталог агентов</h2>
      <button class="btn" id="runChain" disabled>▶ Запустить цепочку</button>
      <button class="btn primary" id="newAgent">＋ Создать агента</button>
    </div>
    <div id="grid" style="flex:1;overflow:auto;padding:18px;display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px"></div>
  </div>`;
  const $ = (id) => root.querySelector("#" + id);

  function skillOptions(sel) {
    return skills.map((s) => `<label style="display:inline-flex;gap:6px;align-items:center;margin:2px 8px 2px 0;font-size:12.5px">
      <input type="checkbox" class="sk" value="${s.id}" ${sel.includes(s.id) ? "checked" : ""}/> ${s.id}</label>`).join("");
  }

  function form(a) {
    a = a || { name: "", description: "", skills: [], steps: "", dod: "", antipatterns: "", profile: "standard" };
    return `
      <label class="faint" style="font-size:12px">Имя</label>
      <input id="f_name" value="${esc(a.name)}" style="width:100%;margin-bottom:8px" placeholder="напр. Аналитик отзывов"/>
      <label class="faint" style="font-size:12px">Описание</label>
      <input id="f_desc" value="${esc(a.description)}" style="width:100%;margin-bottom:8px" placeholder="что делает"/>
      <label class="faint" style="font-size:12px">Скиллы</label>
      <div style="margin:4px 0 8px">${skillOptions(a.skills || [])}</div>
      <label class="faint" style="font-size:12px">Шаги (методика)</label>
      <div id="f_steps_list" style="display:flex;flex-direction:column;gap:6px;margin:4px 0 6px"></div>
      <button type="button" class="btn sm" id="f_step_add" style="margin-bottom:8px">＋ шаг</button>
      <label class="faint" style="font-size:12px">Definition of Done</label>
      <textarea id="f_dod" rows="2" style="width:100%;margin-bottom:8px" placeholder="как понять, что сделано хорошо">${esc(a.dod)}</textarea>
      <label class="faint" style="font-size:12px">Анти-паттерны (чего не делать)</label>
      <textarea id="f_anti" rows="2" style="width:100%;margin-bottom:8px">${esc(a.antipatterns)}</textarea>
      <label class="faint" style="font-size:12px">Профиль</label>
      <select id="f_profile" style="width:auto;display:block;margin-top:4px">
        <option value="standard"${a.profile === "standard" ? " selected" : ""}>standard · 30B</option>
        <option value="code"${a.profile === "code" ? " selected" : ""}>code</option>
        <option value="research"${a.profile === "research" ? " selected" : ""}>ask</option>
      </select>
      <label style="display:flex;gap:8px;align-items:center;margin-top:10px;font-size:12.5px">
        <input type="checkbox" id="f_outward" ${a.outward ? "checked" : ""}/> 🛡 Действует наружу (запуск через подтверждение)</label>`;
  }

  function readForm(b) {
    const steps = [...b.querySelectorAll(".f_step")].map((i) => i.value.trim()).filter(Boolean);
    return {
      name: b.querySelector("#f_name").value.trim(),
      description: b.querySelector("#f_desc").value.trim(),
      skills: [...b.querySelectorAll(".sk:checked")].map((x) => x.value),
      steps: steps.join("\n"),
      dod: b.querySelector("#f_dod").value.trim(),
      antipatterns: b.querySelector("#f_anti").value.trim(),
      profile: b.querySelector("#f_profile").value,
      outward: b.querySelector("#f_outward").checked ? 1 : 0,
    };
  }

  // Список шагов с ↑↓✕ (как в макете-конструкторе).
  function initSteps(b, initial) {
    const list = b.querySelector("#f_steps_list");
    let steps = (initial || "").split("\n").map((s) => s.replace(/^\s*\d+[.)]\s*/, "").trim()).filter(Boolean);
    if (!steps.length) steps = [""];
    const paint = () => {
      list.innerHTML = steps.map((v, i) => `<div style="display:flex;gap:6px;align-items:center">
        <span class="ape-label" style="width:16px;text-align:right">${i + 1}</span>
        <input class="f_step" data-i="${i}" value="${esc(v)}" style="flex:1" placeholder="что сделать на этом шаге"/>
        <button type="button" class="ape-iconbtn st-up" data-i="${i}" title="выше">↑</button>
        <button type="button" class="ape-iconbtn st-dn" data-i="${i}" title="ниже">↓</button>
        <button type="button" class="ape-iconbtn st-rm" data-i="${i}" title="убрать">✕</button></div>`).join("");
      list.querySelectorAll(".f_step").forEach((inp) => inp.oninput = () => { steps[+inp.dataset.i] = inp.value; });
      const swap = (i, j) => { if (j < 0 || j >= steps.length) return; [steps[i], steps[j]] = [steps[j], steps[i]]; paint(); };
      list.querySelectorAll(".st-up").forEach((x) => x.onclick = () => swap(+x.dataset.i, +x.dataset.i - 1));
      list.querySelectorAll(".st-dn").forEach((x) => x.onclick = () => swap(+x.dataset.i, +x.dataset.i + 1));
      list.querySelectorAll(".st-rm").forEach((x) => x.onclick = () => { steps.splice(+x.dataset.i, 1); if (!steps.length) steps = [""]; paint(); });
    };
    paint();
    b.querySelector("#f_step_add").onclick = () => { steps.push(""); paint(); };
  }

  function editAgent(a) {
    const ov = modal(a ? "Редактировать агента" : "Новый агент", form(a), (b) => {
      const data = readForm(b);
      if (!data.name) { alert("Укажи имя"); return false; }
      const req = a
        ? api(A + "/catalog/" + a.id, { method: "PATCH", body: JSON.stringify(data) })
        : api(A + "/catalog", { method: "POST", body: JSON.stringify(data) });
      req.then(load);
    }, "Сохранить агента");
    const b = ov.querySelector("#mBody");
    initSteps(b, a ? a.steps : "");
    // кнопка «Предпросмотр» system-prompt
    const prev = document.createElement("button"); prev.type = "button"; prev.className = "btn sm"; prev.textContent = "👁 Предпросмотр";
    prev.style.marginTop = "10px";
    prev.onclick = () => {
      const d = readForm(b);
      const parts = [`Ты — ${d.name || "агент"}.`];
      if (d.description) parts.push(d.description);
      if (d.steps) parts.push("Методика (шаги):\n" + d.steps.split("\n").map((s, i) => `${i + 1}. ${s}`).join("\n"));
      if (d.dod) parts.push("Definition of Done:\n" + d.dod);
      if (d.antipatterns) parts.push("Избегай:\n" + d.antipatterns);
      if (d.skills.length) parts.push("Скиллы: " + d.skills.join(", "));
      alert(parts.join("\n\n"));
    };
    b.appendChild(prev);
  }

  async function runAgents(ids) {
    if (!ids.length) return;
    const ov = modal("Запуск " + (ids.length > 1 ? "цепочки" : "агента"),
      `<textarea id="task" rows="3" style="width:100%" placeholder="Задача для агента(ов)…"></textarea>
       <div id="res" style="margin-top:12px"></div>`, null);
    const b = ov.querySelector("#mBody");
    // добавим кнопку запуска внутрь модалки
    const run = document.createElement("button"); run.className = "btn primary"; run.textContent = "Запустить";
    run.style.marginTop = "8px"; b.insertBefore(run, b.querySelector("#res"));
    run.onclick = async () => {
      const task = b.querySelector("#task").value.trim(); if (!task) return;
      // governance: если среди выбранных есть агент «наружу» — сначала approve/deny-гейт
      const outward = agents.filter((a) => ids.includes(a.id) && a.outward);
      if (outward.length && ctx.gate) {
        const ok = await ctx.gate({
          title: "Запуск агента с действием наружу",
          fields: [["Агенты", outward.map((a) => a.name).join(", ")], ["Задача", task.slice(0, 80)]],
          body: "Эти агенты помечены как действующие наружу. Запустить под вашу ответственность?",
          allowLabel: "Разрешить запуск",
        });
        if (!ok) { b.querySelector("#res").innerHTML = `<div class="faint">✕ Отклонено — запуск не выполнен.</div>`; return; }
      }
      b.querySelector("#res").innerHTML = `<div class="faint">▍ агенты работают…</div>`;
      const r = await api(A + "/run", { method: "POST", body: JSON.stringify({ agent_ids: ids, task }) });
      if (!r.ok) { b.querySelector("#res").innerHTML = `<div style="color:var(--crit)">${r.error === "auth_required" ? "Нужен вход через GitHub" : "Ошибка: " + esc(r.error)}</div>`; return; }
      b.querySelector("#res").innerHTML = r.steps.map((s) =>
        `<div style="border:1px solid var(--b1);border-radius:11px;padding:10px;margin-bottom:8px">
          <div style="font-weight:600;font-size:13px;margin-bottom:4px">🤖 ${esc(s.name)}</div>
          <div style="white-space:pre-wrap;font-size:13px">${esc(s.text)}</div></div>`).join("");
    };
  }

  function render() {
    $("grid").innerHTML = agents.map((a) => `
      <div class="ape-card" style="padding:16px;gap:8px">
        <div style="display:flex;align-items:center;gap:8px">
          <input type="checkbox" class="pick" data-id="${a.id}" ${chain.has(a.id) ? "checked" : ""} title="в цепочку"/>
          <span style="font-weight:600;font-size:14px;flex:1">${esc(a.name)}${a.outward ? ` <span class="chip" style="color:var(--warn-ink)" title="действует наружу — запуск через подтверждение">🛡 наружу</span>` : ""}</span>
          <span class="ed" data-id="${a.id}" style="cursor:pointer;color:var(--ink3)">✎</span>
          <span class="del" data-id="${a.id}" style="cursor:pointer;color:var(--ink3)">🗑</span>
        </div>
        <div class="faint" style="font-size:12.5px;min-height:32px">${esc(a.description)}</div>
        <div style="display:flex;gap:4px;flex-wrap:wrap">${(a.skills || []).map((s) => `<span class="chip">${esc(s)}</span>`).join("")}</div>
        <button class="btn primary run" data-id="${a.id}" style="margin-top:auto">▶ Запустить</button>
      </div>`).join("") || `<div class="faint">Пусто. Нажми «＋ Создать агента».</div>`;
    $("grid").querySelectorAll(".pick").forEach((c) => c.onclick = () => {
      const id = +c.dataset.id; c.checked ? chain.add(id) : chain.delete(id);
      $("runChain").disabled = chain.size === 0;
      $("runChain").textContent = `▶ Запустить цепочку${chain.size ? " (" + chain.size + ")" : ""}`;
    });
    $("grid").querySelectorAll(".ed").forEach((e) => e.onclick = () => editAgent(agents.find((a) => a.id == e.dataset.id)));
    $("grid").querySelectorAll(".del").forEach((e) => e.onclick = async () => {
      if (confirm("Удалить агента?")) { await api(A + "/catalog/" + e.dataset.id, { method: "DELETE" }); load(); }
    });
    $("grid").querySelectorAll(".run").forEach((e) => e.onclick = () => runAgents([+e.dataset.id]));
  }

  async function load() { agents = await api(A + "/catalog"); render(); }

  $("newAgent").onclick = () => editAgent(null);
  $("runChain").onclick = () => runAgents(agents.filter((a) => chain.has(a.id)).map((a) => a.id));
  await load();
}
