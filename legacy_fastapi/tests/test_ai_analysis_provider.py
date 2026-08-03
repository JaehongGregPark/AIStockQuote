from app import config
from app.services import ai_analysis


def _reset_client_cache():
    ai_analysis._client = None
    ai_analysis._provider = None
    ai_analysis._client_init_attempted = False


def test_no_keys_configured_is_unavailable(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(config, "OPENAI_API_KEY", None)
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    monkeypatch.setattr(config, "AI_PROVIDER", None)
    _reset_client_cache()

    assert ai_analysis._resolve_provider() is None
    assert ai_analysis.is_available() is False
    assert ai_analysis.get_provider() is None


def test_default_priority_prefers_anthropic(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "gemini-test")
    monkeypatch.setattr(config, "AI_PROVIDER", None)
    _reset_client_cache()

    assert ai_analysis._resolve_provider() == "anthropic"


def test_falls_back_to_openai_when_no_anthropic_key(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "gemini-test")
    monkeypatch.setattr(config, "AI_PROVIDER", None)
    _reset_client_cache()

    assert ai_analysis._resolve_provider() == "openai"


def test_falls_back_to_gemini_when_only_gemini_key(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(config, "OPENAI_API_KEY", None)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "gemini-test")
    monkeypatch.setattr(config, "AI_PROVIDER", None)
    _reset_client_cache()

    assert ai_analysis._resolve_provider() == "gemini"


def test_explicit_ai_provider_overrides_priority(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "gemini-test")
    monkeypatch.setattr(config, "AI_PROVIDER", "gemini")
    _reset_client_cache()

    assert ai_analysis._resolve_provider() == "gemini"


def test_explicit_ai_provider_without_matching_key_is_unavailable(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    monkeypatch.setattr(config, "AI_PROVIDER", "gemini")
    _reset_client_cache()

    assert ai_analysis._resolve_provider() is None
