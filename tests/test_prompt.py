"""Prompt/coach tests (no network, no API keys)."""
import json

from osu_critique.coach import SYSTEM_PROMPT, build_user_message, load_system_prompt


def test_system_prompt_encodes_framework():
    assert "You are an osu! gameplay analyst" in SYSTEM_PROMPT
    for marker in ("Critique framework", "UR", "Whiffed presses", "Streams",
                   "failed_play", "map_version_mismatch", "relax"):
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
