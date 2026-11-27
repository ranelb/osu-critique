"""scripts/label_sheet.py --tail-diff: window labels and balanced selection."""
import importlib.util
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "patterns"
spec = importlib.util.spec_from_file_location("label_sheet", ROOT / "scripts" / "label_sheet.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


def seg(a, b, shape="arc"):
    return {"start": a, "end": b, "shape": shape}


def test_window_label_needs_half_the_window():
    assert L.window_label([seg(0, 5)], 0, 7) == "arc"      # 6 of 8
    assert L.window_label([seg(0, 2)], 0, 7) is None        # 3 of 8
    assert L.window_label([], 0, 7) is None
    # the larger overlap wins
    assert L.window_label([seg(0, 2, "line"), seg(3, 8, "zigzag")], 0, 8) == "zigzag"


def test_tail_category():
    assert L.tail_category(None, "arc") == "changed"
    assert L.tail_category("arc", "line") == "changed"
    assert L.tail_category("arc", None) == "changed"
    assert L.tail_category("arc", "arc") == "kept"
    assert L.tail_category(None, None) == "unlabelled"


def test_pick_tail_is_balanced_spread_and_disjoint():
    pool = []
    for m in "abc":
        for i in range(0, 60, 2):
            for cat in ("changed", "kept", "unlabelled"):
                pool.append((m, {"i0": i, "i1": i + 5, "src": cat}))
    got = L.pick_tail(pool, 10, random.Random(1))
    cats = [w["src"] for _m, w in got]
    assert [cats.count(c) for c in ("changed", "kept", "unlabelled")] == [4, 3, 3]
    assert len({m for m, _ in got}) == 3
    for cat in ("changed", "kept", "unlabelled"):
        for m in "abc":
            spans = sorted((w["i0"], w["i1"]) for mm, w in got if mm == m and w["src"] == cat)
            assert all(b0 > a1 for (_, a1), (b0, _) in zip(spans, spans[1:]))


def test_build_tail_on_slider_fixture():
    wins = L.build_tail([FIX / "geo_tail.osu", FIX / "geo_clean.osu"], 6, 1, 0.5)
    assert wins and {w["src"] for w in wins} <= {"changed", "kept", "unlabelled"}
    assert all(w["map"] == "geo_tail" for w in wins)     # geo_clean has no sliders
    assert any(w["src"] == "changed" and w["tails_on"] and not w["tails_off"] for w in wins)
    for w in wins:
        assert w["tails_off"] is None or w["src"] != "changed" or w["tails_off"] != w["tails_on"]


def test_tail_diff_page_is_written(tmp_path):
    out = tmp_path / "p.html"
    L.main([str(out), str(FIX / "geo_tail.osu"), "--tail-diff", "6"])
    data = json.loads(re.search(r"const W=(\[.*?\]);\n", out.read_text()).group(1))
    assert data and all("tails_on" in w for w in data)
