"""Keys come from the environment. `.env` files are read with `export KEY=value` or `KEY=value` lines; a value already
in the environment wins. Nothing here ever prints a value."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET_NAMES = ("AWS_BEARER_TOKEN_BEDROCK", "OPENROUTER_API_KEY", "GITHUB_TOKEN", "MARTIAN_API_KEY")


def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        line = line.removeprefix("export ")
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip("'\"")
    return out


def load_env(root: Path = ROOT) -> list[str]:
    """Loads <root>/.env, then the file CRBENCH_ENV_FILE names (from the environment or that .env; a relative path is
    relative to <root>), into the environment without overriding what is already set. Returns the files read."""
    read: list[str] = []
    local = root / ".env"
    values = read_env_file(local)
    for key, value in values.items():
        os.environ.setdefault(key, value)
    if values:
        read.append(str(local))
    extra = os.environ.get("CRBENCH_ENV_FILE")
    if extra:
        path = Path(extra).expanduser()
        if not path.is_absolute():
            path = (root / path).resolve()
        for key, value in read_env_file(path).items():
            os.environ.setdefault(key, value)
        read.append(str(path))
    return read


def require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} is not set (see .env.example)")
    return value


def region() -> str:
    return os.environ.get("AWS_REGION") or "us-west-2"
