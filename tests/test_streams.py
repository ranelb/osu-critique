"""Stream detection by rhythm + velocity continuity (the spacing proxy retired).

The old rule was ">=4 consecutive circles with <=4r spacing". These tests pin the
two ways it misfired: it rejected wide-but-tight patterns (MONTAGEM's runs are ~6r
wide, so it found 0 segments there) and it accepted runs whose *spacing* was
small while the required speed swung wildly (spacing is a proxy for speed that
only works when the gap is constant - which is exactly when it is not needed).
"""
import pytest

from osu_critique.metrics import streams as S
from osu_critique.metrics import profile as P


def row(t, kind="Circle", spacing=2.0, result="300", error=0.0, key="A"):
    return {"t": float(t), "kind": kind, "spacing_r": spacing, "pattern": "stream",
            "result": result, "error": error, "aim": 5.0, "key": key,
            "end": float(t), "cursor_speed": 0.02, "snap": 1.0, "bpm": 180.0,
            "bpm_eff": 180.0, "angle_deg": 0.0, "strain_aim": 1.0,
            "strain_speed": 1.0}


def steady(n, gap_ms=100.0, spacing=2.0, kind="Circle", start=1000.0):
    """``n`` objects in a run: the first object of a play has no gap to join with."""
    return [row(start + i * gap_ms, kind=kind, spacing=spacing)
            for i in range(n + 1)]


def old_streams(rows):
    """The retired rule, kept here so the misfire stays visible and testable."""
    runs, run = [], []
    for x in rows:
        if x["kind"] == "Circle" and x["pattern"] in ("stream", "dense"):
            run.append(x)
        else:
            if len(run) >= 4:
                runs.append(run)
            run = []
    if len(run) >= 4:
        runs.append(run)
    return runs


# ------------------------------------------------------------- detection ----

def test_a_steady_run_is_one_segment_with_its_material_reported():
    segs = S.stream_stats(steady(8, gap_ms=115.0, spacing=5.0))
    assert len(segs) == 1
    seg = segs[0]
    assert seg["n"] == 8
    assert seg["gap_ms"] == pytest.approx(115.0)
    assert seg["velocity_r_ms"] == pytest.approx(5.0 / 115.0, rel=1e-6)
    assert seg["notes_per_s"] == pytest.approx(1000.0 / 115.0, rel=0.05)
    assert seg["kinds"] == {"Circle": 8}


def test_slider_interleaved_runs_are_found_now():
    """The old rule saw 0 segments here: >=4r spacing and every other a slider."""
    rows = [row(1000 + i * 90.0, kind="Circle" if i % 2 == 0 else "Slider",
                spacing=5.0) for i in range(8)]
    assert old_streams(rows) == []                       # blind
    segs = S.stream_stats(rows)
    # the run is the 7 objects that have a gap to the object before them
    assert len(segs) == 1 and segs[0]["n"] == 7
    assert segs[0]["kinds"] == {"Circle": 3, "Slider": 4}


def test_swinging_required_speed_is_not_a_stream():
    """Steady gaps, spacing 1r <-> 3.9r: the old rule accepts, the new one does not.

    Speed is spacing/dt, so a 4x spacing swing at a constant gap is a 4x speed
    swing - the pattern is filler and bursts welded together, not a stream.
    """
    rows = [row(1000 + i * 100.0, spacing=1.0 if i % 2 == 0 else 3.9)
            for i in range(8)]
    assert len(old_streams(rows)) == 1                   # spacing <= 4r, circles
    assert S.stream_stats(rows) == []                    # velocity continuity


def test_a_run_that_stops_being_steady_is_split():
    rows = steady(5, gap_ms=100.0) + steady(5, gap_ms=400.0, start=2400.0)
    segs = S.stream_stats(rows)
    assert [s["n"] for s in segs] == [5]                 # the slow tail is not a run


def test_slow_runs_are_not_streams():
    assert S.stream_stats(steady(8, gap_ms=400.0)) == []


def test_a_spinner_breaks_a_run():
    rows = (steady(3, gap_ms=100.0)
            + [row(1400, kind="Spinner", spacing=0.0)]
            + [row(1600 + i * 100.0) for i in range(3)])
    assert S.stream_stats(rows) == []                    # 3 + 3, nothing sustained


def test_the_run_keeps_its_timing_and_alternation_numbers():
    rows = steady(6, gap_ms=100.0)
    rows[2]["result"] = "miss"
    rows[2]["error"] = None
    for i, r in enumerate(rows):
        r["key"] = "A" if i % 2 == 0 else "B"
    seg = S.stream_stats(rows)[0]
    assert seg["miss"] == 1
    assert seg["std_err"] == pytest.approx(0.0, abs=1e-9)
    assert seg["alt_ratio"] == pytest.approx(1.0)
    assert seg["key_pattern"] == "BABABA"      # the run starts at the second object


# ------------------------------------------------------- shared primitive ---

def test_find_runs_without_the_velocity_term_is_the_historical_chains_rule():
    rows = ([row(900)]                                    # anchor: no run of its own
            + [row(t) for t in (1000, 1100, 1200, 1300)]
            + [row(t) for t in (1700, 1800, 1900, 2000, 2100)])
    runs = S.find_runs(rows, velocity_tolerance=None, break_kinds=())
    assert [len(r) for r in runs] == [4, 4]
    # and that is what profile.chains reports
    ch = P._chains(rows)
    assert ch["n_chains"] == 2 and ch["notes"] == 8
    assert ch["by_position"][0]["n"] == 8


def test_profile_chains_and_streams_share_the_primitive():
    rows = steady(6, gap_ms=150.0, spacing=2.0)
    assert P._chains(rows)["n_chains"] == 1
    assert len(S.stream_stats(rows)) == 1


# -------------------------------------------------------------- summarise ---

def test_summarise_aggregates_the_material():
    rows = steady(6, gap_ms=100.0, spacing=2.0)
    segs = S.stream_stats(rows)
    s = S.summarise(segs)
    assert s["notes"] == 6 and s["misses"] == 0
    assert s["gap_ms_median"] == pytest.approx(100.0)
    assert s["notes_per_s_p50"] == pytest.approx(10.0, rel=0.05)
    assert s["velocity_r_ms_p50"] == pytest.approx(0.02, rel=1e-6)
    assert s["kinds"] == {"Circle": 6}
    empty = S.summarise([])
    assert empty["notes"] == 0 and empty["gap_ms_median"] is None


# ------------------------------------------------------------- in a play ----

def test_the_metrics_carry_the_new_stream_fields(tmp_path):
    from osu_critique.report import analyze
    m = analyze("tests/fixtures/aaaaa.osr", "tests/fixtures/aaaaa.osu",
                tag="aaaaa", outdir=str(tmp_path), console=False,
                write_objects=False)
    st = m["streams"]
    for k in ("n_segments", "segments", "notes", "misses", "gap_ms_median",
              "notes_per_s_p50", "velocity_r_ms_p50", "kinds"):
        assert k in st, k
    assert st["notes"] == sum(s["n"] for s in st["segments"])
