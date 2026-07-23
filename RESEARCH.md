# RESEARCH.md — Разбор заявок

> Encyclopedia проекта. Читается ПОЛНОСТЬЮ (не grep) перед первой задачей в сессии.
> Источник: код перенесён из `../ТГ агент` (2026-07-23) под этот фреймворк — сам сценарий не менялся.

---

## Что делает система

ИИ-агент партнёрского отдела Альбато: когда сделка в amoCRM (воронка **Partners**) попадает на
этап **«Новый контакт»**, агент сам пишет клиенту (от личного Telegram-аккаунта Варвары, email —
fallback), получает ответ, классифицирует его через Claude на **positive / negative / ambiguous**,
переводит сделку на этап «Первичные переговоры» и ставит задачу на Варвару с нужным текстом.
Если клиент не отвечает — шлёт напоминание, потом закрывает сделку (этап «Блок»).

Полная бизнес-логика сценария (до кода) — в [`Логика ИИ агента.md`](./Логика%20ИИ%20агента.md).
Инструкция по настройке `.env` / первому запуску — в [`README.md`](./README.md).

---

## Архитектура

Один локальный Python-процесс (`main.py`), без вебхуков — amoCRM опрашивается поллингом.
Внутри — четыре независимых asyncio-задачи, сходящиеся в общем `core/state_machine.py`:

```
amo/poller.py ──┐                                   ┌── telegram_channel/sender.py
                 ├─→ core/state_machine.py ─────────┤
email_channel/  ─┘   (вся бизнес-логика переходов)   └── email_channel/sender.py
  poller.py                │
                            ├─→ classify/client.py (Claude tool_use → rule_based fallback)
core/scheduler.py ─────────┘   (напоминания по next_action_at)
                            │
                       db/repository.py (SQLite, data/app.db)
```

`core/state_machine.py` не зависит от канала (Telegram/email) — решает, что делать, и вызывает
`_send_via_channel`. Это единственное место с бизнес-правилами; каналы и amoCRM — только I/O.

### Ключевой инвариант

Один активный отслеживаемый диалог на клиента. После эскалации (`TERMINAL_ESCALATED_STATUSES` —
`ESCALATED_POSITIVE/NEGATIVE/AMBIGUOUS`) бот больше не реагирует на входящие по этой сделке —
`handle_incoming_reply` проверяет статус и выходит рано (`core/state_machine.py`).

---

## Ключевые файлы

| Path | Назначение |
|------|-----------|
| `main.py` | Точка входа: валидирует `.env`, поднимает Telegram-клиент, запускает 3-4 asyncio-задачи |
| `config.py` | `Settings` (dataclass из env), `validate()` — какие переменные обязательны |
| `core/state_machine.py` | ВСЯ бизнес-логика: `process_new_deal`, `process_scheduler_tick`, `handle_incoming_reply` |
| `core/checklist.py` | Чеклист целостности задачи (`assess`) — стек: минимум 2 сервиса (счёт по разделителям); кейс: описана проблема ИЛИ данные для обработки (Claude, фолбэк — длина строки) |
| `core/scheduler.py` | Тик шедулера (по умолчанию раз в 60с) → `process_scheduler_tick` |
| `core/templates.py` | Тексты клиенту/задач на Варвару; `FIRST_MESSAGE_VARIANTS` (анти-бан вариации); `first_message(..., missing_fields)` вставляет предупреждение о нехватке данных перед абзацем согласия на оплату |
| `core/timeutils.py` | Расчёт `next_action_at` (напоминания), таймзона `Europe/Moscow` |
| `db/models.py` | `Status` (state machine states), `Channel`, `ReplyCategory`, `Deal` dataclass |
| `db/repository.py` | SQLite-доступ: `get_deal`, `try_lock`/`unlock` (защита от гонок), `list_due_rows`, переходы статусов |
| `classify/client.py` | Классификация ответа клиента через Claude (`tool_use`, модель `claude-haiku-4-5`), фолбэк — `rule_based.py` |
| `classify/prompt.py` | System-промпт классификатора (3 категории, правила разрешения неоднозначности) |
| `classify/rule_based.py` | Классификация по ключевым словам, если `ANTHROPIC_API_KEY` не задан |
| `classify/faq.py` | База знаний (FAQ) — подбор ответа на ambiguous-вопрос через Claude (`match_faq_sync`), тексты — черновик, см. `docs/faq-knowledge-base.md` |
| `amo/client.py`, `amo/auth.py` | REST-клиент amoCRM (long-lived token ИЛИ OAuth c refresh) |
| `amo/actions.py` | `move_to_negotiations`, `move_to_blocked`, `create_manager_task` |
| `amo/poller.py` | Поллинг сделок на этапе «Новый контакт» (раз в `AMOCRM_POLL_INTERVAL_SECONDS`, по умолчанию 90с) |
| `telegram_channel/client.py` | Telethon-клиент (личный аккаунт), сессия — `data/telegram.session` |
| `telegram_channel/listener.py` | Регистрация обработчиков входящих сообщений |
| `telegram_channel/sender.py` | Отправка сообщений, `TelegramSendError` |
| `telegram_channel/ratelimit.py` | Анти-бан: задержки, `DAILY_TELEGRAM_SEND_CAP` (по умолчанию 40/день), обработка FloodWait/PeerFlood |
| `email_channel/poller.py`, `email_channel/sender.py` | IMAP-поллинг входящих / SMTP-отправка (fallback-канал) |

---

## Состояния сделки (`db/models.py: Status`)

```
NEW → AWAITING_REPLY_1 → AWAITING_REPLY_2 → CLOSED_NO_REPLY   (нет ответа → цепочка напоминаний → закрытие)
                    ↓ (входящий ответ в любой момент из AWAITING_*)
        ESCALATED_POSITIVE / ESCALATED_NEGATIVE / ESCALATED_AMBIGUOUS   (терминальные — бот больше не пишет)
FAILED  (нет ни Telegram username, ни email — сразу задача на Варвару)
```

Чеклист целостности (`core/checklist.py`) НЕ добавляет отдельное состояние и НЕ блокирует
отправку: `process_new_deal` всегда отправляет `FIRST_MESSAGE` и всегда переходит в
`AWAITING_REPLY_1` — если данных не хватает (меньше 2 сервисов в стеке, или в кейсе не описана
ни проблема, ни данные для обработки), в то же сообщение перед абзацем согласия на оплату
(маркер `❗️Важно`) вставляется предупреждение.

---

## Внешние зависимости и переменные окружения

Полный список — `.env.example`. Обязательные для старта (`config.py: Settings.validate`):
amoCRM base URL + pipeline/stage ID + custom field ID + Varvara user ID, Telegram API ID/hash/phone.
`ANTHROPIC_API_KEY` **не обязателен** — без него классификация уходит на `rule_based` (грубее).

| Система | Библиотека | Примечание |
|---------|-----------|-----------|
| amoCRM | `requests` | REST v4, long-lived token или OAuth (`amo/auth.py` сам обновляет access_token) |
| Telegram | `telethon` | MTProto, личный аккаунт (не Bot API) — риск бан, см. `ratelimit.py` |
| Claude | `anthropic` | `tools` + `tool_choice: {"type": "tool", ...}` — форсированная классификация |
| Email | стандартный `smtplib`/`imaplib` (через `email_channel/`) | fallback-канал, не обязателен для первого теста |
| БД | `sqlite3` (stdlib) | `data/app.db`, схема — `db/repository.py` |

---

## Тесты

`tests/` — pytest: `test_repository.py` (SQLite-репозиторий), `test_timeutils.py` (расчёт напоминаний),
`test_rule_based.py` (классификация по правилам), `test_templates.py` (вариации первого сообщения +
вставка предупреждения чеклиста), `test_checklist.py` (чеклист целостности, non-LLM фолбэк),
`test_faq.py` (FAQ — только non-LLM путь: без `ANTHROPIC_API_KEY` и `get_answer`), `conftest.py`
(фикстуры). Нет тестов на `state_machine.py`, `classify/client.py`/`classify/faq.py`/
`core/checklist.py` (LLM-путь) — в проекте нет `pytest-asyncio` (см. `requirements.txt`),
интеграционные точки покрыты только вручную (см. README «Проверка сценария»). Логика
`process_new_deal` (вставка предупреждения в сообщение) проверена ad-hoc smoke-скриптом при
разработке (2026-07-23, мокался telegram), не входит в `tests/`.

## Известные ограничения (из README оригинала)

- Без вебхуков — только поллинг amoCRM (90с) и шедулер (60с). Апгрейд на вебхуки возможен при переезде на VPS.
- Один активный диалог на клиента — конфликт при второй необработанной сделке уходит в ручную задачу.
- Личный Telegram-аккаунт для массовой переписки нарушает ToS Telegram — риск ограничений снижен
  анти-бан мерами, но не исключён полностью.

---

## Статус переноса под фреймворк (2026-07-23) — cutover выполнен

Код скопирован из `../ТГ агент` как есть — сценарий, поведение, `.env` не менялись. В `../ТГ агент`
на момент переноса были незакоммиченные изменения (`classify/rule_based.py` добавлен,
`classify/client.py` и `config.py` изменены, `tests/test_rule_based.py` добавлен) — они попали в
копию, т.к. копировались файлы с диска, не `git show HEAD`.

**Cutover (тот же день, 2026-07-23):** на момент переноса процесс `main.py` в `../ТГ агент` не был
запущен, и `data/` там не менялась с 2026-07-22 17:53 — типичного риска гонки/потери in-flight
состояния не было. `data/agent.log`, `data/app.db`, `data/telegram.session`,
`data/telegram.session-journal` перенесены (`mv`, не `copy`) из `../ТГ агент/data/` сюда —
единственный экземпляр Telegram-сессии и sqlite теперь здесь. `../ТГ агент/data/` — пустая папка,
её код-копия остаётся на диске, но **не является больше источником runtime-состояния**.

⚠️ **Нельзя запускать `main.py` из `../ТГ агент` больше** — там нет `data/`, а главное, если бы она
была восстановлена из бэкапа/копии, две параллельные Telegram MTProto-сессии на одном аккаунте
конфликтуют (logout друг друга / PeerFlood). Этот проект (`Разбор заявок`) — единственный, откуда
следует запускать бота.

**Решено (2026-07-23):** `../ТГ агент` остаётся как код-архив (не удаляется, не переименовывается).
В её `README.md` добавлена пометка ARCHIVED с указанием, что данные и дальнейшая разработка —
только в этом проекте.
