"""Configuration: paths to replay/map sources, overridable via environment.

Defaults match a typical Linux setup with osu!lazer (Flatpak) and danser.
Override any of them with the OSU_* environment variables listed below.
"""
from __future__ import annotations

import os
from pathlib import Path


def _env_path(name: str, default: str) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else Path(default).expanduser()


# danser replay folder + beatmap library
DANSER_REPLAYS = _env_path("OSU_DANSER_REPLAYS", "~/Documents/Danser/Replays")
DANSER_SONGS = _env_path("OSU_DANSER_SONGS", "~/Documents/Danser/Songs")

# osu!lazer data root (Flatpak layout on Linux)
LAZER_DATA = _env_path("OSU_LAZER_DATA", "~/.var/app/sh.ppy.osu/data/osu")
LAZER_EXPORTS = _env_path("OSU_LAZER_EXPORTS", str(LAZER_DATA / "exports"))
LAZER_FILES = _env_path("OSU_LAZER_FILES", str(LAZER_DATA / "files"))
ONLINE_DB = _env_path("OSU_ONLINE_DB", str(LAZER_DATA / "online.db"))

# output directory for metrics JSON + charts
DEFAULT_OUTDIR = Path(os.environ.get("OSU_OUTDIR", "out"))
