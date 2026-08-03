from app import config


def test_persist_env_value_creates_file_and_writes_key(tmp_path, monkeypatch):
    env_path = tmp_path / "sub" / ".env"
    monkeypatch.setattr(config, "ENV_FILE_PATH", env_path)

    config.persist_env_value("ANTHROPIC_API_KEY", "sk-ant-test123")

    assert env_path.exists()
    content = env_path.read_text()
    assert "ANTHROPIC_API_KEY" in content
    assert "sk-ant-test123" in content


def test_persist_env_value_updates_existing_key_without_disturbing_others(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("# comment\nANTHROPIC_API_KEY=old\nOPENAI_API_KEY=keep-me\n")
    monkeypatch.setattr(config, "ENV_FILE_PATH", env_path)

    config.persist_env_value("ANTHROPIC_API_KEY", "new-value")

    content = env_path.read_text()
    assert "new-value" in content
    assert "old" not in content
    assert "keep-me" in content
    assert "# comment" in content
