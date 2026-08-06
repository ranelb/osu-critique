"""Golden regression tests: the pipeline must reproduce the game's recorded
hit counts on known-good replays.

Fixtures live in tests/fixtures/ (committed; they are the author's own
replays — remove the directory if you don't want them public, and the tests
fall back to OSU_TEST_* env vars, then skip).
"""
import os
import json
from pathlib import Path

import pytest

from osu_critique.report import analyze
import slider

FIX = Path(__file__).parent / "fixtures"

CASES = [
    # name, replay env, map env, default replay, default map, expected counts
    (
        "deafheaven",
        "OSU_TEST_DEAFHEAVEN_REPLAY",
        "OSU_TEST_DEAFHEAVEN_MAP",
        str(FIX / "deafheaven.osr"),
        str(FIX / "deafheaven.osu"),
        {"300": 503, "100": 74, "50": 8, "miss": 31},
    ),
    (
        "domino",
        "OSU_TEST_DOMINO_REPLAY",
        "OSU_TEST_DOMINO_MAP",
        str(FIX / "domino.osr"),
        str(FIX / "domino.osu"),
        {"300": 208, "100": 22, "50": 1, "miss": 0},
    ),
    (
        "aaaaa",
        "OSU_TEST_AAAA_REPLAY",
        "OSU_TEST_AAAA_MAP",
        str(FIX / "aaaaa.osr"),
        str(FIX / "aaaaa.osu"),
        {"300": 65, "100": 0, "50": 0, "miss": 0},
    ),
]


def _resolve(name, default_replay, default_map):
    """Fixture first, then env, then default path; returns (replay, map) Paths."""
    replay, map_path = FIX / f"{name}.osr", FIX / f"{name}.osu"
    if replay.exists() and map_path.exists():
        return replay, map_path
    env = {"deafheaven": ("OSU_TEST_DEAFHEAVEN_REPLAY", "OSU_TEST_DEAFHEAVEN_MAP"),
           "domino": ("OSU_TEST_DOMINO_REPLAY", "OSU_TEST_DOMINO_MAP"),
           "aaaaa": ("OSU_TEST_AAAA_REPLAY", "OSU_TEST_AAAA_MAP")}[name]
    r_env, m_env = os.environ.get(env[0]), os.environ.get(env[1])
    if r_env and m_env:
        return Path(r_env).expanduser(), Path(m_env).expanduser()
    return (Path(default_replay).expanduser(), Path(default_map).expanduser())


@pytest.mark.parametrize("name,env_r,env_m,default_r,default_m,expected", CASES)
def test_golden(name, env_r, env_m, default_r, default_m, expected, tmp_path):
    replay, map_path = _resolve(name, default_r, default_m)
    if not replay.exists() or not map_path.exists():
        pytest.skip(f"fixtures for {name} not present")
    metrics = analyze(str(replay), str(map_path), tag=name,
                      outdir=str(tmp_path), console=False)
    det = metrics["counts_detected"]
    for k in ("300", "100", "50"):
        assert abs(det[k] - expected[k]) <= max(4, 0.02 * expected["300"]), \
            f"{k}: detected {det} vs recorded {expected}"
    assert abs(det["miss"] - expected["miss"]) <= 8, \
        f"miss: detected {det} vs recorded {expected}"


def test_scale_calibration_domino(tmp_path):
    """Domino's .osr claims DT but the frames are in map-time: the calibration
    must pick scale 1.0 and produce ~0 detected misses."""
    case = [c for c in CASES if c[0] == "domino"][0]
    replay, map_path = _resolve("domino", case[3], case[4])
    if not replay.exists() or not map_path.exists():
        pytest.skip("domino fixtures not present")
    metrics = analyze(str(replay), str(map_path), tag="domino",
                      outdir=str(tmp_path), console=False)
    assert metrics["counts_detected"]["miss"] == 0
    assert metrics["accuracy"] > 0.90


# ---------------------------------------------------------------- synth ----

SYNTH = [
    # name, (300, 100, 50), expected miss, extra assertions
    ("synth_clean", (17, 2, 1), 0, {}),
    ("synth_htm", (17, 2, 1), 0, {}),           # HT mod: frames at 4/3 scale
    ("synth_dt", (17, 2, 1), 0, {}),            # DT mod: frames at 2/3 scale
    ("synth_mismatch", (17, 2, 1), 20,          # 20 of 40 objects played
     {"map_version_mismatch": True, "failed_play": True}),
    ("synth_oooframes", (17, 2, 1), 0, {}),     # out-of-order trailing frame
]


@pytest.mark.parametrize("name,expected,expected_miss,extra", SYNTH,
                         ids=[s[0] for s in SYNTH])
def test_synthetic(name, expected, expected_miss, extra, tmp_path):
    replay, map_path = FIX / f"{name}.osr", FIX / f"{name}.osu"
    if not replay.exists() or not map_path.exists():
        pytest.skip(f"{name} not generated (run scripts/make_synthetic_fixtures.py)")
    metrics = analyze(str(replay), str(map_path), tag=name,
                      outdir=str(tmp_path), console=False)
    det = metrics["counts_detected"]
    assert (det["300"], det["100"], det["50"]) == expected, det
    assert det["miss"] == expected_miss, det
    assert metrics["whiffed_presses"] == 0
    for k, v in extra.items():
        assert metrics[k] is v


def test_anonymized_player_name():
    """Real fixtures must not contain the author's username."""
    r = slider.Replay.from_path(FIX / "aaaaa.osr", retrieve_beatmap=False)
    assert r.player_name == "TestPlayer"


def test_report_deterministic(tmp_path):
    """The report tier must work with no keys at all."""
    case = [c for c in CASES if c[0] == "aaaaa"][0]
    replay, map_path = _resolve("aaaaa", case[3], case[4])
    if not replay.exists() or not map_path.exists():
        pytest.skip("aaaaa fixtures not present")
    metrics = analyze(str(replay), str(map_path), tag="aaaaa",
                      outdir=str(tmp_path), console=False)
    from osu_critique.cli import render_report
    text = render_report(metrics)
    assert "Accuracy 100.0%" in text
    assert "Primary target" not in text or "No pattern" in text


def test_coach_missing_metrics_friendly_error(tmp_path):
    """A missing metrics file must produce a helpful RuntimeError, not a traceback."""
    from osu_critique.coach import coach
    import pytest
    with pytest.raises(RuntimeError) as ei:
        coach(str(tmp_path / "nope_metrics.json"))
    assert "run `osu-critique analyze" in str(ei.value)


def test_load_metrics_missing_and_bad(tmp_path):
    from osu_critique.cli import _load_metrics
    import pytest
    with pytest.raises(RuntimeError) as ei:
        _load_metrics(str(tmp_path / "missing.json"))
    assert "analyze" in str(ei.value)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(RuntimeError) as ei:
        _load_metrics(str(bad))
    assert "not valid metrics JSON" in str(ei.value)


def test_multi_run_message_and_dir(tmp_path):
    """coach with a directory builds a cross-run table; --all resolves outdir."""
    from osu_critique.coach import build_multi_user_message, _load_metrics_dir
    # create two fake metrics files
    base = {
        "map": "Test Map", "accuracy": 0.9, "ur": 150.0, "early_pct": 0.5,
        "hit_error_ms": {"mean": 2.0, "std": 15.0},
        "aim_px": {"mean": 10.0, "mean_norm": 0.4},
        "counts_recorded": {"miss": 5}, "whiffed_presses": 10,
        "patterns": {"dense": {"miss_rate": 0.1}, "stream": {"miss_rate": 0.02},
                     "jump": {"miss_rate": 0.01}, "bigjump": {"miss_rate": 0.05}},
        "quarters": [{"miss": 1}, {"miss": 2}, {"miss": 1}, {"miss": 1}],
        "map_version_mismatch": False, "failed_play": False,
    }
    for i in range(2):
        m = dict(base, map=f"Map {i}", accuracy=0.9 - i * 0.05)
        (tmp_path / f"run{i}_metrics.json").write_text(json.dumps(m))
    rows = _load_metrics_dir(str(tmp_path))
    assert len(rows) == 2
    msg = build_multi_user_message(rows)
    assert "## Runs — 2 plays" in msg
    assert "Map 1" in msg and "Map 0" in msg
    assert "dense%" in msg and "Q1-Q4 miss" in msg
    assert "Across these runs" in msg.lower() or "ACROSS these runs" in msg
    # empty dir
    empty = tmp_path / "empty"; empty.mkdir()
    assert _load_metrics_dir(str(empty)) == []


def test_call_chat_deadline_fires(tmp_path, monkeypatch):
    """A stalled LLM response must hit the total deadline instead of hanging."""
    import socket, threading, time
    from osu_critique import coach as coach_mod

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def slow_server():
        conn, _ = srv.accept()
        conn.recv(65536)                      # read request headers/body
        # send headers + a partial chunk, then stall forever
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                     b"Transfer-Encoding: chunked\r\n\r\n")
        conn.sendall(b"5\r\n{abc}\r\n")       # valid-ish first chunk
        time.sleep(30)                        # never finish
        conn.close()

    threading.Thread(target=slow_server, daemon=True).start()
    monkeypatch.setenv("OSU_LLM_TIMEOUT", "3")
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="did not finish within"):
        coach_mod._call_chat("sys", "user", "k", f"http://127.0.0.1:{port}", "m")
    assert time.monotonic() - t0 < 15         # bounded, not infinite
    srv.close()


def test_call_chat_streaming_sse(tmp_path, monkeypatch):
    """SSE chunks are assembled (and streamed) into the final text."""
    import socket, threading
    from osu_critique import coach as coach_mod
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]

    def sse_server():
        conn, _ = srv.accept()
        req = b""
        while b"\r\n\r\n" not in req:
            req += conn.recv(4096)
        # drain the request body (Content-Length) so no unread bytes linger
        # in the socket when we close — otherwise the client sees a reset
        header_end = req.index(b"\r\n\r\n") + 4
        for line in req[:header_end].split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                n = int(line.split(b":")[1].strip())
                while len(req) - header_end < n:
                    req += conn.recv(4096)
        conn.sendall(b"HTTP/1.1 200 OK\r\n"
                     b"Content-Type: text/event-stream\r\n"
                     b"Connection: close\r\n"
                     b"Transfer-Encoding: chunked\r\n\r\n")
        for part in (b'data: {"choices":[{"delta":{"content":"Hi "}}]}\n\n',
                     b'data: {"choices":[{"delta":{"content":"there"}}]}\n\n',
                     b"data: [DONE]\n\n"):
            chunk = hex(len(part))[2:].encode() + b"\r\n" + part + b"\r\n"
            conn.sendall(chunk)
        conn.sendall(b"0\r\n\r\n")          # terminal chunk
        conn.close()

    threading.Thread(target=sse_server, daemon=True).start()
    monkeypatch.setenv("OSU_LLM_TIMEOUT", "10")
    out = coach_mod._call_chat("sys", "user", "k", f"http://127.0.0.1:{port}", "m")
    assert out == "Hi there"
    srv.close()
