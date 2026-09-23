"""Транзакционная почта APE через UniOne HTTP-API (порт 443 — SMTP на Timeweb заблокирован).

us1.unione.io геоблокирует RU-IP (403). Поэтому при заданном settings.unione_proxy
(socks5h://mail-tunnel:1080) запрос идёт через SOCKS сквозь не-RU бокс — как в red-team.
Без ключа — dev-режим: письмо не шлётся, код печатается в лог (НЕ возвращается клиенту).

Брендовый OTP-шаблон (dark, table-based, email-safe) под AI Product Engineer.
"""
from __future__ import annotations

import httpx

from server.config import settings

_BG, _CARD, _ACCENT = "#0B1020", "#121936", "#6366F1"
_TEXT, _BODYTX, _MUTED, _BORDER = "#F8FAFC", "#C7CEDB", "#8A93A8", "#26305A"


def email_enabled() -> bool:
    return bool(settings.unione_api_key)


def _wrap(title: str, body: str, preheader: str = "") -> str:
    """Брендовый HTML-конверт письма APE (dark glass, indigo, email-safe таблицами)."""
    pre = (f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{preheader}</div>'
           if preheader else "")
    logo = (
        f'<span style="display:inline-block;width:11px;height:11px;border:2px solid {_ACCENT};'
        f'border-radius:3px;transform:rotate(45deg);vertical-align:middle;margin-right:9px"></span>'
        f'<span style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-weight:700;'
        f'font-size:17px;color:{_TEXT};vertical-align:middle">AI Product '
        f'<span style="color:{_ACCENT}">Engineer</span></span>')
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark"><title>{title}</title></head>
<body style="margin:0;padding:0;background:{_BG};-webkit-text-size-adjust:100%">{pre}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_BG}">
<tr><td align="center" style="padding:32px 16px">
  <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%">
    <tr><td style="padding:0 4px 22px">{logo}</td></tr>
    <tr><td style="background:{_CARD};border:1px solid {_BORDER};border-radius:16px;padding:30px 28px">
      <h1 style="margin:0 0 14px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:21px;font-weight:600;color:{_TEXT}">{title}</h1>
      <div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.65;color:{_BODYTX}">{body}</div>
    </td></tr>
    <tr><td style="padding:20px 6px 0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:12px;line-height:1.7;color:#5A6178">
      <b style="color:#7A8298">AI Product Engineer</b> — курс по инженерии ИИ-продуктов<br>
      <span style="color:#464C60">Если письмо пришло по ошибке — просто проигнорируйте его.</span>
    </td></tr>
  </table>
</td></tr></table></body></html>"""


def send(to: str, subject: str, html: str, reply_to: str | None = None) -> dict:
    """Отправить письмо через UniOne HTTP-API. Возвращает {sent, dev?}."""
    if not settings.unione_api_key:
        return {"sent": False, "dev": True}
    msg = {
        "recipients": [{"email": to}],
        "subject": subject,
        "from_email": settings.mail_from,
        "from_name": settings.mail_from_name,
        "body": {"html": html},
        "track_links": 0, "track_read": 0,
    }
    if reply_to:
        msg["reply_to"] = reply_to
    url = settings.unione_api_url.rstrip("/") + "/en/transactional/api/v1/email/send.json"
    headers = {"X-API-KEY": settings.unione_api_key, "Content-Type": "application/json"}
    # us1 геоблокирует RU-IP → при заданном unione_proxy идём через SOCKS сквозь не-RU бокс
    with httpx.Client(timeout=20, proxy=settings.unione_proxy or None) as c:
        r = c.post(url, json={"message": msg}, headers=headers)
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        data = {}
    # UniOne кладёт реальную причину в message/code — не теряем её за generic «400»
    if r.status_code != 200 or data.get("status") != "success":
        reason = data.get("message") or r.text[:200] or f"HTTP {r.status_code}"
        raise RuntimeError(reason)
    return {"sent": True}


def send_login_code(email: str, code: str, ttl_min: int = 10) -> dict:
    """OTP-код входа для менеджера."""
    body = (
        f"Ваш код для входа в личный кабинет:<br><br>"
        f"<div style='text-align:center;margin:6px 0 4px'>"
        f"<span style='display:inline-block;background:#0B1020;border:1px solid {_BORDER};"
        f"border-radius:12px;padding:14px 26px;color:#fff;font-size:30px;letter-spacing:8px;"
        f"font-weight:700;font-family:\"SF Mono\",Consolas,monospace'>{code}</span></div><br>"
        f"Код действует {ttl_min} минут и вводится один раз. "
        f"Если вы не запрашивали вход — просто проигнорируйте письмо."
    )
    html = _wrap("Код для входа", body, preheader=f"Ваш код входа: {code} (действует {ttl_min} мин)")
    return send(email, f"{code} — код входа · AI Product Engineer", html)
