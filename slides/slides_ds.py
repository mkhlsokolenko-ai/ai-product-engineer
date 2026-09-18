# -*- coding: utf-8 -*-
"""Дизайн-система слайдов курса (портал red-team.tech) — общий модуль для новых деков.

Та же палитра/типографика, что в корневом build_slides.py (Лекция 1), но here — сборка
деков С НУЛЯ (без реколора исходника) + новые примитивы: схемы (flow), таблицы trade-off,
decision-строки, блоки «как в ape». Используется build_lectures.py.

Шрифты для точного рендера: Geist + JetBrains Mono (поставить на машину-презентер).
"""
from __future__ import annotations

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

# ── токены DS (1-в-1 с build_slides.py) ──
BG0 = RGBColor(0x0B, 0x0F, 0x14)
PANEL = RGBColor(0x12, 0x18, 0x21)
RAISED = RGBColor(0x1A, 0x22, 0x2E)
TXT1 = RGBColor(0xE6, 0xED, 0xF3)
TXT2 = RGBColor(0x8B, 0x98, 0xA5)
TXT3 = RGBColor(0x5C, 0x69, 0x75)
ACCENT = RGBColor(0x5B, 0x8C, 0xFF)
GOOD = RGBColor(0x3F, 0xB9, 0x50)   # «лучше / так надо»
CRIT = RGBColor(0xFF, 0x4D, 0x4F)   # «хуже / антипаттерн»
WARN = RGBColor(0xE3, 0xB3, 0x41)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BORDER = RGBColor(0x1F, 0x2A, 0x3A)
UI = "Geist"
MONO = "JetBrains Mono"


# ── низкоуровневые примитивы ──
def _tb(s, l, t, w, h):
    b = s.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    b.text_frame.word_wrap = True
    return b.text_frame


def run(p, text, size, color, bold=False, font=UI):
    r = p.add_run()
    r.text = text
    f = r.font
    f.name = font
    f.size = Pt(size)
    f.bold = bold
    f.color.rgb = color
    return r


def line(s, l, t, w, h, text, size, color, bold=False, align=PP_ALIGN.LEFT, font=UI):
    tf = _tb(s, l, t, w, h)
    p = tf.paragraphs[0]
    p.alignment = align
    run(p, text, size, color, bold, font)
    return tf


def para(tf, space=4):
    p = tf.add_paragraph()
    p.space_after = Pt(space)
    return p


def card(s, l, t, w, h, fill=PANEL, border=None):
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(l), Inches(t), Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    sh.shadow.inherit = False
    if border:
        sh.line.color.rgb = border
        sh.line.width = Pt(1)
    else:
        sh.line.fill.background()
    return sh


def lbl(s, l, t, w, text, color=ACCENT):
    line(s, l, t, w, 0.3, text.upper(), 10.5, color, bold=True, font=MONO)


def bullets(s, l, t, w, h, items, acc=ACCENT, size=11.5, gap=9, marker="› ", color=TXT1):
    """Список с маркером-акцентом. items: str | (bold_head, tail)."""
    tf = _tb(s, l, t, w, h)
    for i, it in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else para(tf, gap)
        run(p, marker, size + 0.5, acc, bold=True, font=MONO)
        if isinstance(it, tuple):
            run(p, it[0] + " — ", size, acc, bold=True)
            run(p, it[1], size, TXT2)
        else:
            run(p, it, size, color)
    return tf


def chip(s, l, t, w, text, fill=RAISED, color=ACCENT, h=0.42):
    sh = card(s, l, t, w, h, fill=fill)
    line(s, l, t + 0.07, w, 0.3, text, 11, color, bold=True, align=PP_ALIGN.CENTER, font=MONO)
    return sh


# ── схемы ──
def flow(s, t, boxes, l=0.6, total_w=12.13, h=1.0, arrow="→", box_fill=PANEL,
         head_color=ACCENT, note_color=TXT2):
    """Горизонтальная цепочка box'ов со стрелками между ними.
    boxes: list of (head, note). Рисует N карточек + (N-1) стрелок.
    """
    n = len(boxes)
    aw = 0.5                      # ширина зоны стрелки
    bw = (total_w - aw * (n - 1)) / n
    x = l
    for i, (head, note) in enumerate(boxes):
        card(s, x, t, bw, h, fill=box_fill, border=BORDER)
        line(s, x + 0.15, t + 0.14, bw - 0.3, 0.4, head, 12, head_color, bold=True, align=PP_ALIGN.CENTER)
        if note:
            line(s, x + 0.15, t + 0.52, bw - 0.3, h - 0.6, note, 9.5, note_color, align=PP_ALIGN.CENTER)
        x += bw
        if i < n - 1:
            line(s, x, t + h / 2 - 0.22, aw, 0.44, arrow, 20, TXT3, align=PP_ALIGN.CENTER)
            x += aw


def formula(s, t, parts, l=0.6, total_w=12.13, h=1.15):
    """Схема-формула: [часть]  →  [часть]  →  [часть] с подписями.
    parts: list of (label, value).
    """
    flow(s, t, [(v, lab) for lab, v in parts], l=l, total_w=total_w, h=h,
         head_color=TXT1, note_color=ACCENT)


def compare_table(s, l, t, w, h, headers, rows, col_widths=None,
                  head_fill=RAISED, head_colors=None, zebra=(PANEL, BG0)):
    """Таблица сравнения. headers: [str]. rows: [[str,...]].
    head_colors: цвет текста заголовков по колонкам (для «лучше/хуже» — GOOD/CRIT).
    """
    ncol = len(headers)
    nrow = len(rows) + 1
    gf = s.shapes.add_table(nrow, ncol, Inches(l), Inches(t), Inches(w), Inches(h))
    tbl = gf.table
    tbl.first_row = False
    tbl.horz_banding = False
    if col_widths:
        for i, cw in enumerate(col_widths):
            tbl.columns[i].width = Inches(cw)
    for c in range(ncol):
        cell = tbl.cell(0, c)
        cell.fill.solid()
        cell.fill.fore_color.rgb = head_fill
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.margin_top = Pt(3); cell.margin_bottom = Pt(3)
        cell.margin_left = Pt(8); cell.margin_right = Pt(8)
        tf = cell.text_frame; tf.word_wrap = True
        p = tf.paragraphs[0]; p.alignment = PP_ALIGN.LEFT
        hc = (head_colors[c] if head_colors else ACCENT)
        run(p, headers[c], 11.5, hc, bold=True, font=MONO)
    for r, rowdata in enumerate(rows, start=1):
        for c in range(ncol):
            cell = tbl.cell(r, c)
            cell.fill.solid()
            cell.fill.fore_color.rgb = zebra[(r - 1) % 2]
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.margin_top = Pt(3); cell.margin_bottom = Pt(3)
            cell.margin_left = Pt(8); cell.margin_right = Pt(8)
            tf = cell.text_frame; tf.word_wrap = True
            p = tf.paragraphs[0]; p.alignment = PP_ALIGN.LEFT
            txt = rowdata[c]
            col = TXT1 if c == 0 else TXT2
            bold = (c == 0)
            run(p, txt, 10.5, col, bold=bold)
    return tbl


def pros_cons(s, t, good_head, good_items, bad_head, bad_items, l=0.6, total_w=12.13, h=3.9):
    """Две колонки: слева «лучше/так надо» (зелёный акцент), справа «хуже/антипаттерн» (красный)."""
    gap = 0.25
    cw = (total_w - gap) / 2
    card(s, l, t, cw, h, fill=PANEL, border=BORDER)
    line(s, l + 0.28, t + 0.22, cw - 0.5, 0.4, "✓ " + good_head.upper(), 11.5, GOOD, bold=True, font=MONO)
    bullets(s, l + 0.28, t + 0.82, cw - 0.55, h - 1.0, good_items, acc=GOOD, gap=10)
    x2 = l + cw + gap
    card(s, x2, t, cw, h, fill=PANEL, border=BORDER)
    line(s, x2 + 0.28, t + 0.22, cw - 0.5, 0.4, "✗ " + bad_head.upper(), 11.5, CRIT, bold=True, font=MONO)
    bullets(s, x2 + 0.28, t + 0.82, cw - 0.55, h - 1.0, bad_items, acc=CRIT, gap=10)


def ape_box(s, l, t, w, h, title, lines, fill=RGBColor(0x0E, 0x14, 0x1C)):
    """Тёмный «терминальный» блок с примером команд ape (mono)."""
    card(s, l, t, w, h, fill=fill, border=BORDER)
    line(s, l + 0.28, t + 0.2, w - 0.5, 0.3, title, 10.5, ACCENT, bold=True, font=MONO)
    tf = _tb(s, l + 0.28, t + 0.66, w - 0.55, h - 0.85)
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else para(tf, 6)
        if ln.startswith("#"):
            run(p, ln, 10.5, TXT3, font=MONO)          # комментарий
        elif ln.startswith("$") or ln.startswith("ape") or ln.startswith("/"):
            run(p, ln, 11, TXT1, bold=True, font=MONO)  # команда
        else:
            run(p, ln, 10.5, TXT2, font=MONO)           # вывод/пояснение


# ── каркас дека ──
class Deck:
    def __init__(self, kicker, title, subtitle, meta):
        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)
        self.prs = prs
        self.blank = prs.slide_layouts[6]
        self.page = 0
        self._cover(kicker, title, subtitle, meta)

    def _new(self):
        s = self.prs.slides.add_slide(self.blank)
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = BG0
        return s

    def _cover(self, kicker, title, subtitle, meta):
        s = self._new()
        card(s, 0.0, 3.05, 0.12, 1.7, fill=ACCENT)   # акцент-полоса
        line(s, 0.75, 1.4, 11.8, 0.4, kicker.upper(), 13, ACCENT, bold=True, font=MONO)
        line(s, 0.7, 3.0, 12.0, 1.6, title, 40, TXT1, bold=True)
        line(s, 0.75, 4.75, 11.5, 0.9, subtitle, 15, TXT2)
        line(s, 0.75, 6.7, 8.0, 0.3, "engineer-ai.pro", 10, ACCENT, font=MONO)
        line(s, 8.5, 6.7, 4.15, 0.3, meta, 10, TXT3, align=PP_ALIGN.RIGHT, font=MONO)

    def section(self, num, title):
        s = self._new()
        line(s, 0.75, 2.9, 3.0, 1.2, num, 66, RGBColor(0x22, 0x2C, 0x3A), bold=True, font=MONO)
        card(s, 0.8, 4.15, 0.9, 0.08, fill=ACCENT)
        line(s, 0.75, 4.4, 11.8, 1.0, title, 30, TXT1, bold=True)
        return s

    def content(self, title, subtitle=""):
        self.page += 1
        s = self._new()
        line(s, 0.6, 0.45, 12.1, 0.65, title, 26, TXT1, bold=True)
        if subtitle:
            line(s, 0.6, 1.28, 12.1, 0.6, subtitle, 13, TXT2)
        line(s, 0.6, 7.12, 9.0, 0.28, "engineer-ai.pro", 9, ACCENT, font=MONO)
        line(s, 9.9, 7.12, 2.7, 0.28, "AI Product Engineer", 8.5, TXT3, align=PP_ALIGN.RIGHT)
        line(s, 12.6, 7.12, 0.55, 0.28, str(self.page), 9, TXT3, align=PP_ALIGN.RIGHT, font=MONO)
        return s

    def save(self, path):
        try:
            self.prs.save(path)
        except PermissionError:
            path = path.replace(".pptx", "_new.pptx")
            self.prs.save(path)
        return path
