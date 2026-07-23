# RESEARCH.md — Разбор заявок

> Encyclopedia проекта. Читается ПОЛНОСТЬЮ (не grep) перед первой задачей в сессии.
> Источник: код перенесён из `../ТГ агент` (2026-07-23) под этот фреймворк — сам сценарий не менялся.

---

## ⚠️ ANTHROPIC_API_KEY пуст (обнаружено 2026-07-23)

`ANTHROPIC_API_KEY=` в `.env` — без значения. Пользователь подтвердил: не чинить сейчас
(«анализируй пока сам сообщения» — 2026-07-23), работаем на фолбэках. Это значит, что ВСЕ
LLM-зависимые функции сейчас реально работают на грубых non-LLM фолбэках, не на Claude:

| Функция | Фолбэк без ключа |
|---------|------------------|
| `classify/client.py: classify_sync` | `classify/rule_based.py` — классификация по ключевым словам |
| `core/checklist.py: _case_describes_problem_or_data` | эвристика: длина текста ≥ 15 символов |
| `core/checklist.py: assess_topic` | keyword-детект темы (см. `_detect_topic_by_keywords`) + "спросить все критерии темы", БЕЗ анализа, что уже написано в тексте — так и должно быть по дизайну fallback'а, но это НЕ то же самое, что реальный семантический анализ |
| `classify/faq.py: match_faq_sync` | нет rule-based фолбэка вовсе — без ключа функция всегда возвращает `None` (ни один FAQ не подбирается), даже с `FAQ_ENABLED=True` |

Проверено вручную (2026-07-23): `assess_topic` с реальным описанием, где 3 из 5 пунктов темы
tilda_iiko уже отвечены клиентом, всё равно вернул все 5 как недостающие — это ожидаемое
поведение фолбэка (не бага промпта), т.к. фолбэк не читает текст семантически. Как только ключ
появится — поведение станет точным (проверено отдельно на реальных примерах до того, как
выяснилось, что ключ пуст: LLM-путь корректно распознавал темы и недостающие пункты).

**Что это значит для оператора (Варвары):** пока ключа нет, стоит вручную перепроверять
классификацию ambiguous/positive/negative и тематические уточняющие вопросы у реальных
клиентов — они могут быть менее точными, чем ожидается по промптам.

---

## Что делает система

ИИ-агент партнёрского отдела Альбато: когда сделка в amoCRM (воронка **Partners**) попадает на
этап **«Новый контакт»**, агент сам пишет клиенту (от личного Telegram-аккаунта Варвары, email —
fallback) и сразу переводит сделку на этап **«Первичные переговоры»** (не дожидаясь ответа). Когда
клиент отвечает — сделка идёт на **«Уточнение ТЗ»**, ответ классифицируется через Claude на
**positive / negative / ambiguous**. Positive/negative, а также ambiguous без совпадения в базе
знаний — сразу «Ручная проверка» (при positive — с примечанием в сделке, содержащим собранное ТЗ)
с задачей на Варвару. Ambiguous **с совпадением в базе знаний** — исключение: бот отвечает сам
и продолжает ждать реакции клиента, не эскалируя. Если клиент не отвечает вовсе (ни на первое
сообщение, ни на такой уточняющий вопрос бота) — шлёт напоминание (сделка уходит на этап
«Молчание»), потом закрывает сделку (этап «Блок»).

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
| `core/checklist.py` | `assess` — общий чеклист (стек ≥2 сервиса; кейс: проблема/данные, Claude+фолбэк). `assess_topic` — тематический чеклист (ИИ-агент/бот, Tilda+iiko, Яндекс Метрика, бот в Максе), см. `_TOPIC_DEFINITIONS` |
| `core/scheduler.py` | Тик шедулера (по умолчанию раз в 60с) → `process_scheduler_tick` |
| `core/templates.py` | Тексты клиенту/задач на Варвару; `FIRST_MESSAGE_VARIANTS` (анти-бан вариации); `first_message(..., missing_fields)` вставляет предупреждение о нехватке данных перед абзацем согласия на оплату; `spec_note` — примечание к сделке с собранным ТЗ (positive-ветка) |
| `core/timeutils.py` | Расчёт `next_action_at` (напоминания), таймзона `Europe/Moscow` |
| `db/models.py` | `Status` (state machine states), `Channel`, `ReplyCategory`, `Deal` dataclass |
| `db/repository.py` | SQLite-доступ: `get_deal`, `try_lock`/`unlock` (защита от гонок), `list_due_rows`, переходы статусов, `restart_reminder_cycle` (бот сам задал вопрос из FAQ и ждёт), `stop_reminders` (сделку вручную увели с этапов бота) |
| `classify/client.py` | Классификация ответа клиента через Claude (`tool_use`, модель `claude-haiku-4-5`), фолбэк — `rule_based.py` |
| `classify/prompt.py` | System-промпт классификатора (3 категории, правила разрешения неоднозначности) |
| `classify/rule_based.py` | Классификация по ключевым словам, если `ANTHROPIC_API_KEY` не задан |
| `classify/faq.py` | База знаний (FAQ) — подбор ответа на ambiguous-вопрос через Claude (`match_faq_sync`). `FAQ_ENABLED=True`; `_USABLE_ENTRIES` исключает черновики-плейсхолдеры из подбора — реально работают только `faq_price`, `faq_timeline`, `faq_who_is_integrator`, `faq_tz_clarification`, остальные ждут фактов в `docs/faq-knowledge-base.md` |
| `amo/client.py`, `amo/auth.py` | REST-клиент amoCRM (long-lived token ИЛИ OAuth c refresh); `get_lead` — текущий статус сделки |
| `amo/actions.py` | `move_to_negotiations` (Первичные переговоры), `move_to_clarification` (Уточнение ТЗ), `move_to_silence` (Молчание), `move_to_manual_review` (Ручная проверка), `move_to_blocked`, `get_lead_status_id`, `create_manager_task`, `add_note` |
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

### CRM-этапы (amoCRM) vs локальный `Status` — это РАЗНЫЕ вещи

Локальный `Status` (выше) отслеживает, что бот уже сделал для reminder-логики/эскалации.
Этапы в amoCRM (2026-07-23, после обновления) меняются в других точках и не имеют 1:1
соответствия локальным статусам:

```
Новый контакт (amoCRM, до первого сообщения)
    → [бот отправил первое сообщение]       → Первичные переговоры  (move_to_negotiations,
                                               сразу в process_new_deal — НЕ ждём ответа)
    → [нет ответа, напоминание №1 отправлено] → Молчание             (move_to_silence)
    → [клиент ответил]                       → Уточнение ТЗ          (move_to_clarification,
                                               в начале handle_incoming_reply)
    → [классификация: positive/negative,
       ИЛИ ambiguous БЕЗ совпадения в FAQ]    → Ручная проверка       (move_to_manual_review)
    → [классификация: ambiguous С совпадением
       в FAQ — бот отвечает сам и ждёт]       → остаётся на Уточнение ТЗ (repo.restart_reminder_cycle,
                                               цикл напоминаний запускается заново, см. п.4
                                               Логика ИИ агента.md)
[нет ответа, цепочка напоминаний исчерпана
 на Первичные переговоры/Молчание/Уточнение ТЗ] → Блок                (move_to_blocked)
[сделку вручную перевели на этап вне этих трёх] → напоминания останавливаются насовсем
                                               (repo.stop_reminders, этап не трогаем)
```

При positive-классификации, перед переводом на «Ручная проверка», в сделку добавляется
примечание (`amo_actions.add_note`) с текстом `core/templates.py: spec_note(stack, case)`,
где `case` — исходный кейс из сделки + текст ответа клиента (чтобы не терять детали,
которые клиент указал в ответе).

Перед КАЖДЫМ напоминанием (`process_scheduler_tick`) шедулер (а) перечитывает сделку из БД, чтобы
не отправить лишнее, если ответ клиента пришёл ровно в этот момент, и (b) проверяет РЕАЛЬНЫЙ
текущий этап в amoCRM через `amo_actions.get_lead_status_id` — не только локальный `Status`,
потому что человек может вручную переместить сделку в amoCRM мимо бота.

Актуальные ID этапов — `.env`: `AMOCRM_STAGE_NEGOTIATIONS_ID`, `AMOCRM_STAGE_CLARIFICATION_ID`,
`AMOCRM_STAGE_SILENCE_ID`, `AMOCRM_STAGE_MANUAL_REVIEW_ID`, `AMOCRM_STAGE_BLOCKED_ID` (все —
обязательные поля в `config.py: Settings._required`).

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

`tests/` — pytest (48 тестов, `.venv/bin/python -m pytest tests/ -q`): `test_repository.py`
(SQLite-репозиторий, включая `restart_reminder_cycle`/`stop_reminders`), `test_timeutils.py`
(расчёт напоминаний), `test_rule_based.py` (классификация по правилам), `test_templates.py`
(вариации первого сообщения + вставка предупреждения чеклиста + `spec_note`), `test_checklist.py`
(чеклист целостности, non-LLM фолбэк), `test_faq.py` (FAQ — только non-LLM путь: без
`ANTHROPIC_API_KEY`, `get_answer`, фильтрация плейсхолдеров из `_USABLE_ENTRIES`/tool-схемы),
`conftest.py` (фикстуры). Нет тестов на `state_machine.py`, `classify/client.py`/`classify/faq.py`
LLM-путь/`core/checklist.py` LLM-путь — в проекте нет `pytest-asyncio` (см. `requirements.txt`),
интеграционные точки покрыты только вручную (см. README «Проверка сценария»). Логика
`process_new_deal` (вставка предупреждения в сообщение) проверена ad-hoc smoke-скриптом при
разработке (2026-07-23, мокался telegram), не входит в `tests/`.

**Локальное окружение (2026-07-23):** для запуска тестов и read-only проверок через amoCRM API
создан `.venv/` (уже в `.gitignore`, не коммитится) — у системного `python3` в этом окружении не
было ни `pytest`, ни `requests`/`anthropic`/`telethon`. Установка: `python3 -m venv .venv &&
.venv/bin/pip install -r requirements.txt`.

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
