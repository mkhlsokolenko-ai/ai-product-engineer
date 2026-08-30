# Стартовый набор скиллов

Раздаётся студентам в неделю 1 как `.opencode/skills/` (или эквивалент для их клиента).
Скилл = папка с `SKILL.md` (frontmatter `name` + `description`, дальше — инструкция агенту).

## Discovery и продуктовое мышление
- **researcher** — направленное desk-исследование (рынок, данные, конкуренты).
- **icp-interviewer** — симулирует представителя ICP, прожимает гипотезу ценности.
- **jtbd-formulator** — формулирует Job To Be Done.
- **idea-scorer** — оценивает одну идею по рубрике.
- **idea-selector** — сравнивает и отбирает лучшую из нескольких.
- **devils-advocate** — жёсткая критика идеи без похвалы.

## Дисциплина проектирования
- **mlsdd-writer** — ML System Design Doc по шаблону Reliable ML.
- **agent-design-writer** — дизайн агента (границы, инструменты, память, деградация).
- **architecture-chooser** — workflow vs agent vs hybrid.
- **rag-architect** — проектирование RAG-pipeline.
- **memory-architect** — двухуровневая память с дистилляцией.

## Инженерная дисциплина
- **adr-writer** — ADR в формате Nygard.
- **spec-reviewer** — полнота acceptance-критериев.
- **test-writer** — тесты ДО реализации (TDD).
- **eval-generator** — eval-датасет + грейдеры (code / LLM-judge / human).
- **grill-me** — безжалостный допрос по плану/дизайну/защите.

## Бизнес-контур
- **cost-estimator** — стоимость user-flow по токенам и тарифам.
- **unit-economics-checker** — unit-экономика на дыры.

## Переиспользовано из sLAVA (generic, под «Build»)
- **conventional-commits** — дисциплина коммитов.
- **fastapi-patterns** — паттерны FastAPI-сервисов.
- **docker-patterns** — паттерны Docker.

> В sLAVA (`~/Desktop/slAVA/.claude/skills`) есть ещё `claude-security-review`,
> `rag-engineer`, `devsecops-practices`, `verify-claude-setup` — подтянуть по мере
> надобности (напр. security-review к неделе 9 про threat model / prompt injection).
