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

import json
from datetime import date, datetime, timedelta, timezone

import jwt
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
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


class PartnerIn(BaseModel):
    name: str
    contact: str = ""
    email: str = ""
    status: str = "active"
    notes: str = ""


class CalendarIn(BaseModel):
    week: int
    title: str
    date_label: str = ""
    type: str = "kt"


class StudentMetaIn(BaseModel):
    student_id: str
    username: str = ""
    partner_id: int | None = None
    risk_note: str = ""
    track_week: int | None = None


class NotesIn(BaseModel):
    body: str = ""


class LectureMaterialIn(BaseModel):
    week: int
    url: str = ""
    title: str = ""


class LecturePassIn(BaseModel):
    next_date: str = ""      # YYYY-MM-DD дата следующей лекции (опц.)


class LectureScheduleIn(BaseModel):
    date: str                # YYYY-MM-DD новая дата этой лекции


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


@app.post("/api/storage/upload")
async def upload_direct(file: UploadFile = File(...), claims: dict = Depends(verify)) -> dict:
    """Загрузка файла ЧЕРЕЗ portal-api (тот же origin → внутренняя сеть до MinIO).
    Надёжнее presigned: без CORS, без кросс-origin и hairpin к публичному s3."""
    sub = claims["sub"]
    mc = _mc(False)
    if not mc.bucket_exists(settings.minio_bucket):
        mc.make_bucket(settings.minio_bucket)
    f = file.file
    f.seek(0, 2); size = f.tell(); f.seek(0)  # размер без чтения в память (spooled temp)
    used = sum(
        (o.size or 0) for o in mc.list_objects(settings.minio_bucket, prefix=f"{sub}/", recursive=True)
    )
    if used + size > settings.storage_limit_bytes:
        raise HTTPException(status_code=413,
                            detail=f"Лимит {settings.storage_limit_bytes // (1024 * 1024)} МБ исчерпан")
    safe = (file.filename or "file").replace("/", "_").replace("\\", "_").replace("..", "_").strip() or "file"
    obj = f"{sub}/{safe}"
    mc.put_object(settings.minio_bucket, obj, f, length=size, part_size=10 * 1024 * 1024,
                  content_type=file.content_type or "application/octet-stream")
    return {"ok": True, "object": obj, "size": size}


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
    _, start = _course_week()
    async with db._conn() as c:  # noqa: SLF001
        cur = await c.execute(
            "SELECT week,block,title,topic,materials_url,outcomes,skills,practice,scheduled_at,status "
            "FROM lectures ORDER BY position,week"
        )
        rows = await cur.fetchall()
        mrows = await (await c.execute(
            "SELECT id,lecture_week,title,url FROM lecture_materials ORDER BY id")).fetchall()
        arows = await (await c.execute("SELECT week FROM assignments")).fetchall()
    mats: dict[int, list] = {}
    for mid, wk, title, url in mrows:
        mats.setdefault(wk, []).append({"id": mid, "title": title, "url": url})
    hw_weeks = {r[0] for r in arows}
    today = date.today()
    from portal_api.store import BLOCK_NAMES
    out = []
    for r in rows:
        week = r[0]
        eff = _effective_date(week, r[8], start)
        item = {
            "week": week, "block": r[1], "block_name": BLOCK_NAMES.get(r[1], ""),
            "title": r[2], "topic": r[3], "materials_url": r[4],
            "materials": mats.get(week, []),
            "outcomes": [x for x in (r[5] or "").split("|") if x],
            "skills": [x for x in (r[6] or "").split(",") if x],
            "practice": r[7] or "",
            "date": eff.isoformat(),
            "status": r[9] or "planned",
        }
        if week in hw_weeks:
            # дедлайн ДЗ — неделя от даты лекции; тикает от фактической даты
            due = eff + timedelta(days=7)
            item["hw_due"] = due.isoformat()
            item["hw_days_left"] = (due - today).days
        out.append(item)
    return out


@app.post("/api/lectures/{week}/pass")
async def lecture_pass(week: int, body: LecturePassIn, claims: dict = Depends(require_staff)) -> dict:
    """Отметить лекцию проведённой; опционально назначить дату следующей (с уведомлением)."""
    by = claims.get("preferred_username", "?")
    _, start = _course_week()
    async with db._conn() as c:  # noqa: SLF001
        row = await (await c.execute(
            "SELECT title,scheduled_at FROM lectures WHERE week=%s", (week,))).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Лекции №{week} нет")
        # если дата не назначалась — фиксируем фактическую как сегодня
        await c.execute(
            "UPDATE lectures SET status='passed', scheduled_at=COALESCE(scheduled_at,%s) WHERE week=%s",
            (date.today(), week))
        nxt = await (await c.execute(
            "SELECT week,title FROM lectures WHERE week>%s ORDER BY week LIMIT 1", (week,))).fetchone()
        tail = ""
        payload = {"week": week, "action": "passed"}
        if body.next_date and nxt:
            try:
                nd = date.fromisoformat(body.next_date[:10])
            except ValueError:
                raise HTTPException(status_code=400, detail="Дата в формате YYYY-MM-DD")
            await c.execute("UPDATE lectures SET scheduled_at=%s WHERE week=%s", (nd, nxt[0]))
            tail = f" Следующая лекция «{nxt[1]}» — {nd.strftime('%d.%m.%Y')}."
            payload.update({"next_week": nxt[0], "next_date": nd.isoformat()})
        await _notify(c, "lecture_passed", f"Лекция №{week} проведена",
                      f"«{row[0]}» отмечена как проведённая.{tail}", by, payload)
    return {"ok": True}


@app.post("/api/lectures/{week}/schedule")
async def lecture_schedule(week: int, body: LectureScheduleIn, claims: dict = Depends(require_staff)) -> dict:
    """Назначить/перенести дату лекции — тикают дедлайны ДЗ, летит уведомление в бот."""
    by = claims.get("preferred_username", "?")
    try:
        nd = date.fromisoformat(body.date[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="Дата в формате YYYY-MM-DD")
    async with db._conn() as c:  # noqa: SLF001
        row = await (await c.execute(
            "SELECT title,scheduled_at FROM lectures WHERE week=%s", (week,))).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Лекции №{week} нет")
        await c.execute("UPDATE lectures SET scheduled_at=%s WHERE week=%s", (nd, week))
        verb = "перенесена на" if row[1] else "назначена на"
        await _notify(c, "lecture_scheduled", f"Лекция №{week}: новая дата",
                      f"«{row[0]}» {verb} {nd.strftime('%d.%m.%Y')}.", by,
                      {"week": week, "action": "scheduled", "date": nd.isoformat()})
    return {"ok": True}


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


@app.get("/api/my/cost-daily")
async def cost_daily(claims: dict = Depends(verify)) -> list[dict]:
    """Cost по дням текущей ISO-недели (для графика в Кабинете)."""
    async with db._conn() as c:  # noqa: SLF001
        rows = await (await c.execute(
            "SELECT EXTRACT(ISODOW FROM ts)::int AS dow, SUM(cost_rub) "
            "FROM cost_journal WHERE student_id=%s AND ts >= date_trunc('week', now()) "
            "GROUP BY dow", (claims["sub"],))).fetchall()
    m = {int(r[0]): float(r[1]) for r in rows}
    days = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    return [{"day": days[i], "cost": round(m.get(i + 1, 0.0), 2)} for i in range(7)]


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


def _effective_date(week: int, scheduled_at, start: date) -> date:
    """Фактическая дата лекции: явно назначенная лектором или расчётная от старта."""
    if scheduled_at:
        return scheduled_at if isinstance(scheduled_at, date) else date.fromisoformat(str(scheduled_at)[:10])
    return start + timedelta(days=(max(1, week) - 1) * 7)


async def _notify(c, kind: str, title: str, body: str, by: str, payload: dict | None = None) -> None:
    """Кладёт событие в outbox (его дренирует Telegram-бот) и зеркалит в анонсы портала."""
    await c.execute(
        "INSERT INTO notifications(kind,title,body,payload,created_by) VALUES(%s,%s,%s,%s,%s)",
        (kind, title, body, json.dumps(payload or {}, ensure_ascii=False), by))
    await c.execute("INSERT INTO announcements(title,body,created_by) VALUES(%s,%s,%s)",
                    (title, body, by))


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


# ─────────────────────────── Командный центр лектора ───────────────────────────

_MONTHS = ["", "янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def _week_date(week: int) -> str:
    start = date.fromisoformat(settings.course_start_date)
    d = start + timedelta(days=(max(1, week) - 1) * 7)
    return f"{d.day} {_MONTHS[d.month]}"


@app.get("/api/admin/roster")
async def admin_roster(claims: dict = Depends(require_staff)) -> dict:
    """Ростер: активность за неделю, КТ-оценки по заданиям, партнёр, риск, прогресс."""
    async with db._conn() as c:  # noqa: SLF001
        asg = await (await c.execute(
            "SELECT id,week,title,max_score FROM assignments ORDER BY position,week")).fetchall()
        act = await (await c.execute(
            "SELECT student_id, MAX(username), SUM(input_tokens+output_tokens), SUM(cost_rub) "
            "FROM cost_journal WHERE ts >= date_trunc('week', now()) GROUP BY student_id")).fetchall()
        proj = await (await c.execute(
            "SELECT student_id,username,description,status FROM projects")).fetchall()
        grd = await (await c.execute("SELECT student_id,assignment_id,score FROM grades")).fetchall()
        subs = await (await c.execute(
            "SELECT student_id, COUNT(*) FILTER (WHERE status='accepted'), COUNT(*) "
            "FROM submissions GROUP BY student_id")).fetchall()
        meta = await (await c.execute(
            "SELECT student_id,username,partner_id,risk_note,track_week FROM student_meta")).fetchall()

    assignments = [{"id": r[0], "week": r[1], "title": r[2], "max": r[3]} for r in asg]
    students: dict[str, dict] = {}

    def row(sid: str, uname: str | None = None) -> dict:
        r = students.get(sid)
        if r is None:
            r = students[sid] = {
                "student_id": sid, "username": uname or sid[:10], "project": "", "status": "idea",
                "partner_id": None, "risk_note": "", "week": None,
                "tokens": 0, "cost_rub": 0.0, "kt": [], "accepted": 0, "submitted": 0}
        elif uname:
            r["username"] = uname
        return r

    for sid, uname, tok, cost in act:
        r = row(sid, uname); r["tokens"] = int(tok or 0); r["cost_rub"] = float(cost or 0)
    for sid, uname, desc, status in proj:
        r = row(sid, uname); r["project"] = desc or ""; r["status"] = status or "idea"
    for sid, acc, tot in subs:
        r = row(sid); r["accepted"] = int(acc or 0); r["submitted"] = int(tot or 0)
    for sid, uname, pid, risk, tw in meta:
        r = row(sid, uname); r["partner_id"] = pid; r["risk_note"] = risk or ""; r["week"] = tw

    gmap: dict[str, dict] = {}
    for sid, aid, score in grd:
        gmap.setdefault(sid, {})[aid] = float(score) if score is not None else None
    for sid, r in students.items():
        r["kt"] = [{"assignment_id": a["id"], "week": a["week"], "title": a["title"],
                    "max": a["max"], "score": gmap.get(sid, {}).get(a["id"])} for a in assignments]

    return {"assignments": assignments,
            "students": sorted(students.values(), key=lambda x: x["username"].lower())}


@app.post("/api/admin/student-meta")
async def set_student_meta(body: StudentMetaIn, claims: dict = Depends(require_staff)) -> dict:
    async with db._conn() as c:  # noqa: SLF001
        await c.execute(
            "INSERT INTO student_meta(student_id,username,partner_id,risk_note,track_week,updated_at) "
            "VALUES(%s,%s,%s,%s,%s,now()) ON CONFLICT(student_id) DO UPDATE SET "
            "username=COALESCE(NULLIF(EXCLUDED.username,''),student_meta.username), "
            "partner_id=EXCLUDED.partner_id, risk_note=EXCLUDED.risk_note, "
            "track_week=EXCLUDED.track_week, updated_at=now()",
            (body.student_id, body.username, body.partner_id, body.risk_note, body.track_week))
    return {"ok": True}


@app.get("/api/admin/partners")
async def get_partners(claims: dict = Depends(require_staff)) -> list[dict]:
    async with db._conn() as c:  # noqa: SLF001
        rows = await (await c.execute(
            "SELECT id,name,contact,email,status,notes FROM partners ORDER BY id")).fetchall()
    return [{"id": r[0], "name": r[1], "contact": r[2], "email": r[3], "status": r[4], "notes": r[5]}
            for r in rows]


@app.post("/api/admin/partners")
async def add_partner(body: PartnerIn, claims: dict = Depends(require_staff)) -> dict:
    async with db._conn() as c:  # noqa: SLF001
        r = await (await c.execute(
            "INSERT INTO partners(name,contact,email,status,notes) VALUES(%s,%s,%s,%s,%s) RETURNING id",
            (body.name, body.contact, body.email, body.status, body.notes))).fetchone()
    return {"ok": True, "id": r[0]}


@app.delete("/api/admin/partners/{pid}")
async def del_partner(pid: int, claims: dict = Depends(require_staff)) -> dict:
    async with db._conn() as c:  # noqa: SLF001
        await c.execute("DELETE FROM partners WHERE id=%s", (pid,))
        await c.execute("UPDATE student_meta SET partner_id=NULL WHERE partner_id=%s", (pid,))
    return {"ok": True}


@app.get("/api/admin/calendar")
async def get_calendar(claims: dict = Depends(require_staff)) -> list[dict]:
    async with db._conn() as c:  # noqa: SLF001
        rows = await (await c.execute(
            "SELECT id,week,date_label,title,type FROM calendar_events ORDER BY week,id")).fetchall()
    return [{"id": r[0], "week": r[1], "date": r[2] or _week_date(r[1]), "title": r[3], "type": r[4]}
            for r in rows]


@app.post("/api/admin/calendar")
async def add_event(body: CalendarIn, claims: dict = Depends(require_staff)) -> dict:
    async with db._conn() as c:  # noqa: SLF001
        r = await (await c.execute(
            "INSERT INTO calendar_events(week,date_label,title,type) VALUES(%s,%s,%s,%s) RETURNING id",
            (body.week, body.date_label, body.title, body.type))).fetchone()
    return {"ok": True, "id": r[0]}


@app.delete("/api/admin/calendar/{eid}")
async def del_event(eid: int, claims: dict = Depends(require_staff)) -> dict:
    async with db._conn() as c:  # noqa: SLF001
        await c.execute("DELETE FROM calendar_events WHERE id=%s", (eid,))
    return {"ok": True}


@app.get("/api/admin/notes")
async def get_notes(claims: dict = Depends(require_staff)) -> dict:
    async with db._conn() as c:  # noqa: SLF001
        r = await (await c.execute(
            "SELECT body FROM lecturer_notes WHERE lecturer_id=%s", (claims["sub"],))).fetchone()
    return {"body": r[0] if r else ""}


@app.put("/api/admin/notes")
async def set_notes(body: NotesIn, claims: dict = Depends(require_staff)) -> dict:
    async with db._conn() as c:  # noqa: SLF001
        await c.execute(
            "INSERT INTO lecturer_notes(lecturer_id,body,updated_at) VALUES(%s,%s,now()) "
            "ON CONFLICT(lecturer_id) DO UPDATE SET body=EXCLUDED.body, updated_at=now()",
            (claims["sub"], body.body))
    return {"ok": True}


# ── Материалы курса (публичный бакет materials, drag-drop лектора) ──

def _ensure_materials() -> None:
    mc = _mc(False)
    if not mc.bucket_exists("materials"):
        mc.make_bucket("materials")
    pol = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
           "Principal": {"AWS": ["*"]}, "Action": ["s3:GetObject"],
           "Resource": ["arn:aws:s3:::materials/*"]}]}
    mc.set_bucket_policy("materials", json.dumps(pol))


@app.get("/api/admin/materials")
async def list_materials(claims: dict = Depends(require_staff)) -> list[dict]:
    try:
        _ensure_materials()
        return [{"name": o.object_name, "size": o.size or 0,
                 "url": f"https://{settings.minio_public}/materials/{o.object_name}"}
                for o in _mc(False).list_objects("materials", recursive=True)]
    except Exception:  # noqa: BLE001
        return []


@app.post("/api/admin/material-upload-url")
async def material_upload_url(filename: str, claims: dict = Depends(require_staff)) -> dict:
    _ensure_materials()
    url = _mc(True).presigned_put_object("materials", filename, expires=timedelta(hours=1))
    return {"url": url, "public_url": f"https://{settings.minio_public}/materials/{filename}"}


@app.post("/api/admin/material-upload")
async def material_upload_direct(file: UploadFile = File(...), claims: dict = Depends(require_staff)) -> dict:
    """Загрузка материала через portal-api (без presigned/CORS)."""
    _ensure_materials()
    safe = (file.filename or "file").replace("/", "_").replace("\\", "_").replace("..", "_").strip() or "file"
    f = file.file
    f.seek(0, 2); size = f.tell(); f.seek(0)
    _mc(False).put_object("materials", safe, f, length=size, part_size=10 * 1024 * 1024,
                          content_type=file.content_type or "application/octet-stream")
    return {"ok": True, "name": safe, "public_url": f"https://{settings.minio_public}/materials/{safe}"}


@app.delete("/api/admin/material")
async def del_material(filename: str, claims: dict = Depends(require_staff)) -> dict:
    _mc(False).remove_object("materials", filename)
    return {"ok": True}


@app.post("/api/admin/lecture-material")
async def attach_lecture_material(body: LectureMaterialIn, claims: dict = Depends(require_staff)) -> dict:
    """Привязать материал к лекции (добавляет в список, не перезаписывает)."""
    if not body.url:
        raise HTTPException(status_code=400, detail="url обязателен")
    title = body.title or body.url.rsplit("/", 1)[-1] or "Материалы"
    async with db._conn() as c:  # noqa: SLF001
        exists = (await (await c.execute(
            "SELECT COUNT(*) FROM lecture_materials WHERE lecture_week=%s AND url=%s",
            (body.week, body.url))).fetchone())[0]
        if not exists:
            await c.execute(
                "INSERT INTO lecture_materials(lecture_week,title,url) VALUES(%s,%s,%s)",
                (body.week, title, body.url))
        # держим materials_url как «первый» материал для обратной совместимости
        await c.execute(
            "UPDATE lectures SET materials_url=COALESCE(NULLIF(materials_url,''),%s) WHERE week=%s",
            (body.url, body.week))
    return {"ok": True}


@app.get("/api/admin/lecture-materials")
async def list_lecture_materials(claims: dict = Depends(require_staff)) -> list[dict]:
    """Все привязки материал→лекция (для админки)."""
    async with db._conn() as c:  # noqa: SLF001
        rows = await (await c.execute(
            "SELECT m.id, m.lecture_week, m.title, m.url, l.title "
            "FROM lecture_materials m LEFT JOIN lectures l ON l.week=m.lecture_week "
            "ORDER BY m.lecture_week, m.id")).fetchall()
    return [{"id": r[0], "week": r[1], "title": r[2], "url": r[3], "lecture": r[4]} for r in rows]


@app.delete("/api/admin/lecture-material/{mid}")
async def detach_lecture_material(mid: int, claims: dict = Depends(require_staff)) -> dict:
    async with db._conn() as c:  # noqa: SLF001
        row = await (await c.execute(
            "SELECT lecture_week, url FROM lecture_materials WHERE id=%s", (mid,))).fetchone()
        await c.execute("DELETE FROM lecture_materials WHERE id=%s", (mid,))
        if row:
            wk, url = row
            # если это был materials_url лекции — заменить на другой оставшийся (или очистить)
            nxt = await (await c.execute(
                "SELECT url FROM lecture_materials WHERE lecture_week=%s ORDER BY id LIMIT 1",
                (wk,))).fetchone()
            await c.execute("UPDATE lectures SET materials_url=%s WHERE week=%s AND materials_url=%s",
                            (nxt[0] if nxt else "", wk, url))
    return {"ok": True}
