"""Portal DB: лекции, домашки, сдачи, оценки. Поверх того же пула, что MCP (server.db)."""
from __future__ import annotations

from server import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS lectures (
    id SERIAL PRIMARY KEY, week INT, block INT, title TEXT, topic TEXT,
    materials_url TEXT, position INT DEFAULT 0
);
CREATE TABLE IF NOT EXISTS assignments (
    id SERIAL PRIMARY KEY, week INT, title TEXT, description TEXT,
    fmt TEXT, max_score INT DEFAULT 10, position INT DEFAULT 0
);
CREATE TABLE IF NOT EXISTS submissions (
    id SERIAL PRIMARY KEY, student_id TEXT, username TEXT, assignment_id INT,
    url TEXT, note TEXT, status TEXT DEFAULT 'submitted',
    submitted_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(student_id, assignment_id)
);
CREATE TABLE IF NOT EXISTS grades (
    id SERIAL PRIMARY KEY, student_id TEXT, username TEXT, assignment_id INT,
    score NUMERIC, feedback TEXT, graded_by TEXT, graded_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(student_id, assignment_id)
);
CREATE TABLE IF NOT EXISTS announcements (
    id SERIAL PRIMARY KEY, title TEXT, body TEXT, created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS projects (
    student_id TEXT PRIMARY KEY, username TEXT, repo_url TEXT, description TEXT,
    status TEXT DEFAULT 'idea', updated_at TIMESTAMPTZ DEFAULT now()
);
"""

# 15 недель × 5 блоков (структура из программы v0.5)
LECTURES = [
    (1, 1, "Вводная: обвязка курса", "MCP-шлюз, лимиты, cost, RAG, портал — как всё устроено", ""),
    (2, 1, "Discovery и ICP", "ICP, JTBD, гипотеза ценности; интервью с представителем ICP", ""),
    (3, 1, "Отбор идеи", "Глубинное исследование, оценка и выбор идеи; devil's advocate", ""),
    (4, 2, "Workflow vs Agent", "Выбор архитектуры под задачу; границы агента", ""),
    (5, 2, "Дизайн-документ и ADR", "MLSDD / Agent Design Doc; решения в формате ADR", ""),
    (6, 2, "Prompt vs context engineering", "Хард-промпты, structured output; черновик cost-модели", ""),
    (7, 3, "Первый агент: TDD", "Спека → тесты до кода → первый tool/агент", ""),
    (8, 3, "Auth, latency, память", "Auth-схемы, контроль latency, двухуровневая память + дистилляция", ""),
    (9, 3, "RAG и безопасность", "RAG-pipeline (chunk/embed/rerank), prompt injection, threat model", ""),
    (10, 3, "Свой MCP-tool и observability", "Пишем свой инструмент; логи/метрики/трейсы", ""),
    (11, 4, "Evals: три грейдера", "code / LLM-as-judge / human; метрики качества", ""),
    (12, 4, "A/B промптов", "Версионирование промптов, прогон eval до/после", ""),
    (13, 4, "Реальные пользователи", "Фидбэк, unit-экономика, стоимость на пользователя", ""),
    (14, 5, "Подготовка защиты", "Pitch, демо, прожарка (grill-me)", ""),
    (15, 5, "Финальная защита", "Защита pet-проекта перед группой и комиссией", ""),
]

# fmt: repo|md|pr
ASSIGNMENTS = [
    (1, "ДЗ-1: 5 идей проекта", "5 проработанных идей в формате .md, применив глубинное исследование "
        "(мин. 4 ч). В каждой: боль+ICP+JTBD, данные, выполнимость, черновик экономики.", "md", 10),
    (3, "ДЗ-2: выбранная идея", "research.md по выбранной идее + ADR обоснования выбора (через idea-selector).", "md", 10),
    (5, "ДЗ-3: дизайн-документ", "MLSDD или Agent Design Doc по шаблону + 2–3 ADR ключевых решений.", "md", 15),
    (10, "ДЗ-4: работающий MVP", "Репозиторий с работающим MVP: тесты, MCP/RAG, cost в журнале.", "repo", 20),
    (13, "ДЗ-5: evals + экономика", "Eval-датасет + метрики (Recall@K/judge) + unit-экономика на 1 стр.", "repo", 15),
    (15, "Защита проекта", "Финальная защита: демо + метрики + бизнес-модель.", "pr", 30),
]


async def ensure() -> None:
    """Создаёт таблицы и засевает лекции/домашки при первом запуске."""
    async with db._conn() as c:  # noqa: SLF001
        await c.execute(SCHEMA)
        n = (await (await c.execute("SELECT COUNT(*) FROM lectures")).fetchone())[0]
        if n == 0:
            for wk, bl, t, tp, u in LECTURES:
                await c.execute(
                    "INSERT INTO lectures(week,block,title,topic,materials_url,position) "
                    "VALUES(%s,%s,%s,%s,%s,%s)", (wk, bl, t, tp, u, wk))
        n = (await (await c.execute("SELECT COUNT(*) FROM assignments")).fetchone())[0]
        if n == 0:
            for wk, t, d, f, ms in ASSIGNMENTS:
                await c.execute(
                    "INSERT INTO assignments(week,title,description,fmt,max_score,position) "
                    "VALUES(%s,%s,%s,%s,%s,%s)", (wk, t, d, f, ms, wk))
