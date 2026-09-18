// Модуль «Кабинет»: расход/квота (my_usage через шлюз) + каркас рабочих источников и RBAC.
const C = "/api/modules/cabinet";
const esc = (s) => (s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const fmt = (n) => (n || 0).toLocaleString("ru-RU");

function tile(label, value, sub) {
  return `<div style="background:var(--panel);border:1px solid var(--b1);border-radius:12px;padding:14px 16px;min-width:170px">
    <div class="faint" style="font-size:11.5px;text-transform:uppercase;letter-spacing:.04em">${esc(label)}</div>
    <div style="font-size:24px;font-weight:700;margin-top:4px">${value}</div>
    <div class="faint" style="font-size:12px">${esc(sub || "")}</div></div>`;
}

export async function mount(root, ctx) {
  const { api } = ctx;
  root.innerHTML = `<div style="padding:22px;overflow:auto;height:100%"><div id="cb">Загрузка…</div></div>`;
  const cb = root.querySelector("#cb");

  let u;
  try { u = await api(C + "/usage"); } catch (e) { u = { ok: false, error: e.message }; }

  let usageHTML;
  if (u.ok) {
    const w = u.report.week || {};
    usageHTML = `<div style="display:flex;gap:12px;flex-wrap:wrap">
      ${tile("Токены за неделю", fmt(w.tokens_used), "из " + fmt(w.limit || 25000000))}
      ${tile("Осталось", fmt(w.remaining), (w.used_pct ?? 0) + "% израсходовано")}
      ${tile("Потрачено", (w.cost_rub != null ? w.cost_rub.toFixed(2) + " ₽" : "—"), "за неделю")}
      ${tile("Вызовов", fmt(w.calls), "через шлюз")}</div>
      <div class="faint" style="font-size:12px;margin-top:10px">Сброс квоты — в понедельник. Self-host 30B считается по нулевой марж. стоимости.</div>`;
  } else if (u.error === "auth_required") {
    usageHTML = `<div class="faint">Войди через GitHub (кнопка вверху), чтобы увидеть расход.</div>`;
  } else {
    usageHTML = `<div style="color:var(--crit)">Не удалось получить расход: ${esc(u.error || "")}</div>`;
  }

  let srcHTML = "";
  try {
    const s = await api(C + "/sources");
    srcHTML = `<h3 style="margin:26px 0 10px">Рабочие источники и доступ</h3>
      <div style="display:flex;flex-direction:column;gap:8px;max-width:640px">
      ${s.connectors.map((c) => `<div style="display:flex;align-items:center;gap:10px;background:var(--panel);border:1px solid var(--b1);border-radius:10px;padding:10px 14px">
        <span style="flex:1;font-size:13.5px">${esc(c.title)}</span>
        <span class="chip">${c.status === "planned" ? "скоро" : esc(c.status)}</span></div>`).join("")}
      <div style="display:flex;align-items:center;gap:10px;background:var(--panel);border:1px solid var(--b1);border-radius:10px;padding:10px 14px">
        <span style="flex:1;font-size:13.5px">RBAC — роли и доступ к инструментам/источникам</span>
        <span class="chip">скоро</span></div></div>
      <div class="faint" style="font-size:12px;margin-top:8px">Коннекторы Word/Excel/ИС и RBAC подключаются на этапе смычки с ABOP (Data Plane). Настроенные источники дадут агенту контекст последних рабочих файлов прямо в чате.</div>`;
  } catch {}

  cb.innerHTML = `<h2 style="margin:0 0 16px">Личный кабинет</h2>${usageHTML}${srcHTML}`;
}
