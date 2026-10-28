from __future__ import annotations

import asyncio
import logging
import os
import time

from reporting import webhook

logger = logging.getLogger(__name__)

# Сторож процесса (решено 2026-10-28, перед переносом на сервер). Без него агент дважды тихо
# умирал: 2026-07-28 Telegram не переподключился ("failed 5 time(s)") и лог оборвался, 2026-10-22
# процесс упал и простоял до ручного запуска. Сторож не чинит — он завершает процесс с кодом 1,
# а поднимает его systemd (Restart=always, см. deploy/). Поэтому SIGTERM-флаг штатной остановки
# здесь НЕ ставится — следующий запуск честно сообщит о нештатном выходе (reporting/crash.py).
_CHECK_INTERVAL_SECONDS = 60
_PROBE_TIMEOUT_SECONDS = 30
_PROBE_FAILURES_TO_RESTART = 3

# Циклы отмечаются не только в конце итерации, но и после каждой обработанной сделки/письма:
# одна итерация опроса amoCRM законно идёт десятки минут (до 3 мин антибан-паузы перед каждым
# первым сообщением + вызовы Claude), а одна сделка — не дольше ~15 мин в худшем случае.
LOOP_SILENCE_LIMIT_SECONDS = 20 * 60

_last_beat: dict[str, float] = {}


def beat(name: str) -> None:
    _last_beat[name] = time.monotonic()


def stale_loops(limits: dict[str, float], now: float | None = None) -> list[str]:
    now = time.monotonic() if now is None else now
    return [name for name, limit in limits.items() if now - _last_beat.get(name, now) > limit]


def _exit(code: int) -> None:
    os._exit(code)


async def _die(process_name: str, reason: str) -> None:
    logger.error("Сторож: %s — завершаю %s для перезапуска", reason, process_name)
    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                webhook.send_error_notification,
                marker=process_name,
                message=f"{reason} — процесс перезапускается",
            ),
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.exception("Сторож: не удалось отправить алерт перед перезапуском")
    _exit(1)


async def watchdog_loop(process_name: str, limits: dict[str, float], telegram_client) -> None:
    """Раз в минуту: (1) цикл из `limits` молчит дольше своего лимита — значит завис;
    (2) лёгкий запрос get_me к Telegram — "зомби"-соединение выглядит подключённым, но не отвечает,
    поэтому проверяем ответом, а не флагом is_connected. Три сбоя подряд — перезапуск."""
    for name in limits:
        _last_beat.setdefault(name, time.monotonic())
    failures = 0
    while True:
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
        stale = stale_loops(limits)
        if stale:
            await _die(process_name, f"нет признаков жизни от цикла(ов) {', '.join(stale)}")
        try:
            await asyncio.wait_for(telegram_client.get_me(), timeout=_PROBE_TIMEOUT_SECONDS)
            failures = 0
        except Exception as exc:
            failures += 1
            logger.warning("Сторож: Telegram не ответил (%s/%s): %r", failures, _PROBE_FAILURES_TO_RESTART, exc)
            if failures >= _PROBE_FAILURES_TO_RESTART:
                await _die(process_name, f"Telegram не отвечает {failures} проверки подряд")
