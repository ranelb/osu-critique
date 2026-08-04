"""Configuration: paths and keys, from env vars, a config file, or defaults.

Precedence: environment variable > config file > default.

The config file (~/.config/osu-critique/config.json, mode 0600) is written by
`osu-critique setup`. Keys are optional — the analysis core needs none of them.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("OSU_CONFIG_DIR",
                                 "~/.config/osu-critique")).expanduser()
CONFIG_PATH = CONFIG_DIR / "config.json"

# ------------------------------------------------------- config file --------

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_config(cfg: dict) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    try:
        CONFIG_PATH.chmod(0o600)
    except OSError:
        pass
    return CONFIG_PATH


def get(name: str, env: str | None = None, default=None):
    """Resolve a single value: env var first, then config file, then default."""
    if env and os.environ.get(env):
        return os.environ[env]
    cfg = load_config()
    if name in cfg and cfg[name] not in (None, ""):
        return cfg[name]
    return default


def _path(name: str, env: str, default: str) -> Path:
    return Path(str(get(name, env, default))).expanduser()


# ---------------------------------------------------------------- paths -----

# osu!lazer data root (Flatpak layout on Linux)
LAZER_DATA = _path("lazer_data", "OSU_LAZER_DATA",
                   "~/.var/app/sh.ppy.osu/data/osu")
LAZER_EXPORTS = Path(str(get("lazer_exports", "OSU_LAZER_EXPORTS",
                             LAZER_DATA / "exports"))).expanduser()
LAZER_FILES = Path(str(get("lazer_files", "OSU_LAZER_FILES",
                           LAZER_DATA / "files"))).expanduser()
ONLINE_DB = Path(str(get("online_db", "OSU_ONLINE_DB",
                         LAZER_DATA / "online.db"))).expanduser()

# output directory for metrics JSON + charts
DEFAULT_OUTDIR = Path(str(get("outdir", "OSU_OUTDIR", "out"))).expanduser()

# ------------------------------------------------------------- BYOK keys ----

def llm_key() -> str | None:
    return get("llm_key", "OSU_LLM_KEY") or None


def llm_base_url() -> str:
    return str(get("llm_base_url", "OSU_LLM_BASE_URL", "https://api.openai.com/v1"))


def llm_model() -> str:
    return str(get("llm_model", "OSU_LLM_MODEL", "gpt-4o-mini"))


def osu_client_id() -> str | None:
    return get("osu_client_id", "OSU_CLIENT_ID") or None


def osu_client_secret() -> str | None:
    return get("osu_client_secret", "OSU_CLIENT_SECRET") or None


def allow_scrape() -> bool:
    """Whether the unofficial HTML profile fallback is permitted (opt-in)."""
    v = str(get("allow_scrape", "OSU_ALLOW_SCRAPE", "false")).lower()
    return v in ("1", "true", "yes", "on")
