# DEPLOY / RUNBOOK — развёртывание, обновление, восстановление

Единый источник для восстановления курсового контура. Секретов и транзиентных IP здесь нет —
они живут в `.env` на сервере и в локальном файле ключей лектора (вне репозитория).

## 1. Топология (server-1 = sLAVA-пилот, 201.51.5.24)

Compose-проект **`ai-product-engineer`** в **`/home/slava/ai-product-engineer`** (НЕ `~/` под root!).
Контейнеры (`docker compose ps`):

| Сервис | Контейнер | Назначение | Наружу |
|---|---|---|---|
| mcp | `ai-product-engineer-mcp-1` | FastMCP-шлюз (`ape-mcp`), profile `mcp` | через Caddy |
| portal-api | `ai-product-engineer-portal-api-1` | FastAPI портала + SSE `/api/chat/stream` (:8090) | через Caddy |
| postgres | `ai-product-engineer-postgres-1` | cost_journal + квоты + лекции/оценки | 127.0.0.1:5433 |
| keycloak | `ai-product-engineer-keycloak-1` | OIDC/JWT (realm `ai-product-engineer`) | auth.engineer-ai.pro |
| caddy | `ai-product-engineer-caddy-1` | TLS-фронт :443 | 80/443 |
| minio | `ai-product-engineer-minio-1` | S3-хранилище проектов | s3.engineer-ai.pro |

Домены: `mcp.engineer-ai.pro` (MCP), `auth.engineer-ai.pro` (Keycloak), `engineer-ai.pro` (портал+`/api`),
`s3.engineer-ai.pro` (MinIO). Self-host LLM — арендованный бокс на Vast (эндпоинт в `.env`).
sLAVA — соседний compose-проект на том же хосте: **не трогать** (Qdrant-коллекции без префикса `ape_`, БД sLAVA).

## 2. Модель деплоя

Git-репо — **источник истины и бэкап**. На сервер код доставляется **scp** (git pull на сервере
не настроен — origin требует auth). Код `mcp` и `portal-api` **запечён в образы** (`build: .`) →
после правки Python-кода нужен **rebuild**. Портал-SPA (`portal/index.html`) — `:ro`-маунт, **scp достаточно**.

### SSH (Windows / Git Bash — важная грабля)
HOME с кириллицей+пробелом ломает запись known_hosts. Опции задавать **инлайн** (не через переменную):
```bash
ssh -i "$HOME/.ssh/id_ed25519" -o UserKnownHostsFile="$HOME/.ssh/known_hosts" \
    -o StrictHostKeyChecking=no -o BatchMode=yes root@201.51.5.24 '<команда>'
```

### Деплой по сервисам (из корня локального репо)
```bash
S='-i '"$HOME"'/.ssh/id_ed25519'   # (в реальности — опции инлайн, см. выше)

# portal-api (код Python → rebuild):
scp <opts> portal_api/main.py portal_api/store.py root@201.51.5.24:/home/slava/ai-product-engineer/portal_api/
scp <opts> server/clients.py server/pricing.py    root@201.51.5.24:/home/slava/ai-product-engineer/server/
ssh <opts> root@201.51.5.24 'cd /home/slava/ai-product-engineer && docker compose build portal-api && docker compose up -d portal-api'

# mcp (profile mcp!):
ssh <opts> root@201.51.5.24 'cd /home/slava/ai-product-engineer && docker compose --profile mcp build mcp && docker compose --profile mcp up -d mcp'

# портал SPA (без rebuild):
scp <opts> portal/index.html root@201.51.5.24:/home/slava/ai-product-engineer/portal/index.html

# смена .env → пересоздать контейнер (иначе держит старое окружение):
ssh <opts> root@201.51.5.24 'cd /home/slava/ai-product-engineer && docker compose up -d --force-recreate portal-api'
```
`portal_api` на старте вызывает `store.ensure()` — создаёт/мигрирует таблицы и **досевает треки**
(engineer сеется только в пустую таблицу; managers — по счётчику `track='managers'`, доедет на прод).

## 3. Ключевые `.env` (маршрутизация → self-host 30B)
```
LOCAL_LLM_BASE_URL=http://<vast-ip>:<port>/v1     # текущий бокс Qwen (меняется при пересоздании)
LOCAL_LLM_MODEL=qwen3-30b-a3b                      # = served-model-name на vLLM
ROUTEAI_CODE_CASCADE=local/qwen3-30b-a3b,deepseek/deepseek-v4-pro
ROUTEAI_RESEARCH_CASCADE=local/qwen3-30b-a3b,deepseek/deepseek-v4-flash
ROUTEAI_STANDARD_CASCADE=local/qwen3-30b-a3b,deepseek/deepseek-v4-flash
```
Все профили → self-host, DeepSeek — fallback. **`server/pricing.py` обязан содержать
`local/qwen3-30b-a3b: (0.0, 0.0)`** — иначе self-host спишется по `__default__` (25/102 ₽) со студентов
(pricing запечён в образ → после правки rebuild mcp+portal-api).

## 4. Self-host Qwen на Vast — жизненный цикл

Модель **`Qwen/Qwen3-30B-A3B-Instruct-2507-FP8`** (served `qwen3-30b-a3b`), образ `vllm/vllm-openai:latest`.
Args: `--max-model-len 32768 --gpu-memory-utilization 0.92 --enable-prefix-caching --max-num-seqs 64
--max-num-batched-tokens 8192 --trust-remote-code --host 0.0.0.0 --port 8000`.
Vast API — **напрямую curl/python** (Bearer; ключ Vast и HF-токен — в локальном файле лектора вне репо).

**Выбор карты (критично):** только **FP8-совместимые Ada/Hopper/Blackwell** (L40, L40S, RTX 6000 Ada,
5880 Ada, 5000 Ada, 4090-48G, RTX PRO 5000/6000, H100). **НЕ брать Ampere** (RTX A6000/A100 — без FP8)
и Turing (RTX 8000). Фильтр офферов: `gpu_ram>=46000`, `cuda_max_good>=12.8`, `verified`, `reliability2>=0.97`.

**Эндпоинты Vast API:** офферы `GET /api/v0/bundles/?q=<json>`; создать `PUT /api/v0/asks/{offer}/`
(body: image/disk/label/runtype:args/args/env{`-p 8000:8000`,HF}); статус `GET /api/v0/instances/{id}/`
(порт: `ports["8000/tcp"][0].HostPort` + `public_ipaddr`); логи `PUT /api/v0/instances/request_logs/{id}/`
→ `result_url`; снос `DELETE /api/v0/instances/{id}/`; старт остановленного `PUT ... {"state":"running"}`.
Грабли: создание может вернуть 400/`success:false` (оффер занят) → **перебирать топ офферов циклом**;
хэш кэша меняется; хост может уйти `offline` (тогда рестарт = `resources_unavailable` → пересоздавать).

**Восстановление при падении инстанса:**
1. Проверить: `GET /instances/{id}/` → `actual_status`; `curl http://<ip>:<port>/v1/models`.
2. Если `offline`/не поднять — найти свежий FP8-оффер, `PUT /asks/{offer}/` (цикл), дождаться `/v1/models`.
3. Прописать новый эндпоинт: `sed -i "s#^LOCAL_LLM_BASE_URL=.*#...#" .env` → `docker compose up -d --force-recreate mcp` (и portal-api, т.к. стриминг ходит через него).
4. Снести мёртвый инстанс (`DELETE`). Проверить `GET /api/v1/instances/` — орфанов нет.
> **Не трогать** Vast-инстанс `49036119` (label `redteam-judge-ab`) — чужой (red-team).

## 5. Стриминг (десктоп-оболочка)
Поток: UI → сайдкар `/threads/{id}/send-stream` → **portal-api `POST /api/chat/stream` (SSE)** →
`server/clients.chat_stream` → vLLM. Квота — до, cost — после (usage из финального чанка). Идёт через
`engineer-ai.pro/api/` (Caddy), **не через MCP**. Если ответ приходит «целиком» (не построчно) —
Caddy буферизует SSE: добавить `flush_interval -1` на `/api` в Caddyfile.

## 6. Проверка после деплоя
```bash
curl -s https://engineer-ai.pro/api/health                       # portal-api
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://engineer-ai.pro/api/chat/stream \
  -H 'Content-Type: application/json' -d '{"prompt":"hi"}'        # ждём 401 (маршрут+auth)
curl -s http://<vast-ip>:<port>/v1/models                         # vLLM жив
# routing в контейнере:
docker exec ai-product-engineer-mcp-1 python -c "from server.config import settings; print(settings.cascade_for('standard'))"
docker exec ai-product-engineer-portal-api-1 python -c "from server.pricing import cost_rub; print(cost_rub('local/qwen3-30b-a3b',1000000,1000000))"  # ждём 0.0
```

## 7. Клиенты и десктоп
- **`ape`** (CLI) — ставится/обновляется `pip install -U "git+https://github.com/mkhlsokolenko-ai/ai-product-engineer#subdirectory=cli"`.
- **APE Desktop** — сборка инсталлятора и **авто-доставка** (electron-updater + CI по тегу `desktop-v*` +
  удалённый UI): см. **`desktop/README.md`**. Приоритеты доработок — `desktop/docs-competitive-moscow.md`.

## 8. Изоляция и безопасность
- НЕ трогать коллекции Qdrant без префикса `ape_` (корпус sLAVA) и БД/тома sLAVA.
- Внутренние порты (8787/8090/5433/6333) наружу не публиковать — только Caddy :443.
- `.env` и ключи в git не коммитятся (`.gitignore`); секреты — вне репо.
- `cost_report` — только realm-role `lecturer`.
