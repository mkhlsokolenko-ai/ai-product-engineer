"""Модуль «Агенты» — каталог + конструктор + запуск цепочек.

Пользователь создаёт агента человекочитаемо (скилл/шаги/DoD/анти-паттерны), собирает из
нескольких агентов цепочку и запускает под задачу. Методика превращается в system-prompt.
Позже: фильтр каталога по RBAC-роли, привязка к правой шторке чата.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ... import db, gateway
from ..chat.module import SKILLS  # переиспользуем краткие подсказки скиллов

MANIFEST = {"id": "agents", "title": "Агенты", "icon": "agents", "ui": "agents", "order": 20}
router = APIRouter()


class AgentIn(BaseModel):
    name: str
    description: str = ""
    skills: list[str] = []
    steps: str = ""
    dod: str = ""
    antipatterns: str = ""
    profile: str = "standard"
    outward: int = 0   # действует наружу → запуск через approve/deny-гейт


class RunIn(BaseModel):
    agent_ids: list[int]
    task: str


_SEED = [
    ("Разбор отзывов", "Находит главные боли в отзывах и предлагает действия.",
     ["idea-scorer"], "1. Выдели повторяющиеся жалобы\n2. Оцени частоту/остроту\n3. Дай 3 действия",
     "Есть 3 конкретных выполнимых действия; каждое привязано к реальной боли.",
     "Не выдумывать боль, которой нет в отзывах."),
    ("Критик идеи", "Жёстко проверяет идею как скептик-инвестор.",
     ["devils-advocate"], "1. Найди слабые места\n2. Проверь спрос и экономику\n3. Вынеси вердикт",
     "Каждое возражение с аргументом; назван 1 killer-риск.",
     "Без похвал и общих слов; не смягчать."),
]


def _row(a: dict) -> dict:
    for k in ("skills",):
        a[k] = [s for s in (a.get(k) or "").split(",") if s]
    return a


def _seed_if_empty():
    if db.q("SELECT COUNT(*) c FROM agents")[0]["c"]:
        return
    for name, desc, sk, steps, dod, anti in _SEED:
        db.run("INSERT INTO agents(name,description,skills,steps,dod,antipatterns,profile,created_at) "
               "VALUES(?,?,?,?,?,?,?,?)", (name, desc, ",".join(sk), steps, dod, anti, "standard", db.now()))


@router.get("/skills")
def skills() -> list[dict]:
    return [{"id": k, "hint": v} for k, v in SKILLS.items()]


@router.get("/catalog")
def catalog() -> list[dict]:
    _seed_if_empty()
    return [_row(a) for a in db.q(
        "SELECT id,name,description,skills,steps,dod,antipatterns,profile,outward FROM agents ORDER BY id")]


@router.post("/catalog")
def create(body: AgentIn) -> dict:
    aid = db.run("INSERT INTO agents(name,description,skills,steps,dod,antipatterns,profile,outward,created_at) "
                 "VALUES(?,?,?,?,?,?,?,?,?)",
                 (body.name, body.description, ",".join(body.skills), body.steps, body.dod,
                  body.antipatterns, body.profile, int(body.outward), db.now()))
    return {"ok": True, "id": aid}


@router.patch("/catalog/{aid}")
def update(aid: int, body: AgentIn) -> dict:
    db.run("UPDATE agents SET name=?,description=?,skills=?,steps=?,dod=?,antipatterns=?,profile=?,outward=? WHERE id=?",
           (body.name, body.description, ",".join(body.skills), body.steps, body.dod,
            body.antipatterns, body.profile, int(body.outward), aid))
    return {"ok": True}


@router.delete("/catalog/{aid}")
def delete(aid: int) -> dict:
    db.run("DELETE FROM agents WHERE id=?", (aid,))
    return {"ok": True}


def _system_for(a: dict) -> str:
    parts = [f"Ты — {a['name']}."]
    if a.get("description"):
        parts.append(a["description"])
    if a.get("steps"):
        parts.append("Методика (шаги):\n" + a["steps"])
    if a.get("dod"):
        parts.append("Definition of Done:\n" + a["dod"])
    if a.get("antipatterns"):
        parts.append("Избегай (анти-паттерны):\n" + a["antipatterns"])
    hints = [f"[{s}] {SKILLS[s]}" for s in (a.get("skills") or []) if s in SKILLS]
    if hints:
        parts.append("Методики-скиллы:\n" + "\n".join(hints))
    return "\n\n".join(parts)


@router.post("/run")
def run(body: RunIn) -> dict:
    agents = []
    for aid in body.agent_ids:
        rows = db.q("SELECT id,name,description,skills,steps,dod,antipatterns,profile FROM agents WHERE id=?", (aid,))
        if rows:
            agents.append(_row(rows[0]))
    if not agents:
        return {"ok": False, "error": "no_agents"}
    steps, prior = [], ""
    try:
        for a in agents:
            prefix = ("Наработки предыдущих ролей:\n" + prior) if prior else ""
            r = gateway.call("chat", {"prompt": f"Задача: {body.task}\n\n{prefix}",
                                      "session_id": "agents-run", "profile": a.get("profile") or "standard",
                                      "system": _system_for(a), "max_tokens": 1200})
            t = r.get("text", "")
            steps.append({"name": a["name"], "text": t})
            prior += f"[{a['name']}]: {t}\n"
    except gateway.AuthRequired:
        return {"ok": False, "error": "auth_required"}
    except gateway.GatewayError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "steps": steps, "combined": "\n\n".join(f"### {s['name']}\n{s['text']}" for s in steps)}
