"""osu! user profile: official API v2 (bring-your-own client credentials)
with an unofficial HTML-scrape fallback (no keys).

Environment:
    OSU_CLIENT_ID       osu! API v2 client id (https://osu.ppy.sh/oauth/clients)
    OSU_CLIENT_SECRET   corresponding client secret
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://osu.ppy.sh/oauth/token"
API_USER_URL = "https://osu.ppy.sh/api/v2/users/{username}/osu"
WEB_USER_URL = "https://osu.ppy.sh/users/{username}"

UA = {"User-Agent": "osu-critique/0.1 (replay analysis)"}


# ------------------------------------------------------------- API v2 ------

def _get_token(client_id, client_secret):
    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
        "scope": "public",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    return data["access_token"]


def fetch_profile_api(username, client_id=None, client_secret=None):
    """Fetch a user's osu!standard stats via API v2."""
    from .config import osu_client_id, osu_client_secret
    client_id = client_id or osu_client_id()
    client_secret = client_secret or osu_client_secret()
    if not client_id or not client_secret:
        raise RuntimeError(
            "no osu! API credentials. Run `osu-critique setup` or set "
            "OSU_CLIENT_ID / OSU_CLIENT_SECRET (create at "
            "https://osu.ppy.sh/oauth/clients). The HTML fallback still works "
            "without credentials.")
    token = _get_token(client_id, client_secret)
    req = urllib.request.Request(
        API_USER_URL.format(username=urllib.parse.quote(username)),
        headers={**UA, "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


# -------------------------------------------------------- HTML fallback ----

def _extract_user_json(page):
    """The osu! profile page embeds the full user object as escaped JSON."""
    s = html.unescape(page)
    j = s.find('"username":"')
    if j < 0:
        raise ValueError("no embedded user JSON found")
    start = s.rfind("{", 0, j)
    depth, end = 0, None
    for k in range(start, len(s)):
        if s[k] == "{":
            depth += 1
        elif s[k] == "}":
            depth -= 1
            if depth == 0:
                end = k + 1
                break
    if end is None:
        raise ValueError("could not parse embedded user JSON")
    return json.loads(s[start:end])


def fetch_profile_scrape(username):
    """Fetch a user's osu!standard stats by scraping the public profile page."""
    req = urllib.request.Request(WEB_USER_URL.format(username=username),
                                 headers={**UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        page = resp.read().decode("utf-8", errors="ignore")
    data = _extract_user_json(page)
    st = data.get("statistics", {})
    st["id"] = data.get("id")
    st["username"] = data.get("username")
    st["country_code"] = data.get("country_code")
    st["join_date"] = data.get("join_date")
    st["rank_highest"] = data.get("rank_highest")
    return st


# -------------------------------------------------------------- summary ----

def summarize(stats):
    """Reduce raw API/scrape stats to a compact summary for humans + coach."""
    def g(*keys, default=None):
        for k in keys:
            if k in stats:
                return stats[k]
        return default

    grades = g("grade_counts") or {}
    level = g("level") or {}
    return {
        "username": g("username"),
        "id": g("id"),
        "country": g("country_code"),
        "pp": g("pp"),
        "global_rank": g("global_rank"),
        "country_rank": g("country_rank"),
        "rank_highest": g("rank_highest"),
        "accuracy_pct": g("hit_accuracy", "accuracy"),
        "play_count": g("play_count"),
        "play_time_hours": round(g("play_time", 0) / 3600, 1) if g("play_time") else None,
        "level": level.get("current"),
        "grades": {"ss": grades.get("ss", 0), "s": grades.get("s", 0),
                   "a": grades.get("a", 0)},
        "counts": {"300": g("count_300"), "100": g("count_100"),
                   "50": g("count_50"), "miss": g("count_miss")},
        "join_date": g("join_date"),
    }


def fetch_profile(username, allow_scrape=None):
    """Official API v2 first; the unofficial HTML scrape runs only when
    explicitly allowed (``--scrape`` flag or ``allow_scrape`` config option).

    ``allow_scrape=None`` means "use the config option"; ``True``/``False``
    override it for a single invocation.
    """
    from .config import allow_scrape as _cfg_allow_scrape
    if allow_scrape is None:
        allow_scrape = _cfg_allow_scrape()
    try:
        return summarize(fetch_profile_api(username))
    except RuntimeError:
        # no credentials configured
        if not allow_scrape:
            raise RuntimeError(
                "no osu! API credentials configured. Either:\n"
                "  1. create free API v2 credentials at https://osu.ppy.sh/oauth/clients, "
                "then run `osu-critique setup` (or set OSU_CLIENT_ID / OSU_CLIENT_SECRET);\n"
                "  2. or explicitly allow the unofficial HTML fallback with "
                "`osu-critique profile <user> --scrape` "
                "(or set allow_scrape: true in the config via `osu-critique setup`).")
        print("note: using the unofficial HTML scrape fallback "
              "(prefer the official API v2)", file=sys.stderr)
        try:
            return summarize(fetch_profile_scrape(username))
        except Exception as e:
            raise RuntimeError(f"profile fetch failed: {e}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"osu! API unreachable: {e.reason}") from e
