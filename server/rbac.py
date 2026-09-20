"""RBAC-политика курсового шлюза. Роли берём из Keycloak JWT (realm_access.roles).

Энфорс — на СЕРВЕРЕ (единая точка), клиент только фильтрует каталог для UX.
Гранулярность: действие (action) × роль. Действие — строка вида "chat", "agents:run",
"connectors:write", "admin", "profile:research".
"""
from __future__ import annotations

# Роль → множество разрешённых действий. "*" = всё.
ROLE_POLICY: dict[str, set[str]] = {
    "admin": {"*"},
    "lecturer": {"*"},
    "analyst": {"chat", "agents:run", "export", "data:read", "profile:code",
                "profile:research", "profile:standard"},
    "manager": {"chat", "agents:run", "export", "profile:code",
                "profile:standard", "profile:research"},
    # базовая роль для всех вошедших (если нет доменной роли)
    "student": {"chat", "agents:run", "export", "profile:code",
                "profile:research", "profile:standard"},
}
# Действия, которые в UI показываются как «запрещено» для роли (для наглядности политики).
KNOWN_ACTIONS = ["chat", "agents:run", "export", "data:read",
                 "connectors:write", "admin"]
BASE_ROLE = "student"


def _clean_roles(roles: list[str]) -> list[str]:
    skip = {"offline_access", "uma_authorization"}
    out = [r for r in (roles or []) if r in ROLE_POLICY and r not in skip]
    return out or [BASE_ROLE]


def roles_from_claims(claims: dict) -> list[str]:
    raw = (claims.get("realm_access") or {}).get("roles") or []
    return _clean_roles(raw)


def allowed(claims: dict, action: str) -> bool:
    for r in roles_from_claims(claims):
        caps = ROLE_POLICY.get(r, set())
        if "*" in caps or action in caps:
            return True
    return False


def effective(claims: dict) -> dict:
    roles = roles_from_claims(claims)
    caps: set[str] = set()
    for r in roles:
        caps |= ROLE_POLICY.get(r, set())
    star = "*" in caps
    allow = KNOWN_ACTIONS if star else sorted(a for a in KNOWN_ACTIONS if a in caps)
    deny = [] if star else sorted(a for a in KNOWN_ACTIONS if a not in caps)
    return {"roles": roles, "allowed": allow, "denied": deny, "enforced": True}
