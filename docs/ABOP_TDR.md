# ABOP — Technical Design Record (TDR)

**Продукт:** ABOP (Agent-Based Operations Platform) — продуктизация LUDA v2, рантайм исполнения агентов.
**Версия:** 0.2, draft
**Связанные документы:** `ABOP_ARD.md` (архитектурные решения — ЧТО и ПОЧЕМУ), `AGENT_FAMILIES_GUIDE.md`, `DATA_RECIPES.md`, `APE_GUIDE.md`, `DEPLOY.md`, `architecture.md`. Каноны LUDA v2 — `Downloads/LUDA pivot/{PRD,ADR,TDR,AOP}.md`.

> Этот документ описывает **техническое устройство** (КАК). Продуктовые решения и их обоснование (ЧТО/ПОЧЕМУ) — в `ABOP_ARD.md`; на конкретные развилки ссылаемся как ADR-0NN. Источник истины по реализации — код: `cli/ape.py` (клиент-рантайм) и `server/` (FastMCP-шлюз).

---

## 1. Границы документа

Документ описывает внутреннее устройство рантайма агентов ABOP в его текущей реализации: топологию (клиент ↔ шлюз ↔ бэкенды), компоненты Agent Plane / Tool Plane / Data Plane, модель данных (Blackboard, долговременная память, навыки, семьи, канонические записи), инварианты безопасности регулируемого периметра, механизмы (use_skill / become / handoff / recall / forget / аудитор / дистилляция), контракты вызова и стек.

**Не описывает:** методологию продукта и обоснование решений (см. `ABOP_ARD.md`); внутреннее устройство LUDA v2 (диагностический аудитор — `Downloads/LUDA pivot/TDR.md`) и sLAVA (RAG по нормативке); реализацию Data Plane в проде (в учебном контуре — упрощённый аналог, см. §12).

**Полигон vs прод.** Реализация живёт в учебном проекте `ai-product-engineer` (CLI `ape` + `server/`). Это **безопасный полигон**, где обкатываются принципы и архитектура; в ABOP-периметр (ФСТЭК/ДСП/ФЗ-152) переносятся паттерны, а часть слоёв заменяется кодом LUDA (ADR-019). Перенос полигон→прод — открытый вопрос §13.

---

## 2. Топология

### 2.1. Развёртывание

```
рабочая машина инженера              периметр шлюза (engineer-ai.pro)
┌────────────────────────┐          ┌──────────────────────────────────────────┐
│  CLI  ape  (Python)    │          │  FastMCP-шлюз  (server/main.py)           │
│  ┌──────────────────┐  │          │  ┌────────────────────────────────────┐  │
│  │ Оркестратор      │  │  HTTPS   │  │ JWTVerifier (Keycloak/JWKS)        │  │
│  │ (планировщик,    │  │  MCP     │  │  issuer·audience·exp·подпись       │  │
│  │  cmd_agents)     │──┼──────────┼─▶│                                    │  │
│  ├──────────────────┤  │ streamable│ ├────────────────────────────────────┤  │
│  │ Воркеры (ReAct,  │  │  -http   │  │ tools: chat · rag_index/search ·   │  │
│  │  stateless)      │  │  JSON-RPC │  │        my_usage · cost_report      │  │
│  ├──────────────────┤  │          │  └───────┬──────────────┬─────────────┘  │
│  │ Blackboard (FS)  │  │          │          │              │                 │
│  │ longterm.jsonl   │  │          │  ┌───────┴──────┐  ┌────┴──────────────┐ │
│  │ Data store (FS)  │  │          │  │ cost_journal │  │ клиенты (clients) │ │
│  └──────────────────┘  │          │  │ (Postgres)   │  │  chat/embed/rerank│ │
│  ~/.ape/               │          │  └──────────────┘  └────┬──────────────┘ │
└────────────────────────┘          └─────────────────────────┼────────────────┘
                                                               │
                            ┌──────────────────────────────────┼───────────────┐
                            ▼                    ▼              ▼                ▼
                     RouteAI (Qwen код /   vLLM local/*    Qdrant (RAG,   sLAVA /rerank
                     DeepSeek ресёрч)      (RTX 6000)      ape_-префикс)  (опц. backend)
```

Клиентское состояние прогона (Blackboard, долговременная память, рецепты и canonical store, конфиг/токены) хранится на диске рабочей машины в `~/.ape/` (`CFG_DIR`). Шлюз безсостоятелен относительно прогона: он метрит и маршрутизирует, но не держит доску.

**Единая точка наружу — шлюз.** CLI не ходит в модели напрямую; любой вызов модели/RAG идёт через MCP-инструмент `chat`/`rag_*`. Внешний egress в прод-периметре — через прокси sLAVA (ADR-018); в учебном контуре модели дёргаются через RouteAI/vLLM за шлюзом.

### 2.2. Транспорт и клиент

- **Протокол:** MCP поверх JSON-RPC 2.0, транспорт `streamable-http` (`_mcp_call` в `ape.py`). Клиент делает `initialize` → `notifications/initialized` → `tools/call`. Ответ читается как `application/json` либо распаковывается из `text/event-stream` (строки `data:`). Сессия MCP держится по заголовку `mcp-session-id`.
- **Устойчивость:** сетевые вызовы (`_mcp_call`, `_post_form`) ретраятся с бэкоффом на TLS-reset/URLError (DPI/антивирус рвут рукопожатие) — до 4 попыток.
- **Авторизация:** OIDC loopback-PKCE (`login`) через Keycloak realm `ai-product-engineer`, IdP-hint `github`. Access-token кешируется в `~/.ape/config.json` (chmod 600), авто-`_refresh` по `expires_at`. На каждый RPC — заголовок `Authorization: Bearer <access_token>`; при 401 — один авторефреш и повтор.

### 2.3. Шлюз (server/)

- `main.py` собирает `FastMCP` с `auth=build_verifier()` и регистрирует инструменты (`register_all`). Транспорт `http`, host/port из настроек, наружу — через Caddy (TLS).
- `auth.py`: `JWTVerifier` проверяет подпись по JWKS realm'а (`kc_jwks_internal`, внутренняя сеть), `issuer`, `audience`. `current_student()` достаёт claims (`sub`/`preferred_username`/`email`) уже провалидированного токена — ключ привязки к `cost_journal`.
- `tools/`: `llm.py` (`chat`, `my_usage`), `rag.py` (`rag_index`, `rag_search`), `admin.py` (`cost_report`, роль лектора).
- `clients.py`: HTTP-клиенты к RouteAI (chat/embed/rerank), vLLM (`local/*`), Qdrant, sLAVA `/rerank`. Каскад моделей по профилю (`cascade_for`).

---

## 3. Компоненты

| Компонент | Модуль / символ | Ответственность | Чего не делает |
|---|---|---|---|
| **Оркестратор** | `cmd_agents`, `_run_wave`, `_wave_items` | Планирует волны (LLM-план→JSON, фолбэк-эвристика), назначает семью+роль, барьер fan-in, поднимает эстафеты и ремедиацию, синтезирует итог | Не исполняет задачу сам |
| **Воркер** | `_agent_run` | ReAct-цикл одного stateless-агента: system из семьи, чтение доски, шаги через tools, become/handoff/final | Не хранит состояние между прогонами |
| **Blackboard** | `bb_append`, `bb_state`, `bb_context`, `bb_compact` | Общая рабочая память прогона (event-sourced, append-only, свёртка, snapshot-компакция) | Не долговременное хранилище |
| **Реестр навыков** | `SKILLS`, `SKILL_SAFETY`, `load_skill_body`, `skills/<id>/SKILL.md` | Карточки + тела навыков (progressive disclosure), метаданные безопасности | Не исполняет навык вместо агента |
| **Реестр семей** | `AGENT_FAMILIES`, `family_system`, `route_family`, `route_member` | Онтология Семья→Член-роль→Навыки, сборка system, маршрутизация | Не жёстко закрепляет роль (become разрешён) |
| **Data Plane** | `data_run`, `data_query`, `_map_field`, `_rule_ok`, `_mask` | Декларативный рецепт источник→canonical JSON, append-only store, чтение агентом | **Заглушка-MVP:** только csv/json, без адаптеров/canonical-движка LUDA (ADR-003/004) |
| **Долговременная память** | `_t_remember`, `recall_longterm`, `forget_expired`, `_MEM_TTL_DAYS` | Слой знания между прогонами с TTL по критичности | Не векторный поиск (грубый лексический recall) |
| **Агент-аудитор** | `_audit_gate` | Governance-петля: выводит Definition of Done из цели, сверяет результат, вердикт+пробелы | Не выполняет задачу заново, не добавляет фактов |
| **Память диалога** | `mem_load/save`, `mem_system`, `_distill`, `mem_add` | Двухуровневая память чата (дистиллят + последние реплики) для REPL | Не связана с Blackboard прогона |
| **Шлюз** | `server/*` | JWT-верификация, каскад моделей, RAG, cost-журнал, квоты | Не оркеструет агентов (оркестрация — на клиенте) |

Агент-аудитор изолирован как отдельная governance-петля: результат прогона проходит через него до синтеза. **Ограничение текущей реализации:** аудитор ходит в ту же модель-класс (`profile=research`), что и воркеры — независимого аудитора нет (см. §12).

---

## 4. Модель данных

Состояние прогона и знания — на файловой системе клиента (`~/.ape/`, ключ по `session_id`). Cost-журнал — в Postgres на шлюзе.

### 4.1. Событие Blackboard (`blackboard-<session>.jsonl`, append-only)

Каждая строка — одно событие. Свёртка (`bb_state`) даёт `(facts, notes, claims)`; `snapshot` сбрасывает базу при компакции.

```jsonc
{"ts": 1.7e9, "type": "set",     "key": "файл:тз.md", "value": "…", "agent": "ты"}
{"ts": 1.7e9, "type": "note",    "text": "применяет навык market-research", "agent": "в1.2"}
{"ts": 1.7e9, "type": "claim",   "task": "собрать рынок", "agent": "в1.1"}
{"ts": 1.7e9, "type": "result",  "text": "итог роли…", "agent": "в1.3"}
{"ts": 1.7e9, "type": "handoff", "task": "посчитать DCF", "to_family": "finance",
                                 "to_member": "valuation", "from": "в1.2"}
{"ts": 1.7e9, "type": "handoff_done", "task": "посчитать DCF", "agent": "оркестратор"}
{"ts": 1.7e9, "type": "snapshot","facts": {...}, "notes": [...], "claims": {...}}
```

Типы: `set` (факт key=value), `note` (крошка), `claim` (застолблённая подзадача — нет дублей), `result` (результат роли), `handoff`/`handoff_done` (эстафета и её погашение), `snapshot` (компакция).

### 4.2. Запись долговременной памяти (`longterm.jsonl`, append-only)

```jsonc
{"key": "dcf-acme", "text": "…", "agent": "в2.1", "session": "ape-1a2b",
 "criticality": "critical", "ttl_days": 365, "saved_ts": 1.7e9}
```

**Классы TTL (`_MEM_TTL_DAYS`, дней):** `operational` 7 · `important` 90 · `critical` 365 · `regulatory` 1825 · `permanent` 0 (не истекает). Класс задаётся явно или выводится эвристикой по ключу (`_mem_class`, `_MEM_KEY_HINT`). `forget_expired` физически удаляет протухшее; `recall_longterm` протухшее не поднимает (двойная защита инварианта TTL).

### 4.3. Метаданные навыка (`skill_safety(id)`)

```python
{"mode": "read|write|action", "egress": "internal|external", "cite": bool}
```

- `mode`: `read` (анализ, без артефактов) · `write` (локальный артефакт в `./ape_work`) · `action` (запись/отсылка во внешнюю систему → только dry_run + подтверждение человека, HITL).
- `egress`: `external` → на границе injection-guard + PII-маскирование.
- `cite`: `True` → числа/факты только из источника (анти-галлюцинация).

Дефолт `_SAFE_DEFAULT = {read, internal, cite:false}`. Пометки инъектятся в system роли (`_safety_line`) и повторно навязываются при `use_skill` (`_t_use_skill`).

### 4.4. Структура семьи (`AGENT_FAMILIES[fam]`)

```python
{"title": str, "profile": "code|research", "mission": str,
 "members": {role_id: (title, [skill_id, ...])}}
```

Три уровня: Семья (направление) → Член-роль → Навыки (переиспользуются из `SKILLS`, не дублируются). Бизнес-семьи ABOP: `analytics`, `finance`, `architecture`, `management`; инженерные семьи APE-полигона: `discovery`, `eng-architect`, `critic`, `economics`, `delivery`, `decisions`.

### 4.5. Каноническая запись Data Plane (`data/<entity>.jsonl`, append-only)

Продукт рецепта: map-поля + самоописание + провенанс + TTL.

```jsonc
{"id": "...", "customer": "ig***@acme.com", "amount": 12000.0,
 "schema": "transaction", "schema_version": "1.0",
 "provenance": {"recipe": "acme", "source": "csv:…", "row": 3, "fetched_at": 1.7e9},
 "ttl_sec": 86400}
```

Чтение (`data_query`) делает dedup по `id` (последняя запись), фильтр по точному совпадению, проекцию полей.

### 4.6. Cost-журнал (Postgres, шлюз)

`cost_journal(student_id, username, session_id, kind[llm|embed|rerank], model, profile, prompt_version, input_tokens, output_tokens, cost_rub, meta jsonb, ts)`. Из него считаются квоты: недельный потолок токенов на студента (`WEEKLY_TOKEN_LIMIT`, дефолт 25M). Лимиты «на сессию»/«сессий в неделю» присутствуют в отчёте, но не ограничивают (`check_quota` гейтит только недельный).

---

## 5. Инварианты

Инварианты регулируемого периметра. Часть — конструктивные (обеспечены кодом), часть — навязываются агенту через system/пометки (LLM-исполнение → не гарантия, а контракт поведения; для прода требуется усиление, см. §13).

| ID | Инвариант | Как обеспечивается |
|---|---|---|
| **A1** | Числа/факты — только из источника (`cite`) | `SKILL_SAFETY[*].cite`; навязывается в system и при `use_skill`; финансы/аналитика помечены `cite:true` |
| **A2** | Действие во внешнюю систему → HITL | `mode:action` → `use_skill` возвращает предписание «только dry_run + подтверждение человека»; ничего не отправляется без одобрения |
| **A3** | Внешний контент → anti-injection + PII | `egress:external` → injection-guard в предписании; `_mask` маскирует ПДн в Data Plane (`pii_mask` в рецепте) |
| **A4** | Автономия агента ≤ контракт LUDA | Прод-связь: ABOP не даёт autonomy_level выше `DeploymentContract` от LUDA (AOP §7.3; в полигоне не форсируется) |
| **A5** | Каждый навык применяется через `use_skill` | System роли даёт только КАРТОЧКИ навыков; полное тело — через `_t_use_skill` (progressive disclosure) |
| **A6** | Забытое по TTL не воскресает | `recall_longterm` пропускает протухшее; `forget_expired` физически чистит (инвариант хранения) |
| **A7** | Воркер stateless | `_agent_run` не хранит состояние между прогонами; состояние — на доске (`bb_*`) и в долговременной памяти (`remember`) |
| **A8** | Claim исключает дубли | `bb_claim` отказывает, если задача уже за другим агентом (`bb_state.claims`) |
| **A9** | Каждый LLM-вызов метрится и лимитируется | `chat` → `check_quota` → `log_usage` в `cost_journal`; недельный потолок токенов |
| **A10** | Единая точка доступа к моделям | Модели дёргаются только через MCP `chat`/`rag_*`; клиент не ходит в RouteAI/vLLM напрямую |
| **A11** | Аудитор не выполняет задачу заново | `_audit_gate` system: «НЕ выполняй задачу заново, НЕ добавляй новых фактов» — только DoD-вердикт |
| **A12** | Egress под JWT студента | Каждый вызов через шлюз с провалидированным Bearer-JWT; изоляция/мультитенантность по `sub` |

---

## 6. Оркестрация волнами (fan-out / fan-in)

### 6.1. План

`cmd_agents(goal)` раскрывает `@файлы` и кладёт их содержимое на доску как факты `файл:…` (каждая волна видит их через `bb_context`). Затем просит модель составить план из 1–3 **волн**; волна = список независимых задач (≤ `AGENT_MAX`=4), каждой задаче назначается семья-исполнитель из ростера. План парсится терпимо (`_json_waves_fam`): невалидная/пропущенная семья до-маршрутизируется эвристикой `route_family`. Фолбэк при сбое планирования — одна волна с одной задачей.

### 6.2. Волна

`_run_wave` нормализует задачи (`_wave_items`: task→семья→член-роль через `route_family`/`route_member`), запускает воркеров в потоках (`threading`), рендерит живой статус, ждёт барьер (все потоки join). Между волнами доска обновлена — следующая волна её читает (fan-in через Blackboard, а не прямой обмен). `STEP_MAX`=5 шагов ReAct на воркера.

### 6.3. Пост-обработка

После волн оркестратор: (1) поднимает **открытые эстафеты** (`bb_pending_handoffs`) доп-волнами (до 2 раз, погашая `handoff_done`); (2) прогоняет **аудитора** (`_audit_gate`); (3) при провале DoD с конкретными пробелами — одна **авто-ремедиация** (волна «закрой пробел»); (4) **синтезирует** единый итог из доски, результатов волн и вердикта. При росте доски >150 событий — `bb_compact`.

---

## 7. Механизмы

- **`use_skill(id)`** (`_t_use_skill`) — progressive disclosure: system даёт лишь карточки навыков роли; полное тело (`skills/<id>/SKILL.md` или карточка-фолбэк, до 6000 симв.) подгружается по требованию, факт применения пишется на доску (аудит), к телу добавляются предписания безопасности по `skill_safety`.
- **`become(member)`** (в `_agent_run`) — смена роли-члена внутри семьи по ходу цикла: переназначает system (`family_system`), фиксирует смену на доске. Роль вне семьи отклоняется.
- **`handoff(task, family, member, result)`** (`_t_handoff`) — эстафета через доску: результат текущей роли → `result`-событие, задача → `handoff`-событие. Оркестратор поднимает непогашенные эстафеты доп-волной. Работает благодаря stateless-воркерам (состояние передаётся через доску, а не через объект).
- **`recall_longterm(query)`** — preflight-петля: перед работой воркер получает в контекст похожее из долговременной памяти (грубый лексический скоринг по словам ≥4 симв.), протухшее по TTL исключено.
- **`forget_expired()`** — вызывается в начале `cmd_agents`: физически удаляет протухшие записи, не раздувая постоянную память.
- **`_audit_gate`** — governance-петля: DoD-вердикт `{dod, checks, passed, gaps}` + одна авто-ремедиация при провале.
- **Дистилляция** — двухуровневая память: `bb_compact` сворачивает лог доски в snapshot; `_distill`/`mem_add` сворачивают старые реплики диалога REPL в структурный конспект (шаблон `_DISTILL_PROMPT`), оставляя последние реплики дословно.

---

## 8. Реестр инструментов агента (`AGENT_TOOLS`)

ReAct-цикл возвращает на каждом шаге ровно один JSON: `{"tool":…,"args":…}` либо `{"final":…}` (`_AGENT_SYS`, парсинг `_json_first`). Инструменты воркера (клиентские, поверх MCP-шлюза):

| Инструмент | Функция | Назначение |
|---|---|---|
| `rag_search` | `_t_rag` | Поиск по своей RAG-коллекции (через `chat`/`rag_search` шлюза) |
| `read_file` / `write_file` | `_t_read` / `_t_write` | Чтение локального файла / запись в `./ape_work` (артефакт, наружу не уходит) |
| `ask` | `_t_ask` | Спросить исследовательскую модель |
| `bb_post` / `bb_read` / `bb_claim` | `_t_bb_*` | Запись факта/крошки, чтение доски, застолбление подзадачи |
| `use_skill` | `_t_use_skill` | Подгрузка методики навыка + предписания безопасности |
| `handoff` | `_t_handoff` | Эстафета задачи другой роли/семье |
| `remember` | `_t_remember` | Долговременная память с TTL по критичности |
| `data_query` | лямбда → `data_query` | Машиночитаемые данные из Data Plane |
| `become` | (в `_agent_run`) | Смена роли-члена внутри семьи |

Воркер подписывает свои записи на доске (`args["_agent"]=me`).

---

## 9. Контракты

### 9.1. Единый контракт вызова (клиент → шлюз, ADR-017)

Любой вызов модели/RAG идёт через MCP-инструмент со сквозными атрибутами:

```
session_id  — id рабочей сессии (группировка вызовов, ключ cost_journal)
JWT         — Bearer, провалидирован JWTVerifier (Keycloak)  → изоляция/мультитенантность по sub
cost_journal — каждый вызов метрится (input/output tokens, cost_rub, model, profile)
```

Ответ `chat` (структурный):

```jsonc
{"text": "...", "model": "qwen/qwen3.8-27b",
 "input_tokens": 812, "output_tokens": 430,
 "finish_reason": "stop", "truncated": false,
 "cost_rub": 0.214, "quota": {"week": {...}, "current_session": {...}}}
```

### 9.2. Вердикт аудитора (`_audit_gate` → синтез)

```jsonc
{"dod": ["критерий1", "..."],
 "checks": [{"criterion": "...", "met": true, "evidence": "..."}],
 "passed": true, "gaps": ["чего не хватает"]}
```

### 9.3. Data Recipe (человеко-редактируемый, декларативный, ADR-004)

Источник→canonical, без исполняемого кода. Шаблон создаётся `/data new`, применяется `data_run`:

```jsonc
{"recipe": "acme", "version": 1,
 "source": {"kind": "csv", "path": "…/orders.csv"},
 "entity": "transaction",
 "map": {"id": {"col": "order_id"}, "customer": {"col": "email"},
         "amount": {"col": "total", "cast": "money"}, "date": {"col": "created_at"}},
 "rules": [{"assert": "amount > 0"}, {"pii_mask": ["customer"]}],
 "emit": {"schema": "transaction", "schema_version": "1.0", "ttl_sec": 86400}}
```

Поддержаны `source.kind`: `csv`, `json`. Касты: `money`/`int`/`lower`/passthrough. Правила: `assert` (сравнение над скаляром, `_rule_ok`) и `pii_mask` (`_mask`).

### 9.4. Связь с LUDA (единственная обязательная, ADR)

ABOP не может дать агенту autonomy_level выше, чем в `DeploymentContract` от LUDA (AOP §7.3). Обмен между репозиториями — только версионированными схемами контрактов (`CI check-no-foreign-imports`), не кодом.

---

## 10. Стек и лицензии

| Слой | Компонент | Примечание |
|---|---|---|
| Язык (клиент) | Python 3.9+, только стандартная библиотека | `cli/ape.py` без внешних зависимостей |
| Язык (шлюз) | Python | `server/` |
| MCP-сервер | FastMCP | JSON-RPC / streamable-http |
| API-каркас | FastAPI/ASGI (через FastMCP `run(transport="http")`) | наружу — Caddy (TLS) |
| Аутентификация | Keycloak / OIDC, JWTVerifier (JWKS) | realm `ai-product-engineer`, PKCE loopback |
| HTTP-клиент | httpx (шлюз), urllib (клиент) | |
| БД (cost) | PostgreSQL (`psycopg`, `psycopg_pool`) | `cost_journal` |
| LLM | RouteAI (OpenAI-совместимый), vLLM `local/*` | Qwen3.8-27B (код), DeepSeek (ресёрч) |
| Embeddings / rerank | BGE-M3 / BGE-reranker (RouteAI или sLAVA `/rerank`) | |
| Vector search | Qdrant (коллекции с префиксом `ape_`) | изоляция от корпуса sLAVA |
| Хранилище проектов | MinIO / S3 (`/api/storage/upload`) | `/save cloud` |
| Sandbox | Docker (эфемерный, allowlist, без сети, `--rm`) | для `run_python` в Tool Plane (проектируется) |

Целевой политикой (ADR-021) допускаются permissive-лицензии (MIT/Apache-2.0/BSD/PostgreSQL). Прод-egress — через прокси sLAVA (ADR-018); `local_llm` — внутренний.

---

## 11. Слои и статус реализации

| Плоскость | Статус | Где |
|---|---|---|
| **Agent Plane** (ReAct, волны, Blackboard, семьи, память, аудитор) | Реализовано | `cli/ape.py` |
| **Tool Plane** (клиентские tools поверх шлюза) | Реализовано частично; примитивы `run_python`(docker)/`web_fetch`/`doc_export` — проектируются | `cli/ape.py` (`AGENT_TOOLS`), `server/tools/` |
| **Data Plane** | реестр адаптеров (csv/json/http/sqlite/computed) + canonical-схемы + валидация + freshness-гейт + lookup; локальный append-only store | `cli/ape.py` (`data_*`, `register_adapter`) |
| **Шлюз** (JWT, каскад, RAG, квоты, cost) | Реализовано | `server/` |

---

## 12. Что осознанно не реализуется сейчас

| Отложено | Причина / замена |
|---|---|
| Полноценный Data Plane (Source Adapters, Canonical Schemas, canonical-движок) | В полигоне — упрощённый `data_query` над csv/json; в проде — код LUDA (`canon/`, `connectors/`, `spec/`, rules-engine), ADR-003/004 |
| Независимый аудитор | Сейчас `_audit_gate` ходит в ту же модель-класс (`research`), что и воркеры; независимая модель/инстанс — план |
| Прод-периметр (ФСТЭК/ДСП/ФЗ-152) | APE — безопасный полигон; перенос паттернов в ABOP-периметр — отдельная фаза (ADR-019) |
| Векторный recall долговременной памяти | Сейчас грубый лексический скоринг (`recall_longterm`); RAG-слой поверх canonical store — открытый вопрос §13.1 |
| Гарантия инвариантов A1–A5 кодом | Сейчас навязываются агенту через system/пометки (LLM-контракт поведения); детерминированные гейты — усиление для прода |
| Мульти-инстанс рантайма | Blackboard/память/store — на локальном диске клиента, ключ по `session_id`; несколько машин разъедутся по состоянию |
| Tool Plane примитивы (`run_python`, `web_fetch`, `render_diagram`, `doc_export`) на шлюз | Проектируются (ARD §4, §7 Ф1); сейчас реализованы клиентские tools |

---

## 13. Открытые технические вопросы

1. **Хранилище Data Plane в проде:** Postgres+JSONB (как в LUDA) vs отдельный движок; где именно живёт RAG-слой поверх canonical store для семантического поиска.
2. **Реестр рецептов данных:** no-code UI-редактор Data Recipe с предпросмотром результата на реальной выборке (фронт ABOP) — формат и валидатор схемы (ADR-004).
3. **Мультитенантность источников:** общие креды vs BYO; изоляция canonical store по арендатору; как `X-Tenant`/`sub` пробрасывается в Data Plane.
4. **Перенос полигон→прод-периметр:** как физически переиспользуются шлюз/Keycloak/модели из учебного контура в ABOP-периметре с регуляторкой (external_egress через прокси sLAVA, local_llm внутренний, ПДн-маскирование на границе).
5. **Усиление инвариантов A1–A5:** какие поведенческие контракты (HITL, injection-guard, cite) вынести в детерминированные гейты на шлюзе/рантайме, а не полагаться на исполнение моделью.
6. **Независимый аудитор:** отдельная модель/инстанс для `_audit_gate`, чтобы governance-петля не зависела от той же модели-класса, что и воркеры.
