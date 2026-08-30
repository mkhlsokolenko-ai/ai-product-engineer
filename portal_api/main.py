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

from datetime import timedelta

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from jwt import PyJWKClient
from minio import Minio

from server import db
from server.config import settings


def _mc(public: bool) -> Minio:
    """MinIO-клиент. public=True -> хост presigned-URL (браузер), иначе внутренний."""
    ep = settings.minio_public if public else settings.minio_internal
    return Minio(ep, access_key=settings.minio_user, secret_key=settings.minio_password, secure=public)

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


# ─────────────────────────── Хранилище (MinIO) ───────────────────────────

@app.get("/api/storage/my-files")
async def my_files(claims: dict = Depends(verify)) -> dict:
    """Файлы проекта студента (префикс <sub>/) + остаток квоты."""
    sub = claims["sub"]
    mc = _mc(False)
    files = []
    try:
        for o in mc.list_objects(settings.minio_bucket, prefix=f"{sub}/", recursive=True):
            files.append({"name": o.object_name[len(sub) + 1:], "size": o.size or 0})
    except Exception:  # noqa: BLE001 — бакета ещё нет / пусто
        files = []
    used = sum(f["size"] for f in files)
    return {
        "files": files,
        "used_bytes": used,
        "limit_bytes": settings.storage_limit_bytes,
        "remaining_bytes": max(0, settings.storage_limit_bytes - used),
        "used_pct": round(100 * used / settings.storage_limit_bytes, 1),
    }


@app.post("/api/storage/upload-url")
async def upload_url(filename: str, size: int = 0, claims: dict = Depends(verify)) -> dict:
    """Presigned PUT-URL для загрузки файла в свой префикс. Проверяет лимит 600 МБ."""
    sub = claims["sub"]
    mc = _mc(False)
    if not mc.bucket_exists(settings.minio_bucket):
        mc.make_bucket(settings.minio_bucket)
    used = sum(
        (o.size or 0) for o in mc.list_objects(settings.minio_bucket, prefix=f"{sub}/", recursive=True)
    )
    if used + max(0, size) > settings.storage_limit_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Лимит {settings.storage_limit_bytes // (1024 * 1024)} МБ исчерпан",
        )
    safe = filename.replace("/", "_").replace("\\", "_").replace("..", "_").strip() or "file"
    obj = f"{sub}/{safe}"
    url = _mc(True).presigned_put_object(settings.minio_bucket, obj, expires=timedelta(hours=1))
    return {"url": url, "object": obj, "method": "PUT", "expires_sec": 3600}
