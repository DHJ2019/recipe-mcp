"""Typed configuration loaded from the local ``.env`` file.

All application code reads configuration through :class:`Settings`. Nothing else
in the package touches ``os.environ`` directly. Validation is deliberately lazy:
constructing settings never fails because a live-integration variable is blank.
Callers ask :meth:`Settings.missing_for` before using an integration and report
the *names* of missing variables, never their values. Values in the repo ``.env``
take precedence over variables exported in the shell, which only fill keys the file
does not set.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

Feature = Literal[
    "model",
    "brain",
    "telegram",
    "shortcut",
    "nyt_browser",
    "whatsapp_export",
    "private_evals",
]

DEFAULT_OPENAI_MODEL = "gpt-4o"
# The only variables the headless brain inherits. Everything else in the daemon's
# environment (the Telegram bot token, model keys, Anthropic API credentials) stays out.
# Add a name here only when `claude` needs it, and note whether its value can hold a
# credential (the proxy variables can, as user:password@host).
BRAIN_ALLOWED_ENV: tuple[str, ...] = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TERM",
    "CLAUDE_CONFIG_DIR",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "https_proxy",
    "http_proxy",
    "no_proxy",
    "NODE_EXTRA_CA_CERTS",
)
DEFAULT_MEMBERS_FILE = Path(".private/members.yaml")


class MissingConfigError(RuntimeError):
    """Raised when a feature is used without its required configuration."""

    def __init__(self, feature: str, names: list[str]) -> None:
        self.feature = feature
        self.names = names
        joined = ", ".join(names)
        super().__init__(f"Missing configuration for {feature}: {joined} (set them in .env)")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Rank the repo ``.env`` above process environment variables.

        A shell profile can export a variable meant for another project (for example a
        different bot's ``TELEGRAM_BOT_TOKEN``); pydantic-settings would otherwise let it
        override the repo file. Process env still supplies keys the file does not set,
        which is what CI relies on with ``env_file=None``.
        """
        return (init_settings, dotenv_settings, env_settings, file_secret_settings)

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str = "sqlite:///data/recipes.db"

    model_provider: Literal["none", "openai", "fake"] = "none"
    model_name: str = ""
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    classification_confidence_threshold: float = 0.8
    default_member: str = ""

    brain: Literal["claude-code", "none"] = "claude-code"
    claude_code_bin: str = "claude"
    claude_code_oauth_token: SecretStr | None = None
    """Long-lived token from `claude setup-token`. Not read by the app; `uv run --env-file`
    exports it so the headless `claude -p` child process can authenticate without the
    keychain (locked at boot before anyone logs in)."""
    brain_model: str = ""
    brain_timeout_seconds: int = 120
    brain_max_turns: int = 8

    telegram_bot_token: SecretStr | None = None
    telegram_allowed_user_ids: str = ""
    telegram_group_chat_id: int | None = None

    shortcut_endpoint_enabled: bool = False
    shortcut_bind_address: str | None = None

    nyt_browser_profile_path: Path = Path(".private/nyt-browser-profile")
    whatsapp_export_path: Path = Path(".private/whatsapp-export.txt")
    private_evals_path: Path = Path(".private/evals")
    temp_media_dir: Path = Path(".private/tmp-media")
    members_path: Path = DEFAULT_MEMBERS_FILE

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        if not value.startswith("sqlite:///"):
            raise ValueError("DATABASE_URL must be a sqlite:/// URL in this release")
        return value

    @field_validator("classification_confidence_threshold")
    @classmethod
    def _validate_threshold(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("CLASSIFICATION_CONFIDENCE_THRESHOLD must be between 0 and 1")
        return value

    # -- derived values -------------------------------------------------

    @property
    def database_path(self) -> Path | None:
        """Filesystem path for the SQLite database, or ``None`` for in-memory."""
        raw = self.database_url.removeprefix("sqlite:///")
        if raw == ":memory:":
            return None
        return Path(raw)

    @property
    def effective_model_name(self) -> str:
        if self.model_name:
            return self.model_name
        if self.model_provider == "openai":
            return DEFAULT_OPENAI_MODEL
        if self.model_provider == "fake":
            return "fake-v1"
        return "none"

    @property
    def has_model(self) -> bool:
        """True when the server itself can call a model (not needed with an agent brain)."""
        return self.model_provider != "none" and not self.missing_for("model")

    @property
    def allowed_telegram_user_ids(self) -> list[int]:
        ids: list[int] = []
        for part in self.telegram_allowed_user_ids.split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
        return ids

    # -- validation -----------------------------------------------------

    def missing_for(self, feature: Feature) -> list[str]:
        """Return the names of variables a feature needs that are not set."""
        missing: list[str] = []
        if feature == "model":
            if self.model_provider == "none":
                missing.append("MODEL_PROVIDER (none: the MCP client agent does the parsing)")
            elif self.model_provider == "openai" and self.openai_api_key is None:
                missing.append("OPENAI_API_KEY")
        elif feature == "brain":
            if self.brain == "none":
                missing.append("BRAIN (none)")
            elif shutil.which(self.claude_code_bin) is None:
                missing.append(f"CLAUDE_CODE_BIN ({self.claude_code_bin!r} not found on PATH)")
        elif feature == "telegram":
            if self.telegram_bot_token is None:
                missing.append("TELEGRAM_BOT_TOKEN")
            if not self.allowed_telegram_user_ids:
                missing.append("TELEGRAM_ALLOWED_USER_IDS")
            if self.telegram_group_chat_id is None:
                missing.append("TELEGRAM_GROUP_CHAT_ID")
        elif feature == "shortcut":
            if not self.shortcut_endpoint_enabled:
                missing.append("SHORTCUT_ENDPOINT_ENABLED (false)")
            if not self.shortcut_bind_address:
                missing.append("SHORTCUT_BIND_ADDRESS")
        elif feature == "nyt_browser":
            if not self.nyt_browser_profile_path.exists():
                missing.append("NYT_BROWSER_PROFILE_PATH (directory does not exist)")
        elif feature == "whatsapp_export":
            if not self.whatsapp_export_path.exists():
                missing.append("WHATSAPP_EXPORT_PATH (file does not exist)")
        elif feature == "private_evals" and not self.private_evals_path.exists():
            missing.append("PRIVATE_EVALS_PATH (directory does not exist)")
        return missing

    def brain_child_env(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """Environment for the headless ``claude -p`` brain.

        Only the names in ``BRAIN_ALLOWED_ENV`` are passed on, so the bot token and any
        model keys never reach the agent. That also keeps out Anthropic API credentials:
        when Claude Code runs headless and finds them it bills the API per token instead
        of using the subscription login or ``CLAUDE_CODE_OAUTH_TOKEN``, which is the whole
        point of the agent brain.
        """
        source = os.environ if base is None else base
        env = {name: source[name] for name in BRAIN_ALLOWED_ENV if name in source}
        if self.claude_code_oauth_token is not None:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = self.claude_code_oauth_token.get_secret_value()
        return env

    def require(self, feature: Feature) -> None:
        missing = self.missing_for(feature)
        if missing:
            raise MissingConfigError(feature, missing)

    def redacted_summary(self) -> dict[str, str]:
        """Configuration overview safe to print: secrets are shown as set/unset."""

        def flag(value: object) -> str:
            return "set" if value else "unset"

        return {
            "APP_ENV": self.app_env,
            "LOG_LEVEL": self.log_level,
            "DATABASE_URL": self.database_url,
            "MODEL_PROVIDER": self.model_provider,
            "MODEL_NAME": self.effective_model_name,
            "OPENAI_API_KEY": flag(self.openai_api_key),
            "ANTHROPIC_API_KEY": flag(self.anthropic_api_key),
            "CLASSIFICATION_CONFIDENCE_THRESHOLD": str(self.classification_confidence_threshold),
            "DEFAULT_MEMBER": self.default_member or "unset",
            "BRAIN": self.brain,
            "CLAUDE_CODE_BIN": self.claude_code_bin,
            "CLAUDE_CODE_OAUTH_TOKEN": flag(self.claude_code_oauth_token),
            "BRAIN_MODEL": self.brain_model or "default",
            "BRAIN_TIMEOUT_SECONDS": str(self.brain_timeout_seconds),
            "BRAIN_MAX_TURNS": str(self.brain_max_turns),
            "TELEGRAM_BOT_TOKEN": flag(self.telegram_bot_token),
            "TELEGRAM_ALLOWED_USER_IDS": f"{len(self.allowed_telegram_user_ids)} id(s)",
            "TELEGRAM_GROUP_CHAT_ID": flag(self.telegram_group_chat_id),
            "SHORTCUT_ENDPOINT_ENABLED": str(self.shortcut_endpoint_enabled).lower(),
            "SHORTCUT_BIND_ADDRESS": flag(self.shortcut_bind_address),
            "NYT_BROWSER_PROFILE_PATH": str(self.nyt_browser_profile_path),
            "WHATSAPP_EXPORT_PATH": str(self.whatsapp_export_path),
            "PRIVATE_EVALS_PATH": str(self.private_evals_path),
            "TEMP_MEDIA_DIR": str(self.temp_media_dir),
        }


def env_file_problems(path: str | Path = ".env") -> list[int]:
    """Line numbers in an env file that are not ``KEY=VALUE``, blank or a comment.

    The usual cause is a long secret that wrapped when it was pasted, which silently
    truncates the value on the line above. Only line numbers are returned, never content.
    """
    env_path = Path(path)
    if not env_path.exists():
        return []
    bad: list[int] = []
    for number, line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, _ = stripped.removeprefix("export ").partition("=")
        if not sep or not key.replace("_", "").isalnum() or not key[0].isalpha():
            bad.append(number)
    return bad


def load_settings(env_file: str | Path | None = ".env", **overrides: Any) -> Settings:
    """Load settings from ``env_file`` (or only the process environment when ``None``).

    Tests pass ``env_file=None`` plus explicit overrides so they never depend on
    the developer's local ``.env``.
    """
    return Settings(_env_file=env_file, **overrides)  # type: ignore[call-arg]
