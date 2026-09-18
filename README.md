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
  db.py                 Postgres cost_journal + недельная квота (25M/студента/неделю)
  clients.py            RouteAI (LLM+embed), Qdrant, reranker, self-host vLLM; chat + chat_stream (SSE)
  pricing.py            тарифы cost-журнала (self-host local/* = 0 ₽)
  tools/                инструменты MCP: chat, my_usage, rag_index, rag_search, cost_report
portal/                 SPA личного кабинета/курса (index.html; :ro-маунт, отдаёт Caddy)
portal_api/             FastAPI портала: лекции/ДЗ/оценки/хранилище + POST /api/chat/stream (SSE)
  store.py              программа курсов: треки engineer (v0.6) и managers
cli/                    курсовой CLI `ape` (v1.18) — чистый stdlib, вход через GitHub
desktop/                APE Desktop — оболочка (Electron + Python sidecar), модульная
skills/                 44 навыка для агентов (семьи Аналитика/Финансы/Архитектура/Менеджмент + инж)
slides/                 генераторы деков лекций в дизайн-системе (slides_ds.py + build_*.py)
examples/               показательный пример для лекции (агент кофейни)
docs/                   architecture, DEPLOY (runbook), курсы, лекции + пакет ABOP (см. ниже)
docker-compose.yml      MCP + portal-api + Postgres + Keycloak + Caddy + MinIO
```

## Ключевые решения (детали в docs/)

- **Аутентификация:** студент → Keycloak (OIDC, GitHub login) → JWT → FastMCP/portal-api
  (проверка по JWKS). Ключа провайдера у студента нет — всё через шлюз.
- **Маршрутизация моделей (актуально):** **все профили** (`standard`/`code`/`research`) →
  **self-host Qwen3-30B-A3B** (`local/qwen3-30b-a3b`, vLLM FP8 на арендованной Ada-карте),
  **DeepSeek — fallback** в каскаде. Claude — только лектор. Задаётся в `.env` cascades.
- **Стриминг:** `POST /api/chat/stream` (portal-api, SSE) → `clients.chat_stream` → vLLM;
  квота проверяется до, cost логируется после (по usage из финального чанка). Для десктоп-оболочки.
- **Квоты:** единственный лимит — **25M токенов/студента/неделю** (сброс в понедельник).
  Cost с первой недели — каждый вызов в Postgres (`cost_journal`); self-host = 0 ₽ per-token.
- **RAG:** BGE-M3 embed → Qdrant (`ape_*`) → BGE-rerank. Переиспользуем стек sLAVA.
- **Экономика:** ~$4–5k за семестр (30 студентов). См. `docs/cost-analysis.md`.

## Быстрый старт (локально)

```bash
cp .env.example .env       # заполни ключи и эндпоинты
pip install -e .
ape-mcp                    # поднимет MCP на 127.0.0.1:8787
```

Деплой/восстановление на server-1 — **`docs/DEPLOY.md`** (runbook: контейнеры, per-service
scp+rebuild, SSH-нюансы, жизненный цикл Qwen-инстанса на Vast). Пример — `examples/coffee-reviews-agent/`.

## Клиенты

- **`ape`** (осн. путь) — курсовой CLI, `pip install -U "git+https://github.com/mkhlsokolenko-ai/ai-product-engineer#subdirectory=cli"`, вход `ape login` (GitHub). Артефакты → `docs/` проекта. Гайд: `docs/APE_GUIDE.md`.
- **APE Desktop** — устанавливаемое приложение (Electron + Python sidecar), модульное (чат/кабинет; roadmap: OCR/NLP/рабочие источники/ABOP). Сборка/доставка: `desktop/README.md`, приоритеты: `desktop/docs-competitive-moscow.md`.
- Портал — `engineer-ai.pro` (кабинет, курс, оценки, хранилище).

## Курсы (портал, трек в `portal_api/store.py`)

- **engineer** (v0.6, 15 недель) — инженерный: discovery → design → build → evals/экономика → защита.
- **managers** — обзорный для менеджеров (8 модулей): промпт, скиллы, свой скилл, данные, проверка, мультиагенты. Программа `docs/course-managers-overview.md`, деки `docs/managers/`.
- Деки лекций — `docs/lecture-*/`, генераторы — `slides/`.

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

### 🛠 Для инженера — точка входа

**Сквозной системный дизайн → [`docs/ABOP_SDD.md`](docs/ABOP_SDD.md)** — как части связаны в жизни + два рыночных
пробела: **подхват уже работающих агентов** организации (brownfield, LangChain/LangGraph как основа; OpenClaw/Hermes
через Agent Adapter Layer + governance-конверт — §3) и **как контракты LUDA попадают в ABOP** (Contract Ingress:
транспорт → валидация схем → привязка к развёртыванию — §4). Решения зафиксированы в [`ABOP_ADR.md`](docs/ABOP_ADR.md)
(ADR-028 конверт-над-рантаймом, ADR-029 Contract Ingress).

### Продукт и архитектура (справка)

[`ABOP_PRD.md`](docs/ABOP_PRD.md) · [`ABOP_ADR.md`](docs/ABOP_ADR.md) ·
[`ABOP_AOP.md`](docs/ABOP_AOP.md) · [`ABOP_TDR.md`](docs/ABOP_TDR.md) ·
[`ABOP_ARD.md`](docs/ABOP_ARD.md) · [`AGENT_FAMILIES_GUIDE.md`](docs/AGENT_FAMILIES_GUIDE.md) ·
[`ABOP_RUNTIME_ARCHITECTURE.md`](docs/ABOP_RUNTIME_ARCHITECTURE.md) (модели/GraphRAG/VRAM) ·
[`ABOP_FLEET_OPS.md`](docs/ABOP_FLEET_OPS.md) (управление флотом в проде).

---

## Статус (актуально)

Развёрнуто на server-1 (`/home/slava/ai-product-engineer`, compose-проект `ai-product-engineer`):
MCP + portal-api + Postgres + Keycloak + Caddy + MinIO. Self-host **Qwen3-30B-A3B FP8** на Vast
(эндпоинт в `.env → LOCAL_LLM_BASE_URL`, инстанс пересоздаётся — см. `docs/DEPLOY.md`). Стриминг,
44 навыка, два курса (engineer/managers), CLI `ape` v1.18, APE Desktop v0.1 (инсталлятор + авто-апдейт).
Полный порядок восстановления/деплоя/настройки — **`docs/DEPLOY.md`**.
