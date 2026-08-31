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

from datetime import date, datetime, timedelta, timezone

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from jwt import PyJWKClient
from minio import Minio
from pydantic import BaseModel

from portal_api import store
from server import db
from server.config import settings


class SubmissionIn(BaseModel):
    assignment_id: int
    url: str
    note: str = ""


class GradeIn(BaseModel):
    student_id: str
    assignment_id: int
    score: float
    feedback: str = ""
    status: str = "accepted"


class AnnIn(BaseModel):
    title: str
    body: str


class ProjectIn(BaseModel):
    repo_url: str = ""
    description: str = ""
    status: str = "idea"


def _mc(public: bool) -> Minio:
    """MinIO-клиент. public=True -> хост presigned-URL (браузер), иначе внутренний."""
    ep = settings.minio_public if public else settings.minio_internal
    return Minio(ep, access_key=settings.minio_user, secret_key=settings.minio_password, secure=public)

app = FastAPI(title="AI Product Engineer — Portal API", version="0.1.0")
# JWKS по внутренней сети (keycloak:8080) — публичный домён из контейнера не доступен.
_jwks = PyJWKClient(settings.kc_jwks_internal)


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


def require_staff(claims: dict = Depends(verify)) -> dict:
    """lecturer или admin."""
    roles = set(claims.get("realm_access", {}).get("roles", []))
    if not ({"lecturer", "admin"} & roles):
        raise HTTPException(status_code=403, detail="Только для lecturer/admin")
    return claims


@app.on_event("startup")
async def _startup() -> None:
    await db.init_pool()
    await store.ensure()


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
async def admin_cost_report(claims: dict = Depends(require_staff)) -> dict:
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


def _safe_name(filename: str) -> str:
    if not filename or ".." in filename or filename.startswith("/") or "\\" in filename:
        raise HTTPException(status_code=400, detail="Недопустимое имя файла")
    return filename


@app.get("/api/storage/download-url")
async def download_url(filename: str, claims: dict = Depends(verify)) -> dict:
    """Presigned GET-URL для скачивания своего файла."""
    obj = f"{claims['sub']}/{_safe_name(filename)}"
    url = _mc(True).presigned_get_object(settings.minio_bucket, obj, expires=timedelta(hours=1))
    return {"url": url}


@app.delete("/api/storage/file")
async def delete_file(filename: str, claims: dict = Depends(verify)) -> dict:
    """Удалить свой файл (только в пределах своего префикса)."""
    obj = f"{claims['sub']}/{_safe_name(filename)}"
    _mc(False).remove_object(settings.minio_bucket, obj)
    return {"ok": True}


# ─────────────────────────── Лекции / Домашки / Оценки ───────────────────────────

@app.get("/api/lectures")
async def lectures(claims: dict = Depends(verify)) -> list[dict]:
    async with db._conn() as c:  # noqa: SLF001
        cur = await c.execute(
            "SELECT week,block,title,topic,materials_url,outcomes,skills "
            "FROM lectures ORDER BY position,week"
        )
        rows = await cur.fetchall()
    from portal_api.store import BLOCK_NAMES
    return [
        {"week": r[0], "block": r[1], "block_name": BLOCK_NAMES.get(r[1], ""),
         "title": r[2], "topic": r[3], "materials_url": r[4],
         "outcomes": [x for x in (r[5] or "").split("|") if x],
         "skills": [x for x in (r[6] or "").split(",") if x]}
        for r in rows
    ]


@app.get("/api/assignments")
async def assignments(claims: dict = Depends(verify)) -> list[dict]:
    async with db._conn() as c:  # noqa: SLF001
        cur = await c.execute(
            "SELECT id,week,title,description,fmt,max_score FROM assignments ORDER BY position,week"
        )
        rows = await cur.fetchall()
    return [
        {"id": r[0], "week": r[1], "title": r[2], "description": r[3], "fmt": r[4], "max_score": r[5]}
        for r in rows
    ]


@app.get("/api/my/submissions")
async def my_submissions(claims: dict = Depends(verify)) -> dict:
    async with db._conn() as c:  # noqa: SLF001
        cur = await c.execute(
            "SELECT assignment_id,url,note,status,submitted_at FROM submissions WHERE student_id=%s",
            (claims["sub"],),
        )
        rows = await cur.fetchall()
    return {
        str(r[0]): {"url": r[1], "note": r[2], "status": r[3], "submitted_at": r[4].isoformat()}
        for r in rows
    }


@app.post("/api/my/submissions")
async def submit(body: SubmissionIn, claims: dict = Depends(verify)) -> dict:
    async with db._conn() as c:  # noqa: SLF001
        await c.execute(
            "INSERT INTO submissions(student_id,username,assignment_id,url,note,status,submitted_at) "
            "VALUES(%s,%s,%s,%s,%s,'submitted',now()) "
            "ON CONFLICT(student_id,assignment_id) DO UPDATE SET "
            "url=EXCLUDED.url, note=EXCLUDED.note, status='submitted', submitted_at=now()",
            (claims["sub"], claims.get("preferred_username", "?"), body.assignment_id, body.url, body.note),
        )
    return {"ok": True}


@app.get("/api/my/grades")
async def my_grades(claims: dict = Depends(verify)) -> dict:
    async with db._conn() as c:  # noqa: SLF001
        cur = await c.execute(
            "SELECT assignment_id,score,feedback,graded_at FROM grades WHERE student_id=%s",
            (claims["sub"],),
        )
        rows = await cur.fetchall()
    return {
        str(r[0]): {
            "score": float(r[1]) if r[1] is not None else None,
            "feedback": r[2],
            "graded_at": r[3].isoformat(),
        }
        for r in rows
    }


@app.get("/api/progress")
async def progress(claims: dict = Depends(verify)) -> dict:
    async with db._conn() as c:  # noqa: SLF001
        total = (await (await c.execute("SELECT COUNT(*) FROM assignments")).fetchone())[0]
        sub = (await (await c.execute(
            "SELECT COUNT(*) FROM submissions WHERE student_id=%s", (claims["sub"],))).fetchone())[0]
        acc = (await (await c.execute(
            "SELECT COUNT(*) FROM submissions WHERE student_id=%s AND status='accepted'",
            (claims["sub"],))).fetchone())[0]
    return {"assignments_total": int(total), "submitted": int(sub), "accepted": int(acc)}


@app.get("/api/admin/submissions")
async def admin_submissions(claims: dict = Depends(require_staff)) -> list[dict]:
    async with db._conn() as c:  # noqa: SLF001
        cur = await c.execute(
            "SELECT s.username,s.assignment_id,a.title,s.url,s.note,s.status,s.submitted_at,"
            "       g.score,g.feedback,s.student_id "
            "FROM submissions s JOIN assignments a ON a.id=s.assignment_id "
            "LEFT JOIN grades g ON g.student_id=s.student_id AND g.assignment_id=s.assignment_id "
            "ORDER BY s.submitted_at DESC"
        )
        rows = await cur.fetchall()
    return [
        {
            "username": r[0], "assignment_id": r[1], "assignment": r[2], "url": r[3], "note": r[4],
            "status": r[5], "submitted_at": r[6].isoformat(),
            "score": float(r[7]) if r[7] is not None else None, "feedback": r[8], "student_id": r[9],
        }
        for r in rows
    ]


@app.post("/api/admin/grade")
async def grade(body: GradeIn, claims: dict = Depends(require_staff)) -> dict:
    async with db._conn() as c:  # noqa: SLF001
        row = await (await c.execute(
            "SELECT username FROM submissions WHERE student_id=%s AND assignment_id=%s",
            (body.student_id, body.assignment_id))).fetchone()
        uname = row[0] if row else "?"
        await c.execute(
            "INSERT INTO grades(student_id,username,assignment_id,score,feedback,graded_by,graded_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,now()) "
            "ON CONFLICT(student_id,assignment_id) DO UPDATE SET "
            "score=EXCLUDED.score, feedback=EXCLUDED.feedback, graded_by=EXCLUDED.graded_by, graded_at=now()",
            (body.student_id, uname, body.assignment_id, body.score, body.feedback,
             claims.get("preferred_username", "?")),
        )
        await c.execute(
            "UPDATE submissions SET status=%s WHERE student_id=%s AND assignment_id=%s",
            (body.status, body.student_id, body.assignment_id),
        )
    return {"ok": True}


# ─────────────────────────── Дашборд / Анонсы / Проект ───────────────────────────

def _course_week() -> tuple[int, date]:
    start = date.fromisoformat(settings.course_start_date)
    delta = (date.today() - start).days
    return (0 if delta < 0 else min(settings.course_weeks, delta // 7 + 1)), start


@app.get("/api/dashboard")
async def dashboard(claims: dict = Depends(verify)) -> dict:
    sub = claims["sub"]
    week, start = _course_week()
    async with db._conn() as c:  # noqa: SLF001
        lecs = await (await c.execute("SELECT week,title,topic FROM lectures ORDER BY week")).fetchall()
        asgs = await (await c.execute("SELECT id,week,title FROM assignments ORDER BY week")).fetchall()
        accepted = {r[0] for r in await (await c.execute(
            "SELECT assignment_id FROM submissions WHERE student_id=%s AND status='accepted'", (sub,))).fetchall()}
        submitted = (await (await c.execute(
            "SELECT COUNT(*) FROM submissions WHERE student_id=%s", (sub,))).fetchone())[0]
        llm = (await (await c.execute(
            "SELECT COUNT(*) FROM cost_journal WHERE student_id=%s AND kind='llm'", (sub,))).fetchone())[0]
        emb = (await (await c.execute(
            "SELECT COUNT(*) FROM cost_journal WHERE student_id=%s AND kind='embed'", (sub,))).fetchone())[0]
        anns = await (await c.execute(
            "SELECT title,body,created_at FROM announcements ORDER BY created_at DESC LIMIT 5")).fetchall()
    cur_lec = None
    for w, t, tp in lecs:
        if w <= max(1, week):
            cur_lec = {"week": w, "title": t, "topic": tp}
    if cur_lec is None and lecs:
        cur_lec = {"week": lecs[0][0], "title": lecs[0][1], "topic": lecs[0][2]}
    now = datetime.now(timezone.utc)
    nd = None
    for aid, aw, at in asgs:
        due = datetime.combine(start + timedelta(days=aw * 7), datetime.min.time(), tzinfo=timezone.utc)
        if aid not in accepted and due > now:
            nd = {"title": at, "week": aw, "due": due.date().isoformat(), "days_left": (due - now).days}
            break
    try:
        files = sum(1 for _ in _mc(False).list_objects(settings.minio_bucket, prefix=f"{sub}/", recursive=True))
    except Exception:  # noqa: BLE001
        files = 0

    def earned(word: str) -> bool:
        return any(aid in accepted for aid, aw, at in asgs if word in at)

    onboarding = [
        {"key": "login", "title": "Вошёл в портал", "done": True},
        {"key": "mcp", "title": "Первый вызов модели через MCP", "done": llm > 0},
        {"key": "rag", "title": "Первая RAG-индексация", "done": emb > 0},
        {"key": "submit", "title": "Первая сдача задания", "done": submitted > 0},
        {"key": "file", "title": "Загрузил файл проекта", "done": files > 0},
    ]
    ach = [
        {"key": "start", "title": "Старт", "icon": "🚀", "earned": True},
        {"key": "mcp", "title": "Первый MCP", "icon": "⚡", "earned": llm > 0},
        {"key": "rag", "title": "RAG", "icon": "🔎", "earned": emb > 0},
        {"key": "hw", "title": "Первая ДЗ", "icon": "📦", "earned": submitted > 0},
        {"key": "mvp", "title": "MVP", "icon": "🚢", "earned": earned("MVP")},
        {"key": "defense", "title": "Защита", "icon": "🏆", "earned": earned("ащит")},
    ]
    return {
        "student": claims.get("preferred_username", "студент"),
        "week": week, "weeks": settings.course_weeks,
        "progress_pct": round(100 * week / settings.course_weeks) if week else 0,
        "current_lecture": cur_lec, "next_deadline": nd,
        "onboarding": onboarding, "achievements": ach,
        "announcements": [{"title": a[0], "body": a[1], "created_at": a[2].isoformat()} for a in anns],
    }


@app.get("/api/announcements")
async def announcements(claims: dict = Depends(verify)) -> list[dict]:
    async with db._conn() as c:  # noqa: SLF001
        rows = await (await c.execute(
            "SELECT title,body,created_by,created_at FROM announcements ORDER BY created_at DESC LIMIT 50")).fetchall()
    return [{"title": r[0], "body": r[1], "by": r[2], "created_at": r[3].isoformat()} for r in rows]


@app.post("/api/admin/announcements")
async def post_announcement(body: AnnIn, claims: dict = Depends(require_staff)) -> dict:
    async with db._conn() as c:  # noqa: SLF001
        await c.execute("INSERT INTO announcements(title,body,created_by) VALUES(%s,%s,%s)",
                        (body.title, body.body, claims.get("preferred_username", "?")))
    return {"ok": True}


@app.get("/api/my/project")
async def get_project(claims: dict = Depends(verify)) -> dict:
    async with db._conn() as c:  # noqa: SLF001
        r = await (await c.execute(
            "SELECT repo_url,description,status FROM projects WHERE student_id=%s", (claims["sub"],))).fetchone()
    return {"repo_url": r[0] if r else "", "description": r[1] if r else "", "status": r[2] if r else "idea"}


@app.post("/api/my/project")
async def set_project(body: ProjectIn, claims: dict = Depends(verify)) -> dict:
    async with db._conn() as c:  # noqa: SLF001
        await c.execute(
            "INSERT INTO projects(student_id,username,repo_url,description,status,updated_at) "
            "VALUES(%s,%s,%s,%s,%s,now()) ON CONFLICT(student_id) DO UPDATE SET "
            "repo_url=EXCLUDED.repo_url,description=EXCLUDED.description,status=EXCLUDED.status,updated_at=now()",
            (claims["sub"], claims.get("preferred_username", "?"), body.repo_url, body.description, body.status))
    return {"ok": True}
