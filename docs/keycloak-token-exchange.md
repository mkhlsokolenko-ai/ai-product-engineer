# Keycloak: token-exchange для remote-коннекторов (runbook)

Цель — оживить делегированный доступ (агент ходит во внешние системы **от имени пользователя**,
а не общим сервис-ключом). Эндпоинт `POST /api/connectors/exchange` (portal_api) уже реализует
RFC 8693 token-exchange к Keycloak; осталось **включить фичу в KC и настроить клиентов внешних систем**.

> ⚠️ **Прод-риск.** Keycloak на server-1 держит вход всех студентов и десктопа. Включение фичи
> требует **рестарта Keycloak** → кратковременный даунтайм входа (~30–60 сек). Делать в согласованное
> окно. Realm/пользователи не затрагиваются (только флаг запуска).

## Состояние (2026-09-21)
- Keycloak **26.0.8**, запуск: `command: ["start","--import-realm"]`, фича token-exchange **выключена**.
- portal_api: `POST /api/connectors/exchange` (право `connectors:write`, есть у lecturer/admin) — при
  выключенной фиче/ненастроенной цели возвращает понятный `{ok:false, configured:false, message}` (не падает).

## Шаг 1. Включить фичу (compose) — требует рестарта KC
В `docker-compose.yml`, сервис `keycloak`, заменить command:
```yaml
    command: ["start", "--import-realm", "--features=token-exchange:v2"]
```
(в KC 26 стандартный V2 token-exchange — preview; для standard-exchange между клиентами достаточно `token-exchange`.)
Применить: `docker compose up -d keycloak` (пересоздаст контейнер, ~30–60с даунтайм auth).
Проверка: `docker logs ai-product-engineer-keycloak-1 | grep -i "token-exchange"` — фича в списке preview.

## Шаг 2. Клиент-получатель токена (на каждую внешнюю систему)
Для каждой цели (onedrive/gsuite/crm) в realm `ai-product-engineer`:
1. **Клиент внешней системы** как Identity Provider или client с настроенным audience.
   - Проще всего: завести client `conn-<target>` (напр. `conn-onedrive`), включить в его маппере
     нужный audience; выдать этому client разрешение быть целью exchange.
2. **Разрешить exchange**: у client-инициатора (`course-mcp`) в *Permissions → token-exchange* добавить
   политику, разрешающую обмен на `conn-<target>` (Admin Console → Clients → conn-<target> →
   Permissions → token-exchange → policy: client `course-mcp`).
3. Для реального доступа к API внешней системы — настроить у `conn-<target>` брокеринг к её OAuth
   (Microsoft/Google): client_id/secret внешнего приложения, scope. Тогда полученный токен годен к их API.

## Шаг 3. Проверка
```bash
# из-под токена lecturer (есть connectors:write):
curl -s -X POST https://engineer-ai.pro/api/connectors/exchange \
  -H "Authorization: Bearer <JWT lecturer>" -H "Content-Type: application/json" \
  -d '{"target":"onedrive","audience":"conn-onedrive"}'
# ожидаем {"ok":true,"delegated":true} после настройки; иначе — message с причиной
```
В десктопе: 🔌 Источники → OneDrive/Google Drive/CRM → «Подключить» → «✓ подключено».

## Границы / что дальше
- **Стандартный exchange** (обмен курсового JWT на токен client-получателя) — работает после шагов 1–2.
- **Реальный доступ к API внешней системы** (чтение файлов OneDrive/Google) — требует шага 3 (брокеринг
  к их OAuth: регистрация OAuth-приложения у вендора, client_id/secret, scopes). Это конфиг вендора, не код.
- Матрица прав: кто из ролей какие системы может подключать — расширить `server/rbac.py`
  (сейчас гейт по `connectors:write`).
