from pathlib import Path

import pytest
import yaml

from server.llm.pricing import load_pricing
from server.settings import Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings() also reads from the real process environment (not just
    .env), so tests must not be at the mercy of whatever the dev shell has
    exported."""
    for key in [
        "TG_HOST",
        "TG_USERNAME",
        "TG_PASSWORD",
        "TG_SECRET",
        "TG_GRAPH",
        "TURSO_DATABASE_URL",
        "TURSO_AUTH_TOKEN",
        "GROQ_API_KEY",
        "LLM_OFFLINE",
        "LLM_SPEND_CAP_USD",
        "DEMO_MODE",
    ]:
        monkeypatch.delenv(key, raising=False)
    # Point at a .env that does not exist so no local dev file leaks in either.
    monkeypatch.setattr(
        Settings, "model_config", {**Settings.model_config, "env_file": "/nonexistent/.env"}
    )


def test_settings_load_with_sensible_defaults_when_env_is_empty() -> None:
    s = Settings()
    assert s.tg_host == "http://localhost"
    assert s.tg_password == "tigergraph"
    assert s.turso_database_url == "file:db/interlock.db"
    assert s.llm_offline is False
    assert s.llm_spend_cap_usd == 25.0


def test_settings_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_HOST", "https://my-savanna-instance.i.tgcloud.io")
    monkeypatch.setenv("LLM_SPEND_CAP_USD", "5")

    s = Settings()

    assert s.tg_host == "https://my-savanna-instance.i.tgcloud.io"
    assert s.llm_spend_cap_usd == 5.0


def test_settings_coerces_bool_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_OFFLINE", "true")
    assert Settings().llm_offline is True


def test_load_pricing_returns_empty_dict_for_missing_file(tmp_path: Path) -> None:
    assert load_pricing(tmp_path / "does-not-exist.yaml") == {}


def test_load_pricing_parses_valid_yaml(tmp_path: Path) -> None:
    config = tmp_path / "models.yaml"
    config.write_text(
        yaml.dump({"pricing_usd_per_million_tokens": {"m": {"input": 1.0, "output": 2.0}}})
    )

    pricing = load_pricing(config)

    assert pricing == {"m": {"input": 1.0, "output": 2.0}}


def test_load_pricing_fails_fast_on_malformed_yaml(tmp_path: Path) -> None:
    """A broken models.yaml must not be silently treated as '$0 for every
    model' -- that would defeat the LLM_SPEND_CAP_USD safety net."""
    config = tmp_path / "models.yaml"
    config.write_text("pricing_usd_per_million_tokens: [this is not: valid: yaml")

    with pytest.raises(yaml.YAMLError):
        load_pricing(config)
