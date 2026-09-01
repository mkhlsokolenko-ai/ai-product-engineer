"""Portal DB: лекции, домашки, сдачи, оценки. Поверх того же пула, что MCP (server.db)."""
from __future__ import annotations

from server import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS lectures (
    id SERIAL PRIMARY KEY, week INT, block INT, title TEXT, topic TEXT,
    outcomes TEXT, skills TEXT, materials_url TEXT, position INT DEFAULT 0
);
-- Материалы, привязанные к конкретной лекции (много на лекцию). lecture_week = lectures.week.
CREATE TABLE IF NOT EXISTS lecture_materials (
    id SERIAL PRIMARY KEY, lecture_week INT NOT NULL, title TEXT, url TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lm_week ON lecture_materials (lecture_week);
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
-- Командный центр лектора --
CREATE TABLE IF NOT EXISTS partners (
    id SERIAL PRIMARY KEY, name TEXT, contact TEXT, email TEXT,
    status TEXT DEFAULT 'active', notes TEXT, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS calendar_events (
    id SERIAL PRIMARY KEY, week INT, date_label TEXT, title TEXT,
    type TEXT DEFAULT 'kt', created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS student_meta (
    student_id TEXT PRIMARY KEY, username TEXT, partner_id INT,
    risk_note TEXT, track_week INT, updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS lecturer_notes (
    lecturer_id TEXT PRIMARY KEY, body TEXT, updated_at TIMESTAMPTZ DEFAULT now()
);
"""

# Календарь курса по умолчанию (сеется, если таблица пуста). date_label пуст —
# API считает дату из COURSE_START_DATE. type: kt | guest | partner | final.
CALENDAR_SEED = [
    (1, "Старт курса · ДЗ-1: 5 идей", "kt"),
    (3, "ДЗ-2: выбранная идея + ADR", "kt"),
    (5, "ДЗ-3: дизайн-документ (MLSDD/Agent)", "kt"),
    (8, "Гость из индустрии (PdM)", "guest"),
    (10, "ДЗ-4: работающий MVP", "kt"),
    (13, "ДЗ-5: evals + unit-экономика", "kt"),
    (14, "Подготовка защиты · прожарка (grill-me)", "guest"),
    (15, "Финальная защита + комиссия", "final"),
]

# 15 недель × 5 блоков (структура из программы v0.5).
# Кортеж: week, block, title, topic, outcomes[], skills[], materials_url.
# Контент авторитетен из кода — ensure() синхронизирует его в БД (UPSERT по week).
LECTURES = [
    (1, 1, "Вводная: обвязка курса", "MCP-шлюз, лимиты, cost, RAG, портал — как всё устроено",
        ["Подключить OpenCode к курсовому MCP-шлюзу",
         "Понимать лимиты токенов, cost-журнал и правила хранилища",
         "Скопировать стартовые скиллы и сделать первый вызов"],
        ["conventional-commits"], "https://s3.engineer-ai.pro/materials/lecture1.pdf"),
    (2, 1, "Discovery и ICP", "ICP, JTBD, гипотеза ценности; интервью с представителем ICP",
        ["Сформулировать ICP и его боль",
         "Проверить гипотезу ценности в интервью",
         "Отделить реальную потребность от придуманной"],
        ["icp-interviewer", "jtbd-formulator"], ""),
    (3, 1, "Отбор идеи", "Глубинное исследование, оценка и выбор идеи; devil's advocate",
        ["Провести глубинное desk-исследование рынка",
         "Оценить идеи по рубрике и выбрать одну",
         "Пройти проверку «адвокатом дьявола»"],
        ["researcher", "idea-scorer", "idea-selector", "devils-advocate"], ""),
    (4, 2, "Workflow vs Agent", "Выбор архитектуры под задачу; границы агента",
        ["Выбирать между workflow, агентом и гибридом",
         "Задавать границы и зону ответственности агента"],
        ["architecture-chooser"], ""),
    (5, 2, "Дизайн-документ и ADR", "MLSDD / Agent Design Doc; решения в формате ADR",
        ["Написать MLSDD / Agent Design Doc по шаблону",
         "Фиксировать ключевые решения в формате ADR"],
        ["mlsdd-writer", "agent-design-writer", "adr-writer"], ""),
    (6, 2, "Prompt vs context engineering", "Хард-промпты, structured output; черновик cost-модели",
        ["Различать prompt- и context-engineering",
         "Надёжно получать structured output",
         "Сделать черновик cost-модели"],
        ["spec-reviewer", "cost-estimator"], ""),
    (7, 3, "Первый агент: TDD", "Спека → тесты до кода → первый tool/агент",
        ["Превратить спеку в тесты до кода",
         "Собрать первый tool/агент по TDD"],
        ["test-writer", "spec-reviewer"], ""),
    (8, 3, "Auth, latency, память", "Auth-схемы, контроль latency, двухуровневая память + дистилляция",
        ["Выбрать auth-схему и контролировать latency",
         "Спроектировать двухуровневую память с дистилляцией"],
        ["memory-architect"], ""),
    (9, 3, "RAG и безопасность", "RAG-pipeline (chunk/embed/rerank), prompt injection, threat model",
        ["Собрать RAG-pipeline: chunk / embed / rerank",
         "Построить threat model и защиту от prompt injection"],
        ["rag-architect"], ""),
    (10, 3, "Свой MCP-tool и observability", "Пишем свой инструмент; логи/метрики/трейсы",
        ["Написать собственный MCP-инструмент",
         "Настроить логи, метрики и трейсы агента"],
        ["fastapi-patterns", "docker-patterns"], ""),
    (11, 4, "Evals: три грейдера", "code / LLM-as-judge / human; метрики качества",
        ["Собрать eval-датасет из спеки",
         "Настроить грейдеры: code / LLM-judge / human"],
        ["eval-generator"], ""),
    (12, 4, "A/B промптов", "Версионирование промптов, прогон eval до/после",
        ["Версионировать промпты",
         "Гонять eval до/после и фиксировать метрику в ADR"],
        ["eval-generator", "adr-writer"], ""),
    (13, 4, "Реальные пользователи", "Фидбэк, unit-экономика, стоимость на пользователя",
        ["Собрать фидбэк реальных пользователей",
         "Посчитать unit-экономику и стоимость на пользователя"],
        ["unit-economics-checker", "cost-estimator"], ""),
    (14, 5, "Подготовка защиты", "Pitch, демо, прожарка (grill-me)",
        ["Собрать pitch и демо проекта",
         "Пройти жёсткую прожарку (grill-me) и закрыть слабые места"],
        ["grill-me"], ""),
    (15, 5, "Финальная защита", "Защита pet-проекта перед группой и комиссией",
        ["Защитить проект: демо + метрики + бизнес-модель",
         "Ответить комиссии по качеству и стоимости"],
        ["grill-me"], ""),
]

# Названия блоков — для заголовков карты курса.
BLOCK_NAMES = {
    1: "Discovery и продукт", 2: "Проектирование", 3: "Инженерия агента",
    4: "Оценка и экономика", 5: "Защита",
}

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
    """Создаёт таблицы, мигрирует колонки и синхронизирует лекции (контент из кода)."""
    async with db._conn() as c:  # noqa: SLF001
        await c.execute(SCHEMA)
        # миграция старой схемы lectures без outcomes/skills
        await c.execute("ALTER TABLE lectures ADD COLUMN IF NOT EXISTS outcomes TEXT")
        await c.execute("ALTER TABLE lectures ADD COLUMN IF NOT EXISTS skills TEXT")
        await c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_lectures_week ON lectures(week)")
        # UPSERT по неделе: код — источник правды для программы курса
        for wk, bl, t, tp, outs, sk, u in LECTURES:
            await c.execute(
                "INSERT INTO lectures(week,block,title,topic,outcomes,skills,materials_url,position) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(week) DO UPDATE SET block=EXCLUDED.block, title=EXCLUDED.title, "
                "topic=EXCLUDED.topic, outcomes=EXCLUDED.outcomes, skills=EXCLUDED.skills, "
                "materials_url=EXCLUDED.materials_url, position=EXCLUDED.position",
                (wk, bl, t, tp, "|".join(outs), ",".join(sk), u, wk))
        n = (await (await c.execute("SELECT COUNT(*) FROM assignments")).fetchone())[0]
        if n == 0:
            for wk, t, d, f, ms in ASSIGNMENTS:
                await c.execute(
                    "INSERT INTO assignments(week,title,description,fmt,max_score,position) "
                    "VALUES(%s,%s,%s,%s,%s,%s)", (wk, t, d, f, ms, wk))
        # миграция: перенести legacy materials_url лекций в lecture_materials (идемпотентно)
        legacy = await (await c.execute(
            "SELECT week, materials_url FROM lectures "
            "WHERE materials_url IS NOT NULL AND materials_url <> ''")).fetchall()
        for wk, url in legacy:
            exists = (await (await c.execute(
                "SELECT COUNT(*) FROM lecture_materials WHERE lecture_week=%s AND url=%s",
                (wk, url))).fetchone())[0]
            if not exists:
                title = url.rsplit("/", 1)[-1] or "Материалы"
                await c.execute(
                    "INSERT INTO lecture_materials(lecture_week,title,url) VALUES(%s,%s,%s)",
                    (wk, title, url))
        # сид календаря курса
        n = (await (await c.execute("SELECT COUNT(*) FROM calendar_events")).fetchone())[0]
        if n == 0:
            for wk, t, ty in CALENDAR_SEED:
                await c.execute(
                    "INSERT INTO calendar_events(week,date_label,title,type) VALUES(%s,'',%s,%s)",
                    (wk, t, ty))
