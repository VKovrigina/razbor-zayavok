from __future__ import annotations

import fcntl
import os
from pathlib import Path

# Открытые файлы блокировок держатся до конца процесса — ОС снимает flock сама при любом выходе,
# в том числе kill -9, поэтому "залипшей" блокировки после краша не бывает.
_held: dict[str, object] = {}


def acquire(name: str, lock_dir: Path | str = "data") -> None:
    """Не даёт запустить второй экземпляр процесса (решено 2026-10-28, перед переносом на
    сервер): две копии main.py/main_cases.py — одна Telegram-сессия с двух мест (Telegram может
    сбросить авторизацию) и двойные сообщения клиентам. Например, если при переезде агент
    остался запущен и на старой машине — там свой data/, это не поймает; ловит второй запуск
    на ЭТОЙ машине."""
    lock_dir = Path(lock_dir)
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_dir / f"{name}.lock", "a+")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        raise SystemExit(f"{name} уже запущен (блокировка {lock_dir / f'{name}.lock'}) — второй экземпляр не стартует")
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    _held[name] = lock_file
