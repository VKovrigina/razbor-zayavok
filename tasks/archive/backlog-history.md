# Backlog — архив истории

> Записи из `BACKLOG.md` → «Recent History», уехавшие за пределы последних 10.

| ID | Title | Done | PR | Artifacts | ADR |
|----|-------|------|----|-----------| ----|
| P-009 | Повторные попытки блокировки во входящих (не терять сообщение клиента при занятой сделке) | 2026-07-24 | — | `core/state_machine.py`, `Логика ИИ агента.md` | — |
| P-006 | Цепочка напоминаний: race-check, guard по реальному этапу CRM, этап «Молчание», FAQ-подбор (3 пункта) без немедленной эскалации | 2026-07-23 | — | `core/state_machine.py`, `db/repository.py`, `amo/actions.py`, `amo/client.py`, `classify/faq.py`, `core/templates.py`, `config.py`, `Логика ИИ агента.md`, `.env` | — |
| P-004 | Новые этапы CRM (Уточнение ТЗ, Ручная проверка) + примечание с ТЗ при positive-ответе | 2026-07-23 | — | `core/state_machine.py`, `amo/actions.py`, `amo/client.py`, `core/templates.py`, `config.py`, `Логика ИИ агента.md`, `.env` | — |
| P-002 | Вариации первого сообщения (анти-бан) + FAQ-база (черновик) + чеклист целостности задачи | 2026-07-23 | — | `core/templates.py`, `classify/faq.py`, `core/checklist.py`, `docs/faq-knowledge-base.md`, тесты | — |
| P-001 | Cutover: перенос `data/` (сессия Telegram, sqlite, логи) из `../ТГ агент` — этот проект теперь единственный источник runtime-состояния | 2026-07-23 | — | `RESEARCH.md` | — |
| P-000 | Перенос кода из `../ТГ агент` под этот фреймворк | 2026-07-23 | — | `RESEARCH.md`, `AGENTS.md` | — |
