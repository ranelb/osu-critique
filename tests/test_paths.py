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
    assert config.stable_root() is None            # no Path created: safe on all Pythons
    assert config._stable_candidates() == []       # no wine candidates on posix


def test_candidate_lists(monkeypatch):
    """Candidate lists (strings only — never instantiate Path under a fake
    os.name; Python 3.11's pathlib dispatches per-instantiation)."""
    from osu_critique import config
    monkeypatch.setattr(config.os, "name", "posix")
    assert "~/.var/app/sh.ppy.osu/data/osu" in config._lazer_candidates()  # Flatpak
    assert "~/.local/share/osu" in config._lazer_candidates()              # AppImage
    monkeypatch.setattr(config.os, "name", "nt")
    monkeypatch.setenv("APPDATA", "/fake/appdata")
    monkeypatch.setenv("LOCALAPPDATA", "/fake/localappdata")
    assert "/fake/appdata/osu" in config._lazer_candidates()               # Windows lazer
    assert config._stable_candidates() == ["/fake/localappdata/osu!"]


def test_env_override_wins(monkeypatch, tmp_path):
    """OSU_STABLE_ROOT / OSU_LAZER_DATA override detection, any platform."""
    from osu_critique import config
    monkeypatch.setenv("OSU_STABLE_ROOT", str(tmp_path / "stable"))
    assert config.stable_root() == tmp_path / "stable"
    monkeypatch.setenv("OSU_LAZER_DATA", str(tmp_path / "lazer"))
    assert config.lazer_data() == tmp_path / "lazer"


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


def test_legacy_osu_prefix_key_alias(tmp_path, monkeypatch):
    """Hand-edited config with 'osu_llm_key' (instead of 'llm_key') must work."""
    from osu_critique import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "config.json")
    (tmp_path / "config.json").write_text('{"osu_llm_key": "sk-legacy"}')
    assert cfg_mod.llm_key() == "sk-legacy"
    # env var still wins over the alias
    monkeypatch.setenv("OSU_LLM_KEY", "sk-env")
    assert cfg_mod.llm_key() == "sk-env"


def test_llm_key_reads_canonical(tmp_path, monkeypatch):
    from osu_critique import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "config.json")
    (tmp_path / "config.json").write_text('{"llm_key": "sk-canon"}')
    assert cfg_mod.llm_key() == "sk-canon"
