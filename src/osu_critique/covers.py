"""Beatmap covers, fetched once from osu!'s asset CDN and cached on disk.

The index knows each beatmap's ``BeatmapSetID`` (parsed from the ``.osu``), and
``assets.ppy.sh`` serves the same cover art the osu! beatmap listing uses. No
API key, no OAuth, one request per map.

A local server must still work on a train, so a failed or disabled fetch is a
placeholder, never an error: the page renders with the map's text and moves on.
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request
from pathlib import Path

#: ``cover@2x`` is the map page's hero (108 KB), ``card@2x`` the 3-column tile
#: (46 KB), and ``thumb`` the 1x card (13 KB) a phone's 64px dense-row thumb and
#: the dimmed picker backgrounds use. Nothing bigger than @2x is downloaded,
#: ever — a listing of 24 tiles was 5 MB before ``thumb`` existed.
SIZES = {"hero": "cover@2x", "card": "card@2x", "thumb": "card"}

#: Bumped when the fetched variant changes. v1 shipped ``fetch`` without a size,
#: so every file it wrote — including "-card.jpg" — was really ``cover@2x``
#: (1800x500): the listing served that for a 64px thumb. v2 re-fetches at the
#: size that was asked for.
CACHE_VERSION = 2
_UA = "osu-critique (local analysis tool)"


def cover_url(set_id: int, size: str = "hero") -> str:
    return f"https://assets.ppy.sh/beatmaps/{int(set_id)}/covers/{SIZES.get(size, SIZES['hero'])}.jpg"


def covers_dir(outdir) -> Path:
    return Path(outdir) / "covers"


def cover_path(outdir, set_id, size: str = "hero") -> Path:
    return covers_dir(outdir) / f"{int(set_id)}-{size}-v{CACHE_VERSION}.jpg"


def enabled() -> bool:
    """``web.cover_cache`` / ``OSU_COVER_CACHE``; on by default."""
    from .config import get

    value = get("web.cover_cache", "OSU_COVER_CACHE", True)
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off")
    return bool(value)


def fetch(set_id, dest: Path, size: str = "hero", timeout: float = 6.0) -> bool:
    """Download one cover variant into ``dest``. False on any failure."""
    try:
        req = urllib.request.Request(cover_url(set_id, size),
                                     headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        if not data:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        return True
    except (urllib.error.URLError, OSError, ValueError, TypeError):
        return False


def ensure(outdir, set_id, size: str = "hero") -> Path | None:
    """The cached cover, fetching it once if allowed. None means "no art".

    A ``.missing`` marker records a CDN 404 so a dead/deleted set is not
    re-fetched on every page load.
    """
    if not set_id:
        return None
    dest = cover_path(outdir, set_id, size)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    marker = dest.with_suffix(dest.suffix + ".missing")
    if marker.exists():
        return None
    if not enabled():
        return None
    if fetch(set_id, dest, size=size):
        # reclaim the v1 file, whose bytes were the hero art under a card name
        legacy = covers_dir(outdir) / f"{int(set_id)}-{size}.jpg"
        if legacy.is_file():
            try:
                legacy.unlink()
            except OSError:
                pass
        return dest
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("")
    except OSError:
        pass
    return None
