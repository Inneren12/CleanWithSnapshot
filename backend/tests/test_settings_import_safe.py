from __future__ import annotations

from pathlib import Path


def test_settings_import_safe(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.delenv("SECRETS_BACKEND", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    from app.settings import Settings

    Settings(_env_file=str(env_file))
