import pytest

from core import process_lock


def test_second_instance_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(process_lock, "_held", {})
    process_lock.acquire("main", lock_dir=tmp_path)

    monkeypatch.setattr(process_lock, "_held", {})  # как будто другой процесс: свой открытый файл
    with pytest.raises(SystemExit) as exc:
        process_lock.acquire("main", lock_dir=tmp_path)
    assert "уже запущен" in str(exc.value)


def test_different_processes_do_not_block_each_other(tmp_path, monkeypatch):
    monkeypatch.setattr(process_lock, "_held", {})
    process_lock.acquire("main", lock_dir=tmp_path)
    process_lock.acquire("main_cases", lock_dir=tmp_path)
    assert set(process_lock._held) == {"main", "main_cases"}


def test_lock_file_contains_pid(tmp_path, monkeypatch):
    import os

    monkeypatch.setattr(process_lock, "_held", {})
    process_lock.acquire("main", lock_dir=tmp_path)
    assert (tmp_path / "main.lock").read_text().strip() == str(os.getpid())
