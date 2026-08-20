import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKEND_PORT", "8123")
    monkeypatch.setenv("LOG_LEVEL", "warning")

    settings = Settings(_env_file=None)

    assert settings.backend_port == 8123
    assert settings.log_level == "warning"


def test_production_rejects_the_development_jwt_key() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production")
