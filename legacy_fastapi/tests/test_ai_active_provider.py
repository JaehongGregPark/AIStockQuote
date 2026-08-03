from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import ai_analysis

client = TestClient(app)


def test_set_active_provider_pins_override_and_persists(monkeypatch):
    monkeypatch.setattr(config, "AI_PROVIDER", None)
    monkeypatch.setattr(ai_analysis, "_PROVIDER_ORDER", ["anthropic", "openai", "gemini"])
    monkeypatch.setattr(ai_analysis, "_provider_key", lambda p: "fake-key")
    monkeypatch.setattr(
        ai_analysis,
        "check_provider",
        lambda p: {
            "provider": p,
            "configured": True,
            "model": f"model-{p}",
            "usable": True,
            "error": None,
            "available_models": [],
        },
    )
    monkeypatch.setattr(ai_analysis, "get_provider", lambda: config.AI_PROVIDER or "anthropic")

    reset_calls = []
    monkeypatch.setattr(ai_analysis, "reset_client_cache", lambda: reset_calls.append(True))

    persist_calls = []
    monkeypatch.setattr(
        config, "persist_env_value", lambda k, v: persist_calls.append((k, v))
    )

    res = client.post("/api/ai/active-provider", json={"provider": "openai"})

    assert res.status_code == 200
    body = res.json()
    assert config.AI_PROVIDER == "openai"
    assert ("AI_PROVIDER", "openai") in persist_calls
    assert reset_calls == [True]
    assert body["ai_provider_override"] == "openai"
    assert body["active_provider"] == "openai"


def test_set_active_provider_null_clears_override_to_auto(monkeypatch):
    monkeypatch.setattr(config, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(ai_analysis, "_PROVIDER_ORDER", ["anthropic", "openai", "gemini"])
    monkeypatch.setattr(ai_analysis, "_provider_key", lambda p: "fake-key")
    monkeypatch.setattr(
        ai_analysis,
        "check_provider",
        lambda p: {
            "provider": p,
            "configured": True,
            "model": f"model-{p}",
            "usable": True,
            "error": None,
            "available_models": [],
        },
    )
    monkeypatch.setattr(ai_analysis, "get_provider", lambda: config.AI_PROVIDER or "anthropic")
    monkeypatch.setattr(ai_analysis, "reset_client_cache", lambda: None)

    persist_calls = []
    monkeypatch.setattr(
        config, "persist_env_value", lambda k, v: persist_calls.append((k, v))
    )

    res = client.post("/api/ai/active-provider", json={"provider": None})

    assert res.status_code == 200
    body = res.json()
    assert config.AI_PROVIDER is None
    assert ("AI_PROVIDER", "") in persist_calls
    assert body["ai_provider_override"] is None
    assert body["active_provider"] == "anthropic"  # falls back to auto priority


def test_set_active_provider_unknown_provider_returns_404():
    res = client.post("/api/ai/active-provider", json={"provider": "unknown-llm"})
    assert res.status_code == 404
