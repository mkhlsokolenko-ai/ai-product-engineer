# Неделя 4 — Design-doc: MLSDD или Agent Design

Дек в дизайн-системе портала (как остальные: схемы, таблицы «что лучше/хуже», примеры «как в `ape`»).

- **`Лекция-4-Design-doc-MLSDD-Agent.pptx`** (`w4l1`, 22.09.2026) — зачем design-doc (intent as
  source of truth), выбор шаблона по архитектуре недели 3 (workflow→MLSDD, agent→Agent Design,
  hybrid→оба), структуры обоих, хороший vs плохой документ, скиллы `mlsdd-writer`/`agent-design-writer`.
  **Практика + проверка вживую:** каждый заполняет ≥4 раздела своей идеи; одна идея защищается
  вживую (5 мин) и проверяется группой/лектором на прочность (spec-reviewer/devils-advocate),
  правки заносятся на месте.

## Как пересобрать
Из корня репозитория: `py slides/build_lectures.py` (собирает все деки; недели 2/3/4/6).
Дизайн-система — `slides/slides_ds.py`. Шрифты: Geist + JetBrains Mono.
