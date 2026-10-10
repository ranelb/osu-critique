"""Online rank status for every played beatmap (osu! API v2, optional network).

A play on a **ranked/approved** map is pp-eligible; **qualified/loved** maps
have a leaderboard but award no pp; **pending/wip/graveyard** award nothing. The
split matters for any "how much of my practice is on pp-eligible maps" question,
and it cannot be read from the replay or the .osu alone.

The map's online ``BeatmapID`` is parsed from the ``.osu`` ``[Metadata]`` (most
played maps carry one), then the IDs are batch-queried. Two things the first
parser got wrong: the batch endpoint returns ``{"beatmaps": [...]}``, not a bare
list, and it accepts at most 50 ids per request.

Credentials are the same client-credentials pair as ``profile``
(``config.osu_client_id/secret``); no network is touched without them.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

API_BEATMAPS = "https://osu.ppy.sh/api/v2/beatmaps?ids[]={ids}"
UA = {"User-Agent": "osu-critique-status/1.0"}

PP_ELIGIBLE = {"ranked", "approved"}
LEADERBOARD_ONLY = {"qualified", "loved"}


def classify(status):
    """``"pp-eligible"`` / ``"leaderboard-only"`` / ``"unranked"`` (None -> None)."""
    if not status:
        return None
    if status in PP_ELIGIBLE:
        return "pp-eligible"
    if status in LEADERBOARD_ONLY:
        return "leaderboard-only"
    return "unranked"


def beatmap_ids(index, needed=None):
    """``{md5: online BeatmapID}`` parsed from each .osu's ``[Metadata]``.

    ``needed`` limits parsing to the maps actually played.
    """
    out = {}
    for md5, path in index.items():
        if needed is not None and md5 not in needed:
            continue
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                txt = f.read()
        except OSError:
            continue
        m = re.search(r"^BeatmapID\s*:\s*(\d+)", txt, re.M)
        if m and int(m.group(1)) > 0:
            out[md5] = int(m.group(1))
    return out


def fetch_statuses(ids, token, chunk=50, log=None):
    """Batch-query the API: ``{beatmap_id: {status, stars, set_id, ranked}}``."""
    got = {}
    ids = sorted(ids)
    for i in range(0, len(ids), chunk):
        part = ids[i:i + chunk]
        url = API_BEATMAPS.format(ids="&ids[]=".join(str(x) for x in part))
        req = urllib.request.Request(
            url, headers={**UA, "Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            for b in json.load(resp).get("beatmaps", []):
                got[b["id"]] = {"status": b.get("status"),
                                "stars": b.get("difficulty_rating"),
                                "set_id": b.get("beatmapset_id"),
                                "ranked": b.get("ranked")}
        if log:
            log(f"status: {min(i + chunk, len(ids))}/{len(ids)}")
    return got


def _load_json(path):
    if os.path.isfile(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def save(cache, cache_path):
    with open(cache_path, "w") as f:
        json.dump(cache, f)
    return cache


def build_statuses(rows, index, cache=None, cache_path=None, player=None,
                   fetch=True, log=print):
    """Resolve status for every played map, caching to ``cache_path``.

    Returns ``(cache, md5_to_id)``. Without credentials and ``fetch=True`` it
    raises RuntimeError (the caller decides how to report it) rather than
    silently skipping.
    """
    cache = {int(k): v for k, v in (cache or {}).items()}
    needed = {m["beatmap_md5"] for m in rows
              if m.get("beatmap_md5")
              and not (player and m.get("player") and m["player"] != player)}
    md5_to_id = beatmap_ids(index, needed)
    missing = [i for i in set(md5_to_id.values()) if i not in cache]
    if missing and fetch:
        from ..config import osu_client_id, osu_client_secret
        from ..profile import _get_token
        cid, secret = osu_client_id(), osu_client_secret()
        if not cid or not secret:
            raise RuntimeError(
                "no osu! API credentials — create a client at "
                "https://osu.ppy.sh/oauth/clients and run `osu-critique setup` "
                "(or export OSU_CLIENT_ID / OSU_CLIENT_SECRET). "
                f"Would query {len(missing)} beatmaps.")
        log(f"status: resolving {len(missing)} beatmaps via API v2")
        cache.update(fetch_statuses(missing, _get_token(cid, secret), log=log))
        if cache_path:
            save(cache, cache_path)
    return cache, md5_to_id


def summarise(rows, cache, md5_to_id, player=None):
    """Play counts and in-game hours per status bucket over ``rows``."""
    from collections import Counter
    seen = set()
    counts, hours = Counter(), Counter()
    n = known = 0
    for m in rows:
        if player and m.get("player") and m["player"] != player:
            continue
        key = m.get("replay_md5") or m.get("tag")
        if key in seen:
            continue
        seen.add(key)
        n += 1
        bid = md5_to_id.get(m.get("beatmap_md5"))
        rec = cache.get(bid) if bid else None
        status = (rec or {}).get("status")
        dur = (m.get("aim_mode") or {}).get("duration_s") or 0
        if status:
            known += 1
            counts[status] += 1
            hours[status] += dur
    total_hours = sum(hours.values()) / 3600.0
    return {"plays": n, "known": known, "counts": dict(counts),
            "hours": {k: v / 3600.0 for k, v in hours.items()},
            "total_hours": total_hours}
