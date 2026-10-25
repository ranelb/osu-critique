"""The report as data: sections, typed items, and the CLI text built from them."""
from __future__ import annotations

from osu_critique.cli import render_report
from osu_critique.report_sections import sections, to_text


def metrics(**over):
    doc = {
        "map": "A - B [Ins]", "accuracy": 0.9, "ur": 150.0, "early_pct": 0.5,
        "counts_recorded": {"300": 80, "100": 15, "50": 2, "miss": 3},
        "counts_detected": {"300": 80, "100": 15, "50": 2, "miss": 3},
        "hit_error_ms": {"mean": -6.3, "std": 13.0, "p10": -20.0, "p90": 8.0,
                         "abs_mean": 11.0},
        "aim_px": {"mean": 12.0, "p90": 20.0, "mean_norm": 0.42},
        "max_combo": 80, "whiffed_presses": 2, "n_objects": 100,
        "key_usage": {"A": 50, "B": 50},
        "trust": {"trustworthy": True, "abs_delta_total": 0, "judged": 100,
                  "abs_delta_pct": 0.0, "count_deltas": {"miss": 0}},
        "time_base": {"overridden": False},
        "profile": {"composition": [
            {"family": "slider_1/2_jump", "n": 40, "share": 0.4, "non300": 8,
             "non300_rate": 0.2, "mean_err_ms": -4.0, "mean_aim_r": 0.4,
             "reported": True}],
            "rate": {"effective_bpm": {"median": 180.0, "min": 176.0, "max": 184.0},
                     "note_gap_ms": {"median": 166.0, "p10": 160.0, "p90": 172.0},
                     "gap_vs_300_window": {"p10_ratio": 6.5}},
            "stamina": {"peak_notes_per_second": 6.4, "seconds_above_6nps": 10.0,
                        "longest_sustained": {"notes": 64, "seconds": 11.0}}},
        "aim_mode": {"n": 100, "window_ms": 320.0,
                     "distance_at_note_r": {"mean": 0.42, "inside_pct": 96.0},
                     "closest_approach_r": {"median": 0.22},
                     "peak_offset_ms": {"median": 8.0, "late_pct": 60.0},
                     "reached_not_on_time": {"n": 4, "pct": 4.0},
                     "error_shape": {"short_pct": 40.0, "past_pct": 35.0},
                     "ceiling": [{"v_lo": 0.0, "v_hi": 1.0, "mean_r": 0.5},
                                 {"v_lo": 2.5, "v_hi": 3.0, "mean_r": 1.2}]},
        "aim_vs_speed": {"slope_r_per_px_ms": 0.06, "r2": 0.05, "bins": []},
        "autopsy": {"shapes": {"classes": [
            {"class": "near-reversal chain", "n": 50, "share": 0.5, "non300": 10,
             "non300_rate": 0.2, "mean_d_r": 0.44, "reported": True}]},
            "arrival_margin_r": {"median": 0.4, "p90": 1.1, "p99": 1.8, "max": 2.1,
                                 "beyond_rim_pct": 12.0, "n": 100},
            "press_vs_arrival_ms": {"median": -9.0, "p10": -25.0, "p90": 6.0,
                                    "pressed_before_arrival_pct": 63.0, "n": 100},
            "legs": {"n": 100, "heading_err_deg": {"median": 2.0, "p90": 7.0,
                                                   "max": 13.0}},
            "stutter": {"n": 6, "presses": 100, "pct": 6.0, "min_early_ms": 30.0,
                        "threshold_r": 1.5},
            "misses": {"n": 1, "rows": [
                {"i": 3, "t": 1300.0, "kind": "Circle", "d_r": 1.5,
                 "closest_r": 0.25, "aim_at_press_r": 1.2, "press_ms": -8.0,
                 "key": "A", "gap_r": 6.0, "turn_deg": 140.0, "speed": 0.4}]}},
        "patterns": {"jump": {"n": 50, "miss": 2, "miss_rate": 0.04,
                              "mean_err": -4.0, "std_err": 12.0}},
        "streams": {"segments": [], "n_segments": 0},
        "breakdown": {"knee": 2.4, "cliff": 3.1, "speed_bins": [
            {"lo": 0.0, "hi": 0.5, "label": "0.0-0.5", "n": 40, "miss": 0,
             "rate": 0.0}]},
        "tapping": {"n": 100, "alt_ratio": 0.97, "same_key_pct": 0.02},
    }
    doc.update(over)
    return doc


def test_sections_are_typed_and_ordered():
    secs = sections(metrics())
    ids = [s["id"] for s in secs]
    assert ids[0] == "summary"
    for expected in ("profile", "timing", "aim", "autopsy", "patterns", "breakdown"):
        assert expected in ids
    for section in secs:
        assert section["title"]
        for item in section["items"]:
            assert item["kind"] in ("kv", "note", "table")
            if item["kind"] == "table":
                assert item["columns"] and isinstance(item["rows"], list)


def test_tables_carry_the_rows_the_web_needs():
    secs = {s["id"]: s for s in sections(metrics())}
    patterns = [i for i in secs["patterns"]["items"] if i["kind"] == "table"][0]
    assert patterns["columns"][0] == "pattern"
    assert patterns["rows"][0][0] == "jump"
    assert len(patterns["columns"]) == 5          # fits a card without scrolling

    tables = [i for i in secs["autopsy"]["items"] if i["kind"] == "table"]
    shapes = next(t for t in tables if t.get("caption", "").startswith("shapes"))
    assert shapes["rows"][0][0] == "near-reversal chain"
    miss_rows = next(t for t in tables if t["columns"][0] == "#")
    assert miss_rows["rows"][0][0] == "#3"

    ceiling = [i for i in secs["aim"]["items"] if i["kind"] == "table"][0]
    assert "aim ceiling" in ceiling["caption"]


def test_the_trust_warning_is_a_tone_not_just_text():
    m = metrics(trust={"trustworthy": False, "abs_delta_total": 30, "judged": 100,
                       "abs_delta_pct": 30.0, "count_deltas": {"miss": 3}})
    summary = sections(m)[0]
    tones = [i.get("tone") for i in summary["items"] if i["kind"] == "note"]
    assert "bad" in tones
    assert any("TRUST:" in i["text"] for i in summary["items"])


def test_the_text_renderer_uses_the_same_sections():
    m = metrics()
    secs = sections(m)
    text = to_text(m, secs)
    for section in secs:
        assert f"## {section['title']}" in text
    assert "bpm effective" in text          # kv value survives
    assert "TIME BASE" not in text          # only when the flag is overridden
    assert text == render_report(m)         # the CLI is the same content


def test_the_cli_report_still_says_what_it_used_to():
    text = render_report(metrics())
    assert "Accuracy 90.0%" in text
    assert "cursor arrival" in text and "there but not then" in text
    assert "aim ceiling" in text
    assert "## Miss autopsy" in text
    assert "shapes (5-note windows)" in text


def test_sections_survive_a_partial_analysis():
    """Five real runs store `legs: null`, empty error_shape and null velocities.

    The old text renderer raised TypeError on them, and the web turned that into
    an empty report. A partial block must degrade, never blank the page.
    """
    m = metrics()
    m["aim_mode"] = {"n": 152, "window_ms": 320.0,
                     "distance_at_note_r": {"mean": 0.42, "inside_pct": 96.0},
                     "closest_approach_r": {}, "peak_offset_ms": {},
                     "reached_not_on_time": {"n": 4, "pct": 4.0},
                     "error_shape": {"short_pct": None, "past_pct": None}}
    m["autopsy"] = {"shapes": {"classes": []}, "arrival_margin_r": None,
                    "press_vs_arrival_ms": None, "legs": None, "stutter": None,
                    "misses": {"n": 0, "rows": []}}
    m["streams"] = {"segments": [{"t_start": 0, "t_end": 5000, "n": 10, "miss": 0,
                                  "std_err": 9.0, "alt_ratio": 0.9}],
                    "gap_ms_median": 120.0, "notes_per_s_p50": None,
                    "velocity_r_ms_p50": None}
    m["profile"]["stamina"] = {"peak_notes_per_second": 6.0}
    m["profile"]["sliders"] = {"n": 10}
    secs = sections(m)
    assert [s["id"] for s in secs][:3] == ["summary", "profile", "timing"]
    text = to_text(m, secs)
    assert "cursor arrival" in text
    assert "there but not then" in text
    assert "None" not in text
