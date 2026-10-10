"""Prompt/coach tests (no network, no API keys)."""
import json

from osu_critique.coach import SYSTEM_PROMPT, build_user_message, load_system_prompt


def test_system_prompt_encodes_framework():
    assert "You are an osu! gameplay analyst" in SYSTEM_PROMPT
    for marker in ("Critique framework", "UR", "Whiffed presses", "Streams",
                   "How it breaks down", "rank_status", "failed_play",
                   "map_version_mismatch", "relax"):
        assert marker in SYSTEM_PROMPT


def test_load_system_prompt_override(tmp_path):
    p = tmp_path / "mine.txt"
    p.write_text("Custom framework")
    assert load_system_prompt(str(p)) == "Custom framework"
    assert load_system_prompt() == SYSTEM_PROMPT


def test_build_user_message_includes_data():
    metrics = {"accuracy": 0.9, "counts_detected": {"300": 10}}
    msg = build_user_message(metrics)
    assert "## Metrics" in msg and "accuracy" in msg
    msg_b = build_user_message(metrics, baseline={"accuracy": 0.8})
    assert "## Baseline" in msg_b
    msg_p = build_user_message(metrics, profile={"username": "tester"})
    assert "## Player profile" in msg_p and "tester" in msg_p


def test_prompt_cli(tmp_path, capsys):
    """osu-critique prompt <metrics.json> prints system + data."""
    from osu_critique.cli import main
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"accuracy": 0.9}))
    assert main(["prompt", str(m)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("You are an osu! gameplay analyst")
    assert "## Metrics" in out


def test_compact_keeps_the_analytic_tail():
    """The old 12k cap truncated every run after the aim block, so the model
    never saw streams/breakdown/tapping. The slimmer keeps them."""
    from osu_critique.coach import _compact
    seg = {"t_start": 1, "t_end": 2, "n": 8, "miss": 0, "std_err": 1.0,
           "alt_ratio": 0.9, "gap_ms": 100.0, "notes_per_s": 10.0}
    metrics = {
        "accuracy": 0.9,
        "streams": {"segments": [{**seg, "std_err": i} for i in range(200)],
                    "notes": 10},
        "breakdown": {"cliff": 2.5, "knee": 1.5, "cascades": [], "ramp": None},
        "tapping": {"alt_ratio": 0.95},
    }
    s = _compact(metrics)
    assert "truncated" not in s
    assert '"breakdown"' in s and '"tapping"' in s
    assert '"segments_shown"' in s
    assert len(metrics["streams"]["segments"]) == 200   # input untouched


def test_enrich_rows_joins_the_corpus_caches(tmp_path):
    from osu_critique.coach import enrich_rows
    md5, rid = "a" * 32, "r1"
    osu = tmp_path / "m.osu"
    osu.write_text("[Metadata]\nBeatmapID:777\n")
    (tmp_path / "lazer_md5_index.json").write_text(json.dumps({md5: str(osu)}))
    (tmp_path / "stars_by_md5.json").write_text(json.dumps(
        {md5: {"NM": 5.0, "DT": 6.5}}))
    (tmp_path / "pp_by_replay.json").write_text(json.dumps(
        {rid: {"pp": 123.4}}))
    (tmp_path / "beatmap_status.json").write_text(json.dumps(
        {"777": {"status": "ranked"}}))
    m = {"beatmap_md5": md5, "replay_md5": rid, "mod_string": "DT"}
    enrich_rows([("t", m)], str(tmp_path))
    assert m["sr"] == {"base": 5.0, "effective": 6.5}
    assert m["pp"]["pp"] == 123.4
    assert m["rank_status"] == "ranked"
    # no caches at all: silently no-op, never raises
    plain = {"beatmap_md5": md5, "replay_md5": rid}
    enrich_rows([("t", plain)], str(tmp_path / "nope"))
    assert "sr" not in plain
