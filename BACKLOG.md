# Backlog

> Единый источник правды для всех задач проекта.
> Обновляется на этапах 1 (TASK) и 7 (MERGE) каждой задачи.

---

## Active Sprint / Current Focus

> Что делается прямо сейчас. Максимум 3-5 задач IN_PROGRESS одновременно.

| ID | Title | Status | Priority | Owner | Started |
|----|-------|--------|----------|-------|---------|
| P-003 | Заполнить реальные факты в `docs/faq-knowledge-base.md` (цены/сроки/условия тарифа) для оставшихся 5 пунктов (`faq_albato_tariff`, `faq_free_estimate`, `faq_can_decline_after_estimate`, `faq_payment_timing`, `faq_multiple_services`), перенести в `classify/faq.py` | `BLOCKED` (ждёт пользователя; 3 из 8 пунктов уже заполнены и включены) | P0 | — | 2026-07-23 |
| P-005 | Вписать реальный `ANTHROPIC_API_KEY` в `.env` — сейчас пуст, вся классификация/чеклисты работают на грубых фолбэках без LLM (см. `RESEARCH.md`) | `BACKLOG` (пользователь пока не чинит, "анализируй сам сообщения") | P0 | — | 2026-07-23 |

---

## Backlog (TODO)

> Приоритезированный список задач. Сортировка: P0 → P1 → P2.

### P0 — Critical (блокирует release)

| ID | Title | Description | Effort | ADR? |
|----|-------|-------------|--------|------|
| | | | S/M/L/XL | yes/no |

### P1 — High (важно для следующего release)

| ID | Title | Description | Effort | ADR? |
|----|-------|-------------|--------|------|
| | | | | |

### P2 — Medium (nice to have)

| ID | Title | Description | Effort | ADR? |
|----|-------|-------------|--------|------|
| | | | | |

### P3 — Low (когда будет время)

| ID | Title | Description | Effort | ADR? |
|----|-------|-------------|--------|------|
| | | | | |

---

## Recent History (последние 10 завершённых)

> Краткое описание последних завершённых задач со ссылками на артефакты.
> Старше 10 — переезжает в `tasks/archive/`.

| ID | Title | Done | PR | Artifacts | ADR |
|----|-------|------|----|-----------| ----|
| P-006 | Цепочка напоминаний: race-check, guard по реальному этапу CRM, этап «Молчание», FAQ-подбор (3 пункта) без немедленной эскалации | 2026-07-23 | — | `core/state_machine.py`, `db/repository.py`, `amo/actions.py`, `amo/client.py`, `classify/faq.py`, `core/templates.py`, `config.py`, `Логика ИИ агента.md`, `.env` | — |
| P-004 | Новые этапы CRM (Уточнение ТЗ, Ручная проверка) + примечание с ТЗ при positive-ответе | 2026-07-23 | — | `core/state_machine.py`, `amo/actions.py`, `amo/client.py`, `core/templates.py`, `config.py`, `Логика ИИ агента.md`, `.env` | — |
| P-002 | Вариации первого сообщения (анти-бан) + FAQ-база (черновик) + чеклист целостности задачи | 2026-07-23 | — | `core/templates.py`, `classify/faq.py`, `core/checklist.py`, `docs/faq-knowledge-base.md`, тесты | — |
| P-001 | Cutover: перенос `data/` (сессия Telegram, sqlite, логи) из `../ТГ агент` — этот проект теперь единственный источник runtime-состояния | 2026-07-23 | — | `RESEARCH.md` | — |
| P-000 | Перенос кода из `../ТГ агент` под этот фреймворк | 2026-07-23 | — | `RESEARCH.md`, `AGENTS.md` | — |

---

## Task Groups

> Группировка задач по эпикам. Каждая группа имеет общую цель.

### Group: {Name}

**Goal:** что хотим достичь

**Tasks:**
- [x] G-001: ...
- [x] G-002: ...
- [ ] G-003: ...
- [ ] G-004: ...

**Status:** 2/4 done

---

## Status Legend

| Status | Meaning |
|--------|---------|
| `BACKLOG` | В очереди, не начата |
| `IN_PROGRESS` | В работе сейчас |
| `BLOCKED` | Заблокирована (указать чем) |
| `IN_REVIEW` | На code review |
| `IN_TESTING` | На тестировании |
| `DONE` | Завершена и смержена |
| `CANCELLED` | Отменена (указать причину) |
