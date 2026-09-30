"""The map-profile block: rate, families, stamina, chains, per-family timing."""
import pytest

from osu_critique.metrics import profile as P
from osu_critique.report import analyze

MAP = "tests/fixtures/aaaaa.osu"
REPLAY = "tests/fixtures/aaaaa.osr"


def row(t, kind="Circle", result="300", err=None, spacing=2.0, snap=2.0,
        aim=None, end=None, bpm=200.0, bpm_eff=200.0):
    return {"t": t, "end": t if end is None else end, "x": 100.0, "y": 100.0,
            "kind": kind, "result": result, "error": err, "aim": aim, "key": "A",
            "cursor_speed": 1.0, "spacing_r": spacing, "pattern": "dense",
            "snap": snap, "bpm": bpm, "bpm_eff": bpm_eff, "angle_deg": 10.0,
            "strain_aim": 1.0, "strain_speed": 1.0}


def test_divisor_labels_follow_the_quarter_beat_convention():
    # snap is stored in quarter-beats, so the osu! divisor is 4 / snap
    assert P.beats_label(0.25) == "1/4"
    assert P.beats_label(1 / 3) == "1/3"
    assert P.beats_label(0.5) == "1/2"
    assert P.beats_label(1.0) == "1/1"
    assert P.beats_label(0.125) == "1/8"
    assert P.beats_label(2.0) == "2 beats"            # slower than a beat: say so
    assert P.beats_label(1.5) == "1.5 beats"


def test_family_names_encode_kind_divisor_and_spacing():
    assert P.family(row(1000, snap=1.0, spacing=1.5)) == "circle_1/4_dense"
    assert P.family(row(1000, snap=2.0, spacing=3.0)) == "circle_1/2_spaced"
    assert P.family(row(1000, snap=4.0, spacing=8.0)) == "circle_1/1_jump"
    assert P.family(row(1000, kind="Slider", snap=2.0, spacing=6.0)) == "slider_1/2_jump"
    assert P.family(row(1000, kind="Spinner")) == "spinner"


def test_rate_reports_real_gaps_and_the_window_ratio():
    rows = [row(1000 * i, snap=None if i == 0 else 1.0) for i in range(6)]  # 1 s apart
    prof = P.build_profile(rows, None, 1.0, windows={"300": 50.0})
    rate = prof["rate"]
    assert rate["note_gap_ms"]["median"] == pytest.approx(1000.0)
    assert rate["gap_vs_300_window"]["median_ratio"] == pytest.approx(20.0)
    assert rate["notes_per_second"]["median_gap_based"] == pytest.approx(1.0)
    assert rate["snap_mix"]["1/4"] == 5


def test_chains_need_a_steady_fast_gap_and_report_position():
    rows = [row(1000 + 100 * i, snap=1.0) for i in range(6)]   # a 6-note run at 100 ms
    rows.append(row(5000, snap=4.0))                           # then a break
    rows.append(row(5400, snap=4.0))
    ch = P.build_profile(rows, None, 1.0, windows={"300": 50.0})["chains"]
    assert ch["n_chains"] == 1 and ch["notes"] == 5            # 5 gaps after the first row
    pos = {p["notes"]: p["n"] for p in ch["by_position"]}
    assert pos == {"1-4": 4, "5-8": 1}


def test_stamina_finds_the_longest_run_and_breaks():
    rows = ([row(1000 * i, snap=4.0) for i in range(4)]        # slow start
            + [row(3000 + 100 * i, snap=1.0) for i in range(9)]  # 900 ms of pressure
            + [row(60000, snap=4.0), row(70000, snap=4.0)])      # a long break
    stam = P.build_profile(rows, None, 1.0, windows={"300": 50.0})["stamina"]
    assert stam["longest_sustained"]["notes"] >= 8
    assert stam["longest_sustained"]["seconds"] > 1.0
    assert stam["breaks"], "the 60 s gap must register as a break"


def test_primary_target_ignores_unpopulated_buckets():
    prof = {"composition": [
        {"family": "a", "n": 5, "share": 0.01, "non300": 5, "non300_rate": 1.0},
        {"family": "b", "n": 100, "share": 0.2, "non300": 50, "non300_rate": 0.5},
        {"family": "c", "n": 400, "share": 0.8, "non300": 20, "non300_rate": 0.05},
    ]}
    assert P.primary_target(prof, 500)["family"] == "b"    # 50% vs 14% overall
    prof["composition"][1].update(non300=8, non300_rate=0.08)
    assert P.primary_target(prof, 500) is None             # no longer clearly worse


def test_profile_in_metrics_and_in_the_report(tmp_path):
    if not REPLAY or not MAP:
        pytest.skip("fixtures missing")
    metrics = analyze(REPLAY, MAP, tag="aaaaa", outdir=str(tmp_path), console=False)
    prof = metrics["profile"]
    for key in ("rate", "composition", "sliders", "stamina", "chains",
                "timing_by_family", "context"):
        assert key in prof, key
    assert prof["rate"]["snap_mix"]
    assert sum(f["n"] for f in prof["composition"]) == metrics["n_objects"]
    from osu_critique.cli import render_report
    text = render_report(metrics)
    assert "## Map profile" in text
    assert "bpm effective" in text



def test_sliders_fall_back_to_length_when_pixel_length_is_absent():
    """Some parsed sliders expose only length; the profile must not report 0."""
    import datetime

    class Slider:
        length = 150.0
        repeat = 1
        time = datetime.timedelta(milliseconds=1000)
        end_time = datetime.timedelta(milliseconds=1300)

    class FakeMap:
        def hit_objects(self):
            return [Slider()]

    sl = P._sliders(FakeMap(), 1.0)
    assert sl["n"] == 1
    assert sl["cursor_speed_px_ms"]["median"] == pytest.approx(0.5)
    assert sl["long_path_share"] == 1.0


def test_primary_target_gate_scales_down_on_short_maps():
    prof = {"composition": [
        {"family": "small", "n": 13, "share": 0.07, "non300": 4, "non300_rate": 0.31},
        {"family": "big", "n": 161, "share": 0.93, "non300": 22, "non300_rate": 0.14},
    ]}
    assert P.primary_target(prof, 174)["family"] == "small"    # 31% vs 15% overall
    assert P.primary_target(prof, 1016) is None                # 13 objects is noise there
