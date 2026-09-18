# Неделя 2 — JTBD, ICP, шорт-лист идей

Деки в дизайн-системе портала (как Лекция 1, но подробнее: схемы, подходы, таблицы
«что лучше/хуже», примеры «как это делать в `ape`»).

- **`Лекция-2-JTBD-ICP.pptx`** (`w2l1`, 08.09.2026) — JTBD-формула, ICP-канва,
  антипаттерны, источники ICP (партнёр vs Kaggle), воркшоп, чеклист 7/7.
- **`Лекция-2b-Reverse-JTBD.pptx`** (`w2l2`, 08.09.2026) — reverse JTBD пяти продуктов
  (Cursor / Perplexity / Granola / NotebookLM / Replit), паттерны победителей.

## Как пересобрать
Из корня репозитория `ai-product-engineer`:
```bash
py slides/build_lectures.py     # соберёт все деки недель 2–3
```
Дизайн-система и примитивы — в [`../../slides/slides_ds.py`](../../slides/slides_ds.py),
контент деков — в [`../../slides/build_lectures.py`](../../slides/build_lectures.py).
Шрифты для точного рендера: **Geist** + **JetBrains Mono**.
