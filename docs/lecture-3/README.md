# Неделя 3 — AI-native discovery + выбор архитектуры

Деки в дизайн-системе портала (как Лекция 1, но подробнее: схемы, подходы, таблицы
«что лучше/хуже», примеры «как это делать в `ape`»).

- **`Лекция-3-AI-native-discovery.pptx`** (`w3l1`, 15.09.2026) — 3 способа AI в discovery,
  триада Осадчего, эхо-камера и адвокат дьявола, симуляция vs живое интервью, cost-журнал.
- **`Лекция-3b-Workflow-vs-Agent.pptx`** (`w3l2`, 15.09.2026) — три архитектуры, схемы
  потока управления, decision tree по 5 критериям, что лучше/хуже, стоимость решения,
  выбор через `architecture-chooser`.
- **`Лекция-3c-Evals-Qwen-Judge.pptx`** (`w3l4`, 17.09.2026) — три грейдера, LLM-as-judge,
  экономика судьи на self-host Qwen (≈0 ₽), trajectory/outcome-грейдер, хендс-он на
  `coffee-reviews-agent`, калибровка, A/B, ADR. Полный конспект пары —
  [`../lectures/2026-09-17-evals-qwen-judge.md`](../lectures/2026-09-17-evals-qwen-judge.md).

> `w3l3` (Speed-dating защита + КТ1) — воркшоп-регламент, отдельный контентный дек не нужен.

## Как пересобрать
Из корня репозитория `ai-product-engineer`:
```bash
py slides/build_lectures.py     # соберёт все деки недель 2–3
```
Дизайн-система и примитивы — в [`../../slides/slides_ds.py`](../../slides/slides_ds.py),
контент деков — в [`../../slides/build_lectures.py`](../../slides/build_lectures.py).
Шрифты для точного рендера: **Geist** + **JetBrains Mono**.
