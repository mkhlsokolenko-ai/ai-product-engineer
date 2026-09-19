"""Модуль «Граф агента» (GraphLens) — визуальная сборка потока агента (палитра→холст→инспектор).
Пока предпросмотр раскладки по макету; интерактивный холст — отдельный заход. UI-only.
"""
from __future__ import annotations
from fastapi import APIRouter

MANIFEST = {"id": "graphlens", "title": "Граф", "icon": "graphlens", "ui": "graphlens", "order": 30}
router = APIRouter()
