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
    # never touch this machine's config/exports from a route test
    monkeypatch.setattr("osu_critique.export.enabled", lambda: False)
    monkeypatch.setattr("osu_critique.digest._export_mtimes", lambda: [])
    monkeypatch.setattr("osu_critique.config.lazer_exports",
                        lambda: Path("/nonexistent/osu-exports"))


def metrics(tag, replay, beatmap, accuracy, played_at, mod_string="NM",
            trustworthy=True, delta=0, n_objects=100, counts=None,
            composition=None, shapes=None, objects=True, misses=None,
            quarters=None):
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
        "autopsy": {"shapes": {"classes": shapes or []},
                    "misses": {"rows": misses or []}},
        "aim_mode": {"is_relax": False, "mean_norm": 0.4},
        "streams": {"n_segments": 1, "notes": 10},
        "quarters": quarters or [],
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
                 composition=comp, shapes=shape,
                 misses=[{"i": 3, "t": 1300.0, "kind": "Circle", "d_r": 1.5,
                          "closest_r": 0.25, "aim_at_press_r": 1.2,
                          "press_ms": -8.0, "key": "A", "gap_r": 6.0,
                          "turn_deg": 140.0, "speed": 0.4}]), DEAF),
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
    assert "res-miss" in r.text
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


# ------------------------------------------------------------ annotations ----

def post_note(client, path, **fields):
    data = {"body": "", "t": "", "tag": ""}
    data.update(fields)
    return client.post(path, data=data, follow_redirects=False)


def test_map_note_shows_on_the_map_and_on_every_attempt(client):
    r = post_note(client, f"/map/{MAP_A}/annotations",
                  body="the second kiai is the wall", t="2:14.312", tag="kiai jumps")
    assert r.status_code == 303
    assert r.headers["location"] == f"/map/{MAP_A}"

    page = client.get(f"/map/{MAP_A}").text
    assert "the second kiai is the wall" in page
    assert "2:14.312" in page
    assert ">kiai<" in page and ">jumps<" in page

    # every attempt of that map sees it
    for replay in ("1", "2", "3"):
        run_page = client.get("/run/" + replay * 32).text
        assert "the second kiai is the wall" in run_page
    # another map does not
    assert "the second kiai is the wall" not in client.get(f"/map/{MAP_B}").text


def test_run_note_is_scoped_to_that_attempt(client):
    post_note(client, "/run/" + "2" * 32 + "/annotations",
              body="felt sloppy here", t_map="1.500", tag="feel")
    assert "felt sloppy here" in client.get("/run/" + "2" * 32).text
    assert "felt sloppy here" not in client.get("/run/" + "3" * 32).text
    # it still counts as a note on the map (listed as run-scoped)
    assert "run-scoped note" in client.get(f"/map/{MAP_A}").text


def test_stamp_from_the_run_form_can_apply_to_the_whole_map(client):
    post_note(client, "/run/" + "2" * 32 + "/annotations",
              body="this jump is a wall", t_map="12.000", scope="map")
    map_page = client.get(f"/map/{MAP_A}").text
    assert "this jump is a wall" in map_page
    assert "0:12.000" in map_page
    # a map-scoped note shows on another attempt too
    assert "this jump is a wall" in client.get("/run/" + "3" * 32).text


def test_note_timestamp_is_rendered_as_a_chip(client):
    post_note(client, f"/map/{MAP_A}/annotations", body="here", t="0:02.500")
    page = client.get(f"/map/{MAP_A}").text
    assert '<span class="chip">0:02.500</span>' in page


def test_delete_note(client):
    post_note(client, f"/map/{MAP_A}/annotations", body="temporary")
    page = client.get(f"/map/{MAP_A}").text
    note_id = page.split("/annotations/")[1].split("/delete")[0]
    r = client.post(f"/annotations/{note_id}/delete",
                    data={"next": f"/map/{MAP_A}"}, follow_redirects=False)
    assert r.status_code == 303
    assert "temporary" not in client.get(f"/map/{MAP_A}").text


def test_empty_note_is_refused(client):
    assert post_note(client, f"/map/{MAP_A}/annotations", body="  ").status_code == 400


def test_bad_timestamp_is_refused(client):
    assert post_note(client, f"/map/{MAP_A}/annotations",
                     body="x", t="two minutes").status_code == 400


def test_delete_refuses_an_open_redirect(client):
    post_note(client, f"/map/{MAP_A}/annotations", body="temporary")
    note_id = client.get(f"/map/{MAP_A}").text.split("/annotations/")[1].split("/delete")[0]
    r = client.post(f"/annotations/{note_id}/delete",
                    data={"next": "//evil.example/x"}, follow_redirects=False)
    assert r.headers["location"] == "/"


def test_note_body_is_escaped(client):
    post_note(client, f"/map/{MAP_A}/annotations",
              body="<script>alert(1)</script>")
    page = client.get(f"/map/{MAP_A}").text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_run_page_renders_the_playhead_for_dt_aware_stamping(client):
    page = client.get("/run/" + "2" * 32).text
    assert 'data-rows-scale="1.0"' in page
    assert 'id="playhead"' in page
    assert 'id="t-map"' in page
    assert "obj-row" in page


def test_boot_rebuilds_a_schema_from_another_build(tmp_path):
    out = build_corpus(tmp_path)
    import sqlite3
    conn = sqlite3.connect(out / index.DB_FILENAME)
    conn.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    app = create_app(outdir=out, index_on_boot=True)
    with TestClient(app) as c:
        assert c.get("/").status_code == 200
    conn = sqlite3.connect(out / index.DB_FILENAME)
    assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == str(index.SCHEMA_VERSION)
    conn.close()


# -------------------------------------------------------------- critiques ----

FAKE_TEXT = "Your timing spread widens after the first kiai."


def fake_generate(system, user, on_delta=None, model=None, key=None):
    for chunk in ("Your timing ", "spread widens ", "after the first kiai."):
        if on_delta:
            on_delta(chunk)
    return FAKE_TEXT, "test-model"


@pytest.fixture
def llm(monkeypatch):
    """A key that exists and a model that answers without touching the network."""
    import osu_critique.coach as coach_mod
    import osu_critique.config as config_mod

    monkeypatch.setattr(config_mod, "llm_key", lambda: "test-key")
    monkeypatch.setattr(coach_mod, "generate_critique", fake_generate)
    return monkeypatch


def test_without_a_key_the_button_says_why_and_the_route_refuses(client, monkeypatch):
    import osu_critique.config as config_mod
    monkeypatch.setattr(config_mod, "llm_key", lambda: None)
    page = client.get("/run/" + "2" * 32)
    assert "No LLM key configured" in page.text
    assert 'id="critique-form"' not in page.text
    r = client.post("/run/" + "2" * 32 + "/critique", follow_redirects=False)
    assert r.status_code == 400
    assert "OSU_LLM_KEY" in r.text
    # the streaming client (the browser's fetch) gets JSON
    r = client.post("/run/" + "2" * 32 + "/critique",
                    headers={"accept": "text/event-stream"}, follow_redirects=False)
    assert r.status_code == 400 and "OSU_LLM_KEY" in r.json()["detail"]


def test_a_blocking_critique_is_stored_and_shown(client, llm):
    r = client.post("/run/" + "2" * 32 + "/critique", follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/run/" + "2" * 32).text
    assert FAKE_TEXT in page
    assert "test-model" in page
    assert "No stored critique" not in page

    sidecar = Path(client.app.state.outdir) / "critiques" / ("2" * 32 + ".json")
    assert json.loads(sidecar.read_text())["body"] == FAKE_TEXT

    conn = index.connect(Path(client.app.state.outdir) / index.DB_FILENAME)
    try:
        assert conn.execute("SELECT COUNT(*) FROM critiques").fetchone()[0] == 1
    finally:
        conn.close()


def test_the_streaming_path_emits_sse_and_stores_the_result(client, llm):
    r = client.post("/run/" + "3" * 32 + "/critique",
                    headers={"accept": "text/event-stream"},
                    follow_redirects=False)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    body = r.text
    assert '"delta": "Your timing "' in body
    assert '"done": true' in body
    assert body.rstrip().endswith("data: [DONE]")
    assert FAKE_TEXT in client.get("/run/" + "3" * 32).text


def test_a_changed_run_marks_the_critique_stale(client, llm):
    client.post("/run/" + "2" * 32 + "/critique", follow_redirects=False)
    assert "stale — the run" not in client.get("/run/" + "2" * 32).text

    # edit the artifact: the stored critique no longer describes this play
    out = Path(client.app.state.outdir)
    doc = json.loads((out / "a2_metrics.json").read_text())
    doc["accuracy"] = 0.71
    (out / "a2_metrics.json").write_text(json.dumps(doc))

    page = client.get("/run/" + "2" * 32).text
    assert "stale — the run or its notes changed" in page


def test_adding_a_note_marks_the_critique_stale(client, llm):
    client.post("/run/" + "2" * 32 + "/critique", follow_redirects=False)
    assert "stale — the run" not in client.get("/run/" + "2" * 32).text
    post_note(client, f"/map/{MAP_A}/annotations", body="this is the hard part")
    assert "stale — the run or its notes changed" in client.get("/run/" + "2" * 32).text


def test_deleting_a_critique(client, llm):
    client.post("/run/" + "2" * 32 + "/critique", follow_redirects=False)
    sidecar = Path(client.app.state.outdir) / "critiques" / ("2" * 32 + ".json")
    assert sidecar.exists()
    r = client.post("/run/" + "2" * 32 + "/critique/delete",
                    data={"next": "/run/" + "2" * 32}, follow_redirects=False)
    assert r.status_code == 303
    assert not sidecar.exists()
    assert "No stored critique" in client.get("/run/" + "2" * 32).text


def test_llm_remote_false_refuses_non_loopback_clients(tmp_path, monkeypatch, llm):
    import osu_critique.config as config_mod
    real_get = config_mod.get

    def gated(name, env=None, default=None):
        if name == "web.llm_remote":
            return False
        return real_get(name, env, default)

    monkeypatch.setattr(config_mod, "get", gated)
    out = build_corpus(tmp_path)
    app = create_app(outdir=out, index_on_boot=False)

    remote = TestClient(app)                      # host "testclient"
    r = remote.post("/run/" + "2" * 32 + "/critique", follow_redirects=False)
    assert r.status_code == 403
    assert "local-only" in r.text
    r = remote.post("/run/" + "2" * 32 + "/critique",
                    headers={"accept": "text/event-stream"}, follow_redirects=False)
    assert r.status_code == 403 and "local-only" in r.json()["detail"]
    # reading is still open
    assert remote.get("/run/" + "2" * 32).status_code == 200

    local = TestClient(app, client=("127.0.0.1", 5000))
    r = local.post("/run/" + "2" * 32 + "/critique", follow_redirects=False)
    assert r.status_code == 303


# ------------------------------------------------------------------- feed ----

def test_feed_renders_a_digest_as_a_page_not_a_text_blob(tmp_path):
    out = build_corpus(tmp_path)
    from osu_critique import digest
    digest.build(outdir=out, since="2026-09-01T00:00:00", ingest_first=False)
    app = create_app(outdir=out, index_on_boot=False)
    client = TestClient(app)
    r = client.get("/feed")
    assert r.status_code == 200
    # structure, not <pre>
    assert 'class="digest-head"' in r.text
    assert "maps worth another look" in r.text
    assert 'class="minigrid"' in r.text
    assert '<pre class="report">' not in r.text
    # the cards link to the map pages and load covers
    assert f'href="/map/{MAP_A}"' in r.text
    assert f"/api/cover/{MAP_A}" in r.text
    # and the plays table links to the runs
    assert '/run/' in r.text


def test_feed_falls_back_to_text_for_a_digest_without_a_sidecar(tmp_path):
    out = build_corpus(tmp_path)
    d = out / "digests"
    d.mkdir()
    (d / "2026-01-01_0000.md").write_text("# Digest — old\n\nnothing fancy\n")
    app = create_app(outdir=out, index_on_boot=False)
    r = TestClient(app).get("/feed")
    assert "older digest" in r.text
    assert '<details class="panel legacy">' in r.text
    assert "nothing fancy" in r.text


def test_feed_is_empty_before_the_first_digest(client):
    r = client.get("/feed")
    assert r.status_code == 200
    assert "No digests yet" in r.text


def test_nav_links_the_feed(client):
    assert 'href="/feed"' in client.get("/").text


# ------------------------------------------------------ digest button ------

def test_the_feed_can_run_a_digest(monkeypatch, tmp_path):
    out = build_corpus(tmp_path)
    app = create_app(outdir=out, index_on_boot=False)
    client = TestClient(app)

    calls = {}

    def fake_ingest(outdir=None, since_epoch=0.0, limit=None, quiet=False):
        calls["ingest"] = since_epoch
        return {"candidates": 0, "analysed": 0, "known": 0, "failed": 0,
                "seconds": 0.0, "tags": []}

    monkeypatch.setattr("osu_critique.digest.ingest", fake_ingest)
    r = client.post("/feed/digest", data={"since": ""}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/feed"
    assert "ingest" in calls                     # it did try to ingest first
    assert list((out / "digests").glob("*.md")), "a digest was written"
    page = client.get("/feed").text
    assert 'class="digest-head"' in page


def test_a_failing_digest_reports_why(monkeypatch, tmp_path):
    out = build_corpus(tmp_path)
    client = TestClient(create_app(outdir=out, index_on_boot=False))

    def boom(**kwargs):
        raise RuntimeError("no replays in ./replays")

    monkeypatch.setattr("osu_critique.digest.build", boom)
    r = client.post("/feed/digest", data={"since": ""}, follow_redirects=False)
    assert r.status_code == 500
    assert "no replays" in r.text


def test_two_digests_at_once_are_refused(monkeypatch, tmp_path):
    import threading
    out = build_corpus(tmp_path)
    client = TestClient(create_app(outdir=out, index_on_boot=False))
    started, release = threading.Event(), threading.Event()

    def slow(**kwargs):
        started.set()
        release.wait(5)
        return {"n_runs": 0, "markdown": "", "path": None}

    monkeypatch.setattr("osu_critique.digest.build", slow)
    worker = threading.Thread(target=lambda: client.post("/feed/digest", data={}),
                              daemon=True)
    worker.start()
    assert started.wait(5)
    second = client.post("/feed/digest", data={}, follow_redirects=False)
    assert second.status_code == 409
    assert "already running" in second.text
    release.set()
    worker.join(5)


# --------------------------------------------------------------- boards -----

def test_run_page_has_a_collapsed_board_section(client):
    page = client.get("/run/" + "2" * 32).text
    assert '<details class="panel fold" id="boards">' in page
    assert "where it went wrong" in page
    assert 'id="boards-data"' in page
    assert 'id="miss-boards"' in page
    assert "closest 0.25r" in page or "near-miss" in page
    # collapsed by default: the details tag must not carry `open`
    section = page.split('<details class="panel fold" id="boards">')[1].split(">")[0]
    assert "open" not in section


# ------------------------------------------------- deterministic report -----

def test_the_report_renders_as_cards_not_a_text_blob(client):
    page = client.get("/run/" + "2" * 32).text
    assert 'id="report"' in page
    assert 'class="rsection"' in page
    assert "Map profile" in page or "Timing" in page
    assert 'class="rnote ' in page or 'class="rkv"' in page
    # the deterministic report is no longer a <pre>; only the LLM critique is
    assert page.count('<pre class="report"') <= 1
    assert page.index('id="report"') < page.index('<pre class="report"')


# ------------------------------------------------------- rail and folds ----

def test_every_rail_entry_points_at_a_block_that_exists(client):
    page = client.get("/run/" + "2" * 32).text
    assert 'class="rail"' in page
    assert 'aria-label="this run"' in page
    for anchor in ("stats", "chart", "boards", "objects", "report",
                   "critique", "annotations"):
        assert f'data-spy="{anchor}"' in page
        assert f'id="{anchor}"' in page
    # the rail comes before the content it links to
    assert page.index('class="rail"') < page.index('id="stats"')


def test_heavy_blocks_start_collapsed(client):
    page = client.get("/run/" + "2" * 32).text
    for block in ("objects", "report", "annotations"):
        opening = page.split(f'<details class="panel fold" id="{block}"')[1].split(">")[0]
        assert "open" not in opening, block
    # the llm panel is open when there is nothing stored: the form is the point
    opening = page.split('<details class="panel fold" id="critique"')[1].split(">")[0]
    assert "open" in opening


def test_peeks_name_the_rule_not_a_number_from_the_cards(client):
    page = client.get("/run/" + "2" * 32).text
    assert "every miss and every non-300, in map order" in page
    assert "of 12 objects" in page                  # 12 object rows in the fixture
    assert "sections of tables and thresholds" in page
    assert "map notes" in page or "map note" in page


def test_the_object_table_is_its_own_fold(client):
    page = client.get("/run/" + "2" * 32).text
    assert 'id="all-objects-details"' in page
    assert 'id="object-table"' in page
    # the old separate button did nothing: expanding the details showed an empty div
    assert 'id="all-objects"' not in page


def test_the_report_count_matches_the_cards_rendered(client):
    import re

    page = client.get("/run/" + "2" * 32).text
    cards = page.count('<article class="rsection')
    stated = re.search(r"<span class=\"peek\">(\d+) sections?", page)
    assert stated is not None
    assert int(stated.group(1)) == cards


def test_report_txt_is_the_cli_rendering(tmp_path):
    from osu_critique.report_sections import sections, to_text

    out = build_corpus(tmp_path)
    c = TestClient(create_app(outdir=out, index_on_boot=False))
    res = c.get("/run/" + "2" * 32 + "/report.txt")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    doc = json.loads((out / "a2_metrics.json").read_text())
    assert res.text == to_text(doc, sections(doc))
    assert c.get("/run/" + "9" * 32 + "/report.txt").status_code == 404


def test_the_map_page_has_a_rail_too(client):
    page = client.get("/map/" + MAP_A).text
    assert 'class="rail"' in page
    for anchor in ("attempts", "annotations"):
        assert f'data-spy="{anchor}"' in page
        assert f'id="{anchor}"' in page


# ------------------------------------------------------------ client side ----

APP_JS = Path(__file__).parent.parent / "src/osu_critique/web/static/app.js"


def test_app_js_defines_every_function_it_calls():
    """A deleted function definition is invisible to a server-rendered test.

    0.22.0 shipped with initAnnotations and initBoards sliced out of app.js: the
    page rendered, the rail worked, and the playhead, the boards and the copy
    button were silently dead. Cheapest possible guard: every init*() that is
    called must have a definition in the same file.
    """
    import re

    src = APP_JS.read_text()
    defined = set(re.findall(r"(?:async\s+)?function\s+(\w+)", src))
    called = set(re.findall(r"\b(init[A-Z]\w*)\(\)", src))
    assert called, "no init* calls found — the regex or the file changed"
    assert called <= defined, f"called but never defined: {sorted(called - defined)}"


def test_the_report_text_is_inlined_and_matches_the_endpoint(client):
    import re

    page = client.get("/run/" + "2" * 32).text
    assert 'id="report-text"' in page
    assert '/report.txt"' in page                    # the always-available link
    block = re.search(r'<script type="application/json" id="report-text">(.*?)</script>',
                      page, re.S)
    assert block is not None
    inlined = json.loads(block.group(1))
    served = client.get("/run/" + "2" * 32 + "/report.txt").text
    assert inlined == served
    assert "Report" in inlined


def test_static_assets_are_cache_busted_by_version(client):
    page = client.get("/run/" + "2" * 32).text
    assert "/static/style.css?v=" in page
    assert "/static/app.js?v=" in page
