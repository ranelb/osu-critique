"""The digest: window, ingest, history comparison, and the written file."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from osu_critique import digest, index

M = "a" * 32


@pytest.fixture(autouse=True)
def no_real_exporter(monkeypatch):
    """Tests must never read this machine's config, exports dir or osu! DB."""
    monkeypatch.setattr("osu_critique.export.enabled", lambda: False)
    monkeypatch.setattr("osu_critique.digest._export_mtimes", lambda: [])
    monkeypatch.setattr("osu_critique.config.lazer_exports",
                        lambda: Path("/nonexistent/osu-exports"))


def run_doc(tag, replay, played_at, accuracy=0.9, miss=3, n=100, ur_pct=50.0,
            trust=True):
    counts = {"300": n - miss, "100": 0, "50": 0, "miss": miss}
    return {
        "schema_version": 1, "tag": tag, "beatmap_md5": M, "replay_md5": replay,
        "played_at": played_at, "player": "p", "map": "Artist - Title [Insane]",
        "mods": {"RX": False, "AP": False}, "mod_string": "NM",
        "time_scale": 1.0, "difficulty": {"CS": 4, "AR": 9, "OD": 8, "HP": 5},
        "n_objects": n, "n_objects_map": n, "accuracy": accuracy,
        "max_combo": n - 1, "full_combo": False, "ur": ur_pct * 10,
        "ur_pct_of_300_window": ur_pct,
        "hit_error_ms": {"mean": 0.0, "std": 20.0},
        "aim_px": {"mean": 10.0, "mean_norm": 0.4},
        "whiffed_presses": 0,
        "counts_recorded": counts, "counts_detected": counts,
        "trust": {"trustworthy": trust, "abs_delta_total": 0, "judged": n},
        "failed_play": False, "time_base": {"overridden": False},
        "windows_ms": {"300": 25.0, "100": 66.0, "50": 108.0},
        "profile": {"composition": []}, "autopsy": {"shapes": {"classes": []}},
        "aim_mode": {"is_relax": False}, "streams": {"n_segments": 0},
    }


def write_run(outdir: Path, doc: dict) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"{doc['tag']}_metrics.json"
    path.write_text(json.dumps(doc))
    index.upsert_run(doc, path, outdir=outdir)
    return path


def corpus(outdir: Path, n=3, start_day=10):
    for i in range(n):
        write_run(outdir, run_doc(f"r{i}", f"{i:032x}",
                                  f"2026-10-{start_day + i:02d}T20:00:00",
                                  accuracy=0.80 + i * 0.03,
                                  miss=5 - i, ur_pct=60.0 - i * 3))
    return outdir


def test_render_names_the_numbers_and_the_window():
    doc = {"generated": "2026-10-24T19:00:00", "window_from": "2026-10-20T10:00:00",
           "n_runs": 1, "n_maps": 1,
           "runs": [{"when": "2026-10-21 20:00", "map": "A - B [Ins]",
                     "mods": "NM", "accuracy": 0.91, "ur": 120.0, "miss": 2,
                     "trust": True}],
           "history": {"n": 40, "timing_pct": 71.0, "timing_median": 70.0,
                       "miss_pct": 44.0, "miss_median": 3.7},
           "maps": [], "ingest": {"analysed": 1, "known": 0, "failed": 0,
                                  "seconds": 0.4}}
    text = digest.render(doc)
    assert "1 new play over 1 map" in text
    assert "since 2026-10-20 10:00" in text
    assert "91.00%" in text
    assert "71%" in text and "44%" in text
    assert "no model was called" in text


def test_build_writes_a_file_and_moves_the_marker(tmp_path):
    out = corpus(tmp_path / "out")
    doc = digest.build(outdir=out, since="2026-10-01T00:00:00", ingest_first=False)
    assert doc["n_runs"] == 3
    assert doc["n_maps"] == 1
    path = Path(doc["path"])
    assert path.is_file() and path.parent.name == "digests"
    assert "3 new plays" in path.read_text()
    assert digest.last_digest(out)[0] == doc["generated"]


def test_second_build_says_nothing_new(tmp_path):
    out = corpus(tmp_path / "out")
    digest.build(outdir=out, since="2026-10-01T00:00:00", ingest_first=False)
    again = digest.build(outdir=out, ingest_first=False)
    assert again["n_runs"] == 0
    assert "Nothing new" in again["markdown"]


def test_stdout_mode_writes_nothing(tmp_path):
    out = corpus(tmp_path / "out")
    doc = digest.build(outdir=out, since="2026-10-01T00:00:00",
                       ingest_first=False, write=False)
    assert "path" not in doc
    assert not (out / "digests").exists()


def test_history_compares_only_prior_runs(tmp_path):
    out = tmp_path / "out"
    for i in range(12):                       # history: spread 80..91%
        write_run(out, run_doc(f"h{i}", f"h{i:031d}",
                               f"2026-09-{i + 1:02d}T20:00:00",
                               ur_pct=80.0 + i))
    write_run(out, run_doc("new", "n" * 32, "2026-10-20T20:00:00", ur_pct=52.0))
    doc = digest.build(outdir=out, since="2026-10-01T00:00:00", ingest_first=False)
    assert doc["history"]["n"] == 12
    assert doc["history"]["timing_pct"] is not None   # the feed draws a meter
    # 52 is lower (better) than all twelve 80..91 values
    assert doc["history"]["timing_pct"] == pytest.approx(100.0)
    assert "better than **100%**" in doc["markdown"]


def test_ingest_skips_known_replays_and_analyses_new_ones(tmp_path, monkeypatch):
    out = tmp_path / "out"
    write_run(out, run_doc("known", "k" * 32, "2026-10-01T20:00:00"))
    exports = tmp_path / "exports"
    exports.mkdir()
    known = exports / "known.osr"
    fresh = exports / "Artist - Title [Insane] (2026-10-20_20-00).osr"
    known.write_bytes(b"x")
    fresh.write_bytes(b"y")
    map_file = exports / "map.osu"
    map_file.write_text("osu file format v14")

    monkeypatch.setattr("osu_critique.io.pairing.pair_all",
                        lambda replay_filter=None: [
                            ("lazer", str(known), str(map_file)),
                            ("lazer", str(fresh), str(map_file))])
    monkeypatch.setattr(digest, "_replay_md5",
                        lambda p: "k" * 32 if p.endswith("known.osr") else "f" * 32)

    def fake_analyze(replay_path, map_path, tag="run", outdir=None, console=False,
                     do_charts=False, **kw):
        write_run(Path(outdir), run_doc(tag, "f" * 32, "2026-10-20T20:00:00"))
        return {}

    monkeypatch.setattr("osu_critique.report.analyze", fake_analyze)
    stats = digest.ingest(out, since_epoch=0, quiet=True)
    assert stats["candidates"] == 2
    assert stats["known"] == 1
    assert stats["analysed"] == 1
    assert stats["tags"] == ["Insane_2026-10-20_2000"]
    assert index.connect(out / index.DB_FILENAME).execute(
        "SELECT COUNT(*) FROM runs WHERE replay_md5 = ?", ("f" * 32,)).fetchone()[0] == 1


def test_ingest_respects_the_mtime_window(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    exports = tmp_path / "exports"
    exports.mkdir()
    old = exports / "old.osr"
    old.write_bytes(b"x")
    os.utime(old, (1_600_000_000, 1_600_000_000))
    monkeypatch.setattr("osu_critique.io.pairing.pair_all",
                        lambda replay_filter=None: [
                            p for p in [("lazer", str(old), "map")]
                            if replay_filter is None or replay_filter(p[1])])
    assert digest.ingest(out, since_epoch=1_700_000_000, quiet=True)["candidates"] == 0
    assert digest.ingest(out, since_epoch=0, quiet=True)["candidates"] == 1


def test_load_digests_is_newest_first(tmp_path):
    out = corpus(tmp_path / "out")
    digest.build(outdir=out, since="2026-10-01T00:00:00", ingest_first=False)
    items = digest.load_digests(out)
    assert len(items) == 1
    assert items[0]["name"].endswith(".md")
    assert "Digest —" in items[0]["text"]


def test_build_writes_a_json_sidecar_for_the_feed(tmp_path):
    out = corpus(tmp_path / "out")
    doc = digest.build(outdir=out, since="2026-10-01T00:00:00", ingest_first=False)
    stem = Path(doc["path"]).with_suffix("")
    assert stem.with_suffix(".md").is_file()
    side = json.loads(stem.with_suffix(".json").read_text())
    for key in ("generated", "n_runs", "runs", "history", "maps", "best", "worst"):
        assert key in side
    assert "markdown" not in side and "path" not in side
    assert side["best"]["accuracy"] >= side["worst"]["accuracy"]

    items = digest.load_digests(out)
    assert items[0]["data"]["n_runs"] == 3
    assert "worth" in items[0]["data"]          # a view concern, added on load
    assert [w["md5"] for w in items[0]["data"]["worth"]] == [M]


# ---------------------------------------------------------- the watermark ----

def test_ingest_watermark_is_the_newest_file_not_now(tmp_path, monkeypatch):
    """The bug that lost a night: a marker set to "now" skips older exports."""
    out = tmp_path / "out"
    out.mkdir()
    exports = tmp_path / "exports"
    exports.mkdir()
    old = exports / "old.osr"
    old.write_bytes(b"x")
    os.utime(old, (1_700_000_000, 1_700_000_000))
    monkeypatch.setattr("osu_critique.config.lazer_exports", lambda: exports)
    monkeypatch.setattr("osu_critique.io.pairing.pair_all",
                        lambda replay_filter=None: [])
    monkeypatch.setattr("osu_critique.digest._export_mtimes",
                        lambda: [1_700_000_000.0])
    stats = digest.ingest(out, since_epoch=1_600_000_000, quiet=True)
    assert stats["watermark"] == pytest.approx(1_700_000_000)
    assert stats["watermark"] != pytest.approx(datetime.now().timestamp(), abs=1000)


def test_a_summarise_only_digest_does_not_advance_the_ingest_watermark(tmp_path):
    out = corpus(tmp_path / "out")
    (out / "digests").mkdir()
    (out / "digests" / ".ingest").write_text("1000.000\n")
    digest.build(outdir=out, since="2026-10-01T00:00:00", ingest_first=False,
                 quiet=True)
    # untouched: the next ingest still looks at everything newer than 1000
    assert digest.last_ingest(out) == pytest.approx(1000.0)


def test_legacy_folders_fall_back_to_the_old_marker(tmp_path):
    out = tmp_path / "out"
    (out / "digests").mkdir(parents=True)
    marker = out / "digests" / ".last"
    marker.write_text("2026-10-20T10:00:00\n")
    os.utime(marker, (1_650_000_000, 1_650_000_000))
    assert digest.last_ingest(out) == pytest.approx(1_650_000_000)


# --------------------------------------------------------------- export -----

def test_the_digest_exports_first_when_enabled(tmp_path, monkeypatch):
    out = corpus(tmp_path / "out")
    calls = {}

    def fake_run(**kwargs):
        calls["ran"] = True
        return {"ok": True, "exported": 3, "total": 10, "beatmaps": 4,
                "seconds": 1.0, "pruned": []}

    monkeypatch.setattr("osu_critique.export.enabled", lambda: True)
    monkeypatch.setattr("osu_critique.export.run", fake_run)
    monkeypatch.setattr("osu_critique.digest.ingest",
                        lambda *a, **k: {"candidates": 0, "analysed": 0,
                                         "known": 0, "failed": 0, "seconds": 0.0,
                                         "tags": [], "watermark": 0.0})
    doc = digest.build(outdir=out, since="2026-10-01T00:00:00", write=False,
                       quiet=True)
    assert calls.get("ran")
    assert doc["export"]["exported"] == 3
    assert "Exported 3 replays from osu! first." in doc["markdown"]


def test_an_export_failure_is_reported_not_fatal(tmp_path, monkeypatch):
    out = corpus(tmp_path / "out")
    from osu_critique.export import ExportError

    def boom(**kwargs):
        raise ExportError("no BeatmapExporter found")

    monkeypatch.setattr("osu_critique.export.enabled", lambda: True)
    monkeypatch.setattr("osu_critique.export.run", boom)
    monkeypatch.setattr("osu_critique.digest.ingest",
                        lambda *a, **k: {"candidates": 0, "analysed": 0,
                                         "known": 0, "failed": 0, "seconds": 0.0,
                                         "tags": [], "watermark": 0.0})
    doc = digest.build(outdir=out, since="2026-10-28T00:00:00", write=False,
                       quiet=True)
    assert "No replays to read: no BeatmapExporter found" in doc["markdown"]


def test_an_empty_window_says_why(tmp_path):
    out = corpus(tmp_path / "out")
    doc = digest.build(outdir=out, since="2026-12-01T00:00:00",
                       ingest_first=False, write=False, quiet=True)
    assert doc["n_runs"] == 0
    assert "Nothing new" in doc["markdown"]
    assert "export.enabled: true" in doc["markdown"]


def test_a_play_exported_late_still_counts_as_new(tmp_path, monkeypatch):
    """The reported bug: play at 21:00, digest at 22:34, export at 22:58.

    The play predates the marker and the previous digest covered nothing, so a
    timestamp-only window drops it. The freshly ingested tag is what catches it.
    """
    out = corpus(tmp_path / "out")
    late = run_doc("late", "l" * 32, "2026-10-20T21:00:00", accuracy=0.93)
    write_run(out, late)
    # a digest ran afterwards, over an older corpus, and covered up to the 18th
    (out / "digests").mkdir()
    (out / "digests" / ".last").write_text("2026-10-22T22:34:00\n")
    digest.window_path(out).write_text(json.dumps({"played_at": "2026-10-18T00:00:00"}))

    monkeypatch.setattr("osu_critique.digest.ingest",
                        lambda *a, **k: {"candidates": 1, "analysed": 1, "known": 0,
                                         "failed": 0, "seconds": 0.1,
                                         "tags": ["late"], "watermark": 0.0})
    doc = digest.build(outdir=out, ingest_first=True, write=False, quiet=True)
    assert doc["n_runs"] == 1
    assert doc["runs"][0]["when"].startswith("2026-10-20")
