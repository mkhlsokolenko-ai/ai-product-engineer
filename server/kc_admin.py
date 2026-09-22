"""Keycloak admin + impersonation для email-кода входа менеджеров.

Поток: verify-код → ensure_user(email) (создать/найти + роль manager) →
impersonate(user_id) (RFC 8693 token-exchange с requested_subject) → реальный JWT realm'а,
который проходит тот же verify(), что и обычные токены (aud=course-mcp).

Клиент-инициатор — ape-exchange (confidential, service account). Его сервис-аккаунту нужны
realm-management роли: manage-users, view-users, impersonation. Настраивается kcadm (см. runbook).
"""
from __future__ import annotations

import httpx

from server.config import settings


def _token_url() -> str:
    return f"{settings.kc_admin_internal.rstrip('/')}/realms/{settings.kc_realm}/protocol/openid-connect/token"


def _admin_base() -> str:
    return f"{settings.kc_admin_internal.rstrip('/')}/admin/realms/{settings.kc_realm}"


async def _sa_token(cli: httpx.AsyncClient) -> str:
    """client_credentials сервис-аккаунта ape-exchange."""
    r = await cli.post(_token_url(), data={
        "grant_type": "client_credentials",
        "client_id": settings.kc_exchange_client,
        "client_secret": settings.kc_exchange_secret,
    })
    r.raise_for_status()
    return r.json()["access_token"]


async def _assign_realm_role(cli: httpx.AsyncClient, admin: str, user_id: str, role: str) -> None:
    """Назначить пользователю realm-роль (idempotent)."""
    rr = await cli.get(f"{_admin_base()}/roles/{role}",
                       headers={"Authorization": f"Bearer {admin}"})
    if rr.status_code != 200:
        return  # роли нет в realm — пропускаем (RBAC отработает по BASE_ROLE)
    role_obj = rr.json()
    await cli.post(f"{_admin_base()}/users/{user_id}/role-mappings/realm",
                   headers={"Authorization": f"Bearer {admin}", "Content-Type": "application/json"},
                   json=[{"id": role_obj["id"], "name": role_obj["name"]}])


async def ensure_user(email: str, role: str) -> str:
    """Найти пользователя по email или создать; гарантировать realm-роль. Вернуть user_id."""
    email = email.strip().lower()
    async with httpx.AsyncClient(timeout=20) as cli:
        admin = await _sa_token(cli)
        h = {"Authorization": f"Bearer {admin}"}
        # exact-поиск по email
        r = await cli.get(f"{_admin_base()}/users",
                          params={"email": email, "exact": "true"}, headers=h)
        r.raise_for_status()
        users = r.json()
        if users:
            uid = users[0]["id"]
        else:
            cr = await cli.post(f"{_admin_base()}/users", headers={**h, "Content-Type": "application/json"},
                                json={"username": email, "email": email, "enabled": True,
                                      "emailVerified": True,
                                      "attributes": {"track": ["managers"], "origin": ["email-otp"]}})
            if cr.status_code not in (201, 204):
                raise RuntimeError(f"KC create user failed: {cr.status_code} {cr.text[:200]}")
            loc = cr.headers.get("Location", "")
            uid = loc.rstrip("/").split("/")[-1]
        await _assign_realm_role(cli, admin, uid, role)
        return uid


async def impersonate(user_id: str) -> dict:
    """Выдать реальный токен realm'а от имени пользователя (impersonation token-exchange).

    Возвращает полный ответ токен-эндпоинта (access_token, refresh_token, expires_in, ...).
    """
    async with httpx.AsyncClient(timeout=20) as cli:
        sa = await _sa_token(cli)
        r = await cli.post(_token_url(), data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "client_id": settings.kc_exchange_client,
            "client_secret": settings.kc_exchange_secret,
            "subject_token": sa,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "requested_subject": user_id,
            "audience": settings.kc_audience,
        })
        if r.status_code != 200:
            detail = ""
            try:
                j = r.json()
                detail = j.get("error_description") or j.get("error") or ""
            except Exception:  # noqa: BLE001
                detail = r.text[:200]
            raise RuntimeError(f"impersonation failed: {r.status_code} {detail}")
        return r.json()
