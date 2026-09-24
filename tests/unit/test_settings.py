from pathlib import Path

import pytest

from recipe_mcp.settings import MissingConfigError, Settings, load_settings


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings tests must not see CI or developer environment variables."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def test_defaults_without_env_file() -> None:
    s = load_settings(env_file=None)
    assert s.model_provider == "none"
    assert s.effective_model_name == "none"
    assert s.brain == "claude-code"
    assert s.missing_for("model") == [
        "MODEL_PROVIDER (none: the MCP client agent does the parsing)"
    ]
    assert load_settings(env_file=None, model_provider="openai").effective_model_name == "gpt-4o"
    assert s.database_path == Path("data/recipes.db")
    assert s.classification_confidence_threshold == 0.8
    assert s.members_path == Path(".private/members.yaml")


def test_empty_values_in_env_file_are_treated_as_unset(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "MODEL_PROVIDER=openai\nOPENAI_API_KEY=\nMODEL_NAME=\nTELEGRAM_ALLOWED_USER_IDS=\n"
    )
    s = load_settings(env_file=env)
    assert s.openai_api_key is None
    assert s.missing_for("model") == ["OPENAI_API_KEY"]
    assert s.allowed_telegram_user_ids == []


def test_require_reports_names_not_values(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "MODEL_PROVIDER=openai\nOPENAI_API_KEY=sk-test-not-real\nTELEGRAM_BOT_TOKEN=123:abc\n"
        "TELEGRAM_ALLOWED_USER_IDS=111, 222,x\n"
    )
    s = load_settings(env_file=env)
    s.require("model")
    assert s.allowed_telegram_user_ids == [111, 222]
    with pytest.raises(MissingConfigError) as exc:
        s.require("telegram")
    assert exc.value.names == ["TELEGRAM_GROUP_CHAT_ID"]
    assert "123:abc" not in str(exc.value)
    summary = s.redacted_summary()
    assert summary["OPENAI_API_KEY"] == "set"
    assert summary["TELEGRAM_BOT_TOKEN"] == "set"
    joined = " ".join(summary.values())
    assert "sk-test" not in joined and "123:abc" not in joined


def test_brain_missing_binary_is_reported_by_name() -> None:
    s = load_settings(env_file=None, claude_code_bin="no-such-binary-xyz")
    assert s.missing_for("brain") == ["CLAUDE_CODE_BIN ('no-such-binary-xyz' not found on PATH)"]
    assert load_settings(env_file=None, brain="none").missing_for("brain") == ["BRAIN (none)"]


def test_threshold_and_default_member(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("CLASSIFICATION_CONFIDENCE_THRESHOLD=0.6\nDEFAULT_MEMBER=alex\n")
    s = load_settings(env_file=env)
    assert s.classification_confidence_threshold == 0.6
    assert s.default_member == "alex"
    with pytest.raises(ValueError):
        load_settings(env_file=None, classification_confidence_threshold=1.5)


def test_fake_provider_needs_no_key() -> None:
    s = load_settings(env_file=None, model_provider="fake")
    assert s.missing_for("model") == []
    assert s.effective_model_name == "fake-v1"


def test_memory_database_and_invalid_url() -> None:
    assert load_settings(env_file=None, database_url="sqlite:///:memory:").database_path is None
    with pytest.raises(ValueError):
        load_settings(env_file=None, database_url="postgres://x")


def test_repo_env_file_beats_shell_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: a shell-exported TELEGRAM_BOT_TOKEN must not override the repo .env."""
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=111:repo-bot\nTELEGRAM_GROUP_CHAT_ID=-5\n")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "999:other-bot")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    s = load_settings(env_file=env)
    assert s.telegram_bot_token is not None
    assert s.telegram_bot_token.get_secret_value() == "111:repo-bot"
    assert s.telegram_group_chat_id == -5
    assert s.log_level == "DEBUG"

    shell_only = load_settings(env_file=None)
    assert shell_only.telegram_bot_token is not None
    assert shell_only.telegram_bot_token.get_secret_value() == "999:other-bot"


def test_brain_child_env_strips_anthropic_api_credentials() -> None:
    s = load_settings(env_file=None, claude_code_oauth_token="oat-test-not-real")
    env = s.brain_child_env(
        {
            "PATH": "/usr/bin",
            "ANTHROPIC_API_KEY": "sk-ant-x",
            "ANTHROPIC_AUTH_TOKEN": "t",
            "HOME": "/h",
        }
    )
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["PATH"] == "/usr/bin" and env["HOME"] == "/h"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "oat-test-not-real"
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in load_settings(env_file=None).brain_child_env({})


def test_env_file_problems_reports_wrapped_values_by_line_only(tmp_path: Path) -> None:
    from recipe_mcp.settings import env_file_problems

    env = tmp_path / ".env"
    env.write_text(
        "APP_ENV=development\n\n# comment\nCLAUDE_CODE_OAUTH_TOKEN=first-half\n"
        "second-half-of-token\nexport LOG_LEVEL=INFO\n"
    )
    assert env_file_problems(env) == [5]
    assert env_file_problems(tmp_path / "missing.env") == []
