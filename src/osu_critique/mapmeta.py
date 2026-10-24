"""Read the parts of a ``.osu`` file the analysis itself never needs.

The pipeline parses hit objects and difficulty and throws the rest away, but a
map page wants the title block and the background image name. This reads those
two sections with the stdlib only — no second beatmap parser, no dependency.

Everything here is best-effort: a malformed or truncated file yields ``None``
fields, never an exception. The index records that as ``metadata_missing``.
"""
from __future__ import annotations

from pathlib import Path

#: ``[Metadata]`` keys we keep, in the order the page renders them.
METADATA_KEYS = ("Title", "TitleUnicode", "Artist", "ArtistUnicode", "Creator",
                 "Version", "Source", "Tags", "BeatmapID", "BeatmapSetID")


def _parse_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _quoted(line: str):
    """The first double-quoted field on a line, or None."""
    start = line.find('"')
    if start < 0:
        return None
    end = line.find('"', start + 1)
    if end < 0:
        return None
    return line[start + 1:end]


def parse_text(text: str) -> dict:
    """Parse ``.osu`` text into the map-page metadata dict.

    Keys: every entry of :data:`METADATA_KEYS` (camel-cased back to the osu!
    spelling minus spaces), plus ``mode``, ``background`` and ``audio``.
    """
    meta: dict = {k: None for k in METADATA_KEYS}
    meta.update({"mode": None, "background": None, "audio": None})
    section = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if section == "General":
            if line.lower().startswith("audiofilename:"):
                meta["audio"] = line.split(":", 1)[1].strip() or None
            elif line.lower().startswith("mode:"):
                meta["mode"] = _parse_int(line.split(":", 1)[1])
        elif section == "Metadata":
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            if key in meta and key not in ("mode", "background", "audio"):
                meta[key] = value.strip() or None
        elif section == "Events":
            # Background: ``0,0,"file.jpg",x,y``. Video is ``1,...``; breaks,
            # storyboard commands and samples are not backgrounds.
            if not line.startswith("0,"):
                continue
            if meta["background"] is None:
                name = _quoted(line)
                if name:
                    meta["background"] = name

    for key in ("BeatmapID", "BeatmapSetID"):
        meta[key] = _parse_int(meta[key])
    return meta


def parse_file(map_path) -> dict:
    """Parse a ``.osu`` from disk. Never raises; returns empty metadata on error."""
    try:
        raw = Path(map_path).read_bytes()
    except OSError:
        return {**{k: None for k in METADATA_KEYS},
                "mode": None, "background": None, "audio": None}
    # osu! writes a UTF-8 BOM on some versions (and the fixtures carry one).
    text = raw.decode("utf-8-sig", errors="replace")
    return parse_text(text)


def display_name(meta: dict, fallback: str | None = None) -> str:
    """``Artist - Title [Version]`` or the fallback (the metrics' ``map``)."""
    artist = meta.get("ArtistUnicode") or meta.get("Artist")
    title = meta.get("TitleUnicode") or meta.get("Title")
    version = meta.get("Version")
    if not artist and not title:
        return fallback or ""
    name = " - ".join(x for x in (artist, title) if x)
    if version:
        name = f"{name} [{version}]"
    return name
