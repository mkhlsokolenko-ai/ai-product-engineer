# Портал курса — engineer-ai.pro

Первый срез: статический SPA (без сборки), раздаётся Caddy с server-1. Дизайн — DS
red-team.tech. Вход — **Keycloak (OIDC Authorization Code + PKCE, S256)**, кнопка
«Продолжить с GitHub» уходит на наш realm с `kc_idp_hint=github`.

Хостинг: **server-1** (201.51.5.24), тот же Caddy, что и Keycloak. Записи `A @`/`A www`
→ 201.51.5.24.

## Что уже есть (`index.html`)
- Лендинг + логин (GitHub / логин-пароль) через Keycloak, без внешних библиотек.
- Кабинет после входа: имя, роль (student/lecturer из realm-роли), плейсхолдеры баланса
  токенов (неделя / сессии / стоимость).
- `loadUsage()` дёргает `/api/my-usage` — заработает, когда поднимем **Portal API**.

## Деплой (на server-1)
```bash
cd ~/ai-product-engineer && git pull
docker compose up -d caddy      # Caddy выпустит TLS для engineer-ai.pro и раздаст /srv/portal
```

## Дальше
1. **Portal API** (FastAPI): `/api/my-usage`, `/api/leaderboard`, `/api/admin/*` поверх
   `cost_journal`; проверка JWT тем же способом, что MCP (`server/auth.py`).
2. Экраны из pmhucks-вёрстки: админка (KPI AI-токены/стоимость), кабинет (табы), лидерборд.
3. Компоненты DS из redteam-ai `_design_v4` (GradeBadge, ProgressBar) под оценки/прогресс.
