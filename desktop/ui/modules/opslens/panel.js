// Модуль «Операции» (OpsLens) — карта процессов с живыми агентами на участках (по макету).
// Предпросмотр: структура ДС + примерные участки; интерактивная карта/semantic-zoom — отдельный заход.
export async function mount(root) {
  const zones = [
    ["Приём заявок", "2 агента", "ok"], ["Квалификация", "1 агент", "ok"],
    ["Подготовка КП", "агент на участке", "warn"], ["Согласование", "только наблюдение", "idle"],
    ["Отправка", "governance-гейт", "warn"], ["Аналитика", "1 агент", "ok"],
  ];
  const dot = (s) => ({ ok: "var(--ok-ink)", warn: "var(--warn-ink)", idle: "var(--ink-3)" }[s] || "var(--ink-3)");
  root.innerHTML = `<div style="flex:1;min-width:0;height:100%;display:flex;flex-direction:column">
    <div style="display:flex;align-items:center;gap:12px;padding:14px 20px;border-bottom:1px solid var(--line)">
      <h1 class="ape-h1" style="margin:0;flex:1;font-size:22px">Операции</h1>
      <span class="chip">предпросмотр · только наблюдение</span>
      <button class="btn" disabled>Слой: процессы</button>
    </div>
    <div style="flex:1;overflow:auto;padding:20px">
      <div class="ape-label" style="margin-bottom:10px">Карта процесса · живые экземпляры на участках</div>
      <div style="display:flex;align-items:stretch;gap:0;flex-wrap:wrap">
        ${zones.map((z, i) => `
          <div class="ape-card" style="padding:14px 16px;gap:6px;min-width:170px;flex:1 1 170px">
            <div style="display:flex;align-items:center;gap:8px"><span style="width:8px;height:8px;border-radius:9999px;background:${dot(z[2])};flex:none"></span><b style="font-size:13.5px">${z[0]}</b></div>
            <div class="faint" style="font-size:12px">${z[1]}</div>
          </div>
          ${i < zones.length - 1 ? `<div style="align-self:center;color:var(--ink-3);padding:0 6px">→</div>` : ""}`).join("")}
      </div>
      <div class="faint" style="font-size:12.5px;margin-top:16px;line-height:1.6">
        Чтобы менять схему процесса и сажать агентов — переключитесь на слой правки (Граф).
        Semantic-zoom, инспектор участка (автономия/контракт/конверт участка), история и аудит — следующий заход.
      </div>
    </div>
  </div>`;
}
