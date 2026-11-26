"""
All SolanumAI configuration.
"""

import os
import re
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_UNSUPPORTED_TENANTS = {"common", "organizations"}


def _blank(value: object) -> bool:
    """
    True for None, '' or whitespace.
    """
    if value is None:
        return True
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    return not str(value).strip()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_name: str = "SolanumAI"
    app_env: Literal["dev", "prod"] = "dev"

    # session cookie
    session_secret: SecretStr
    session_max_age_seconds: int = 8 * 60 * 60  # 8 hr
    cookie_secure: bool = False

    # sign-in: password and/or Microsoft
    auth_password_enabled: bool = True
    app_login_password: SecretStr | None = None
    ms_client_id: str | None = None
    ms_client_secret: SecretStr | None = None
    ms_tenant: str | None = None
    allowed_emails: str = ""

    # models: MLflow registry
    mlflow_tracking_uri: str
    model_alias: str = "champion"
    model_retry_seconds: int = 60

    max_upload_mb: int = 20

    # database
    db_host: str
    db_port: int = 5432
    db_name: str
    db_sslmode: str = "prefer"
    agent_user: str
    agent_password: SecretStr
    app_user: str
    app_password: SecretStr
    app_owner_user: str
    app_owner_password: SecretStr

    @property
    def microsoft_enabled(self) -> bool:
        return not _blank(self.ms_client_id)

    @property
    def allowed_email_set(self) -> frozenset[str]:
        return frozenset(
            e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()
        )

    @model_validator(mode="after")
    def _check_sign_in(self) -> "Settings":
        if not self.auth_password_enabled and not self.microsoft_enabled:
            raise ValueError(
                "No sign-in method: set AUTH_PASSWORD_ENABLED=true or MS_CLIENT_ID"
            )

        if self.auth_password_enabled and _blank(self.app_login_password):
            raise ValueError(
                "Password sign-in needs APP_LOGIN_PASSWORD (secrets/<env>/app-login-password)"
            )

        if self.microsoft_enabled:
            if _blank(self.ms_tenant) or _blank(self.ms_client_secret):
                raise ValueError(
                    "Microsoft sign-in needs MS_TENANT and MS_CLIENT_SECRET (secrets/<env>/ms-client-secret)"
                )

            tenant = self.ms_tenant.strip().lower()

            if tenant in _UNSUPPORTED_TENANTS:
                raise ValueError(
                    f"MS_TENANT={tenant} is not supported: use a tenant ID or 'consumers'"
                )

            if tenant == "consumers" and not self.allowed_email_set:
                raise ValueError(
                    "MS_TENANT=consumers lets ANY personal Microsoft account in: set ALLOWED_EMAILS"
                )

        return self

    def registry_name_for(self, key: str, default: str) -> str:
        """MLflow registered name: MODEL_NAME_<KEY> if set (e.g. to try a challenger model),
        otherwise the name in registry.py."""
        env_name = "MODEL_NAME_" + re.sub(r"[^A-Za-z0-9]", "_", key).upper()
        return os.environ.get(env_name) or default


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]
