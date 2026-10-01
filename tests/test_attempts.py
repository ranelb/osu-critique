"""Cross-attempt structure: stable weaknesses vs one-off noise.

The reference is the RASPUTIN 09-01 -> 09-22 comparison (docs/ROADMAP.md item 4):
the 1/2 jump buckets roughly halve while the 1/4 dense bucket barely moves. The
published figures (25.3 -> 13.3, 34.3 -> 17.1, 27.7 -> 22.8) predate the 1 ms
edge guard, so the acceptance test pins today's numbers *and* the shape of the
change; the qualitative claim is what the item was written for.
"""
import json
import os

import pytest

from osu_critique.metrics import attempts as A
from osu_critique.cli import main


def fam(name, n, non300):
    return {"family": name, "n": n, "share": 0.1, "non300": int(n * non300),
            "non300_rate": non300, "reported": n >= 10}


def shape(name, n, non300):
    return {"class": name, "n": n, "share": 0.5, "non300": int(n * non300),
            "non300_rate": non300, "reported": n >= 10}


def attempt(tag, f300, n=400, played="2026-09-01T10:00:00", classes=None,
            md5="m" * 32, replay_md5=None, extra_fams=()):
    det = {"300": f300, "100": n - f300, "50": 0, "miss": 0}
    return {
        "tag": tag, "beatmap_md5": md5, "map": "Test Map [X]",
        "replay_md5": replay_md5, "played_at": played, "n_objects": n,
        "accuracy": f300 / n, "counts_detected": det,
        "trust": {"trustworthy": True},
        "profile": {"composition": list(extra_fams)},
        "autopsy": {"shapes": {"classes": classes or []}},
    }


# ----------------------------------------------------------------- group ----

def test_group_orders_by_play_time_and_drops_duplicate_exports():
    a = attempt("a", 300, played="2026-09-22T20:00:00", replay_md5="r1")
    b = attempt("b", 260, played="2026-09-01T08:00:00", replay_md5="r2")
    dup = attempt("b_copy", 260, played="2026-09-01T08:00:00", replay_md5="r2")
    groups = A.group([("a", a), ("b", b), ("b_copy", dup)])
    assert list(groups) == ["m" * 32]
    ms = groups["m" * 32]
    assert [m["tag"] for m in ms] == ["b", "a"]          # oldest first
    assert ms[0]["duplicates"] == ["b_copy"]


def test_group_keeps_both_when_the_replay_hash_is_missing():
    a = attempt("a", 300, played="2026-09-01T08:00:00")
    b = attempt("b", 260, played="2026-09-02T08:00:00")
    ms = A.group([("a", a), ("b", b)])["m" * 32]
    assert [m["tag"] for m in ms] == ["a", "b"]


# --------------------------------------------------------------- compare ----

def test_a_consistent_weakness_is_flagged_and_a_swing_is_not():
    # both attempts: 300 of 400 (so the play is 25% off 300)
    weak = fam("circle_1/2_jump", 60, 0.60)      # 2.4x worse, every attempt
    swing = fam("slider_1/2_jump", 60, 0.10)     # fine here ...
    a = attempt("a", 300, extra_fams=[weak, swing],
                classes=[shape("near-reversal chain", 100, 0.40)])
    swing_b = dict(swing, non300_rate=0.55)      # ... and awful next time
    b = attempt("b", 300, played="2026-09-20T10:00:00",
                extra_fams=[weak, swing_b],
                classes=[shape("near-reversal chain", 100, 0.20)])
    cmp = A.compare([a, b])
    rows = {f["name"]: f for f in cmp["families"]}
    assert rows["circle_1/2_jump"]["stable_weakness"] is True
    assert rows["circle_1/2_jump"]["volatile"] is False
    assert rows["slider_1/2_jump"]["stable_weakness"] is False
    assert rows["slider_1/2_jump"]["volatile"] is True
    assert cmp["stable_weaknesses"] == ["circle_1/2_jump"]
    assert "circle_1/2_jump" in cmp["verdict"]
    # shapes are compared the same way and can also swing
    shapes = {f["name"]: f for f in cmp["shapes"]}
    assert shapes["near-reversal chain"]["volatile"] is True


def test_thin_buckets_are_reported_but_never_drive_the_verdict():
    tiny = fam("circle_1/4_dense", 6, 0.9)       # n=6 under the 10-object gate
    a = attempt("a", 300, extra_fams=[tiny])
    b = attempt("b", 300, played="2026-09-20T10:00:00", extra_fams=[tiny])
    cmp = A.compare([a, b])
    row = cmp["families"][0]
    assert row["reported"] is False and row["solid"] is False
    assert cmp["stable_weaknesses"] == []
    assert "no structural weakness" in cmp["verdict"]


def test_the_gate_scales_with_map_length():
    small = fam("circle_1/2_jump", 12, 0.60)     # 12 objects: solid on a 150-map
    a = attempt("a", 100, n=150, extra_fams=[small])
    b = attempt("b", 100, n=150, played="2026-09-20T10:00:00", extra_fams=[small])
    assert A.compare([a, b])["gate"] == pytest.approx(10.0)
    assert A.compare([a, b])["families"][0]["solid"] is True
    # the same 15-object bucket is solid on the short map, thin on the long one
    long_a = attempt("a", 700, n=1016, extra_fams=[fam("circle_1/2_jump", 15, 0.4)])
    long_b = attempt("b", 700, n=1016, played="2026-09-20T10:00:00",
                     extra_fams=[fam("circle_1/2_jump", 15, 0.4)])
    assert A.compare([long_a, long_b])["gate"] == pytest.approx(20.0)
    assert A.compare([long_a, long_b])["families"][0]["solid"] is False
    short_a = attempt("a", 100, n=150, extra_fams=[fam("circle_1/2_jump", 15, 0.4)])
    short_b = attempt("b", 100, n=150, played="2026-09-20T10:00:00",
                      extra_fams=[fam("circle_1/2_jump", 15, 0.4)])
    assert A.compare([short_a, short_b])["gate"] == pytest.approx(10.0)
    assert A.compare([short_a, short_b])["families"][0]["solid"] is True


def test_one_attempt_is_not_a_comparison():
    cmp = A.compare([attempt("only", 300, extra_fams=[fam("x", 50, 0.9)])])
    assert cmp["n_attempts"] == 1 and cmp["families"] == []
    assert cmp["verdict"] is None


def test_the_overall_rate_comes_from_our_own_judgement():
    m = attempt("a", 200, n=400)                 # 200 off 300
    assert A._non300(m) == pytest.approx(0.5)
    m2 = {"accuracy": 0.75, "counts_detected": {}, "n_objects": 0}
    assert A._non300(m2) == pytest.approx(0.25)


# ------------------------------------------------------------------ build ---

def test_build_groups_and_renders(capsys):
    rows = [("a", attempt("a", 300, extra_fams=[fam("f", 40, 0.5)])),
            ("b", attempt("b", 200, played="2026-09-20T10:00:00",
                          extra_fams=[fam("f", 40, 0.9)])),
            ("c", attempt("c", 300, md5="n" * 32))]
    block = A.build(rows)
    assert block["n_runs"] == 3 and block["n_maps"] == 2
    assert block["n_repeated"] == 1
    for line in A.describe(block):
        print(line)
    out = capsys.readouterr().out
    assert "CROSS-ATTEMPT (3 runs over 2 maps, 1 with repeats)" in out
    assert "Test Map [X]" in out and "attempts)" in out
    assert "(thin)" in out or "swings" in out or "consistent" in out


def test_describe_all_includes_single_attempt_maps(capsys):
    block = A.build([("c", attempt("c", 300, md5="n" * 32))])
    assert "Test Map [X]" not in "\n".join(A.describe(block))
    assert "Test Map [X]" in "\n".join(A.describe(block, only_repeated=False))


# -------------------------------------------------------------------- cli ---

def test_cli_attempts_reads_a_directory(tmp_path, capsys):
    for i, (tag, f300, when) in enumerate((("run1", 300, "2026-09-01T10:00:00"),
                                           ("run2", 200, "2026-09-20T10:00:00"))):
        m = attempt(tag, f300, played=when, extra_fams=[fam("circle_1/2_jump", 40, 0.5 + 0.3 * i)])
        (tmp_path / f"{tag}_metrics.json").write_text(json.dumps(m))
    assert main(["attempts", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "CROSS-ATTEMPT (2 runs over 1 maps" in out
    assert "circle_1/2_jump" in out


def test_cli_attempts_json_and_missing(tmp_path, capsys):
    m = attempt("run1", 300, played="2026-09-01T10:00:00")
    (tmp_path / "run1_metrics.json").write_text(json.dumps(m))
    assert main(["attempts", str(tmp_path), "--json"]) == 0
    block = json.loads(capsys.readouterr().out)
    assert block["n_maps"] == 1
    assert main(["attempts", str(tmp_path / "nope")]) == 2


# --------------------------------------------------------- the reference ----

def test_acceptance_on_the_reference_attempts(tmp_path, capsys):
    """RASPUTIN 09-01 -> 09-22: the 1/2 jump buckets halve, 1/4 dense barely moves."""
    replay, map_path = (os.environ.get("OSU_TEST_MONTAGEM_REPLAY"), None)
    ras = os.environ.get("OSU_TEST_RASPUTIN_REPLAYS")      # colon-separated attempts
    rmap = os.environ.get("OSU_TEST_RASPUTIN_MAP")
    if not (ras and rmap):
        pytest.skip("set OSU_TEST_RASPUTIN_REPLAYS / OSU_TEST_RASPUTIN_MAP "
                    "(attempts in play order) to check the reference comparison")
    from osu_critique.report import analyze
    rows = []
    for i, rp in enumerate(ras.split(":")):
        m = analyze(rp, rmap, tag=f"att{i}", outdir=str(tmp_path), console=False,
                    write_objects=False)
        rows.append((f"att{i}", m))
    cmp = A.compare([m for _n, m in rows])
    rows_by = {f["name"]: f for f in cmp["families"]}
    half = [rows_by.get("slider_1/2_jump"), rows_by.get("slider_1/2_spaced")]
    assert all(f is not None and f["reported"] for f in half), rows_by.keys()
    for f in half:
        assert f["rates"][-1] <= f["rates"][0] * 0.75, f     # roughly halved
    dense = rows_by.get("slider_1/4_dense")
    assert dense is not None and dense["reported"]
    assert abs(dense["rates"][-1] - dense["rates"][0]) < 0.10, dense  # barely moves
    assert abs(dense["delta_pts"]) < 10.0
