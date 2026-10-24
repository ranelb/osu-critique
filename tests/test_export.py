"""The opt-in exporter: keystrokes, gating, hashes, and parsing the output."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

from osu_critique import export


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OSU_EXPORT_ENABLED", raising=False)
    monkeypatch.setattr(export, "enabled", lambda: False)
    with pytest.raises(export.ExportError, match="disabled"):
        export.run()


def test_keystrokes_reset_the_filter_when_no_status_is_asked_for(monkeypatch):
    monkeypatch.setattr(export, "statuses", lambda: [])
    assert export.plan_input() == b"5\nreset\n\n1\n0\n"
    assert export.plan_input(["ranked", "loved"]) == b"5\nstatus ranked,loved\n\n1\n0\n"


def test_unknown_status_is_refused_before_it_reaches_the_menu(monkeypatch):
    monkeypatch.setattr(export, "statuses", lambda: [])
    with pytest.raises(export.ExportError, match="unknown status"):
        export.plan_input(["wip"])


def test_run_parses_the_exporter_output(tmp_path, monkeypatch):
    fake = tmp_path / "BeatmapExporterCLI"
    fake.write_text("#!/bin/sh\n"
                    "printf 'Exported 2/10 score replays from 3 beatmaps to %s\\n' \"$DEST\"\n"
                    "printf 'Select operation: '\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(export, "enabled", lambda: True)
    monkeypatch.setattr(export, "binary_path", lambda: fake)
    monkeypatch.setattr(export, "statuses", lambda: [])
    monkeypatch.setenv("DEST", str(tmp_path / "out"))
    monkeypatch.setattr("osu_critique.config.lazer_exports", lambda: tmp_path / "exports")
    (tmp_path / "exports").mkdir()
    result = export.run(timeout=20)
    assert result["ok"] is True
    assert result["exported"] == 2
    assert result["total"] == 10
    assert result["beatmaps"] == 3
    assert result["dest"] == str(tmp_path / "out")


def test_pruning_only_touches_other_players(tmp_path, monkeypatch):
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "me A rank on x.osr").write_bytes(b"a")
    (exports / "other B rank on y.osr").write_bytes(b"b")
    fake = tmp_path / "be"
    fake.write_text("#!/bin/sh\necho 'Exported 0/0 score replays from 0 beatmaps to /nowhere'\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(export, "enabled", lambda: True)
    monkeypatch.setattr(export, "binary_path", lambda: fake)
    monkeypatch.setattr("osu_critique.config.lazer_exports", lambda: exports)
    result = export.run(timeout=20, prune_player="me")
    assert result["pruned"] == ["other B rank on y.osr"]
    assert (exports / "me A rank on x.osr").exists()


def test_install_verifies_the_hash(tmp_path, monkeypatch):
    payload = b"fake binary bytes"
    good = hashlib.sha256(payload).hexdigest()
    manifest = {"version": "v0", "assets": {
        "test-key": {"name": "be", "size": len(payload), "sha256": good}}}
    monkeypatch.setattr(export, "MANIFEST", manifest)
    monkeypatch.setattr(export, "platform_key", lambda: "test-key")
    monkeypatch.setattr(export, "bin_dir", lambda: tmp_path / "bin")

    def download(url, dest, timeout=120):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)

    monkeypatch.setattr(export, "_download", download)
    path = export.install()
    assert path.read_bytes() == payload
    assert os.access(path, os.X_OK)

    bad = dict(manifest)
    bad["assets"] = {"test-key": dict(manifest["assets"]["test-key"], sha256="0" * 64)}
    monkeypatch.setattr(export, "MANIFEST", bad)
    with pytest.raises(export.ExportError, match="could not install"):
        export.install(force=True)
    assert not (tmp_path / "bin" / "be").exists()


def test_status_is_jsonable(monkeypatch, tmp_path):
    monkeypatch.setattr(export, "statuses", lambda: [])
    monkeypatch.setattr("osu_critique.config.lazer_exports", lambda: tmp_path)
    doc = export.status()
    assert doc["enabled"] in (True, False)
    assert doc["exports_dir"] == str(tmp_path)
    assert doc["statuses"] == ["<all>"]
    assert doc["manifest_version"].startswith("v")
