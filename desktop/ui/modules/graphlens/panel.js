// Модуль «Граф» (GraphLens) — раскладка сборки потока агента по макету (палитра/холст/инспектор).
// Предпросмотр: показывает структуру ДС; интерактивный холст (drag-drop, связи) — отдельный заход.
export async function mount(root) {
  const palette = ["ожидание", "входящие", "наружу", "модель", "инструмент", "условие"];
  root.innerHTML = `<div style="flex:1;min-width:0;height:100%;display:flex;flex-direction:column">
    <div style="display:flex;align-items:center;gap:12px;padding:14px 20px;border-bottom:1px solid var(--line)">
      <h1 class="ape-h1" style="margin:0;flex:1;font-size:22px">Граф агента</h1>
      <span class="chip">предпросмотр · интерактив в разработке</span>
      <button class="btn" disabled>Проверить</button><button class="btn primary" disabled>В прод</button>
    </div>
    <div style="flex:1;display:flex;min-height:0">
      <div style="width:180px;flex:none;border-right:1px solid var(--line);padding:14px;display:flex;flex-direction:column;gap:8px">
        <div class="ape-label">Палитра · тяни на холст</div>
        ${palette.map((b) => `<div class="ape-card" style="padding:10px 12px;gap:0;font-size:13px;font-weight:600;cursor:grab">${b}</div>`).join("")}
      </div>
      <div style="flex:1;position:relative;overflow:hidden;background:
        radial-gradient(circle at center, rgba(255,255,255,.05) 1px, transparent 1px) 0 0/22px 22px">
        <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:8px;text-align:center;color:var(--ink-3)">
          <div style="font-size:15px;font-weight:600;color:var(--ink-2)">Холст пуст — три шага до результата</div>
          <div style="font-size:13px;max-width:360px">1. Перетащите блок из палитры · 2. Свяжите блоки за точки · 3. Нажмите «Проверить»</div>
        </div>
      </div>
      <div style="width:260px;flex:none;border-left:1px solid var(--line);padding:14px">
        <div class="ape-label" style="margin-bottom:8px">Инспектор узла</div>
        <div class="faint" style="font-size:13px;line-height:1.6">Семья · член семьи · модель узла · таймаут ожидания · периметр/права узла · исходящие связи. Выберите узел на холсте.</div>
      </div>
    </div>
    <div class="faint" style="font-size:12px;padding:10px 20px;border-top:1px solid var(--line)">Проверка исполнимости: среда обойдёт граф — доступность компонентов, связность, циклы. Полный интерактив холста — следующий заход.</div>
  </div>`;
}
