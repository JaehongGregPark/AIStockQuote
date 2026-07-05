from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import ai_analysis

client = TestClient(app)


def test_update_provider_config_sets_key_and_model(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(config, "ANTHROPIC_MODEL", "claude-sonnet-5")

    monkeypatch.setattr(
        ai_analysis,
        "check_provider",
        lambda p: {
            "provider": p,
            "configured": True,
            "model": config.ANTHROPIC_MODEL,
            "usable": True,
            "error": None,
            "available_models": [],
        },
    )
    reset_calls = []
    monkeypatch.setattr(ai_analysis, "reset_client_cache", lambda: reset_calls.append(True))

    persist_calls = []
    monkeypatch.setattr(
        config, "persist_env_value", lambda k, v: persist_calls.append((k, v))
    )

    res = client.post(
        "/api/ai/config/anthropic",
        json={"api_key": "sk-ant-new", "model": "claude-haiku-4-5"},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["model"] == "claude-haiku-4-5"
    assert body["persisted_to_env"] is True
    assert config.ANTHROPIC_API_KEY == "sk-ant-new"
    assert config.ANTHROPIC_MODEL == "claude-haiku-4-5"
    assert reset_calls == [True]
    assert ("ANTHROPIC_API_KEY", "sk-ant-new") in persist_calls
    assert ("ANTHROPIC_MODEL", "claude-haiku-4-5") in persist_calls


def test_update_provider_config_ignores_blank_values(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "existing-key")
    monkeypatch.setattr(config, "OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setattr(
        ai_analysis,
        "check_provider",
        lambda p: {
            "provider": p,
            "configured": True,
            "model": config.OPENAI_MODEL,
            "usable": True,
            "error": None,
            "available_models": [],
        },
    )
    monkeypatch.setattr(ai_analysis, "reset_client_cache", lambda: None)

    persist_calls = []
    monkeypatch.setattr(
        config, "persist_env_value", lambda k, v: persist_calls.append((k, v))
    )

    res = client.post("/api/ai/config/openai", json={"api_key": "   ", "model": ""})

    assert res.status_code == 200
    assert res.json()["persisted_to_env"] is False
    assert config.OPENAI_API_KEY == "existing-key"
    assert config.OPENAI_MODEL == "gpt-4o-mini"
    assert persist_calls == []


def test_update_provider_config_unknown_provider_returns_404():
    res = client.post("/api/ai/config/unknown", json={})
    assert res.status_code == 404
