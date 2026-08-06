"""Configuration: paths and keys, from env vars, a config file, or detection.

Precedence: environment variable > config file > auto-detection > default.

Paths are **resolved lazily and dynamically** rather than hardcoded: known
osu! install locations are probed (platform-aware) and the first one that
exists wins. Everything can be overridden with env vars or the config file
(`osu-critique setup`). No hardcoded single-path defaults.

Supported installs:
- osu!stable:  Windows ``%LOCALAPPDATA%/osu!``; Linux wine prefixes (best-effort)
- osu!lazer:   Windows ``%APPDATA%/osu``, Linux Flatpak ``~/.var/app/sh.ppy.osu/data/osu``,
               Linux AppImage / macOS ``~/.local/share/osu``
- project folders: ``./replays`` + ``./maps`` in the current directory
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
    """Resolve a single value: env var first, then config file, then default.

    Config keys may be hand-edited with the ``osu_`` prefix (e.g.
    ``osu_llm_key`` instead of ``llm_key``) — a legacy alias lookup covers
    that so a misremembered key name never silently disables a setting.
    """
    if env and os.environ.get(env):
        return os.environ[env]
    cfg = load_config()
    for key in (name, "osu_" + name):
        if key in cfg and cfg[key] not in (None, ""):
            return cfg[key]
    return default


# ------------------------------------------------------- path resolution ----

def _path(s: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(s)))


def _resolve(env: str, name: str, candidates: list[str], fallback: str) -> Path:
    """Override (env/config) > first existing candidate > platform fallback."""
    explicit = get(name, env, None)
    if explicit:
        return _path(str(explicit))
    for c in candidates:
        p = _path(c)
        if p.exists():
            return p
    return _path(fallback)


# ------------------------------------------------------------- osu!lazer ----

def _lazer_candidates() -> list[str]:
    c = []
    if os.name == "nt":                       # Windows
        c.append(os.environ.get("APPDATA", "") + "/osu")
    c += [
        "~/.var/app/sh.ppy.osu/data/osu",     # Linux Flatpak
        "~/.local/share/osu",                 # Linux AppImage / macOS
        "~/Library/Application Support/osu",  # macOS (classic)
    ]
    return c


def lazer_data() -> Path:
    return _resolve("OSU_LAZER_DATA", "lazer_data", _lazer_candidates(),
                    _lazer_candidates()[-1] if not os.name == "nt"
                    else os.environ.get("APPDATA", "") + "/osu")


def lazer_exports() -> Path:
    return _path(str(get("lazer_exports", "OSU_LAZER_EXPORTS", lazer_data() / "exports")))


def lazer_files() -> Path:
    return _path(str(get("lazer_files", "OSU_LAZER_FILES", lazer_data() / "files")))


def online_db() -> Path:
    return _path(str(get("online_db", "OSU_ONLINE_DB", lazer_data() / "online.db")))


# ------------------------------------------------------------ osu!stable ----

def _stable_candidates() -> list[str]:
    # osu!stable is only supported on Windows here (Linux players use lazer)
    if os.name == "nt":
        return [os.environ.get("LOCALAPPDATA", "") + "/osu!"]
    return []


def stable_root() -> Path | None:
    """Stable install root; None on platforms without stable support."""
    if os.name != "nt" and not get("stable_root", "OSU_STABLE_ROOT", None):
        return None
    return _resolve("OSU_STABLE_ROOT", "stable_root", _stable_candidates(),
                    os.environ.get("LOCALAPPDATA", "") + "/osu!")


def stable_songs() -> Path | None:
    root = stable_root()
    return root / "Songs" if root else None


def stable_replays() -> Path | None:
    root = stable_root()
    return root / "Replays" if root else None


# -------------------------------------------------- project folders + out ----

def replays_dir() -> Path:
    return _path(str(get("replays_dir", "OSU_REPLAYS_DIR", "replays")))


def maps_dir() -> Path:
    return _path(str(get("maps_dir", "OSU_MAPS_DIR", "maps")))


def outdir() -> Path:
    return _path(str(get("outdir", "OSU_OUTDIR", "out")))


def cache_dir() -> Path:
    return _path(str(get("cache_dir", "OSU_CACHE_DIR",
                         "~/.cache/osu-critique")))


# ------------------------------------------------------------- BYOK keys ----

def llm_key() -> str | None:
    return get("llm_key", "OSU_LLM_KEY") or None


def llm_base_url() -> str:
    return str(get("llm_base_url", "OSU_LLM_BASE_URL",
                   "https://api.deepseek.com"))


def llm_model() -> str:
    return str(get("llm_model", "OSU_LLM_MODEL", "deepseek-v4-flash"))


def osu_client_id() -> str | None:
    return get("osu_client_id", "OSU_CLIENT_ID") or None


def osu_client_secret() -> str | None:
    return get("osu_client_secret", "OSU_CLIENT_SECRET") or None


def allow_scrape() -> bool:
    """Whether the unofficial HTML profile fallback is permitted (opt-in)."""
    v = str(get("allow_scrape", "OSU_ALLOW_SCRAPE", "false")).lower()
    return v in ("1", "true", "yes", "on")
