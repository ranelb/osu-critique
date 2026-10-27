"""The user-profile fetch: API v2 nests every stat under ``statistics``.

The API user object keeps pp / rank / play_count / counts / level / grades inside
a ``statistics`` dict; the HTML page embeds them flat. Both paths must arrive at
``summarize()`` looking the same, or the whole profile prints ``None`` — which is
exactly what shipped before this test.
"""
import json

from osu_critique import profile as P

# a trimmed real GET /users/{id}/osu response
API_USER = {
    "id": 37788237,
    "username": "TestPlayer",
    "country_code": "DE",
    "join_date": "2025-04-21T16:42:13+00:00",
    "rank_highest": {"rank": 203418, "updated_at": "2026-10-06T12:48:49Z"},
    "statistics": {
        "pp": 3765.74,
        "global_rank": 203898,
        "country_rank": 10154,
        "accuracy": 0.924982,
        "hit_accuracy": 92.4982,
        "play_count": 8730,
        "play_time": 693065,
        "level": {"current": 98, "progress": 0},
        "grade_counts": {"ss": 0, "s": 16, "a": 258},
        "count_300": 1670316,
        "count_100": 420826,
        "count_50": 40293,
        "count_miss": 101925,
    },
}


def test_fetch_profile_api_flattens_statistics(monkeypatch):
    """Regression: returning the raw user object left every field None."""
    monkeypatch.setattr(P, "_get_token", lambda *a, **k: "token")
    payload = json.dumps(API_USER).encode()

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return payload

    monkeypatch.setattr(P.urllib.request, "urlopen", lambda *a, **k: _Resp())
    st = P.fetch_profile_api("TestPlayer", "id", "secret")

    assert st["pp"] == 3765.74
    assert st["global_rank"] == 203898
    assert st["play_count"] == 8730
    assert st["count_miss"] == 101925
    assert st["username"] == "TestPlayer"


def test_summarize_reads_the_flat_shape():
    s = P.summarize(P._flatten(API_USER))
    assert s["pp"] == 3765.74
    assert s["global_rank"] == 203898
    assert s["country_rank"] == 10154
    assert s["play_count"] == 8730
    assert s["play_time_hours"] == 192.5
    assert s["level"] == 98
    assert s["grades"] == {"ss": 0, "s": 16, "a": 258}
    assert s["counts"] == {"300": 1670316, "100": 420826, "50": 40293,
                           "miss": 101925}
    assert s["accuracy_pct"] == 92.4982          # percent, not a 0..1 fraction
    assert s["rank_highest"]["rank"] == 203418


def test_api_and_scrape_paths_produce_the_same_flat_shape():
    """The scrape path already flattened; the API path must match it exactly."""
    api = P._flatten(API_USER)
    scraped = dict(API_USER["statistics"])
    for k in ("id", "username", "country_code", "join_date", "rank_highest"):
        scraped[k] = API_USER.get(k)
    assert api == scraped
