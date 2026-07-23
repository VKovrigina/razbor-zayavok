import dataclasses

import pytest

from config import settings as base_settings


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """db.repository, направленный на временную SQLite-базу (не трогает data/app.db)."""
    test_settings = dataclasses.replace(base_settings, db_path=str(tmp_path / "test.db"))
    monkeypatch.setattr("db.repository.settings", test_settings)

    from db import repository as repository_module

    repository_module.init_db()
    return repository_module
