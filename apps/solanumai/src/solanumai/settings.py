"""
All SolanumAI configuration, read once from environment variables.
"""

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _blank(value: object) -> bool:
    """
    True for None, '' or whitespace. Empty env lines (ENTRA_TENANT_ID=) arrive as ''.
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

    session_secret: SecretStr
    session_max_age_seconds: int = 8 * 60 * 60  # 8 Hours
    cookie_secure: bool = (
        False  # True once served over HTTPS (cookie is then never sent over http)
    )

    # --- login ---
    auth_mode: Literal["password", "entra"] = "password"
    app_login_password: SecretStr | None = None
    entra_tenant_id: str | None = None
    entra_client_id: str | None = None
    entra_client_secret: SecretStr | None = None

    # --- ML models and the prediction log ---
    models_dir: Path = Path("/models")
    store_path: Path = Path("/var/lib/solanumai/app.db")
    max_upload_mb: int = 20

    # --- database: read-only role for the explorer and the agent ---
    db_host: str
    db_port: int = 5432
    db_name: str
    db_sslmode: str = "prefer"
    agent_user: str
    agent_password: SecretStr

    @model_validator(mode="after")
    def _check_auth(self) -> "Settings":
        if self.auth_mode == "password" and _blank(self.app_login_password):
            raise ValueError(
                "AUTH_MODE=password needs APP_LOGIN_PASSWORD (secrets/<env>/app-login-password)"
            )
        if self.auth_mode == "entra":
            missing = [
                name.upper()
                for name in (
                    "entra_tenant_id",
                    "entra_client_id",
                    "entra_client_secret",
                )
                if _blank(getattr(self, name))
            ]

            if missing:
                raise ValueError(f"AUTH_MODE=entra needs: {', '.join(missing)}")
        return self

    def uri_for_model(self, key: str) -> str:
        """Where to load model <key> from.
        MODEL_URI_<KEY> wins, e.g. models:/oa@champion for the MLflow registry.
        Otherwise the MLflow-format folder <MODELS_DIR>/<key>/model."""
        env_name = "MODEL_URI_" + re.sub(r"[^A-Za-z0-9]", "_", key).upper()
        return os.environ.get(env_name) or str(self.models_dir / key / "model")


@lru_cache
def get_settings() -> Settings:
    return Settings()
