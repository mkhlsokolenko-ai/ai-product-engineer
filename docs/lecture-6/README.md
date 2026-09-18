# Неделя 6 — Анатомия агента (точка входа в разработку)

Дек в дизайн-системе портала (как Лекция 1, подробно: схемы, подходы, таблицы «что
лучше/хуже», примеры «как это делать в `ape`»).

- **`Лекция-6-Анатомия-агента.pptx`** (`w6l1`) — чем агент отличается от вызова LLM,
  анатомия из 8 компонентов, принципы (ReAct-loop, условие остановки), виды агентов
  (ReAct / planner / reflection / router / multi-agent) с плюсами/минусами, и
  **требования к данным: агент ≠ человек** → canonical typed JSON (Data Plane / `/data`).
  Это стартовая точка разработки — с неё студент начинает собирать своего агента.

**ДЗ на разработку агента:** [`../lectures/dz-agent-anatomy.md`](../lectures/dz-agent-anatomy.md)
(анатомия + паттерн + loop с условием остановки + ≥2 tools + structured output + Data-recipe
источник→canonical JSON; идёт в допуск к КТ2).

> `w6l2` (Hard prompts + КТ2) — сюда переехали prompt vs context engineering и hard prompts.

## Как пересобрать
Из корня репозитория `ai-product-engineer`:
```bash
py slides/build_lectures.py     # соберёт все деки (недели 2, 3, 6)
```
Дизайн-система — [`../../slides/slides_ds.py`](../../slides/slides_ds.py), контент —
[`../../slides/build_lectures.py`](../../slides/build_lectures.py). Шрифты: **Geist** + **JetBrains Mono**.
