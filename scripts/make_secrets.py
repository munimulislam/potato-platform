"""
Create the secret files for one environment, once per machine.
Writes secrets/<env>/<name> with a strong random value.
Never overwrites an existing file.
RUN:
    uv run python scripts/make_secrets.py dev
    uv run python scripts/make_secrets.py prod
"""

import secrets
import sys
from pathlib import Path

# Every secret the stack needs. Add new ones here, and in compose.yaml under secrets:
NAMES = [
    "postgres-password",
    "dlt-password",
    "dbt-password",
    "dagster-password",
    "agent-password",
    "app-password",
    "app-owner-password",
    "mlflow-password",
    "session-secret",
    "app-login-password",
]


def main() -> None:
    env = sys.argv[1] if len(sys.argv) > 1 else "dev"
    target = Path("secrets") / env
    target.mkdir(parents=True, exist_ok=True)

    for name in NAMES:
        path = target / name

        if path.is_dir():
            path.rmdir()
            continue

        if path.is_file():
            print(f"kept     {path}")
            continue

        path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        print(f"created  {path}")


if __name__ == "__main__":
    main()
