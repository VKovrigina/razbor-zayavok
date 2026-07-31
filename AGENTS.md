# AGENTS.md — Project Hub

> Хаб проекта (<200 строк). Агент читает это в начале каждой сессии.
> Навигация и ключевые факты — здесь; глубокий контент — в `RESEARCH.md`.

---

## Project Overview

**Name:** Разбор заявок
**Type:** Backend-агент (Python, asyncio), без UI
**Status:** Active — код и runtime-состояние (Telegram-сессия, sqlite) перенесены из `../ТГ агент`, cutover выполнен 2026-07-23
**Started:** 2026-07-23

**One-line description:** ИИ-агент amoCRM ↔ Telegram/Email для партнёрского отдела Альбато —
пишет клиенту при попадании сделки на этап «Новый контакт», классифицирует ответ через Claude
(positive/negative/ambiguous), ведёт напоминания и ставит задачи менеджеру.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3, asyncio |
| Telegram | telethon (личный аккаунт, MTProto) |
| CRM | amoCRM REST API v4 (`requests`) |
| Классификация | Anthropic Claude (`tools`/`tool_choice`), fallback — rule-based |
| Email fallback | smtplib/imaplib |
| БД | SQLite (`data/app.db`) |
| Testing | pytest |

---

## Architecture

**Pattern:** Монолит, один процесс, 3-4 параллельных asyncio-задачи, сходящиеся в
`core/state_machine.py` (канало-независимая бизнес-логика). Подробности, диаграмма, state machine
диаграмма состояний — в `RESEARCH.md`.

**Key decisions:** ADR пока не заводились (проект перенесён как есть) — см. `docs/adr/` для новых.

---

## Key Files & Directories

| Path | Purpose |
|------|---------|
| `main.py` | Точка входа, запуск asyncio-задач |
| `main_cases.py` | Точка входа сценария "Выдача кейсов партнёрам" — отдельный процесс (реализован 2026-07-31, P-058..P-061) |
| `cases/` | Модуль сценария "Выдача кейсов партнёрам": своя БД (`app_cases.db`), aiogram-бот, AmoCRM-поллер триггера, вторая telethon-сессия, передача контакта |
| `config.py` | Settings из `.env`, валидация обязательных переменных (`validate()` для `main.py`, `validate_cases()` для `main_cases.py`) |
| `core/` | Бизнес-логика: state machine, шедулер напоминаний, тексты, время |
| `classify/` | Классификация ответа клиента через Claude + rule-based fallback |
| `amo/` | amoCRM REST-клиент, действия (перевод этапа, задачи) |
| `telegram_channel/` | Telethon-клиент, отправка/приём, анти-бан rate limit |
| `email_channel/` | IMAP-поллинг / SMTP-отправка (fallback) |
| `db/` | SQLite repository + модели (`Status`, `Channel`, `ReplyCategory`, `Deal`) |
| `tests/` | pytest — repository, timeutils, rule_based |
| `data/` | Runtime state (создаётся при первом запуске) — сессия Telegram, sqlite, логи. **Не в git.** |
| `README.md` | Установка `.env`, первый запуск, проверка сценария |
| `Логика ИИ агента.md` | Исходное ТЗ сценария (до кода) |
| `RESEARCH.md` | Deep dive по архитектуре — читать полностью перед первой задачей |
| `tasks/` | Активные задачи (артефакты pipeline) |
| `docs/adr/` | Architecture Decision Records |

---

## Active Work

**Current focus:** перенос завершён (код + cutover runtime-состояния из `../ТГ агент`,
2026-07-23, см. `RESEARCH.md` → «Статус переноса»). Этот проект — единственный, откуда
запускается бот. Открыто: что делать с папкой `../ТГ агент` (архив/удалить/оставить) — решение
за пользователем.

**Recent decisions:** нет ADR ещё — первая реальная задача в этом проекте должна завести первую.

---

## Where to Find What

| Need | Look in |
|------|---------|
| Что делать дальше? | `BACKLOG.md` (Active Sprint) |
| Как устроена бизнес-логика? | `RESEARCH.md` |
| Исходное ТЗ сценария? | `Логика ИИ агента.md` |
| Как поднять локально? | `README.md` |
| Почему так решили? | `docs/adr/` |
| Что было сделано? | `CHANGELOG.md` + `BACKLOG.md` (Recent History) |
| Правила работы агента? | `CLAUDE.md` (проектные) + `~/.claude/CLAUDE.md` (глобальные) |
| Какие skills доступны? | `.claude/skills/` |
| Как работает pipeline? | `WORKFLOW.md` |

---

## Conventions

### Git
- Репозиторий пока не инициализирован в этой папке (код скопирован, не смигрирован с историей).
- Branches: `feat/`, `fix/`, `refactor/`, `docs/`
- Commits: conventional commits

### Code
- Python, `from __future__ import annotations`, dataclasses, type hints — как в перенесённом коде
- Тесты — pytest, см. `tests/`
- Секреты — только `.env` (не коммитить), `.gitignore` уже настроен под `data/*.db`, `*.session`, `.venv/`

### Process
- Pipeline: `WORKFLOW.md` (7 этапов)
- multi-agent: выключен (`.claude/project-config.yml`) — один агент делает всё

---

## Project-Specific Rules

- Это единственный проект с "боевым" runtime-состоянием (сессия Telegram, sqlite, `.env`) — cutover
  из `../ТГ агент` выполнен 2026-07-23. **Не запускать `main.py` из `../ТГ агент`** — там больше
  нет `data/`, а параллельная Telegram-сессия на том же аккаунте конфликтует с этой.
- **Сценарий "Выдача кейсов партнёрам"** (было спланировано как отдельный проект
  `../Выдача кейсов к группу` — встроено сюда вторым независимым процессом, реализовано
  2026-07-31, P-058..P-061): entrypoint `main_cases.py` — свой aiogram-бот (только публикация
  кейса и обработка клика «Беру», НЕ шлёт сообщения в разделе передачи контакта), свой AmoCRM-
  поллер триггера, своя **вторая** telethon-сессия того же аккаунта (`TELEGRAM_CASES_SESSION_PATH`,
  не конфликтует с сессией `main.py` — это два разных "устройства" одного номера, авторизована
  2026-07-31). Полностью независим от `main.py` в рантайме — не запускается из одного процесса с
  ним, своя БД (`data/app_cases.db`, отдельно от `app.db`), координация только через уже
  существующие в этом проекте amoCRM-теги/поля/этапы (`set_channel_tag`, `set_full_spec_field`,
  `AMOCRM_STAGE_TAKEN_BY_PARTNER_ID`), никакого прямого вызова между процессами. Полный сценарий —
  см. `Логика ИИ агента.md` → «Выдача кейса партнёрам». Планирование велось в
  `../Выдача кейсов к группу` (superseded, реализация полностью здесь).

---

## Glossary

| Term | Meaning |
|------|---------|
| Сделка (deal) | Lead в amoCRM, воронка Partners |
| Варвара | Менеджер партнёрского отдела — от её личного Telegram-аккаунта агент пишет клиентам |
| Эскалация | Перевод сделки в терминальный статус (`ESCALATED_*`) — бот прекращает автоответы, дальше работает человек |
| Cutover | Переключение "боевого" runtime-состояния с `../ТГ агент` на этот проект (пока не выполнено) |
