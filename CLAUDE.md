# CLAUDE.md — Разбор заявок

> Проектная специфика. Универсальные правила процесса — в `~/.claude/CLAUDE.md`, здесь не дублируются.

## Контекст проекта

- Стек: Python (asyncio), telethon (Telegram, личный аккаунт), requests (AmoCRM REST), anthropic (Claude)
- Архитектура: см. `AGENTS.md` и `RESEARCH.md` — один процесс, 3-4 asyncio-задачи, бизнес-логика в `core/state_machine.py`
- Multi-agent orchestration: выключена, один агент делает всё (`.claude/project-config.yml`)
- Происхождение: код и runtime-состояние перенесены из `../ТГ агент` (2026-07-23, cutover выполнен) под этот pipeline-фреймворк, сценарий не менялся
- Референс: [`../ТГ агент`](../ТГ%20агент) — исходный код-архив, БЕЗ данных, decommissioned; [`../Выдача кейсов к группу`](../Выдача%20кейсов%20к%20группу) — похожие amoCRM-паттерны

## Правила проекта

- Секреты (`TELEGRAM_API_HASH`, `AMOCRM_ACCESS_TOKEN`, `ANTHROPIC_API_KEY` и т.д.) — только в `.env`,
  никогда в код или коммиты.
- `data/` (telegram.session, app.db, логи) — единственный живой экземпляр, перенесён из
  `../ТГ агент` при cutover. Не коммитить, не удалять, не восстанавливать копию в `../ТГ агент`.
- **Не запускать `main.py` из `../ТГ агент`** — параллельная Telegram-сессия того же аккаунта
  конфликтует с этой (см. `RESEARCH.md` → «Статус переноса»).
- **Любое изменение логики агента (`core/state_machine.py`, `core/checklist.py`,
  `core/templates.py`, ветвление classify/FAQ) — синхронизировать с [`Логика ИИ агента.md`](./Логика%20ИИ%20агента.md)
  в том же ответе.** Это живое ТЗ-описание сценария для человека (не код) — должно всегда
  соответствовать реальному поведению кода, а не отставать от него.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
