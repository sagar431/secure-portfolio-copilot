import pytest

from app.core.config import Settings


def test_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKEND_PORT", "8123")
    monkeypatch.setenv("LOG_LEVEL", "warning")

    settings = Settings(_env_file=None)

    assert settings.backend_port == 8123
    assert settings.log_level == "warning"
