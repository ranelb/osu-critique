"""Route tests for the dashboard and its settings (needs the ``[web]`` extra).

The dashboard is settings-driven, so most of these check the round trip:
a POST changes the file, the next GET obeys it. A malformed settings file must
never blank the page — that is the failure mode a config UI always ships with.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="web extra not installed")

from fastapi.testclient import TestClient  # noqa: E402

from osu_critique import blacklist, dashboard, index, library  # noqa: E402
from osu_critique.web.app import create_app  # noqa: E402

MAP_PLAYED = "a" * 32
MAP_NEW = "b" * 32
MAP_HARD = "c" * 32
MAP_MANIA = "d" * 32
ALL_WIDGETS = [w["id"] for w in dashboard.WIDGETS]


def ago(days: float) -> str:
    return (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")


def metrics_doc(tag, beatmap, accuracy, played_at, player="ran27"):
    return {
        "schema_version": 1, "tag": tag, "beatmap_md5": beatmap,
        "replay_md5": tag.ljust(32, "0")[:32], "played_at": played_at,
        "player": player, "map": f"Map {beatmap[0].upper()} [Insane]",
        "mods": {}, "mod_string": "NM", "time_scale": 1.0,
        "difficulty": {"CS": 4.0, "AR": 9.0, "OD": 8.0, "HP": 5.0},
        "n_objects": 300, "n_objects_map": 300, "accuracy": accuracy,
        "max_combo": 100, "full_combo": False, "ur": 120.0,
        "ur_pct_of_300_window": 50.0,
        "hit_error_ms": {"mean": 0.0, "std": 20.0, "p10": -20.0, "p90": 20.0},
        "counts_recorded": {"300": 290, "100": 8, "50": 0, "miss": 2},
        "counts_detected": {"300": 290, "100": 8, "50": 0, "miss": 2},
        "trust": {"trustworthy": True, "abs_delta_total": 0, "judged": 300},
        "failed_play": False, "time_base": {"overridden": False},
        "aim_mode": {"is_relax": False},
    }


def map_feats(md5, title, *, sr=5.0, mode=0, length_ms=90_000, set_id=None):
    return {
        "beatmap_md5": md5, "map_path": f"/maps/{md5}.osu", "feature_version": 1,
        "set_id": set_id, "beatmap_id": None, "mode": mode, "title": title,
        "artist": "Artist", "creator": "Mapper", "version": "Insane",
        "sr": sr, "bpm": 180.0, "length_ms": length_ms, "ar": 9.0, "od": 8.0,
        "cs": 4.0, "hp": 5.0, "n_objects": 300, "n_circles": 300, "n_sliders": 0,
        "n_spinners": 0, "slider_ratio": 0.2, "density": 3.0,
        "dense_share": 0.2, "stream_share": 0.2, "jump_share": 0.2,
        "bigjump_share": 0.2, "anti_flow_share": 0.2, "flow_share": 0.2,
        "kiai_share": 0.0, "strain_aim_max": 10.0, "strain_speed_max": 10.0,
        "sustained_share": 0.3, "sustained_max": 20, "sustained_nps": 6.0,
    }


def build_corpus(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    out.mkdir()
    (out / "stars_by_md5.json").write_text(json.dumps({MAP_PLAYED: {"NM": 5.0}}))
    conn = index.connect(index.db_path(out))
    try:
        library.upsert(conn, map_feats(MAP_PLAYED, "Played Map", set_id=1),
                       mtime=1.0, size=1)
        library.upsert(conn, map_feats(MAP_NEW, "New Map", set_id=2),
                       mtime=1.0, size=1)
        library.upsert(conn, map_feats(MAP_HARD, "Too Hard", sr=9.5, set_id=3),
                       mtime=1.0, size=1)
        library.upsert(conn, map_feats(MAP_MANIA, "Mania Map", mode=3, set_id=4),
                       mtime=1.0, size=1)
        conn.execute("INSERT INTO meta (key, value) VALUES ('library_scanned_at', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (datetime.now().isoformat(timespec="seconds"),))
        conn.commit()
    finally:
        conn.close()
    for i, days in enumerate((2, 5, 9)):
        doc = metrics_doc(f"p{i}", MAP_PLAYED, 0.90 + i * 0.01, ago(days))
        path = out / f"{doc['tag']}_metrics.json"
        path.write_text(json.dumps(doc))
        index.upsert_run(doc, path, outdir=out)
    # the .osu would carry the set id; the fixture has no map file, so set it
    # after the runs exist (the first upsert creates the beatmaps row)
    conn = index.connect(index.db_path(out))
    try:
        conn.execute("UPDATE beatmaps SET set_id = 1 WHERE beatmap_md5 = ?",
                     (MAP_PLAYED,))
        conn.commit()
    finally:
        conn.close()
    return out


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "config" / "dashboard.json"
    monkeypatch.setattr(dashboard, "settings_path", lambda: path)
    monkeypatch.setattr("osu_critique.digest._export_mtimes", lambda: [])
    return path


@pytest.fixture
def client(tmp_path, settings_file):
    out = build_corpus(tmp_path)
    return TestClient(create_app(outdir=out, index_on_boot=False))


def ids(html: str) -> list[str]:
    """Widget ids in document order (the page order the rail also uses)."""
    found = [(html.index(f'id="w-{w}"'), f"w-{w}")
             for w in ALL_WIDGETS if f'id="w-{w}"' in html]
    return [name for _pos, name in sorted(found)]


# --------------------------------------------------------------- the page --

def test_dashboard_is_the_home_page_and_maps_moved(client):
    home = client.get("/")
    assert home.status_code == 200
    # the h1 is the page's name for a screen reader; sighted readers get the
    # hero, which is the numbers, not a label saying "dashboard"
    assert '<h1 class="sr-only">dashboard</h1>' in home.text
    assert 'class="hero"' in home.text
    assert 'class="card"' not in home.text
    maps = client.get("/maps")
    assert maps.status_code == 200
    assert 'class="card"' in maps.text


def test_every_default_widget_is_on_the_page(client):
    html = client.get("/").text
    assert ids(html) == [f"w-{w}" for w in ALL_WIDGETS]
    assert "ran27" in html


def test_the_toc_lists_the_enabled_widgets(client):
    html = client.get("/").text
    for widget in ALL_WIDGETS:
        assert f'data-spy="w-{widget}"' in html


def test_recommendations_appear_and_explain_themselves(client):
    html = client.get("/").text
    assert "New Map" in html
    assert "never played" in html
    assert "Too Hard" not in html          # outside the star band
    assert "Mania Map" not in html         # not std


def test_library_state_is_reported(client):
    html = client.get("/").text
    assert "library: 4 maps" in html


def test_the_page_says_when_the_library_was_never_scanned(tmp_path, settings_file):
    out = tmp_path / "out"
    out.mkdir()
    app = create_app(outdir=out, index_on_boot=False)
    page = TestClient(app).get("/")
    # no index at all: the empty page, not a crash
    assert page.status_code == 200
    assert "batch" in page.text or "index" in page.text


def test_unscanned_library_hint_when_runs_exist_but_maps_do_not(tmp_path, settings_file):
    out = tmp_path / "out"
    out.mkdir()
    doc = metrics_doc("q0", MAP_PLAYED, 0.9, ago(1))
    path = out / "q0_metrics.json"
    path.write_text(json.dumps(doc))
    index.upsert_run(doc, path, outdir=out)
    page = TestClient(create_app(outdir=out, index_on_boot=False)).get("/")
    assert "library: <span class=\"warn\">not scanned" in page.text
    assert "osu-critique library scan" in page.text


# ---------------------------------------------------------------- settings --

def test_a_disabled_widget_disappears_from_the_page(client):
    r = client.post("/settings", data={"w:form": "on", "player": "",
                                       "stretch": "0.5", "cards": "6",
                                       "bucket": ["new", "improver", "maintain"]},
                    follow_redirects=False)
    assert r.status_code in (302, 303)
    html = client.get("/").text
    assert ids(html) == ["w-form"]
    assert "w-calendar" not in html


def test_order_follows_the_settings_file(client, settings_file):
    doc = dashboard.defaults()
    doc["widgets"] = list(reversed(doc["widgets"]))
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(doc))
    html = client.get("/").text
    assert ids(html) == [f"w-{w['id']}" for w in doc["widgets"]]


def test_moving_a_widget_up_keeps_the_other_controls(client, settings_file):
    doc = dashboard.defaults()
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(doc))
    data = {"player": "", "stretch": "0.5", "cards": "6",
            "bucket": ["new", "improver", "maintain"]}
    for w in doc["widgets"]:
        data[f"w:{w['id']}"] = "on"
    data["move:recent"] = "up"
    r = client.post("/settings", data=data, follow_redirects=False)
    assert r.status_code in (302, 303)
    saved = json.loads(settings_file.read_text())
    order = [w["id"] for w in saved["widgets"]]
    assert order.index("recent") == order.index("calendar") - 1
    assert all(w["on"] for w in saved["widgets"])


def test_a_toggle_and_a_move_in_one_submit(client, settings_file):
    doc = dashboard.defaults()
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(doc))
    data = {"player": "", "stretch": "0.5", "cards": "6",
            "bucket": ["new"], "move:skills": "up"}
    for w in doc["widgets"]:
        if w["id"] != "whatsnew":
            data[f"w:{w['id']}"] = "on"
    client.post("/settings", data=data, follow_redirects=False)
    saved = json.loads(settings_file.read_text())
    assert [w["id"] for w in saved["widgets"]][1] == "skills"
    assert not next(w for w in saved["widgets"] if w["id"] == "whatsnew")["on"]
    assert saved["buckets"] == ["new"]


def test_malformed_settings_file_still_renders_the_defaults(client, settings_file):
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text("{{ nonsense")
    html = client.get("/").text
    assert ids(html) == [f"w-{w}" for w in ALL_WIDGETS]


def test_unknown_ids_are_ignored_and_missing_ones_defaulted(client, settings_file):
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps({
        "widgets": [{"id": "form", "on": True, "window": None},
                    {"id": "wat", "on": False, "window": 3}],
    }))
    saved = dashboard.load()
    assert [w["id"] for w in saved["widgets"]][0] == "form"
    assert "wat" not in [w["id"] for w in saved["widgets"]]
    assert len(saved["widgets"]) == len(ALL_WIDGETS)


def test_out_of_range_controls_are_clamped():
    doc = dashboard.normalise({"stretch": 9, "cards": 42,
                               "buckets": ["nonsense"], "player": "  x  "})
    assert doc["stretch"] == 1.0
    assert doc["cards"] == 6
    assert doc["buckets"] == ["new", "improver", "maintain"]
    assert doc["player"] == "x"


def test_a_window_not_offered_falls_back(tmp_path):
    path = tmp_path / "dashboard.json"
    path.write_text(json.dumps({"widgets": [
        {"id": "trend", "on": True, "window": 999}]}))
    doc = dashboard.normalise(json.loads(path.read_text()))
    trend = next(w for w in doc["widgets"] if w["id"] == "trend")
    assert trend["window"] in (13, 26)


def test_reset_restores_defaults(client, settings_file):
    client.post("/settings", data={"w:form": "on", "reset": "1"},
                follow_redirects=False)
    saved = json.loads(settings_file.read_text())
    assert [w["id"] for w in saved["widgets"]] == ALL_WIDGETS
    assert all(w["on"] for w in saved["widgets"])


def test_player_override_changes_what_the_page_says(client, settings_file, tmp_path):
    out = client.app.state.outdir
    doc = metrics_doc("other0", MAP_PLAYED, 0.5, ago(1), player="someone")
    path = Path(out) / "other0_metrics.json"
    path.write_text(json.dumps(doc))
    index.upsert_run(doc, path, outdir=out)
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps({"player": "someone"}))
    html = client.get("/").text
    assert "<b>someone</b>" in html


def test_settings_page_shows_resolved_paths_read_only(client):
    page = client.get("/settings").text
    assert "resolved paths" in page
    assert "blacklist" in page
    # nothing that writes a key or a bind address
    for forbidden in ('name="llm_key"', 'name="host"', 'name="port"'):
        assert forbidden not in page


# --------------------------------------------------------------- blacklist --

def test_the_cross_on_a_card_blocks_the_map(client, settings_file, tmp_path):
    out = client.app.state.outdir
    assert "New Map" in client.get("/").text
    r = client.post("/blacklist", data={"md5": MAP_NEW, "scope": "map", "next": "/"},
                    follow_redirects=False)
    assert r.status_code in (302, 303)
    assert MAP_NEW in blacklist.load(out)["maps"]
    assert "New Map" not in client.get("/").text
    conn = index.connect(index.db_path(out))
    try:
        keys = {row["key"] for row in conn.execute("SELECT key FROM blacklist")}
    finally:
        conn.close()
    assert MAP_NEW in keys


def test_the_set_button_blocks_the_whole_set(client, settings_file):
    out = client.app.state.outdir
    client.post("/blacklist", data={"md5": MAP_NEW, "set_id": "2",
                                    "scope": "set", "next": "/"})
    doc = blacklist.load(out)
    assert doc["sets"] == [2]
    assert doc["maps"] == []


def test_settings_lists_and_unblocks(client, settings_file):
    out = client.app.state.outdir
    blacklist.add_map(out, MAP_NEW)
    page = client.get("/settings").text
    assert MAP_NEW in page
    client.post("/blacklist/remove", data={"md5": MAP_NEW, "next": "/settings"},
                follow_redirects=False)
    assert blacklist.load(out)["maps"] == []


# ------------------------------------------------------------------ learn --

def test_learn_defines_every_term_with_a_stable_anchor(client):
    r = client.get("/learn")
    assert r.status_code == 200
    from osu_critique.web import glossary
    for term in glossary.TERMS:
        assert f'id="{term["id"]}"' in r.text
        assert term["short"] and term["long"] and term["how"] and term["doc"]
        assert term["id"] == term["id"].lower().replace(" ", "-")
    ids = [t["id"] for t in glossary.TERMS]
    assert len(ids) == len(set(ids))


def test_every_glossary_link_on_the_dashboard_resolves(client):
    """The done-when: no card may point at an anchor that does not exist."""
    import re
    page = client.get("/").text
    learn = client.get("/learn").text
    targets = set(re.findall(r'href="/learn#([a-z0-9-]+)"', page))
    assert targets, "the dashboard links to no glossary anchor at all"
    missing = sorted(t for t in targets if f'id="{t}"' not in learn)
    assert missing == []


def test_terms_carry_a_tooltip_not_just_a_link(client):
    page = client.get("/").text
    assert 'class="gloss"' in page
    assert 'title="your miss rate minus your own median' in page


def test_learn_is_linked_from_the_dashboard_header(client):
    assert 'href="/learn"' in client.get("/").text


def test_glossary_internal_backlinks_exist(client):
    import re
    learn = client.get("/learn").text
    backlinks = set(re.findall(r'href="#([a-z]+)"', learn))
    for target in backlinks:
        assert f'id="{target}"' in learn


# ---------------------------------------------------- blacklist everywhere --

def test_the_listing_card_can_blacklist_and_unblock(client):
    out = client.app.state.outdir
    page = client.get("/maps").text
    assert 'class="card-x"' in page
    assert "never suggest this map" in page
    client.post("/blacklist", data={"md5": MAP_PLAYED, "scope": "map",
                                    "next": "/maps"})
    blocked_page = client.get("/maps").text
    assert "card-wrap is-blocked" in blocked_page
    assert "suggest this map again" in blocked_page
    assert MAP_PLAYED in blacklist.load(out)["maps"]
    client.post("/blacklist/remove", data={"md5": MAP_PLAYED, "next": "/maps"})
    assert blacklist.load(out)["maps"] == []
    assert "card-wrap is-blocked" not in client.get("/maps").text


def test_the_map_page_can_blacklist_the_difficulty_and_the_set(client):
    out = client.app.state.outdir
    page = client.get(f"/map/{MAP_PLAYED}").text
    assert "never suggest this difficulty" in page
    assert "whole set" in page
    client.post("/blacklist", data={"md5": MAP_PLAYED, "scope": "map",
                                    "next": f"/map/{MAP_PLAYED}"})
    page = client.get(f"/map/{MAP_PLAYED}").text
    assert "blacklisted" in page and "unblock" in page
    client.post("/blacklist/remove", data={"md5": MAP_PLAYED,
                                           "next": f"/map/{MAP_PLAYED}"})
    assert "never suggest this difficulty" in client.get(f"/map/{MAP_PLAYED}").text


# ------------------------------------------------------------ open in osu --

def test_a_recommendation_opens_in_osu_through_the_server(client):
    """The button posts the md5; the server builds the URI from the index."""
    out = client.app.state.outdir
    conn = index.connect(index.db_path(out))
    try:
        conn.execute("UPDATE library_beatmaps SET beatmap_id = 424242, "
                     "set_id = 31337 WHERE beatmap_md5 = ?", (MAP_NEW,))
        conn.commit()
    finally:
        conn.close()
    page = client.get("/").text
    assert 'action="/open"' in page
    assert f'name="md5" value="{MAP_NEW}"' in page


def test_the_open_route_launches_the_beattap_in_the_game(client, monkeypatch):
    from osu_critique.web import app as web_app

    out = client.app.state.outdir
    conn = index.connect(index.db_path(out))
    try:
        conn.execute("UPDATE library_beatmaps SET beatmap_id = 424242 "
                     "WHERE beatmap_md5 = ?", (MAP_NEW,))
        conn.commit()
    finally:
        conn.close()
    seen = []
    monkeypatch.setattr(web_app, "_launch_uri", lambda uri: seen.append(uri) or True)
    r = client.post("/open", data={"md5": MAP_NEW, "next": "/#w-recommend"},
                    follow_redirects=False)
    assert r.status_code in (302, 303)
    assert seen == ["osu://b/424242"]
    assert r.headers["location"] == "/#w-recommend?open=ok"


def test_a_map_with_only_a_set_id_opens_the_set(client, monkeypatch):
    from osu_critique.web import app as web_app

    out = client.app.state.outdir
    conn = index.connect(index.db_path(out))
    try:
        conn.execute("UPDATE library_beatmaps SET beatmap_id = NULL, set_id = 31337 "
                     "WHERE beatmap_md5 = ?", (MAP_NEW,))
        conn.commit()
    finally:
        conn.close()
    seen = []
    monkeypatch.setattr(web_app, "_launch_uri", lambda uri: seen.append(uri) or True)
    client.post("/open", data={"md5": MAP_NEW, "next": "/"}, follow_redirects=False)
    assert seen == ["osu://s/31337"]


def test_the_open_route_cannot_be_asked_to_open_anything_else(client, monkeypatch):
    from osu_critique.web import app as web_app

    seen = []
    monkeypatch.setattr(web_app, "_launch_uri", lambda uri: seen.append(uri) or True)
    for md5 in ("", "javascript:alert(1)", "../../etc/passwd", "f" * 32):
        r = client.post("/open", data={"md5": md5, "next": "/"},
                        follow_redirects=False)
        assert r.headers["location"].endswith("open=no-id")
    assert seen == []


def test_a_failed_launch_says_so(client, monkeypatch):
    from osu_critique.web import app as web_app

    out = client.app.state.outdir
    conn = index.connect(index.db_path(out))
    try:
        conn.execute("UPDATE library_beatmaps SET beatmap_id = 424242 "
                     "WHERE beatmap_md5 = ?", (MAP_NEW,))
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(web_app, "_launch_uri", lambda uri: False)
    r = client.post("/open", data={"md5": MAP_NEW, "next": "/"},
                    follow_redirects=False)
    assert r.headers["location"].endswith("open=error")


def test_the_dashboard_reports_what_the_open_click_did(client):
    assert "osu! was asked to open that map" in client.get("/?open=ok").text
    assert "Could not launch osu!" in client.get("/?open=error").text
    assert "no online id" in client.get("/?open=no-id").text


def test_the_map_page_offers_the_game_link_both_ways(client):
    out = client.app.state.outdir
    conn = index.connect(index.db_path(out))
    try:
        conn.execute("UPDATE beatmaps SET beatmap_id = 555001, set_id = 999001 "
                     "WHERE beatmap_md5 = ?", (MAP_PLAYED,))
        conn.commit()
    finally:
        conn.close()
    page = client.get(f"/map/{MAP_PLAYED}").text
    assert 'action="/open"' in page
    assert "play in osu!" in page
    # the raw protocol link stays for a page served from another machine
    assert 'href="osu://b/555001"' in page
    assert "direct link" in page
