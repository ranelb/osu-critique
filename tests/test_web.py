"""Route-level tests for the web frontend (needs the ``[web]`` extra).

FastAPI's TestClient is enough: if a page cannot be asserted through it, the
page is doing something a test cannot see, which is the point of keeping the
frontend server-rendered.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="web extra not installed")

from fastapi.testclient import TestClient  # noqa: E402

from osu_critique import covers, index  # noqa: E402
from osu_critique.web.app import create_app  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
MAP_A = "a" * 32
MAP_B = "b" * 32
DEAF = FIXTURES / "deafheaven.osu"      # Title DEAFHEAVEN, set 2393752, id 5658686
AAAA = FIXTURES / "aaaaa.osu"           # set 2338325, id 5021628


@pytest.fixture(autouse=True)
def no_lazer_scan(monkeypatch):
    monkeypatch.setattr(index._MapResolver, "_build", lambda self: {})


def metrics(tag, replay, beatmap, accuracy, played_at, mod_string="NM",
            trustworthy=True, delta=0, n_objects=100, counts=None,
            composition=None, shapes=None, objects=True):
    det = counts or {"300": 90, "100": 8, "50": 0, "miss": 2}
    doc = {
        "schema_version": 1, "tag": tag, "beatmap_md5": beatmap,
        "replay_md5": replay, "played_at": played_at, "player": "test",
        "map": "Artist - Title [Insane]",
        "mods": {"DT": mod_string == "DT", "RX": False, "AP": False},
        "mod_string": mod_string, "time_scale": 1.0,
        "difficulty": {"CS": 4.0, "AR": 9.0, "OD": 8.0, "HP": 5.0},
        "n_objects": n_objects, "n_objects_map": n_objects,
        "accuracy": accuracy, "max_combo": 90, "full_combo": False,
        "ur": 120.0, "ur_pct_of_300_window": 50.0,
        "hit_error_ms": {"mean": 1.0, "std": 20.0, "p10": -20.0, "p90": 20.0,
                         "abs_mean": 15.0},
        "aim_px": {"mean": 12.0, "p90": 20.0, "mean_norm": 0.4},
        "whiffed_presses": 3,
        "counts_recorded": det,
        "counts_detected": det,
        "trust": {"trustworthy": trustworthy, "abs_delta_total": delta,
                  "abs_delta_pct": delta / max(1, n_objects) * 100,
                  "judged": n_objects,
                  "count_deltas": {"300": 0, "100": 0, "50": 0, "miss": 0}},
        "failed_play": False,
        "time_base": {"overridden": False, "note": None},
        "windows_ms": {"300": 24.8, "100": 66.4, "50": 108.0},
        "profile": {"composition": composition or []},
        "autopsy": {"shapes": {"classes": shapes or []}},
        "aim_mode": {"is_relax": False, "mean_norm": 0.4},
        "streams": {"n_segments": 1, "notes": 10},
    }
    return doc


def obj_rows(n=12):
    rows = []
    for i in range(n):
        rows.append({"i": i, "t": 1000 + i * 100, "end_t": 1000 + i * 100,
                     "x": 100, "y": 100, "kind": "Circle",
                     "result": "miss" if i == 3 else "300",
                     "pattern": "flow", "error_ms": -40.0 if i == 3 else 2.0,
                     "aim_px": 10.0, "aim_r": 0.4, "spacing_r": 2.0,
                     "strain_aim": 1.0, "strain_speed": 1.0,
                     "snap": 4.0, "bpm": 180.0, "bpm_eff": 180.0,
                     "angle_deg": 30.0, "cursor_speed": 0.5,
                     "key": "A", "slider_tail_off": None,
                     "slider_missed_ticks": None, "slider_off_pct": None})
    return rows


def build_corpus(tmp_path):
    """Two maps: A with three attempts (one untrustworthy), B with one."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "stars_by_md5.json").write_text(
        json.dumps({MAP_A: {"NM": 6.4}, MAP_B: {"NM": 2.1}}))
    (out / "pp_by_replay.json").write_text(json.dumps({"r3" * 10 + "ab": {"pp": 150}}))
    (out / "beatmap_status.json").write_text(
        json.dumps({"5658686": {"status": "ranked"}, "5021628": {"status": "loved"}}))

    comp = [{"family": "flow", "n": 60, "share": 0.6, "non300": 18,
             "non300_rate": 0.30, "reported": True}]
    shape = [{"class": "near-reversal chain", "n": 40, "share": 0.4,
              "non300": 8, "non300_rate": 0.20, "reported": True}]
    runs = [
        (metrics("a1", "1" * 32, MAP_A, 0.80, "2026-09-01T10:00:00",
                 trustworthy=False, delta=15, composition=comp, shapes=shape), DEAF),
        (metrics("a2", "2" * 32, MAP_A, 0.90, "2026-09-10T10:00:00",
                 composition=comp, shapes=shape), DEAF),
        (metrics("a3", "3" * 32, MAP_A, 0.95, "2026-09-20T10:00:00", mod_string="DT",
                 composition=comp, shapes=shape), DEAF),
        (metrics("b1", "4" * 32, MAP_B, 0.70, "2026-08-01T10:00:00",
                 n_objects=80), AAAA),
    ]
    for doc, map_path in runs:
        path = out / f"{doc['tag']}_metrics.json"
        path.write_text(json.dumps(doc))
        (out / f"{doc['tag']}_objects.json").write_text(
            json.dumps({"schema_version": 1, "objects": obj_rows()}))
        index.upsert_run(doc, path, outdir=out, map_path=map_path)
    return out


@pytest.fixture
def client(tmp_path):
    out = build_corpus(tmp_path)
    app = create_app(outdir=out, index_on_boot=False)
    return TestClient(app)


# ------------------------------------------------------------------ list ----

def test_home_lists_one_card_per_map(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "DEAFHEAVEN" in r.text
    assert "AaAaAaAAaAaAAa" in r.text          # the second map's title
    assert r.text.count('class="card"') == 2


def test_home_search_filters(client):
    r = client.get("/", params={"q": "deaf"})
    assert r.text.count('class="card"') == 1
    assert "AaAaAaAAaAaAAa" not in r.text


def test_home_status_filter_uses_the_beatmap_status_cache(client):
    r = client.get("/", params={"status": "ranked"})
    assert "DEAFHEAVEN" in r.text
    assert "AaAaAaAAaAaAAa" not in r.text


def test_home_sort_by_accuracy_orders_by_best(client):
    r = client.get("/", params={"sort": "accuracy"})
    assert r.text.index("DEAFHEAVEN") < r.text.index("AaAaAaAAaAaAAa")


def test_home_sort_by_recent_puts_the_newest_run_first(client):
    r = client.get("/", params={"sort": "recent"})
    assert r.text.index("DEAFHEAVEN") < r.text.index("AaAaAaAAaAaAAa")


def test_api_runs_shape(client):
    doc = client.get("/api/runs").json()
    assert doc["total"] == 2
    card = next(m for m in doc["maps"] if m["md5"] == MAP_A)
    assert card["attempts"] == 3
    assert card["best_acc"] == pytest.approx(0.95)
    assert card["sr"] == pytest.approx(6.4)
    assert card["rank_status"] == "ranked"


# ------------------------------------------------------------------- map ----

def test_map_page_shows_the_attempts_and_the_cross_attempt_block(client):
    r = client.get(f"/map/{MAP_A}")
    assert r.status_code == 200
    assert "DEAFHEAVEN" in r.text
    assert "attempts" in r.text
    assert r.text.count('href="/run/') == 3
    assert "cross-attempt structure" in r.text
    assert "consistent weakness" in r.text or "swings" in r.text


def test_map_page_golden_structure(client):
    """The page's semantic content, pinned: headings, order, and the attempt rows."""
    r = client.get(f"/map/{MAP_A}")
    html = r.text
    headings = [h for h in ("attempts", "cross-attempt structure", "annotations")
                if h in html]
    assert headings == ["attempts", "cross-attempt structure", "annotations"]
    # newest attempt first, with its real numbers
    assert html.index("2026-09-20 10:00") < html.index("2026-09-10 10:00")
    assert "95.00%" in html and "80.00%" in html
    # the untrusted attempt is marked, not hidden
    assert "differs" in html


def test_map_attempts_partial_is_a_fragment(client):
    r = client.get(f"/map/{MAP_A}/attempts", params={"sort": "accuracy"})
    assert r.status_code == 200
    assert r.text.lstrip().startswith('<section class="panel" id="attempts">')
    assert "<html" not in r.text


def test_map_unknown_is_404_html(client):
    r = client.get("/map/" + "f" * 32)
    assert r.status_code == 404
    assert "not found" in r.text.lower() or "404" in r.text


def test_api_map_unknown_is_404_json(client):
    r = client.get("/api/map/" + "f" * 32)
    assert r.status_code == 404
    assert r.json()["detail"]


# ------------------------------------------------------------------- run ----

def test_run_page_renders_the_good_trust_banner(client):
    r = client.get("/run/" + "2" * 32)
    assert r.status_code == 200
    assert "banner good" in r.text
    assert "matches the game" in r.text
    assert "deterministic critique" in r.text
    assert "TestPlayer" not in r.text


def test_run_page_makes_an_untrustworthy_run_look_different(client):
    bad = client.get("/run/" + "1" * 32)
    good = client.get("/run/" + "2" * 32)
    assert "banner bad" in bad.text
    assert "banner good" not in bad.text
    assert "Judgement differs from the game" in bad.text
    assert "15 of 100 objects disagree" in bad.text
    # the difference is not just a class: the wording changes
    assert "Judgement differs from the game" not in good.text


def test_run_page_lists_the_interesting_objects(client):
    r = client.get("/run/" + "2" * 32)
    assert "objects worth looking at" in r.text
    assert 'class="res-miss"' in r.text
    assert "load the full object table" not in r.text  # 1 miss < the table limit


def test_run_page_says_when_objects_are_missing(client, tmp_path):
    out = client.app.state.outdir
    path = Path(out) / "noobj_metrics.json"
    doc = metrics("noobj", "9" * 32, MAP_B, 0.5, "2026-07-01T10:00:00")
    path.write_text(json.dumps(doc))
    index.upsert_run(doc, path, outdir=out, map_path=AAAA)
    r = client.get("/run/" + "9" * 32)
    assert r.status_code == 200
    assert "--no-objects" in r.text
    assert client.get("/api/objects/" + "9" * 32).status_code == 404


def test_api_objects_returns_the_artifact_verbatim(client):
    doc = client.get("/api/objects/" + "2" * 32).json()
    assert len(doc["objects"]) == 12
    assert doc["objects"][3]["result"] == "miss"


def test_unknown_run_is_404(client):
    assert client.get("/run/" + "e" * 32).status_code == 404


def test_frames_route_is_reserved_not_missing(client):
    r = client.get("/run/" + "2" * 32 + "/frames")
    assert r.status_code == 501
    assert "reserved" in r.json()["detail"]


# ---------------------------------------------------------------- covers ----

def test_cover_is_served_from_the_cache_without_network(client, monkeypatch):
    out = Path(client.app.state.outdir)
    dest = covers.cover_path(out, 2393752, "card")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    r = client.get(f"/api/cover/{MAP_A}", params={"size": "card"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content.startswith(b"\xff\xd8")


def test_cover_offline_is_a_placeholder_not_an_error(client, monkeypatch):
    monkeypatch.setattr(covers, "fetch", lambda *a, **k: False)
    assert client.get(f"/api/cover/{MAP_A}", params={"size": "hero"}).status_code == 404
    # and the page still renders
    assert client.get(f"/map/{MAP_A}").status_code == 200


def test_cover_rejects_an_unknown_size(client):
    assert client.get(f"/api/cover/{MAP_A}", params={"size": "huge"}).status_code == 400


# --------------------------------------------------------------- startup ----

def test_boot_builds_a_missing_index(tmp_path):
    out = build_corpus(tmp_path)
    db = out / index.DB_FILENAME
    db.unlink()
    app = create_app(outdir=out, index_on_boot=True)
    with TestClient(app) as c:
        assert c.get("/").status_code == 200
    assert db.exists()


def test_healthz(client):
    assert client.get("/healthz").text == "ok"


# ------------------------------------------------------------- no-extra ----

def test_core_imports_without_fastapi():
    code = ("import sys, osu_critique.cli, osu_critique.index, osu_critique.web;"
            "print('fastapi' in sys.modules)")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False"
