# Курс для менеджеров (трек `managers`) — обзорный

Вводный курс «AI для менеджеров: основы работы с ИИ-агентами» — для нетехнических пользователей
с нуля. Программа: [`../course-managers-overview.md`](../course-managers-overview.md).

## Деки (в дизайн-системе портала)
8 модулей, по деку на модуль:

- `M1-chto-takoe-agent.pptx` — что такое ИИ-агент, LLM vs агент, где помогает менеджеру
- `M2-prompt.pptx` — промпт по формуле РЗФО, хороший vs плохой · **ДЗ: составить промпт**
- `M3-skilly.pptx` — готовые скиллы, как подключить из UI · **ДЗ: подключить скилл**
- `M4-svoy-skill.pptx` — свой скилл (SKILL.md без кода) · **ДЗ: составить свой скилл**
- `M5-dannye.pptx` — данные для ИИ (агент ≠ человек), файлы/RAG на пальцах
- `M6-proverka.pptx` — галлюцинации, проверка, мини-оценка · **ДЗ: проверка**
- `M7-agenty.pptx` — несколько агентов, делегирование · **ДЗ: запустить агентов**
- `M8-mini-assistent.pptx` — итог: связка промпт+скилл+данные+проверка

## Пересборка
Из корня репозитория:
```bash
py slides/build_managers.py
```
Дизайн-система — [`../../slides/slides_ds.py`](../../slides/slides_ds.py), контент деков —
[`../../slides/build_managers.py`](../../slides/build_managers.py). Шрифты: **Geist** + **JetBrains Mono**.

## Портал
Курс живёт отдельным треком `managers` (колонка `track` в `lectures`/`assignments`,
сид в `portal_api/store.py`: `MANAGERS_LECTURES` / `MANAGERS_ASSIGNMENTS`). В портале —
переключатель «Инженерный / Для менеджеров» во вкладке «Курс». API: `/api/lectures?track=managers`,
`/api/assignments?track=managers` (по умолчанию `engineer` — обратная совместимость).
Деплой: rebuild portal-api (`ensure()` создаст колонку и досеет трек) + scp `portal/index.html`.
