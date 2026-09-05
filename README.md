# AI Product Engineer — курсовой контур

Инфраструктура курса **AI Product Engineer** (Соколенко М.В. · РУТ (МИИТ)): единая точка доступа
студентов к LLM и RAG через **FastMCP-сервер** с аутентификацией **Keycloak**,
cost-журналом в **Postgres** и переиспользованием живого стека **sLAVA** (Qdrant +
BGE-эмбеддер/реранкер + RouteAI) на **server-1** (201.51.5.24).

Лицензия материалов — **MIT** (как в программе курса).

## Что здесь

```
server/                 FastMCP-сервер (шлюз к моделям + RAG + квоты + cost-лог)
  auth.py               Keycloak JWT/JWKS
  db.py                 Postgres cost_journal + квоты (5M/сессия, 5/нед, 25M/нед)
  clients.py            RouteAI (LLM+embed), Qdrant, reranker, self-hosted vLLM
  pricing.py            тарифы для cost-журнала
  tools/                инструменты MCP: chat, my_usage, rag_index, rag_search, cost_report
skills/                 37 навыков для агентов (семьи Аналитика/Финансы/Архитектура/Менеджмент + инж)
examples/               показательный пример для лекции (агент кофейни)
docs/                   architecture, cost-analysis, alternatives, DEPLOY + пакет ABOP (см. ниже)
docker-compose.yml      MCP + Postgres + Caddy (TLS)
```

## Ключевые решения (детали в docs/)

- **Аутентификация:** студент → Keycloak (OIDC, GitHub login) → JWT → FastMCP (проверка
  по JWKS). Ключа провайдера у студента нет — всё через шлюз.
- **Маршрутизация моделей:** кодинг → **Qwen3.8-27B** (self-host на RTX 6000), исследования
  → **только DeepSeek**, разнообразие/fallback → RouteAI-каскад. Claude — **только лектор**.
- **Квоты:** 5M токенов/сессия × 5 сессий/неделю = 25M/студента/неделю. Cost с первой
  недели — каждый вызов в Postgres.
- **RAG:** BGE-M3 embed → Qdrant (свои коллекции `ape_*`) → BGE-rerank. Переиспользуем
  живой стек sLAVA.
- **Экономика:** ~$4–5k за весь семестр (30 студентов) вместо десятков тысяч на
  Claude-для-всех. См. `docs/cost-analysis.md`.

## Быстрый старт (локально)

```bash
cp .env.example .env       # заполни ключи и эндпоинты
pip install -e .
ape-mcp                    # поднимет MCP на 127.0.0.1:8787
```

Деплой на server-1 — `docs/DEPLOY.md`. Пример для лекции — `examples/coffee-reviews-agent/`.

## Клиент

Студенты работают через **OpenCode CLI** (OSS, OpenAI-совместимый), подключённый к
курсовому MCP по JWT. Скиллы из `skills/` кладутся в клиент как стартовый набор.

## ABOP — среда разработки агентов (продуктизация ядра)

Ядро (`cli/ape.py` + `server/`) — рабочая база продукта **ABOP** (Agent-Based Operations Platform):
онтология Семья→Роль→Навык, оркестрация волнами, Data Plane, память, аудитор. Полный пакет документов
(продукт/архитектура/дизайн/фронт) — в `docs/`.

### 🎨 Для дизайнера — точка входа

**Начинать отсюда → [`docs/ABOP_DESIGN_HANDOFF.md`](docs/ABOP_DESIGN_HANDOFF.md)** — навигатор: порядок
чтения, карта доков по ролям и **матрица привязки экран↔данные↔исполнение** (чтобы рисовать реальность,
а не выдумывать). Обязательные доки для отрисовки концепта фронта:

| Док | Что даёт |
|---|---|
| [`ABOP_PRD.md`](docs/ABOP_PRD.md) | что рисуем: вкладки, режимы, функции (FR-A/R/G/I/O) |
| [`ABOP_DESIGN_KIT.md`](docs/ABOP_DESIGN_KIT.md) + [`docs/brand/`](docs/brand/) | токены, компоненты, маскот Эйп, спиннеры, «язык ожидания» |
| [`ABOP_SCREENS.md`](docs/ABOP_SCREENS.md) | раскладка экранов: зоны, состояния, кликабельность |
| [`ABOP_OPERATIONS_MAP.md`](docs/ABOP_OPERATIONS_MAP.md) | главный экран Операций: semantic-zoom карта процессов с агентами |
| [`ABOP_UX_REFINEMENT.md`](docs/ABOP_UX_REFINEMENT.md) + [`ABOP_UX_FIXES.md`](docs/ABOP_UX_FIXES.md) | доработки по ревью + готовые тексты (не сочинять) |
| [`ABOP_2MIN_TEST.md`](docs/ABOP_2MIN_TEST.md) | критерий приёмки понимания (новичок за 2 мин, gate ≥7/10) |
| [`ABOP_DESIGN_GAPS.md`](docs/ABOP_DESIGN_GAPS.md) | чего не хватает + вкладка Безопасность + слайдер прав + light-тема |

Привязка к жизни (данные/сущности/исполнение): [`ABOP_API.md`](docs/ABOP_API.md) ·
[`ABOP_TDR.md`](docs/ABOP_TDR.md) · [`ABOP_RUNTIME_ARCHITECTURE.md`](docs/ABOP_RUNTIME_ARCHITECTURE.md) ·
[`ABOP_FLEET_OPS.md`](docs/ABOP_FLEET_OPS.md).

### Продукт и архитектура (справка)

[`ABOP_PRD.md`](docs/ABOP_PRD.md) · [`ABOP_ADR.md`](docs/ABOP_ADR.md) ·
[`ABOP_AOP.md`](docs/ABOP_AOP.md) · [`ABOP_TDR.md`](docs/ABOP_TDR.md) ·
[`ABOP_ARD.md`](docs/ABOP_ARD.md) · [`AGENT_FAMILIES_GUIDE.md`](docs/AGENT_FAMILIES_GUIDE.md) ·
[`ABOP_RUNTIME_ARCHITECTURE.md`](docs/ABOP_RUNTIME_ARCHITECTURE.md) (модели/GraphRAG/VRAM) ·
[`ABOP_FLEET_OPS.md`](docs/ABOP_FLEET_OPS.md) (управление флотом в проде).

---

## Статус

Каркас v0.1: рабочий MCP-сервер, 37 навыков, пример для лекции, cost-анализ и деплой-гайд.
Перед потоком: развернуть Keycloak-realm, вписать боевые эндпоинты/ключи в `.env`,
поднять vLLM с Qwen3.8-27B на арендованной RTX 6000, актуализировать тарифы.
