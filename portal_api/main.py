"""Portal API (FastAPI).

Отдаёт порталу живые данные из того же Postgres, что пишет MCP (cost_journal):
    GET /api/my-usage         — расход текущего студента (кабинет)
    GET /api/leaderboard      — топ по токенам за неделю
    GET /api/admin/cost-report— сводка по группе (только роль lecturer)
    GET /api/health           — liveness (без токена)

JWT валидируется по JWKS Keycloak (тот же realm, что у MCP). Токен портала несёт
aud=course-mcp (audience-mapper клиента portal).
"""
from __future__ import annotations

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from jwt import PyJWKClient

from server import db
from server.config import settings

app = FastAPI(title="AI Product Engineer — Portal API", version="0.1.0")
_jwks = PyJWKClient(settings.kc_jwks_uri)


def verify(authorization: str = Header(default="")) -> dict:
    """Валидирует Bearer-JWT Keycloak, возвращает claims."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Требуется Bearer-токен")
    token = authorization[7:]
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.kc_audience,
            issuer=settings.kc_issuer,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=401, detail=f"Невалидный токен: {e}") from e


def require_lecturer(claims: dict = Depends(verify)) -> dict:
    roles = claims.get("realm_access", {}).get("roles", [])
    if "lecturer" not in roles:
        raise HTTPException(status_code=403, detail="Только для роли lecturer")
    return claims


@app.on_event("startup")
async def _startup() -> None:
    await db.init_pool()


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "service": "portal-api"}


@app.get("/api/my-usage")
async def my_usage(session_id: str = "", claims: dict = Depends(verify)) -> dict:
    return await db.student_report(claims["sub"], session_id or None)


@app.get("/api/leaderboard")
async def leaderboard(claims: dict = Depends(verify)) -> list[dict]:
    async with db._conn() as conn:  # noqa: SLF001 — переиспользуем пул MCP
        cur = await conn.execute(
            "SELECT username, SUM(input_tokens+output_tokens) AS t, SUM(cost_rub) AS c "
            "FROM cost_journal WHERE ts >= date_trunc('week', now()) "
            "GROUP BY username ORDER BY t DESC LIMIT 50"
        )
        rows = await cur.fetchall()
    return [{"username": r[0], "tokens": int(r[1]), "cost_rub": float(r[2])} for r in rows]


@app.get("/api/admin/cost-report")
async def admin_cost_report(claims: dict = Depends(require_lecturer)) -> dict:
    async with db._conn() as conn:  # noqa: SLF001
        cur = await conn.execute(
            "SELECT username, SUM(input_tokens+output_tokens) AS t, SUM(cost_rub) AS c, "
            "       COUNT(DISTINCT session_id) AS s, COUNT(*) AS n "
            "FROM cost_journal WHERE ts >= date_trunc('week', now()) "
            "GROUP BY username ORDER BY t DESC"
        )
        rows = await cur.fetchall()
    return {
        "week_limit": settings.weekly_token_limit,
        "students": [
            {
                "username": r[0],
                "tokens": int(r[1]),
                "cost_rub": float(r[2]),
                "sessions": int(r[3]),
                "calls": int(r[4]),
                "weekly_used_pct": round(100 * int(r[1]) / settings.weekly_token_limit, 1),
            }
            for r in rows
        ],
    }
