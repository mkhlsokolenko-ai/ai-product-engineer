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
skills/                 21 скилл для агентов студентов (см. skills/README.md)
examples/               показательный пример для лекции (агент кофейни)
docs/                   architecture, cost-analysis, alternatives, DEPLOY
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

## Статус

Каркас v0.1: рабочий MCP-сервер, 21 скилл, пример для лекции, cost-анализ и деплой-гайд.
Перед потоком: развернуть Keycloak-realm, вписать боевые эндпоинты/ключи в `.env`,
поднять vLLM с Qwen3.8-27B на арендованной RTX 6000, актуализировать тарифы.
