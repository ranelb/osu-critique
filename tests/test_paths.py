"""Path resolution and folder-pairing tests (no network, no osu! install)."""
import os
import zipfile
from pathlib import Path

import pytest


def test_probe_picks_first_existing(tmp_path, monkeypatch):
    """Resolution: env override > first existing candidate > fallback."""
    from osu_critique.config import _resolve
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    # existing candidate wins over non-existing one
    assert _resolve("X_ENV", "x", [str(b), str(a)], str(tmp_path / "f")) == a
    # env override wins over everything
    monkeypatch.setenv("X_ENV", str(b))
    assert _resolve("X_ENV", "x", [str(a)], str(tmp_path / "f")) == b
    # nothing exists -> fallback
    assert _resolve("X_ENV2", "x", [str(b)], str(tmp_path / "fallback")) == tmp_path / "fallback"


def test_stable_is_windows_only(monkeypatch):
    from osu_critique import config
    monkeypatch.setattr(config.os, "name", "posix")
    assert config.stable_root() is None
    monkeypatch.setattr(config.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", "/fake/localappdata")
    assert config.stable_root() == Path("/fake/localappdata/osu!")


def test_lazer_candidates_cover_linux(monkeypatch):
    """Linux lazer candidates must cover Flatpak and AppImage locations."""
    from osu_critique import config
    monkeypatch.setattr(config.os, "name", "posix")
    cands = config._lazer_candidates()
    assert "~/.var/app/sh.ppy.osu/data/osu" in cands      # Flatpak
    assert "~/.local/share/osu" in cands                  # AppImage
    monkeypatch.setattr(config.os, "name", "nt")
    monkeypatch.setenv("APPDATA", "/fake/appdata")
    cands = config._lazer_candidates()
    assert "/fake/appdata/osu" in cands                   # Windows lazer


def test_osz_extraction(tmp_path):
    """maps/ + .osz archives: .osu content extracted to cache, deduped."""
    import hashlib
    from osu_critique.io.pairing import index_maps_folder
    maps = tmp_path / "maps"
    maps.mkdir()
    (maps / "plain.osu").write_text("osu file format v14\n")
    packed_content = "osu file format v14\n[Metadata]\nTitle:packed\n"
    with zipfile.ZipFile(maps / "packed.osz", "w") as z:
        z.writestr("song.osu", packed_content)
        z.writestr("readme.txt", "ignore me")
    cache = tmp_path / "cache"
    idx = index_maps_folder(maps, cache)
    assert len(idx) == 2                       # plain + packed (different content)
    assert "readme.txt" not in idx
    packed_md5 = hashlib.md5(packed_content.encode()).hexdigest()
    assert idx[packed_md5].startswith(str(cache))
    assert (cache / f"{packed_md5}.osu").exists()


def test_folder_pairing_with_fixtures(tmp_path):
    """replays/ + maps/ end-to-end using the committed golden pair (Domino)."""
    from osu_critique.io.pairing import pair_folders
    fix = Path(__file__).parent / "fixtures"
    replays, maps = tmp_path / "replays", tmp_path / "maps"
    replays.mkdir(), maps.mkdir()
    (replays / "domino.osr").write_bytes((fix / "domino.osr").read_bytes())
    (maps / "domino.osu").write_bytes((fix / "domino.osu").read_bytes())  # bytes: CRLF maps!
    pairs = pair_folders(replays_dir=replays, maps_dir=maps,
                         cache=tmp_path / "cache")
    assert len(pairs) == 1
    rp, mp = pairs[0]
    assert rp.endswith("domino.osr") and mp.endswith("domino.osu")
