#!/usr/bin/env python3
"""ape — курсовой CLI «AI Product Engineer».

Единая точка доступа к моделям курса через MCP-шлюз engineer-ai.pro.
  ape login              — вход через GitHub (браузер), токен сохраняется и авто-обновляется
  ape code "<задача>"    — генерация/правка кода   -> self-host Qwen3.8-27B
  ape ask  "<вопрос>"    — ресёрч и рассуждения     -> DeepSeek
  ape chat "<запрос>"    — общий профиль
  ape rag index <файлы>  — проиндексировать документы в свою RAG-коллекцию
  ape rag search "<q>"   — поиск по своей коллекции
  ape usage              — расход токенов и квота недели
  ape whoami / ape logout / ape session new

Зависимостей нет — только стандартная библиотека Python 3.9+.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import random
import re
import secrets
import shutil
import ssl
import sys
import threading
import time
from datetime import datetime
import urllib.parse
import urllib.request
import webbrowser

KC = "https://auth.engineer-ai.pro/realms/ai-product-engineer/protocol/openid-connect"
MCP = "https://mcp.engineer-ai.pro/mcp"
PORTAL = "https://engineer-ai.pro"
CLIENT = "portal"
CFG_DIR = os.path.join(os.path.expanduser("~"), ".ape")
CFG = os.path.join(CFG_DIR, "config.json")

# Windows-консоль по умолчанию cp1251/cp866 и падает на '₽', '→', '✓' и кириллице
# (UnicodeEncodeError). Переводим вывод в UTF-8 с безопасной заменой — не крашится нигде.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# На Windows включаем ANSI-цвета в самой консоли (conhost/PowerShell) — тогда
# дизайн работает без Windows Terminal. Если не вышло — гасим цвета.
_ANSI = True
if os.name == "nt":
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetConsoleMode(k.GetStdHandle(-11), 7)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING | ...
    except Exception:
        _ANSI = os.environ.get("WT_SESSION") is not None

# Палитра CLI: голубой акцент + серые оттенки.
C = {
    "cy": "\033[38;5;81m",    # голубой акцент
    "cy2": "\033[38;5;39m",   # насыщенный синий
    "blue": "\033[38;5;75m",  # мягкий сине-голубой
    "gray": "\033[38;5;245m", # серый
    "dim": "\033[38;5;240m",  # тёмно-серый
    "green": "\033[38;5;114m", "yellow": "\033[38;5;179m", "red": "\033[38;5;203m",
    "bold": "\033[1m", "off": "\033[0m",
}
# Вертикальный сине-голубой градиент для лого
GRAD = ["\033[38;5;24m", "\033[38;5;31m", "\033[38;5;38m", "\033[38;5;45m", "\033[38;5;51m"]
# Градиент «думанья»: от бледно-голубого к насыщенному фиолетовому (256-цвета)
SPIN_RAMP = [159, 153, 111, 75, 69, 63, 99, 105, 135, 141, 177]
SPIN_RAMP = [f"\033[38;5;{n}m" for n in SPIN_RAMP]
if not _ANSI:
    C = {kk: "" for kk in C}
    GRAD = ["" for _ in GRAD]
    SPIN_RAMP = [""]


def col(s, c):
    return f"{C[c]}{s}{C['off']}"


# ─────────────────────── конфиг ───────────────────────

def load_cfg() -> dict:
    try:
        with open(CFG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(cfg: dict) -> None:
    os.makedirs(CFG_DIR, exist_ok=True)
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    try:
        os.chmod(CFG, 0o600)
    except Exception:
        pass


# ─────────────────────── OIDC (loopback PKCE) ───────────────────────

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def login(idp: str | None = "github") -> None:
    verifier = _b64(secrets.token_bytes(48))
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    state = _b64(secrets.token_bytes(16))
    holder: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            holder["code"] = (q.get("code") or [None])[0]
            holder["state"] = (q.get("state") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "<html><body style='font-family:sans-serif;text-align:center;padding-top:60px'>"
                "<h2>ape: вход выполнен ✓</h2><p>Можно вернуться в терминал и закрыть вкладку.</p>"
                "</body></html>".encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    redirect = f"http://127.0.0.1:{port}/callback"
    params = {"client_id": CLIENT, "response_type": "code", "scope": "openid",
              "redirect_uri": redirect, "state": state,
              "code_challenge": challenge, "code_challenge_method": "S256"}
    if idp:
        params["kc_idp_hint"] = idp
    url = KC + "/auth?" + urllib.parse.urlencode(params)

    print(col("Открываю браузер для входа через GitHub…", "gray"))
    print(col("Если не открылось — вставь ссылку вручную:", "gray"))
    print("  " + url)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    try:
        webbrowser.open(url)
    except Exception:
        pass
    for _ in range(300):  # ждём редирект до 5 мин
        if "code" in holder:
            break
        time.sleep(1)
    srv.server_close()
    if not holder.get("code") or holder.get("state") != state:
        sys.exit(col("Вход не завершён.", "red"))

    data = urllib.parse.urlencode({
        "grant_type": "authorization_code", "client_id": CLIENT,
        "code": holder["code"], "redirect_uri": redirect, "code_verifier": verifier}).encode()
    tok = _post_form(KC + "/token", data)
    _store_tokens(tok)
    who = _claims().get("preferred_username") or "студент"
    print(col(f"Готово. Вошёл как {who}.", "green"))
    print(col("Дальше: ape code \"…\"  ·  ape ask \"…\"  ·  ape usage", "gray"))


def _post_form(url: str, data: bytes) -> dict:
    req = urllib.request.Request(url, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    last = None
    for attempt in range(4):  # ретрай на TLS-reset/сетевых сбоях (DPI/антивирус)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError:
            raise
        except (ssl.SSLError, urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = e
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
    raise SystemExit(col(
        f"Не удалось соединиться с auth.engineer-ai.pro (TLS сброшен: {last}).\n"
        "Проверь сеть/антивирус/VPN и повтори.", "red"))


def _store_tokens(tok: dict) -> None:
    cfg = load_cfg()
    cfg["access_token"] = tok["access_token"]
    if tok.get("refresh_token"):
        cfg["refresh_token"] = tok["refresh_token"]
    cfg["expires_at"] = time.time() + int(tok.get("expires_in", 300)) - 30
    save_cfg(cfg)


def _refresh() -> bool:
    cfg = load_cfg()
    rt = cfg.get("refresh_token")
    if not rt:
        return False
    try:
        tok = _post_form(KC + "/token", urllib.parse.urlencode({
            "grant_type": "refresh_token", "client_id": CLIENT, "refresh_token": rt}).encode())
        _store_tokens(tok)
        return True
    except Exception:
        return False


def token() -> str:
    cfg = load_cfg()
    if not cfg.get("access_token"):
        sys.exit(col("Сначала выполни: ape login", "yellow"))
    if time.time() >= cfg.get("expires_at", 0):
        if not _refresh():
            sys.exit(col("Сессия истекла. Выполни: ape login", "yellow"))
        cfg = load_cfg()
    return cfg["access_token"]


def _claims() -> dict:
    try:
        p = load_cfg()["access_token"].split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p))
    except Exception:
        return {}


# ─────────────────────── MCP-клиент (JSON-RPC / streamable-http) ───────────────────────

def _mcp_call(tool: str, args: dict) -> dict:
    tok = token()
    sid = {"v": None}

    def rpc(method, params=None, notify=False, retry=True):
        body = {"jsonrpc": "2.0", "method": method}
        if not notify:
            body["id"] = 1
        if params is not None:
            body["params"] = params
        hdr = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream",
               "Authorization": "Bearer " + tok}
        if sid["v"]:
            hdr["mcp-session-id"] = sid["v"]
        req = urllib.request.Request(MCP, data=json.dumps(body).encode(), headers=hdr)
        # DPI/провайдер/антивирус иногда рвут TLS на рукопожатии (UNEXPECTED_EOF) —
        # ретраим с бэкоффом: reset вероятностный, обычно пробивается со 2-3 попытки.
        last = None
        for attempt in range(4):
            try:
                r = urllib.request.urlopen(req, timeout=120)
                break
            except urllib.error.HTTPError as e:
                if e.code == 401 and retry and _refresh():
                    return rpc(method, params, notify, retry=False)
                sys.exit(col(f"Шлюз вернул {e.code}. Попробуй войти заново: ape login", "red"))
            except (ssl.SSLError, urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last = e
                if attempt < 3:
                    print(col(f"…сеть нестабильна, повтор {attempt + 2}/4", "gray"), file=sys.stderr)
                    time.sleep(1.5 * (attempt + 1))
        else:
            sys.exit(col(
                "Не удалось соединиться с mcp.engineer-ai.pro (TLS-соединение сброшено).\n"
                "Обычно это блокировка/антивирус/сеть на твоей стороне. Попробуй:\n"
                "  • запустить команду ещё раз (часто помогает со 2–3 попытки);\n"
                "  • временно выключить проверку HTTPS в антивирусе или VPN;\n"
                "  • другую сеть (мобильный интернет как точку доступа).\n"
                f"Детали: {last}", "red"))
        if not sid["v"] and r.headers.get("mcp-session-id"):
            sid["v"] = r.headers.get("mcp-session-id")
        if notify:
            return None
        raw = r.read().decode()
        if "text/event-stream" in (r.headers.get("Content-Type") or ""):
            raw = "".join(l[5:].strip() for l in raw.splitlines() if l.startswith("data:"))
        return json.loads(raw)

    rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "ape-cli", "version": "1.0"}})
    rpc("notifications/initialized", notify=True)
    res = rpc("tools/call", {"name": tool, "arguments": args})
    if "error" in res:
        sys.exit(col("Ошибка шлюза: " + json.dumps(res["error"], ensure_ascii=False), "red"))
    r = res["result"]
    if r.get("structuredContent"):
        return r["structuredContent"]
    if r.get("content"):
        try:
            return json.loads(r["content"][0]["text"])
        except Exception:
            return {"text": r["content"][0]["text"]}
    return {}


def _session_id() -> str:
    cfg = load_cfg()
    sid = cfg.get("session_id")
    if not sid:
        sid = "ape-" + secrets.token_hex(4)
        cfg["session_id"] = sid
        save_cfg(cfg)
    return sid


# ─────────────────────── Память диалога (между сессиями + компрессия) ───────────────────────

def _mem_path() -> str:
    return os.path.join(CFG_DIR, f"mem-{_session_id()}.json")


def mem_load() -> dict:
    try:
        with open(_mem_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"summary": "", "turns": []}


def mem_save(m: dict) -> None:
    os.makedirs(CFG_DIR, exist_ok=True)
    with open(_mem_path(), "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False)


def mem_system(base: str, m: dict) -> str:
    """Собирает system-промпт с памятью: сжатое резюме + последние реплики."""
    ctx = ""
    if m.get("summary"):
        ctx += f"\n\n[Память диалога, сжато]\n{m['summary']}"
    recent = m.get("turns", [])[-6:]
    if recent:
        ctx += "\n\n[Последние реплики]\n" + "\n".join(
            f"{'Ты' if t['role'] == 'user' else 'Ассистент'}: {t['content'][:600]}" for t in recent)
    return (base + ctx).strip() if ctx else base


def mem_add(m: dict, user: str, assistant: str) -> None:
    m.setdefault("turns", []).append({"role": "user", "content": user})
    m["turns"].append({"role": "assistant", "content": assistant})
    # Компрессия: старые реплики сворачиваем в короткое резюме.
    over = len(m["turns"]) > 12 or sum(len(t["content"]) for t in m["turns"]) > 5000
    if over:
        keep = m["turns"][-6:]
        old = m["turns"][:-6]
        transcript = "\n".join(f"{t['role']}: {t['content'][:800]}" for t in old)
        print(col("  ⟳ сжимаю память диалога…", "dim"), file=sys.stderr)
        try:
            r = _mcp_call("chat", {
                "prompt": "Сожми в 5–8 коротких пунктов ключевые факты, решения и контекст "
                          "этого диалога, чтобы можно было продолжить работу. Без воды, только суть.\n\n"
                          f"Текущее резюме:\n{m.get('summary','')}\n\nСтарые реплики:\n{transcript}",
                "session_id": _session_id(), "profile": "research", "system": "", "max_tokens": 400})
            m["summary"] = (r.get("text") or m.get("summary", "")).strip()
            m["turns"] = keep
        except Exception:
            pass
    mem_save(m)


LAST_REMAIN = None  # остаток недельной квоты (для титульной строки ввода)


# ─────────────────────── Скиллы (вкл/выкл, инъекция в system) ───────────────────────
# name -> (заголовок, зачем, инструкция-стиль для модели)
SKILLS = {
    "researcher": ("Researcher", "направленное desk-исследование",
                   "Проводи направленное исследование: рынок, данные, аналоги; указывай источник каждого факта."),
    "icp-interviewer": ("ICP Interviewer", "интервью с представителем ICP",
                        "Прожимай гипотезу ценности от лица ICP: боли, контекст, готовность платить."),
    "jtbd-formulator": ("JTBD", "Job To Be Done",
                        "Формулируй задачу через JTBD: какую работу нанимают продукт делать."),
    "idea-scorer": ("Idea Scorer", "оценка идеи по рубрике",
                    "Оценивай идею по рубрике (боль, данные, выполнимость, экономика) с баллами и обоснованием."),
    "idea-selector": ("Idea Selector", "выбор лучшей идеи",
                      "Сравнивай варианты по критериям и обоснованно выбирай один."),
    "devils-advocate": ("Devil's Advocate", "жёсткая критика",
                        "Критикуй без похвалы: где идея/решение сломается, худшие сценарии, риски."),
    "architecture-chooser": ("Architecture Chooser", "workflow vs agent",
                             "Выбирай архитектуру (workflow/agent/hybrid) под задачу, не усложняя без нужды."),
    "mlsdd-writer": ("MLSDD", "ML System Design Doc",
                     "Структурируй как ML System Design Doc: границы, данные, метрики, риски, деградация."),
    "agent-design-writer": ("Agent Design", "дизайн агента",
                            "Проектируй агента: инструменты, память, границы, поведение при сбое."),
    "adr-writer": ("ADR", "фиксация решений",
                   "Оформляй ключевые решения как ADR: контекст, варианты, решение, последствия."),
    "spec-reviewer": ("Spec Reviewer", "полнота спеки",
                      "Проверяй полноту acceptance-критериев, ищи дыры и неоднозначности."),
    "cost-estimator": ("Cost Estimator", "стоимость по токенам",
                       "Оценивай стоимость user-flow в токенах и деньгах, показывай расчёт."),
    "test-writer": ("Test Writer (TDD)", "тесты до кода",
                    "Сначала тесты (включая краевые случаи), потом реализация под них."),
    "memory-architect": ("Memory Architect", "память агента",
                         "Проектируй двухуровневую память с дистилляцией, контролируй объём контекста."),
    "rag-architect": ("RAG Architect", "RAG-pipeline",
                      "Проектируй RAG: chunking/embed/rerank под домен + метрики качества retrieval."),
    "eval-generator": ("Eval Generator", "eval-датасет и грейдеры",
                       "Строй eval: кейсы, грейдеры (code/LLM-judge/human), метрики, пороги."),
    "unit-economics-checker": ("Unit Economics", "проверка экономики",
                               "Проверяй unit-экономику на пользователя, ищи дыры до масштабирования."),
    "grill-me": ("Grill Me", "жёсткий допрос",
                 "Допрашивай по дереву решений, дожимай до цифр и критериев, подсвечивай слабые места."),
    "conventional-commits": ("Conventional Commits", "дисциплина коммитов",
                             "Сообщения коммитов — по Conventional Commits (feat/fix/... + суть)."),
    "fastapi-patterns": ("FastAPI Patterns", "паттерны FastAPI",
                         "Пиши FastAPI по best practices: схемы, зависимости, обработка ошибок."),
    "docker-patterns": ("Docker Patterns", "паттерны Docker",
                        "Docker по best practices: слои, кэш, минимальный образ, воспроизводимость."),
}


def skills_active() -> list[str]:
    return [s for s in load_cfg().get("skills", []) if s in SKILLS]


def skills_set(names) -> None:
    cfg = load_cfg(); cfg["skills"] = sorted(set(names)); save_cfg(cfg)


def skills_system(base: str) -> str:
    """Добавляет в system-промпт инструкции активных скиллов."""
    act = skills_active()
    if not act:
        return base
    block = "\n".join(f"- {SKILLS[s][0]} ({s}): {SKILLS[s][2]}" for s in act)
    add = "\n\n[Активные навыки — применяй их подход]\n" + block
    return (base + add).strip()


# ─────────────────────── команды ───────────────────────

def _read_prompt(text: str | None, files: list[str], stdin: bool) -> str:
    parts = []
    if text:
        parts.append(text)
    for fp in files or []:
        with open(fp, encoding="utf-8") as f:
            parts.append(f"\n\n=== файл {os.path.basename(fp)} ===\n{f.read()}")
    if stdin and not sys.stdin.isatty():
        parts.append("\n\n" + sys.stdin.read())
    if not parts:
        sys.exit(col("Пустой запрос. Пример: ape code \"напиши функцию …\"", "yellow"))
    return "".join(parts)


_PHRASES = [
    "Размышляю", "Кручу колесо", "Думаю о бесконечно-вечном", "Фрактальное подобие",
    "Сверяюсь со вселенной", "Разматываю клубок", "Собираю мысли в кучу",
    "Ловлю дзен", "Считаю на пальцах у робота", "Гоняю электроны", "Плету нейросеть",
    "Заглядываю за горизонт", "Медитирую над токенами", "Ищу изящное решение",
]
_SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _spin_call(tool: str, args: dict):
    """Вызов MCP с анимацией «думанья»: спиннер, фраза, таймер. Возвращает результат."""
    if not sys.stdout.isatty():
        return _mcp_call(tool, args)
    box = {}
    def worker():
        try:
            box["res"] = _mcp_call(tool, args)
        except BaseException as e:  # noqa: BLE001 — пробросим в main-поток
            box["err"] = e
    th = threading.Thread(target=worker, daemon=True)
    start = time.time(); th.start()
    i = 0; phrase = random.choice(_PHRASES); swap = start + 2.5
    while th.is_alive():
        now = time.time()
        if now > swap:
            phrase = random.choice(_PHRASES); swap = now + 2.5
        frame = _SPIN[i % len(_SPIN)]
        grad = SPIN_RAMP[i % len(SPIN_RAMP)]  # плавный перелив бледно-синий → фиолетовый
        sys.stdout.write(f"\r  {grad}{frame} {phrase}…{C['off']} {C['dim']}{now - start:4.1f}s{C['off']}" + " " * 6)
        sys.stdout.flush(); i += 1; time.sleep(0.1)
    th.join()
    sys.stdout.write("\r" + " " * 60 + "\r"); sys.stdout.flush()
    if "err" in box:
        raise box["err"]
    return box.get("res"), time.time() - start


def _chat(profile: str, prompt: str, system: str, max_tokens: int) -> str | None:
    global LAST_REMAIN
    label = {"code": "Qwen3.8-27B", "research": "DeepSeek", "standard": "каскад"}.get(profile, profile)
    system = skills_system(system)  # подмешиваем активные скиллы
    act = skills_active()
    head = f"  → {label}"
    if act:
        head += f"   {C['cy']}🧩 {', '.join(act)}{C['off']}{C['dim']}"
    print(col(head, "dim"), file=sys.stderr)
    out = _spin_call("chat", {"prompt": prompt, "session_id": _session_id(),
                              "profile": profile, "system": system, "max_tokens": max_tokens})
    res, elapsed = out if isinstance(out, tuple) else (out, None)
    if res.get("error"):
        print(col(res.get("message", res["error"]), "yellow")); return None
    text = res.get("text", "")
    _print_answer(text, res.get("truncated"), collapse=(profile != "code"))
    q = (res.get("quota") or {}).get("week", {})
    if q.get("remaining") is not None:
        LAST_REMAIN = q["remaining"]
    used, o = res.get("input_tokens", 0), res.get("output_tokens", 0)
    tail = f"  {res.get('model','?')} · {used}+{o} ток"
    if elapsed is not None:
        tail += f" · {elapsed:.1f}s"
    tail += f" · {res.get('cost_rub',0):.3f}₽"
    if q:
        tail += f" · осталось {q.get('remaining',0):,}".replace(",", " ")
    print(col(tail, "dim"), file=sys.stderr)
    return text


LAST_ANSWER = ""       # полный текст последнего ответа (для /more и /save)
PREVIEW_LINES = 30     # сколько строк показываем сразу


def _colorize(lines):
    """Внутри код-блоков (```) подсвечивает diff: +добавлено голубым, -удалено красным."""
    if not _ANSI:
        return lines
    out = []; fence = False
    for ln in lines:
        st = ln.lstrip()
        if st.startswith("```"):
            fence = not fence; out.append(ln); continue
        if fence:
            if st.startswith(("+++", "---")):
                out.append(ln)
            elif st.startswith("+"):
                out.append(C["cy"] + ln + C["off"])      # добавлено — голубой
            elif st.startswith("-"):
                out.append(C["red"] + ln + C["off"])      # удалено — красный
            elif st.startswith("@@"):
                out.append(C["dim"] + ln + C["off"])
            else:
                out.append(ln)
        else:
            out.append(ln)
    return out


def _print_answer(text: str, truncated: bool = False, collapse: bool = True) -> None:
    """Печатает ответ с diff-подсветкой; длинный (если collapse) сворачивает до превью."""
    global LAST_ANSWER
    LAST_ANSWER = text
    lines = text.split("\n")
    colored = _colorize(lines)
    if (not collapse) or (not sys.stdout.isatty()) or len(lines) <= PREVIEW_LINES + 3:
        print("\n".join(colored))
    else:
        print("\n".join(colored[:PREVIEW_LINES]))
        rest = len(lines) - PREVIEW_LINES
        print(col(f"  ⋯ ещё {rest} строк · /more — раскрыть полностью · /save <файл> — сохранить",
                  "cy"))
    if truncated:
        print(col("  ⚠ ответ упёрся в лимит длины — напиши «продолжи» или повтори с большим объёмом",
                  "yellow"))


# ─────────────────────── Сохранение ответа (локально / в проект студента) ───────────────────────

_CODE_EXTS = (".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".cpp", ".c", ".rb",
              ".sh", ".sql", ".json", ".yaml", ".yml", ".html", ".css", ".ipynb")


def _extract_code(text: str) -> str | None:
    """Первый код-блок из markdown (без ``` рамки) — чтобы .py-файл был запускаемым."""
    m = re.search(r"```[^\n]*\n(.*?)```", text, re.S)
    return m.group(1).rstrip("\n") if m else None


def _default_name(ext: str = ".md") -> str:
    return "ape-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ext


def _payload_for(name: str) -> str:
    """Для кодовых расширений сохраняем сам код (без markdown-обвязки), иначе — весь ответ."""
    if name.lower().endswith(_CODE_EXTS):
        code = _extract_code(LAST_ANSWER)
        if code:
            return code
    return LAST_ANSWER


def _save_local(path: str, content: str) -> str:
    path = os.path.expanduser(path)
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return os.path.abspath(path)


def _upload_cloud(filename: str, content: bytes) -> dict:
    """Загрузка в хранилище проекта студента через portal-api (тот же JWT)."""
    tok = token()
    boundary = "----ape" + secrets.token_hex(8)
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        PORTAL + "/api/storage/upload", data=body,
        headers={"Authorization": "Bearer " + tok,
                 "Content-Type": "multipart/form-data; boundary=" + boundary})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def do_save(rest: str) -> None:
    if not LAST_ANSWER:
        print(col("  Нечего сохранять — сначала задай вопрос.", "gray")); return
    sp = rest.split(maxsplit=1)
    if sp and sp[0] == "cloud":                       # /save cloud [имя]
        name = (sp[1].strip() if len(sp) > 1 else _default_name())
        content = _payload_for(name)
        try:
            _upload_cloud(name, content.encode("utf-8"))
            print(col(f"  ☁ загружено в проект: {name} — открой портал → «Мой проект»", "cy"))
        except Exception as e:  # noqa: BLE001
            print(col(f"  Не удалось загрузить в облако: {e}", "yellow"))
    else:                                             # /save [путь/имя]
        name = rest.strip() or _default_name()
        content = _payload_for(name)
        try:
            p = _save_local(name, content)
            print(col(f"  💾 сохранено: {p} ({len(content)} символов)", "cy"))
        except Exception as e:  # noqa: BLE001
            print(col(f"  Не удалось сохранить: {e}", "yellow"))


def cmd_code(a):
    _chat("code", _read_prompt(a.prompt, a.file, a.stdin),
          a.system or "Ты пишешь чистый production-код. Возвращай только запрошенное.", a.max_tokens)


def cmd_ask(a):
    _chat("research", _read_prompt(a.prompt, a.file, a.stdin), a.system or "", a.max_tokens)


def cmd_chat(a):
    _chat("standard", _read_prompt(a.prompt, a.file, a.stdin), a.system or "", a.max_tokens)


def cmd_rag(a):
    if a.rag_cmd == "index":
        docs = []
        for fp in a.files:
            with open(fp, encoding="utf-8") as f:
                docs.append(f.read())
        res = _mcp_call("rag_index", {"documents": docs, "session_id": _session_id()})
        print(col(f"Проиндексировано документов: {res.get('indexed', len(docs))}", "green"))
    else:
        res = _mcp_call("rag_search", {"query": a.query, "session_id": _session_id(),
                                       "top_k": a.top_k})
        for i, h in enumerate(res.get("results", res.get("hits", [])), 1):
            txt = h.get("text") or h.get("document") or json.dumps(h, ensure_ascii=False)
            print(col(f"[{i}] score={h.get('score','?')}", "blue"))
            print(txt[:500])


def cmd_usage(a):
    res = _mcp_call("my_usage", {"session_id": _session_id()})
    wk = res.get("week", {})
    ss = res.get("sessions_this_week", {})
    print(col("Расход за неделю", "bold"))
    print(f"  токены:  {wk.get('tokens_used',0):,} / {wk.get('limit',0):,}"
          f"  (осталось {wk.get('remaining',0):,})".replace(",", " "))
    print(f"  стоимость: {wk.get('cost_rub',0):.2f} ₽   вызовов: {wk.get('calls',0)}")
    print(col(f"  сессий открыто: {ss.get('opened',0)} (без лимита — считается только недельный потолок)", "gray"))


def cmd_whoami(a):
    c = _claims()
    if not c:
        sys.exit(col("Не выполнен вход. ape login", "yellow"))
    roles = (c.get("realm_access") or {}).get("roles", [])
    role = "admin" if "admin" in roles else "lecturer" if "lecturer" in roles else "student"
    print(f"{c.get('preferred_username','?')} · {role} · сессия {_session_id()}")


def cmd_logout(a):
    try:
        os.remove(CFG)
    except FileNotFoundError:
        pass
    print(col("Вышел. Токен удалён.", "green"))


def cmd_session(a):
    if a.session_cmd == "new":
        cfg = load_cfg()
        cfg["session_id"] = "ape-" + secrets.token_hex(4)
        save_cfg(cfg)
        print(col(f"Новая сессия: {cfg['session_id']}", "green"))
    else:
        print(_session_id())


def cmd_login(a):
    login(None if a.no_github else "github")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ape", description="CLI курса AI Product Engineer")
    sub = p.add_subparsers(dest="cmd", required=True)

    lg = sub.add_parser("login", help="вход через GitHub (браузер)")
    lg.add_argument("--no-github", action="store_true", help="выбрать способ входа в браузере")
    lg.set_defaults(func=cmd_login)

    for name, fn, hlp in [("code", cmd_code, "код -> Qwen"), ("ask", cmd_ask, "ресёрч -> DeepSeek"),
                          ("chat", cmd_chat, "общий профиль")]:
        c = sub.add_parser(name, help=hlp)
        c.add_argument("prompt", nargs="?", help="текст запроса")
        c.add_argument("-f", "--file", action="append", help="приложить файл (можно несколько)")
        c.add_argument("-s", "--system", default="", help="системный промпт")
        c.add_argument("--stdin", action="store_true", help="дочитать запрос из stdin (pipe)")
        c.add_argument("--max-tokens", type=int, default=4096, dest="max_tokens")
        c.set_defaults(func=fn)

    rg = sub.add_parser("rag", help="своя RAG-коллекция")
    rsub = rg.add_subparsers(dest="rag_cmd", required=True)
    ri = rsub.add_parser("index", help="проиндексировать файлы")
    ri.add_argument("files", nargs="+")
    rs = rsub.add_parser("search", help="поиск по коллекции")
    rs.add_argument("query")
    rs.add_argument("--top-k", type=int, default=5, dest="top_k")
    rg.set_defaults(func=cmd_rag)

    sub.add_parser("usage", help="расход и квота").set_defaults(func=cmd_usage)
    sub.add_parser("whoami", help="кто я").set_defaults(func=cmd_whoami)
    sub.add_parser("logout", help="выйти").set_defaults(func=cmd_logout)
    ss = sub.add_parser("session", help="рабочая сессия (квота 5M ток/сессия)")
    ss.add_argument("session_cmd", nargs="?", choices=["new", "show"], default="show")
    ss.set_defaults(func=cmd_session)
    return p


# ─────────────────────── Интерактивный режим (REPL) ───────────────────────

_CODE_SYS = "Ты пишешь чистый production-код. Возвращай только запрошенное."


def _fmt_rem(n) -> str:
    if n is None:
        return "—"
    return (f"{n/1e6:.1f}M" if n >= 1e6 else f"{n/1e3:.0f}k" if n >= 1e3 else str(n))


# Морда обезьяны (ape) в стиле Донки Конга: массивная бровь, двухцветная —
# тёмный мех (DK) + светлая морда (TN) + акцент на глазах/носу/улыбке (FT).
_FUR = "\033[38;5;94m"    # тёмно-коричневый мех
_MUZ = "\033[38;5;180m"   # светлая морда (муцзл)
_FEAT = "\033[38;5;52m"   # почти чёрный — глаза/ноздри/улыбка
# каждая строка — список (текст, цвет). Все строки шириной 17.
_MONKEY = [
    [("   ▄▟▀▀▀▀▀▀▀▙▄   ", _FUR)],
    [("  ▟███████████▙  ", _FUR)],                                        # массивная бровь
    [(" ██▌ ", _FUR), ("◕", _FEAT), ("     ", _MUZ), ("◕", _FEAT), (" ▐██ ", _FUR)],
    [(" ██▌  ", _FUR), ("▗▄▄▄▖", _MUZ), ("  ▐██ ", _FUR)],                # верх морды
    [("  ▜█▖ ", _FUR), ("▼", _FEAT), ("   ", _MUZ), ("▼", _FEAT), (" ▗█▛  ", _FUR)],  # ноздри
    [("   ▜█▖", _FUR), ("╲___╱", _FEAT), ("▗█▛   ", _FUR)],               # улыбка
    [("    ▜██▄▄▄██▛    ", _FUR)],
]
# Крупные буквы APE (AI Product Engineer)
_APE = [
    "█▀█ █▀█ █▀▀",
    "█▀█ █▀▀ █▀▀",
    "▀ ▀ ▀   ▀▀▀",
]


def _banner() -> None:
    o, b = C["off"], C["bold"]
    cy2, g, dim = C["cy2"], C["gray"], C["dim"]
    print()
    for row in _MONKEY:
        line = "".join((seg if _ANSI else "") + txt + (o if _ANSI else "") for txt, seg in row)
        print(f"   {line}")
    print()
    for i, l in enumerate(_APE):
        gc = GRAD[min(i + 1, len(GRAD) - 1)]
        tail = "   AI Product Engineer" if i == 0 else "   CLI курса · engineer-ai.pro" if i == 1 else ""
        print(f"   {b}{gc}{l}{o}{g}{tail}{o}")
    who = _claims().get("preferred_username")
    print()
    if who:
        print(f"   {dim}вошёл как {cy2}{who}{dim} · память диалога включена · /help — команды{o}\n")
    else:
        print(f"   {C['yellow']}не вошёл — набери /login{o}\n")


_HELP = f"""  {C['bold']}Команды{C['off']} {C['dim']}(через /){C['off']}
    {C['cy']}/code{C['off']} <текст>    код на Qwen3.8-27B
    {C['cy']}/ask{C['off']}  <текст>    ресёрч / рассуждения на DeepSeek
    {C['cy']}/mode{C['off']} code|ask   сменить режим по умолчанию (для текста без /)
    {C['cy']}/skills{C['off']}          список скиллов, вкл/выкл (Y/N), активные видны при ответах
    {C['cy']}/rag{C['off']} search <q>  поиск по своей RAG-коллекции
    {C['cy']}/rag{C['off']} index <ф.>  проиндексировать файлы
    {C['cy']}/more{C['off']}            раскрыть последний ответ полностью
    {C['cy']}/save{C['off']} <файл>     сохранить на компьютер (.md/.py/… — код запишется без обвязки)
    {C['cy']}/save cloud{C['off']} <имя> загрузить в свой проект (портал → «Мой проект»)
    {C['cy']}/memory{C['off']}          показать, что агент помнит
    {C['cy']}/forget{C['off']}          очистить память этой сессии
    {C['cy']}/usage{C['off']}           расход и остаток квоты
    {C['cy']}/whoami{C['off']} {C['dim']}·{C['off']} {C['cy']}/login{C['off']} {C['dim']}·{C['off']} {C['cy']}/logout{C['off']} {C['dim']}·{C['off']} {C['cy']}/clear{C['off']} {C['dim']}·{C['off']} {C['cy']}/exit{C['off']}
  {C['dim']}Без / — запрос уходит в текущем режиме. Память копится и сжимается сама.{C['off']}"""


def _mk_getch():
    """Возвращает функцию чтения одной клавиши (спец. → 'UP'/'DOWN'), или None."""
    if os.name == "nt":
        try:
            import msvcrt
        except Exception:
            return None

        def getch():
            c = msvcrt.getwch()
            if c in ("\x00", "\xe0"):  # спец-клавиша: код во втором символе
                c2 = msvcrt.getwch()
                return {"H": "UP", "P": "DOWN", "K": "LEFT", "M": "RIGHT"}.get(c2, "")
            return c
        return getch
    # POSIX
    try:
        import termios, tty  # noqa: F401
    except Exception:
        return None

    def getch():
        import termios as _t, tty as _tty
        fd = sys.stdin.fileno()
        old = _t.tcgetattr(fd)
        try:
            _tty.setcbreak(fd)
            c = sys.stdin.read(1)
            if c == "\x1b":  # ESC-последовательность (стрелки)
                seq = sys.stdin.read(2)
                return {"[A": "UP", "[B": "DOWN", "[C": "RIGHT", "[D": "LEFT"}.get(seq, "")
            return c
        finally:
            _t.tcsetattr(fd, _t.TCSADRAIN, old)
    return getch


# Команды для выпадающего списка (после ввода "/")
_CMDS = [
    ("/code", "код на Qwen3.8-27B"),
    ("/ask", "ресёрч / рассуждения на DeepSeek"),
    ("/mode", "режим по умолчанию (code|ask)"),
    ("/skills", "скиллы: список, вкл/выкл"),
    ("/rag", "своя RAG-коллекция (search|index)"),
    ("/more", "раскрыть последний ответ полностью"),
    ("/save", "сохранить: /save <файл> (на комп) · /save cloud <имя> (в проект)"),
    ("/memory", "что агент помнит"),
    ("/forget", "очистить память сессии"),
    ("/usage", "расход и остаток квоты"),
    ("/whoami", "кто я"),
    ("/login", "вход через GitHub"),
    ("/logout", "выйти из аккаунта"),
    ("/clear", "очистить экран"),
    ("/help", "справка"),
    ("/exit", "выход"),
]


def _term_w() -> int:
    return max(40, shutil.get_terminal_size(fallback=(90, 24)).columns)


def _topbar(mode: str) -> str:
    o, cy, dim = C["off"], C["cy"], C["dim"]
    W = _term_w()
    title = f" {mode} "
    rem = f" осталось {_fmt_rem(LAST_REMAIN)} "
    fill = max(1, W - 4 - len(title) - len(rem))
    return f"{dim}╭─{cy}{title}{dim}{'─' * fill}{rem}─╮{o}"


def _matches(buf: str):
    if not buf.startswith("/"):
        return []
    return [c for c in _CMDS if c[0].startswith(buf.lower())] or []


def _read_input(mode: str) -> str:
    """Полноширинная строка ввода с выпадающим списком команд после '/'.
    Fallback на обычный input(), если raw-режим недоступен (пайп/неподдерж.)."""
    print(_topbar(mode))
    prompt = f"  {C['cy']}›{C['off']} "
    pvis = 4  # видимая длина "  › "
    getch = _mk_getch()
    if getch is None or not sys.stdin.isatty():
        try:
            return input(prompt)
        except EOFError:
            raise
    sys.stdout.write(prompt); sys.stdout.flush()
    buf = ""; sel = 0; drawn = 0

    def redraw():
        nonlocal drawn
        ms = _matches(buf)
        sys.stdout.write("\r\033[J")  # в начало строки + очистить всё ниже
        sys.stdout.write(prompt + buf)
        if ms:
            sys.stdout.write("\n")
            for i, (name, desc) in enumerate(ms[:8]):
                mark = "▸" if i == sel else " "
                if i == sel:
                    sys.stdout.write(f"  {C['cy']}{mark} {name:<9}{C['off']} {C['gray']}{desc}{C['off']}\n")
                else:
                    sys.stdout.write(f"  {C['dim']}{mark} {name:<9} {desc}{C['off']}\n")
            drawn = min(len(ms), 8)
            sys.stdout.write(f"\033[{drawn + 1}A")  # вернуть курсор на строку ввода
        else:
            drawn = 0
        sys.stdout.write(f"\r\033[{pvis + len(buf)}C")  # к концу набранного
        sys.stdout.flush()

    redraw()
    while True:
        ch = getch()
        if ch in ("\r", "\n"):
            ms = _matches(buf)
            # если открыт список — Enter выбирает подсвеченную команду; иначе отправляет как есть
            chosen = ms[min(sel, len(ms) - 1)][0] if ms else buf
            sys.stdout.write("\r\033[J\n"); sys.stdout.flush()
            return chosen
        if ch == "\x03":  # Ctrl+C
            sys.stdout.write("\r\033[J"); sys.stdout.flush()
            raise KeyboardInterrupt
        if ch in ("\x08", "\x7f"):  # Backspace
            buf = buf[:-1]; sel = 0; redraw(); continue
        if ch == "\t":  # Tab — докомплитить выбранную команду
            ms = _matches(buf)
            if ms:
                buf = ms[sel][0] + " "; sel = 0; redraw()
            continue
        if ch in ("UP", "DOWN"):
            ms = _matches(buf)
            if ms:
                sel = (sel + (1 if ch == "DOWN" else -1)) % min(len(ms), 8)
                redraw()
            continue
        if ch and ch >= " ":  # печатный символ
            buf += ch; sel = 0; redraw()


def _skills_menu() -> None:
    """Интерактивный список скиллов: ↑↓ выбор, Y вкл, N выкл, Enter/Space переключить, Q выход."""
    names = sorted(SKILLS.keys())
    active = set(skills_active())
    getch = _mk_getch()
    if getch is None or not sys.stdin.isatty():  # fallback без raw-режима
        print(col("  Скиллы (переключай: /skills on <имя> | /skills off <имя>):", "bold"))
        for n in names:
            mark = f"{C['green']}✓{C['off']}" if n in active else f"{C['dim']}·{C['off']}"
            print(f"   {mark} {n:<22} {C['dim']}{SKILLS[n][0]}{C['off']}")
        return
    sel = 0; N = len(names)

    def draw(first=False):
        if not first:
            sys.stdout.write(f"\033[{N + 1}A")
        sys.stdout.write("\r\033[J")
        print(f"  {C['bold']}Скиллы{C['off']} {C['dim']}· ↑↓ выбор · Y вкл · N выкл · Enter переключить · Q выход{C['off']}")
        for i, n in enumerate(names):
            on = n in active
            box = f"{C['green']}[✓]{C['off']}" if on else f"{C['dim']}[ ]{C['off']}"
            if i == sel:
                print(f"  {C['cy']}▸{C['off']} {box} {C['cy']}{n:<22}{C['off']}{C['gray']}{SKILLS[n][0]}{C['off']}")
            else:
                print(f"    {box} {C['dim']}{n:<22}{SKILLS[n][0]}{C['off']}")

    draw(first=True)
    while True:
        ch = getch()
        if ch in ("q", "Q", "\x1b", "\x03"):
            break
        elif ch == "UP":
            sel = (sel - 1) % N; draw()
        elif ch == "DOWN":
            sel = (sel + 1) % N; draw()
        elif ch in ("y", "Y"):
            active.add(names[sel]); draw()
        elif ch in ("n", "N"):
            active.discard(names[sel]); draw()
        elif ch in ("\r", "\n", " "):
            active.discard(names[sel]) if names[sel] in active else active.add(names[sel]); draw()
    skills_set(active)
    sys.stdout.write("\r\033[J")
    print(f"  {C['cy']}Активно скиллов: {len(active)}{f' · {chr(0x1F9E9)} ' + ', '.join(sorted(active)) if active else ''}{C['off']}")


def _repl() -> None:
    global LAST_REMAIN
    os.system("")  # активирует VT на некоторых Windows-консолях
    _banner()
    try:
        u = _mcp_call("my_usage", {"session_id": _session_id()})
        LAST_REMAIN = (u.get("week") or {}).get("remaining")
    except Exception:
        pass
    mode = "code"
    while True:
        try:
            line = _read_input(mode).strip()
        except EOFError:
            print(); break
        except KeyboardInterrupt:
            print(col("\n  (Ctrl+C) — для выхода набери /exit", "dim")); continue
        if not line:
            continue
        try:
            if line.startswith("/"):
                parts = line[1:].split(maxsplit=1)
                if not parts:
                    continue
                cmd = parts[0].lower()
                rest = parts[1].strip() if len(parts) > 1 else ""
                if cmd in ("exit", "quit", "q"):
                    print(col("  До связи!", "cy")); break
                elif cmd in ("help", "h", "?"):
                    print(_HELP)
                elif cmd == "clear":
                    os.system("cls" if os.name == "nt" else "clear"); _banner()
                elif cmd == "mode":
                    if rest in ("code", "ask"):
                        mode = rest; print(col(f"  режим по умолчанию: {mode}", "dim"))
                    else:
                        print(col("  /mode code  или  /mode ask", "gray"))
                elif cmd in ("code", "ask"):
                    prof = "code" if cmd == "code" else "research"
                    if rest:
                        _mem_turn(prof, rest)
                    else:
                        mode = cmd; print(col(f"  режим по умолчанию: {mode}", "dim"))
                elif cmd == "rag":
                    sp = rest.split(maxsplit=1)
                    if sp and sp[0] == "search" and len(sp) > 1:
                        cmd_rag(type("A", (), {"rag_cmd": "search", "query": sp[1], "top_k": 5}))
                    elif sp and sp[0] == "index" and len(sp) > 1:
                        cmd_rag(type("A", (), {"rag_cmd": "index", "files": sp[1].split()}))
                    else:
                        print(col("  /rag search <запрос>  или  /rag index <файлы>", "gray"))
                elif cmd == "skills":
                    sp = rest.split()
                    if not sp:
                        _skills_menu()
                    elif sp[0] == "on" and len(sp) > 1:
                        act = set(skills_active()) | {s for s in sp[1:] if s in SKILLS}
                        skills_set(act); print(col(f"  включено: {', '.join(sorted(act)) or '—'}", "cy"))
                    elif sp[0] == "off" and len(sp) > 1:
                        act = set(skills_active()) - set(sp[1:])
                        skills_set(act); print(col(f"  активно: {', '.join(sorted(act)) or '—'}", "cy"))
                    elif sp[0] == "clear":
                        skills_set([]); print(col("  все скиллы выключены", "cy"))
                    else:
                        print(col("  /skills — меню · /skills on <имя> · /skills off <имя> · /skills clear", "gray"))
                elif cmd == "memory":
                    m = mem_load()
                    if m.get("summary"):
                        print(col("  Сжато:", "dim")); print("  " + m["summary"].replace("\n", "\n  "))
                    print(col(f"  реплик в памяти: {len(m.get('turns', []))}", "dim"))
                elif cmd == "forget":
                    try:
                        os.remove(_mem_path())
                    except FileNotFoundError:
                        pass
                    print(col("  Память этой сессии очищена.", "cy"))
                elif cmd == "more":
                    if LAST_ANSWER:
                        print("\n".join(_colorize(LAST_ANSWER.split("\n"))))
                    else:
                        print(col("  Нечего раскрывать — сначала задай вопрос.", "gray"))
                elif cmd == "save":
                    do_save(rest)
                elif cmd == "usage":
                    cmd_usage(None)
                elif cmd == "whoami":
                    cmd_whoami(None)
                elif cmd == "login":
                    login("github")
                elif cmd == "logout":
                    cmd_logout(None)
                else:
                    print(col(f"  Неизвестная команда /{cmd}. /help — список.", "yellow"))
            else:
                _mem_turn("code" if mode == "code" else "research", line)
        except SystemExit as e:
            if isinstance(e.code, str):
                print(e.code)
        except KeyboardInterrupt:
            print(col("\n  прервано", "dim"))
        except Exception as e:  # noqa: BLE001 — REPL не должен падать целиком
            print(col(f"  Ошибка: {e}", "yellow"))


def _mem_turn(profile: str, prompt: str) -> None:
    """Один ход диалога с памятью: подмешиваем контекст, сохраняем ответ."""
    m = mem_load()
    base = _CODE_SYS if profile == "code" else ""
    mx = 8000 if profile == "research" else 4000  # research/исследования не режем
    text = _chat(profile, prompt, mem_system(base, m), mx)
    if text:
        mem_add(m, prompt, text)


def main():
    known = {"login", "code", "ask", "chat", "rag", "usage", "whoami", "logout",
             "session", "repl", "-h", "--help"}
    argv = sys.argv[1:]
    if not argv or argv[0] == "repl":
        return _repl()
    if argv[0] not in known:  # `ape "напиши функцию…"` → сразу код на Qwen
        return _chat("code", " ".join(argv),
                     "Ты пишешь чистый production-код. Возвращай только запрошенное.", 2048)
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
