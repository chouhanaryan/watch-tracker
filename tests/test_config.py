"""Config must tolerate empty env vars — GitHub Actions passes undefined
secrets as empty strings, not missing variables."""

import importlib


def test_empty_env_values_treated_as_unset(monkeypatch):
    for name in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
                 "EMAIL_FROM", "EMAIL_TO", "DEFAULT_CHECK_INTERVAL_MINUTES",
                 "SCHEDULER_ENABLED", "DATABASE_PATH"):
        monkeypatch.setenv(name, "")

    from app import config
    config = importlib.reload(config)

    assert config.SMTP_PORT == 587
    assert config.DEFAULT_CHECK_INTERVAL_MINUTES == 10
    assert config.EMAIL_TO == []
    assert config.DATABASE_PATH.endswith("watchtracker.db")
    assert config.smtp_configured() is False

    monkeypatch.undo()
    importlib.reload(config)


def test_populated_env_values_still_win(monkeypatch):
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("EMAIL_TO", "a@x.com, b@y.com")

    from app import config
    config = importlib.reload(config)

    assert config.SMTP_PORT == 2525
    assert config.EMAIL_TO == ["a@x.com", "b@y.com"]

    monkeypatch.undo()
    importlib.reload(config)
