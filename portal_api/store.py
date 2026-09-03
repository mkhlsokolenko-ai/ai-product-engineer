"""Portal DB: лекции, домашки, сдачи, оценки. Поверх того же пула, что MCP (server.db)."""
from __future__ import annotations

from server import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS lectures (
    id SERIAL PRIMARY KEY, code TEXT, week INT, seq INT DEFAULT 1, block INT, title TEXT, topic TEXT,
    outcomes TEXT, skills TEXT, materials_url TEXT, practice TEXT, position INT DEFAULT 0,
    scheduled_at DATE, status TEXT DEFAULT 'planned'
);
-- Исходящая очередь уведомлений: её дренирует Telegram-бот (пока — зеркалятся в announcements).
CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY, kind TEXT, title TEXT, body TEXT, payload TEXT,
    status TEXT DEFAULT 'pending', created_by TEXT, created_at TIMESTAMPTZ DEFAULT now(),
    sent_at TIMESTAMPTZ
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

# Программа v0.6: 15 недель × 5 блоков, 2–3 лекции в неделю (по сессиям программы).
# Кортеж: code, week, seq, block, title, topic, outcomes[], skills[].
# code — стабильный ключ (ensure() делает UPSERT по code, сохраняя дату/статус лектора).
# Материалы/ДЗ привязаны к КАЛЕНДАРНОЙ неделе (week); материал lecture1.pdf уже в lecture_materials.
LECTURES = [
    # ── Блок 1. Discovery + ICP + выбор архитектуры (нед. 1–3) ──
    ("w1l1", 1, 1, 1, "Кто такой Product Engineer + setup",
        "Роль PE и связь с FDE, 4 контура курса, живое демо MVP за 45 минут в OpenCode",
        ["Понимать роль Product Engineer и отличие от full-stack/PM",
         "Увидеть скорость AI-native разработки на живом демо"],
        []),
    ("w1l2", 1, 2, 1, "Setup-марафон: окружение курса",
        "OpenCode → MCP-шлюз, JWT от Keycloak, репо ai-pe-{фамилия}, первый вызов с cost",
        ["Подключить OpenCode к курсовому MCP-шлюзу по JWT",
         "Собрать структуру репо и сделать первый вызов с cost в кабинете"],
        ["conventional-commits"]),
    ("w2l1", 2, 1, 1, "JTBD, ICP и шорт-лист идей",
        "JTBD-формула, ICP-канва на 1 страницу, антипаттерны; воркшоп по своей идее",
        ["Сформулировать ICP конкретного человека, а не «всех»",
         "Написать JTBD без тавтологии и собрать шорт-лист из 3 идей"],
        ["icp-interviewer", "jtbd-formulator"]),
    ("w2l2", 2, 2, 1, "Reverse JTBD на реальных продуктах",
        "Разбор Cursor / Perplexity / Granola / NotebookLM / Replit — восстановление ICP и JTBD",
        ["Восстановить ICP и JTBD существующих AI-продуктов",
         "Отделить реальную потребность от придуманной"],
        ["jtbd-formulator"]),
    ("w3l1", 3, 1, 1, "AI-native discovery",
        "Симулированные интервью, конкурентный анализ, эхо-камера и адвокат дьявола",
        ["Провести AI-симуляцию интервью как подготовку к живому",
         "Избежать эхо-камеры через hard prompts и devil's advocate"],
        ["icp-interviewer", "devils-advocate", "researcher"]),
    ("w3l2", 3, 2, 1, "Выбор архитектуры: workflow vs agent",
        "Decision tree по 5 критериям; выбор и обоснование архитектуры pet-проекта",
        ["Выбирать между workflow, агентом и гибридом по 5 критериям",
         "Оценить идеи по рубрике и выбрать одну"],
        ["architecture-chooser", "idea-scorer", "idea-selector"]),
    ("w3l3", 3, 3, 1, "Speed-dating защита + КТ1",
        "5-минутная защита идеи + архитектурного решения, вопросы группы и эксперта",
        ["Защитить идею за 5 минут: ICP, JTBD, архитектура",
         "Пройти вопросы лектора и внешнего эксперта"],
        []),
    # ── Блок 2. MLSDD / Agent Design + Cost model (нед. 4–6) ──
    ("w4l1", 4, 1, 2, "Design-doc: MLSDD или Agent Design",
        "Выбор шаблона под архитектуру, структура документа, первая версия на паре",
        ["Выбрать MLSDD vs Agent Design под своё решение",
         "Заполнить минимум 4 раздела содержательно, с цифрами"],
        ["mlsdd-writer", "agent-design-writer"]),
    ("w5l1", 5, 1, 2, "ADR в формате Nygard",
        "Context · Decision · Alternatives · Consequences; ADR как код архитектурных решений",
        ["Писать ADR в формате Nygard с ≥2 альтернативами",
         "Фиксировать ключевые решения по мере проектирования"],
        ["adr-writer"]),
    ("w5l2", 5, 2, 2, "Cost-of-AI ADR",
        "Cascade, prompt caching, расчёт стоимости в рублях, per-user cost на 3 уровнях нагрузки",
        ["Посчитать per-user cost и сценарии на 100/1000/10000",
         "Выбрать cascade с обоснованием в рублях"],
        ["cost-estimator"]),
    ("w6l1", 6, 1, 2, "Анатомия агента + prompt vs context engineering",
        "Agent core/loop/tools/memory, hard prompt, structured output, отбор контекста",
        ["Различать prompt- и context-engineering",
         "Описать анатомию своего агента и надёжно получать structured output"],
        ["spec-reviewer"]),
    ("w6l2", 6, 2, 2, "Hard prompts + КТ2",
        "Переписываем system prompt по чеклисту; защита design-doc + ADR + анатомии агента",
        ["Написать hard prompt с явными запретами и edge cases",
         "Защитить дизайн-документ и cost-ADR за 7 минут"],
        []),
    # ── Блок 3. Build + Controls (нед. 7–10) ──
    ("w7l1", 7, 1, 3, "TDD до кода",
        "Тесты ДО реализации по acceptance из спеки, защита от overfit на тесты",
        ["Превратить acceptance-критерии в тесты до кода",
         "Понимать, как не переобучиться на собственные тесты"],
        ["test-writer"]),
    ("w7l2", 7, 2, 3, "Subagent-разделение: тест / код / ревью",
        "TDD-цикл с тремя ролями subagent-ов (A пишет тесты, B код, C ревьюит спеку)",
        ["Пройти TDD-цикл с тремя subagent-ролями",
         "Реализовать первую фичу MVP через тесты"],
        ["spec-reviewer"]),
    ("w8l1", 8, 1, 3, "Границы системы + auth-схемы",
        "Что контролируем (API/БД/контракты/sandbox), auth-ландшафт (API-key/OAuth/OIDC/JWT/mTLS)",
        ["Определить границы pet-проекта: что контролируем, что отдаём агенту",
         "Выбрать auth-схему и понимать trust chain курсовой инфры"],
        []),
    ("w8l2", 8, 2, 3, "Память агента: короткая, долгая, дистилляция",
        "Двухуровневая память, триггер по токенам, reference implementation memory_manager.py",
        ["Спроектировать двухуровневую память с дистилляцией",
         "Адаптировать reference-код под свой домен"],
        ["memory-architect"]),
    ("w8l3", 8, 3, 3, "Latency и cost controls",
        "Rate-limit, prompt caching, fallback chain, streaming; замер latency p95",
        ["Внедрить cost/latency-контроли в pet-проект",
         "Замерить latency-профиль и зафиксировать в ADR"],
        ["cost-estimator"]),
    ("w9l1", 9, 1, 3, "MCP и свой первый tool",
        "MCP в деталях, function calling vs MCP, пишем собственный tool для FastMCP",
        ["Написать собственный MCP-инструмент",
         "Выбирать между function calling и MCP осознанно"],
        ["fastapi-patterns", "docker-patterns"]),
    ("w9l2", 9, 2, 3, "Безопасность агента: prompt injection + threat model",
        "Trust boundaries, whitelist tools, human-in-the-loop, threat model на 5 строк",
        ["Построить threat model для каждого tool",
         "Защитить агента от prompt injection тремя способами"],
        []),
    ("w9l3", 9, 3, 3, "RAG-pipeline, фреймворки, протоколы",
        "Chunk/embed/retrieve/rerank, landscape фреймворков, inter-service протоколы",
        ["Собрать базовый RAG-pipeline и осознанно выбрать chunking/embedding",
         "Осознанно решить, нужен ли фреймворк (ADR)"],
        ["rag-architect"]),
    ("w10l1", 10, 1, 3, "Observability: logs / metrics / traces",
        "Три сигнала наблюдаемости, что показывать на защите, где смотреть в кабинете",
        ["Читать logs / metrics / traces и объяснять сигналы",
         "Понимать, какой сигнал отвечает на какой вопрос"],
        []),
    ("w10l2", 10, 2, 3, "Sprint review — КТ3",
        "Live demo MVP, метрики (latency p95, cost/request), проекция на 10/100/1000 юзеров",
        ["Защитить работающий MVP с метриками и cost-проекцией",
         "Показать, что контролируешь построчно, а что отдал агенту"],
        ["grill-me"]),
    # ── Блок 4. Evals + Unit economics + Real users (нед. 11–13) ──
    ("w11l1", 11, 1, 4, "Data-driven quality: три грейдера",
        "code / LLM-as-judge / human, когда какой; RAG-специфичные метрики",
        ["Выбрать грейдеры под свою задачу (минимум 2 из 3)",
         "Понимать, зачем нужна human-выборка для калибровки"],
        ["eval-generator"]),
    ("w11l2", 11, 2, 4, "Eval-датасет и прогон + prompt versioning",
        "30–50 примеров, прогон по 2 cascade, метрики, версионирование промптов",
        ["Собрать eval-датасет и посчитать метрики",
         "Версионировать промпты и выбрать cascade по цифрам (ADR)"],
        ["eval-generator", "adr-writer"]),
    ("w12l1", 12, 1, 4, "Unit economics целиком",
        "CAC, ARPU, gross margin с AI-costs, payback; marginal cost ≠ 0; бизнес-модель на 1 стр",
        ["Собрать бизнес-модель на одну страницу с sensitivity-анализом",
         "Посчитать unit-экономику с учётом переменной стоимости AI"],
        ["unit-economics-checker", "cost-estimator"]),
    ("w13l1", 13, 1, 4, "Тестирование на реальных пользователях",
        "Раздать MVP 3–5 людям из ICP, собрать фидбэк, метрики, готовность платить, реальный cost",
        ["Собрать качественный фидбэк реальных пользователей",
         "Замерить реальную unit-экономику вместо модельной"],
        ["unit-economics-checker"]),
    ("w13l2", 13, 2, 4, "КТ4: цифры с пользователями",
        "Защита: 2 подтверждённые + 2 опровергнутые гипотезы, реальная экономика, план на финал",
        ["Защитить выводы реального тестирования",
         "Показать, что меняешь на финале и почему"],
        ["grill-me"]),
    # ── Блок 5. Pitch + Ship (нед. 14–15) ──
    ("w14l1", 14, 1, 5, "Питч инвесторам: структура Y Combinator",
        "10 слайдов YC, чем питч отличается от демо, специфика AI-продуктов; сборка дека",
        ["Собрать питч-дек по YC-структуре из материалов курса",
         "Связать каждый слайд с артефактом, накопленным за курс"],
        []),
    ("w14l2", 14, 2, 5, "Отработка устного питча",
        "3 минуты + неудобные вопросы инвесткомитета, запись и разбор себя, pitch-critic",
        ["Уложить устный питч в 3 минуты",
         "Пройти прожарку и закрыть 3 слабых места"],
        ["grill-me"]),
    ("w15l1", 15, 1, 5, "Финальная защита",
        "Инвестиционный питч + техническая сессия перед комиссией (лектор + 2 эксперта)",
        ["Защитить проект: демо + метрики + бизнес-модель",
         "Ответить комиссии по качеству, стоимости и достоверности"],
        ["grill-me"]),
]

# Названия блоков — для заголовков карты курса.
BLOCK_NAMES = {
    1: "Discovery и продукт", 2: "Проектирование", 3: "Инженерия агента",
    4: "Оценка и экономика", 5: "Защита",
}

# Мини-задания «к следующей паре» — практика, НЕ оценка/КТ. Для недель без формального ДЗ.
PRACTICE = {
    2: "Проведи одно интервью с представителем ICP через icp-interviewer. Выпиши 3 неожиданных инсайта и одну боль, которую раньше недооценивал.",
    4: "Для своей идеи реши: workflow, agent или гибрид (через architecture-chooser). Обоснуй выбор в 5 строк и назови границы агента.",
    6: "Возьми один свой промпт и перепиши его как спецификацию со structured output (JSON-схема). Сравни ответ до и после.",
    7: "Выбери одну функцию проекта: напиши тесты ДО кода (TDD), затем реализуй так, чтобы они прошли. Приложи ссылку на коммит.",
    8: "Набросай схему памяти агента: что держим в системном промпте, что в контексте, что дистиллируем. Прикинь бюджет latency на один шаг.",
    9: "Собери мини-RAG на 5 своих документах, померь recall@3 на 5 вопросах. Отметь одно место, уязвимое к prompt injection.",
    11: "Составь eval-набор на 10 кейсов: для каждого укажи тип грейдера (code / LLM-judge / human) и ожидаемый результат.",
    12: "Сделай A/B двух версий одного промпта на своём eval-наборе. Зафиксируй метрику до/после в ADR.",
    14: "Прогони свою защиту через grill-me. Выпиши 3 слабых места и план, как закрыть каждое до финала.",
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
        await c.execute("ALTER TABLE lectures ADD COLUMN IF NOT EXISTS practice TEXT")
        await c.execute("ALTER TABLE lectures ADD COLUMN IF NOT EXISTS scheduled_at DATE")
        await c.execute("ALTER TABLE lectures ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'planned'")
        await c.execute("ALTER TABLE lectures ADD COLUMN IF NOT EXISTS code TEXT")
        await c.execute("ALTER TABLE lectures ADD COLUMN IF NOT EXISTS seq INT DEFAULT 1")
        # Переход на ключ по code: неделя больше НЕ уникальна (2–3 лекции/нед по программе v0.6).
        await c.execute("DROP INDEX IF EXISTS ux_lectures_week")
        # Одноразовая чистка строк старого сида (1 лекция = 1 неделя, без code).
        await c.execute("DELETE FROM lectures WHERE code IS NULL")
        await c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_lectures_code ON lectures(code)")
        # Сид программы — ТОЛЬКО в пустую таблицу: дальше планом владеет лектор (CRUD в портале),
        # правки/добавления не перезатираются при рестарте.
        have = (await (await c.execute("SELECT COUNT(*) FROM lectures")).fetchone())[0]
        if have == 0:
            last_seq: dict[int, int] = {}
            for _, wk, seq, *_ in LECTURES:
                last_seq[wk] = max(last_seq.get(wk, 0), seq)
            for pos, (code, wk, seq, bl, t, tp, outs, sk) in enumerate(LECTURES, 1):
                practice = PRACTICE.get(wk, "") if seq == last_seq[wk] else ""
                await c.execute(
                    "INSERT INTO lectures(code,week,seq,block,title,topic,outcomes,skills,practice,position) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (code, wk, seq, bl, t, tp, "|".join(outs), ",".join(sk), practice, pos))
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
