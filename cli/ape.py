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
import secrets
import ssl
import sys
import threading
import time
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

C = {"gray": "\033[90m", "blue": "\033[38;5;99m", "green": "\033[32m",
     "yellow": "\033[33m", "red": "\033[31m", "bold": "\033[1m", "off": "\033[0m"}
if os.name == "nt" and not os.environ.get("WT_SESSION"):
    C = {k: "" for k in C}  # старый cmd.exe без ANSI


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
        frame = _SPIN[i % len(_SPIN)] if os.environ.get("WT_SESSION") else "|/-\\"[i % 4]
        sys.stdout.write(col(f"\r  {frame} {phrase}… {now - start:4.1f}s", "blue") + " " * 6)
        sys.stdout.flush(); i += 1; time.sleep(0.1)
    th.join()
    sys.stdout.write("\r" + " " * 60 + "\r"); sys.stdout.flush()
    if "err" in box:
        raise box["err"]
    return box.get("res"), time.time() - start


def _chat(profile: str, prompt: str, system: str, max_tokens: int) -> None:
    label = {"code": "Qwen3.8-27B", "research": "DeepSeek", "standard": "каскад"}.get(profile, profile)
    print(col(f"  → {label}", "gray"), file=sys.stderr)
    out = _spin_call("chat", {"prompt": prompt, "session_id": _session_id(),
                              "profile": profile, "system": system, "max_tokens": max_tokens})
    res, elapsed = out if isinstance(out, tuple) else (out, None)
    if res.get("error"):
        print(col(res.get("message", res["error"]), "yellow")); return
    print(res.get("text", ""))
    q = (res.get("quota") or {}).get("week", {})
    used, o = res.get("input_tokens", 0), res.get("output_tokens", 0)
    tail = f"{res.get('model','?')} · {used}+{o} ток"
    if elapsed is not None:
        tail += f" · {elapsed:.1f}s"
    tail += f" · {res.get('cost_rub',0):.3f}₽"
    if q:
        tail += f" · осталось {q.get('remaining',0):,}".replace(",", " ")
    print(col(tail, "gray"), file=sys.stderr)


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
        c.add_argument("--max-tokens", type=int, default=2048, dest="max_tokens")
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

def _banner() -> None:
    a, o, b, g = C["blue"], C["off"], C["bold"], C["gray"]
    logo = [
        "        ▲        ",
        "       ╱ ╲       ",
        "      ╱   ╲      ",
        "     ╱─────╲     ",
        "    ◦       ◦    ",
    ]
    who = _claims().get("preferred_username")
    right = [
        f"{b}ape{o}{a} · CLI курса AI Product Engineer",
        f"{g}engineer-ai.pro{o}",
        "",
        f"{g}Пиши запрос и Enter → код на Qwen3.8-27B.{o}",
        f"{g}/ask <текст> — ресёрч (DeepSeek) · /help · /exit{o}",
    ]
    print()
    for i, l in enumerate(logo):
        r = right[i] if i < len(right) else ""
        print(f"  {a}{l}{o}  {r}")
    if who:
        print(f"  {g}вошёл как {who}. Команды — через / (напиши /help){o}")
    else:
        print(f"  {C['yellow']}не вошёл — набери /login{o}")
    print()


_HELP = """  Команды (через /):
    /code <текст>    код на Qwen3.8-27B
    /ask  <текст>    ресёрч/рассуждения на DeepSeek
    /rag search <q>  поиск по своей RAG-коллекции
    /rag index <ф.>  проиндексировать файлы
    /usage           расход и остаток квоты
    /whoami          кто я
    /login /logout   вход / выход
    /clear           очистить экран
    /help            эта справка
    /exit  (или Ctrl+C дважды)  выход
  Без / — запрос уходит на Qwen (код). Пиши прямо в строке."""


def _repl() -> None:
    _banner()
    while True:
        try:
            line = input(col("ape ▸ ", "blue")).strip()
        except EOFError:
            print(); break
        except KeyboardInterrupt:
            print(col("\n  (Ctrl+C) — для выхода набери /exit", "gray")); continue
        if not line:
            continue
        try:
            if line.startswith("/"):
                parts = line[1:].split(maxsplit=1)
                cmd = (parts[0] or "").lower()
                rest = parts[1].strip() if len(parts) > 1 else ""
                if cmd in ("exit", "quit", "q"):
                    print(col("  Пока!", "gray")); break
                elif cmd in ("help", "h", "?"):
                    print(_HELP)
                elif cmd == "clear":
                    os.system("cls" if os.name == "nt" else "clear"); _banner()
                elif cmd == "code":
                    if rest:
                        _chat("code", rest, "Ты пишешь чистый production-код. Возвращай только запрошенное.", 2048)
                    else:
                        print(col("  Пример: /code напиши функцию быстрой сортировки", "gray"))
                elif cmd == "ask":
                    if rest:
                        _chat("research", rest, "", 2048)
                    else:
                        print(col("  Пример: /ask когда RAG лучше дообучения?", "gray"))
                elif cmd == "rag":
                    sp = rest.split(maxsplit=1)
                    if sp and sp[0] == "search" and len(sp) > 1:
                        cmd_rag(type("A", (), {"rag_cmd": "search", "query": sp[1], "top_k": 5}))
                    elif sp and sp[0] == "index" and len(sp) > 1:
                        cmd_rag(type("A", (), {"rag_cmd": "index", "files": sp[1].split()}))
                    else:
                        print(col("  /rag search <запрос>  или  /rag index <файлы>", "gray"))
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
                _chat("code", line, "Ты пишешь чистый production-код. Возвращай только запрошенное.", 2048)
        except SystemExit as e:
            msg = e.code if isinstance(e.code, str) else None
            if msg:
                print(msg)
        except KeyboardInterrupt:
            print(col("\n  прервано", "gray"))
        except Exception as e:  # noqa: BLE001 — REPL не должен падать целиком
            print(col(f"  Ошибка: {e}", "yellow"))


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
