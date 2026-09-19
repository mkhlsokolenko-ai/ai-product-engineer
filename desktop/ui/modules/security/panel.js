// Модуль «Безопасность» (AdminScreens): RBAC-политика, периметр, эскалация, ре-аттестация, аудит.
// Структура по макету; энфорс — на шлюзе (роли Keycloak), пока предпросмотр. + демо approve/deny-гейта.
const S = "/api/modules/security";
const esc = (s) => (s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

export async function mount(root, ctx) {
  const { api, gate } = ctx;
  let p = {};
  try { p = await api(S + "/policy"); } catch {}
  const badge = p.enforced
    ? `<span class="chip on">RBAC активен</span>`
    : `<span class="chip">предпросмотр · энфорс на шлюзе позже</span>`;

  const roles = (p.roles || []).map((r) => `
    <div class="ape-card" style="padding:14px 16px;gap:8px">
      <div style="display:flex;align-items:center;gap:8px"><b style="flex:1;font-size:14px">${esc(r.role)}</b>
        <button class="ape-iconbtn" title="Править (позже)" disabled>✎</button></div>
      <div style="display:flex;gap:6px;flex-wrap:wrap"><span class="ape-label" style="width:74px">разрешено</span>${(r.allowed || []).map((x) => `<span class="chip on">${esc(x)}</span>`).join("")}</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap"><span class="ape-label" style="width:74px">запрещено</span>${(r.denied || []).map((x) => `<span class="chip" style="color:var(--danger-ink)">${esc(x)}</span>`).join("") || '<span class="faint" style="font-size:12px">—</span>'}</div>
    </div>`).join("");

  const card = (title, body) => `<div class="ape-card" style="padding:16px;gap:6px"><div class="ape-label">${esc(title)}</div><div style="font-size:13px;line-height:1.5;color:var(--ink-2)">${body}</div></div>`;

  root.innerHTML = `<div style="height:100%;overflow:auto;padding:22px">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
      <h1 class="ape-h1" style="margin:0;flex:1">Безопасность</h1>${badge}
      <button class="btn" id="gateDemo">Демо approve/deny</button>
    </div>
    <div class="ape-label" style="margin:4px 0 10px">Политика доступа · роль → разрешено / запрещено</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin-bottom:18px">${roles}</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px">
      ${card("Периметр агента", esc(p.perimeter || ""))}
      ${card("Модель эскалации", esc((p.escalation || {}).note || ""))}
      ${card("Ре-аттестация прав", "Период " + ((p.reattest || {}).period_days || "—") + " дн. · " + esc((p.reattest || {}).note || ""))}
      ${card("Аудит ИБ", esc(p.audit_note || ""))}
    </div>
    <div class="faint" style="font-size:12px;margin-top:14px">Роли приходят из Keycloak; правки версионируются и попадают в аудит ИБ. Реальный энфорс — на шлюзе (агент × инструмент × источник).</div>
  </div>`;

  root.querySelector("#gateDemo").onclick = async () => {
    const ok = await gate({
      title: "Оценка идеи · отправка письма",
      fields: [["Кому", "partner@example.com"], ["Тема", "Оценка идеи · маркетплейс подрядчиков"], ["Провенанс", "312 записей · маска применена"]],
      body: "Добрый день! Прогон завершён: результат положительный при удержании. Критик отметил риск концентрации трафика — предлагаю проверить гипотезу на втором канале до масштабирования.",
      allowLabel: "Разрешить отправку",
    });
    alert(ok ? "✓ Действие разрешено (при коннекторах — отправится)" : "✕ Отклонено — наружу ничего не ушло");
  };
}
