"""Settings come from environment variables (GitHub Actions secrets) or a local .env file."""

from __future__ import annotations

import os
from pathlib import Path


class ConfigError(RuntimeError):
    pass


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader: KEY=VALUE lines, existing environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def require(name: str) -> str:
    value = env(name)
    if value is None:
        raise ConfigError(f"Missing setting {name} (set it in the environment, a GitHub secret, or .env)")
    return value
