"""Typed application settings, loaded from environment with fail-fast checks."""
from __future__ import annotations
import secrets
import sys
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    app_name: str = "IAG"
    env: str = Field(default="development", alias="IAG_ENV")
    database_url: str = Field(default="sqlite+aiosqlite:///./iag_test.db", alias="IAG_DATABASE_URL")
    secret_key: str = Field(default="", alias="IAG_SECRET_KEY")
    session_expire_minutes: int = Field(default=480, alias="IAG_SESSION_EXPIRE_MINUTES")
    access_token_expire_minutes: int = Field(default=30, alias="IAG_ACCESS_TOKEN_EXPIRE_MINUTES")
    max_login_attempts: int = Field(default=5, alias="IAG_MAX_LOGIN_ATTEMPTS")
    lockout_duration_minutes: int = Field(default=15, alias="IAG_LOCKOUT_DURATION_MINUTES")
    bootstrap_admin_username: str = Field(default="admin", alias="IAG_BOOTSTRAP_ADMIN_USERNAME")
    bootstrap_admin_password: str = Field(default="", alias="IAG_BOOTSTRAP_ADMIN_PASSWORD")
    cors_origins: str = Field(default="", alias="IAG_CORS_ORIGINS")
    reminder_delay_minutes: int = Field(default=60, alias="IAG_REMINDER_DELAY_MINUTES")
    reminder_poll_seconds: int = Field(default=60, alias="IAG_REMINDER_POLL_SECONDS")
    reminder_max_attempts: int = Field(default=3, alias="IAG_REMINDER_MAX_ATTEMPTS")
    reminder_stuck_minutes: int = Field(default=15, alias="IAG_REMINDER_STUCK_MINUTES")
    reminder_batch_size: int = Field(default=25, alias="IAG_REMINDER_BATCH_SIZE")
    app_base_url: str = Field(default="http://localhost:8090", alias="IAG_APP_BASE_URL")
    smtp_host: str = Field(default="", alias="IAG_SMTP_HOST")
    smtp_port: int = Field(default=587, alias="IAG_SMTP_PORT")
    smtp_user: str = Field(default="", alias="IAG_SMTP_USER")
    smtp_password: str = Field(default="", alias="IAG_SMTP_PASSWORD")
    smtp_from: str = Field(default="", alias="IAG_SMTP_FROM")
    connector_poll_seconds: int = Field(default=60, alias="IAG_CONNECTOR_POLL_SECONDS")
    connector_stuck_minutes: int = Field(default=15, alias="IAG_CONNECTOR_STUCK_MINUTES")
    connector_timeout_seconds: int = Field(default=30, alias="IAG_CONNECTOR_TIMEOUT_SECONDS")
    connector_max_rows: int = Field(default=50000, alias="IAG_CONNECTOR_MAX_ROWS")
    remediation_poll_seconds: int = Field(default=30, alias="IAG_REMEDIATION_POLL_SECONDS")
    remediation_stuck_minutes: int = Field(default=15, alias="IAG_REMEDIATION_STUCK_MINUTES")
    remediation_max_attempts: int = Field(default=3, alias="IAG_REMEDIATION_MAX_ATTEMPTS")
    remediation_webhook_timeout_seconds: int = Field(
        default=10, alias="IAG_REMEDIATION_WEBHOOK_TIMEOUT_SECONDS"
    )
    risk_unreviewed_days: int = Field(default=90, alias="IAG_RISK_UNREVIEWED_DAYS")
    def db_url_sync(self) -> str:
        """Sync driver URL for Alembic and tests."""
        if self.database_url.startswith("sqlite+aiosqlite"):
            return self.database_url.replace("sqlite+aiosqlite", "sqlite", 1)
        if self.database_url.startswith("postgresql+asyncpg"):
            return self.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2", 1)
        return self.database_url
    def validate_secrets(self) -> None:
        """Fail fast when a deployment-critical secret is missing."""
        if self.env == "test":
            return
        if not self.secret_key:
            if self.env == "development":
                self.secret_key = secrets.token_hex(32)
                print("[settings] no IAG_SECRET_KEY: generated ephemeral dev key", file=sys.stderr)
                return
            raise RuntimeError(
                "IAG_SECRET_KEY is required outside development. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if len(self.secret_key) < 32:
            raise RuntimeError("IAG_SECRET_KEY must be at least 32 chars")
    def validate_smtp(self) -> None:
        """If SMTP is configured, the full credential set must be present.
        Empty host = dev mode: worker delivers log-only, no SMTP at all."""
        if not self.smtp_host:
            return
        missing = [name for name, val in (
            ("IAG_SMTP_USER", self.smtp_user),
            ("IAG_SMTP_PASSWORD", self.smtp_password),
            ("IAG_SMTP_FROM", self.smtp_from),
        ) if not val]
        if missing:
            raise RuntimeError("IAG_SMTP_HOST set but missing: " + ", ".join(missing))
