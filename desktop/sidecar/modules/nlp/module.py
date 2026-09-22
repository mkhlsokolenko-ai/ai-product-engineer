"""Модуль «NLP» — обработка текста под менеджерские задачи.

Гибрид: извлечение сущностей — ЛОКАЛЬНО (regex, приватно, мгновенно, без зависимостей);
классификация / тональность / саммари-задачи — через self-host Qwen (шлюз). Без torch,
не раздувает бандл.
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter
from pydantic import BaseModel

from ... import gateway

MANIFEST = {"id": "nlp", "title": "Текст", "icon": "nlp", "ui": "nlp", "order": 65}
router = APIRouter()


class NlpIn(BaseModel):
    text: str
    op: str = "entities"   # entities | classify | sentiment | summary


# ── локальное извлечение сущностей (regex, RU/EN) ──
_RE = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "phone": re.compile(r"(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"),
    "money": re.compile(r"\d[\d\s.,]*\s*(?:руб|₽|р\.|rub|USD|\$|EUR|€|тыс|млн|млрд)\b", re.I),
    "date": re.compile(r"\b\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}\b|\b\d{1,2}\s+(?:янв|фев|мар|апр|ма[йя]|июн|июл|авг|сен|окт|ноя|дек)[а-я]*\s*\d{0,4}", re.I),
    "inn": re.compile(r"\b\d{10}\b|\b\d{12}\b"),
    "percent": re.compile(r"\d+(?:[.,]\d+)?\s*%"),
    "url": re.compile(r"https?://[^\s)]+"),
    "org": re.compile(r'(?:ООО|АО|ПАО|ЗАО|ИП)\s+[«"][^»"]+[»"]|[«"][^»"]{2,40}[»"]'),
}


def _entities(text: str) -> dict:
    out = {}
    for k, rx in _RE.items():
        vals = []
        for m in rx.findall(text):
            v = (m if isinstance(m, str) else m[0]).strip()
            if v and v not in vals:
                vals.append(v)
        if vals:
            out[k] = vals[:30]
    return out


def _ask(text: str, system: str, prompt: str, max_tokens: int = 500) -> dict:
    try:
        r = gateway.call("chat", {"prompt": prompt, "session_id": "nlp", "profile": "standard",
                                  "system": system, "max_tokens": max_tokens})
    except gateway.AuthRequired:
        return {"ok": False, "error": "auth_required"}
    except gateway.GatewayError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "text": r.get("text", "")}


_LABELS = ["жалоба", "запрос информации", "заявка/заказ", "благодарность", "счёт/оплата", "спам", "другое"]


@router.get("/status")
def status() -> dict:
    return {"ok": True, "ops": ["entities", "classify", "sentiment", "summary"],
            "entities_local": True, "model_ops": ["classify", "sentiment", "summary"]}


@router.post("/run")
def run(body: NlpIn) -> dict:
    t = (body.text or "").strip()
    if not t:
        return {"ok": False, "error": "empty"}
    op = body.op

    if op == "entities":  # локально, без сети
        ents = _entities(t)
        return {"ok": True, "op": op, "entities": ents,
                "note": "локально · " + (str(sum(len(v) for v in ents.values())) + " сущностей" if ents else "не найдено")}

    if op == "classify":
        r = _ask(t, "Ты — классификатор деловых обращений. Ответь СТРОГО одним ярлыком из списка, без пояснений.",
                 f"Ярлыки: {', '.join(_LABELS)}.\n\nТекст:\n{t}\n\nЯрлык:", 20)
        if not r["ok"]:
            return {"ok": False, "op": op, "error": r["error"]}
        label = r["text"].strip().lower().splitlines()[0]
        label = next((l for l in _LABELS if l in label), label[:40])
        return {"ok": True, "op": op, "label": label}

    if op == "sentiment":
        r = _ask(t, "Ты — анализатор тональности. Ответь СТРОГО JSON без пояснений.",
                 f'Оцени тональность. Верни JSON {{"tone":"позитивная|нейтральная|негативная","score":-1..1,"why":"кратко"}}\n\nТекст:\n{t}', 120)
        if not r["ok"]:
            return {"ok": False, "op": op, "error": r["error"]}
        try:
            m = re.search(r"\{.*\}", r["text"], re.S)
            data = json.loads(m.group(0)) if m else {"tone": r["text"][:30]}
        except Exception:  # noqa: BLE001
            data = {"tone": r["text"][:40]}
        return {"ok": True, "op": op, **data}

    if op == "summary":
        r = _ask(t, "Ты — деловой ассистент. Кратко и по делу, без воды.",
                 f"Сделай саммари текста (3-5 пунктов) и отдельно список задач с ответственными, если есть:\n\n{t}", 700)
        if not r["ok"]:
            return {"ok": False, "op": op, "error": r["error"]}
        return {"ok": True, "op": op, "text": r["text"]}

    return {"ok": False, "error": "bad_op"}
