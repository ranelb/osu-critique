"""Star rating and pp, via ``rosu-pp-py`` (optional extra ``osu-critique[stars]``).

The core package measures the play; it does not run osu!'s difficulty/pp
algorithm, and lazer's Realm is not readable from Python. Both live behind this
optional module instead, so the core install stays numpy+slider.

``rosu-pp-py`` is a ~600 KB Rust wheel and is imported lazily: everything here
that does not call it (mod canonicalisation, the md5 -> map index, the cache
shapes) is testable without it.

Two gotchas, both paid for in time:

- **lazer's ``files/`` store is content-addressed by SHA-256; a replay's
  ``beatmap_md5`` is MD5.** The path cannot be derived from the hash — every
  blob's ``.osu`` bytes must be hashed to build md5 -> path. This reuses
  ``io.pairing.build_lazer_index`` and caches the index.
- **Relax/Autopilot are unranked** and ``rosu-pp`` rejects them: strip RX/AP
  before computing pp (NF/EZ/HD/HR/DT/NC/HT/FL/SD/PF/SO/TD are kept). SR is
  unaffected by HD/NF/RX, so only DT/HT/HR are recomputed as mod families, but
  NM is always computed (the base rating other mods are read against).
"""
from __future__ import annotations

import json
import os

# mods that change star rating; canonicalised to the rankable family
SR_MODS = {"DT": "DT", "NC": "DT", "HT": "HT", "DC": "HT", "HR": "HR"}
# mods rosu-pp will accept as ranked (RX/AP stripped)
PP_RANKED = {"NF", "EZ", "HD", "HR", "DT", "NC", "HT", "FL", "SD", "PF", "SO", "TD"}


def _tokens(mod_string):
    """Split a mod label into two-letter mods.

    Handles both ``"DT+HR"`` and the concatenated ``"DTHR"`` / ``"NCDT"``
    forms, and drops ``"NM"``.
    """
    raw = (mod_string or "").upper().replace(",", "+").replace(";", "+")
    out = []
    for tok in raw.split("+"):
        tok = tok.strip()
        if not tok or tok == "NM":
            continue
        if len(tok) == 2:
            out.append(tok)
        else:                                   # concatenated two-letter mods
            out.extend(tok[i:i + 2] for i in range(0, len(tok) - 1, 2))
    return out


def effective_sr_mods(mod_string):
    """The comma list of mods that change SR, canonicalised and deduped.

    ``"NCDT"`` / ``"DT,NC"`` collapse to ``"DT"``; HD/NF/RX are dropped.
    """
    out = []
    for tok in _tokens(mod_string):
        canon = SR_MODS.get(tok)
        if canon and canon not in out:
            out.append(canon)
    return ",".join(sorted(out))


def pp_mods(mod_string):
    """The rankable mods, canonicalised order preserved (RX/AP stripped)."""
    keep = []
    for tok in _tokens(mod_string):
        canon = SR_MODS.get(tok, tok)
        if canon in PP_RANKED and canon not in keep:
            keep.append(canon)
    return ",".join(keep)


def collect_needed(rows, player=None):
    """``{beatmap_md5: {effective SR mod strings}}`` over metrics rows.

    Every map always gets the empty string (NM), because the base rating is
    needed even when the map was only ever played modded.
    """
    need = {}
    for m in rows:
        if player and m.get("player") and m["player"] != player:
            continue
        md5 = m.get("beatmap_md5")
        if not md5:
            continue
        need.setdefault(md5, set()).add(effective_sr_mods(m.get("mod_string")))
        need[md5].add("")
    return need


def _load_json(path):
    if os.path.isfile(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def load_index(outdir, files_dir=None):
    """md5 -> path for the lazer store, cached at ``<outdir>/lazer_md5_index.json``."""
    from ..io import pairing
    from ..config import lazer_files as _lazer_files

    cache_path = os.path.join(str(outdir), "lazer_md5_index.json")
    cached = _load_json(cache_path)
    if cached:
        return cached
    index = pairing.build_lazer_index(files_dir or _lazer_files())
    with open(cache_path, "w") as f:
        json.dump(index, f)
    return index


def _rosu():
    try:
        from rosu_pp_py import Beatmap, Difficulty, Performance
    except ImportError as e:                                     # pragma: no cover
        raise RuntimeError(
            "rosu-pp-py is not installed; install the optional extra: "
            "pip install 'osu-critique[stars]'") from e
    return Beatmap, Difficulty, Performance


def build_stars(rows, index, cache=None, player=None, log=print):
    """``{md5: {"NM"|"DT"|"HT"|"HR": stars}}`` for every map in ``rows``.

    Only mods that change SR are stored; HD/NF/RX reuse the NM value by
    definition.
    """
    cache = {} if cache is None else cache
    need = collect_needed(rows, player=player)
    # only pull in rosu-pp when there is actually work: a fully cached set is
    # usable without the optional extra installed
    todo = [md5 for md5, mods in need.items()
            if index.get(md5) and any((m or "NM") not in cache.get(md5, {})
                                      for m in mods)]
    if not todo:
        return cache
    Beatmap, Difficulty, _ = _rosu()
    missing = 0
    for md5 in sorted(todo):
        path = index.get(md5)
        if not path or not os.path.isfile(path):
            missing += 1
            continue
        entry = cache.setdefault(md5, {})
        bm = None
        for mods in sorted(need[md5]):
            key = mods or "NM"
            if key in entry:
                continue
            try:
                if bm is None:
                    bm = Beatmap(path=path)
                diff = Difficulty(mods=mods) if mods else Difficulty()
                entry[key] = round(diff.calculate(bm).stars, 3)
            except Exception as e:                               # noqa: BLE001
                log(f"stars: {md5[:8]} {key}: {e}")
    if missing:
        log(f"stars: {missing} maps not found in the lazer store")
    return cache


def build_pp(rows, index, cache=None, player=None, log=print):
    """``{replay_md5: {pp, stars, aim, speed, combo, n, mods}}`` for every play."""
    cache = {} if cache is None else cache
    maps = {}
    skipped = 0
    rows = [m for m in rows
            if (not player or not m.get("player") or m["player"] == player)
            and m.get("replay_md5") and m.get("beatmap_md5") in index
            and m["replay_md5"] not in cache]
    if not rows:
        return cache
    Beatmap, _, Performance = _rosu()
    for m in rows:
        key = m.get("replay_md5")
        md5 = m.get("beatmap_md5")
        cr = m.get("counts_recorded") or {}
        try:
            bm = maps.get(md5)
            if bm is None:
                bm = maps[md5] = Beatmap(path=index[md5])
            p = Performance(mods=pp_mods(m.get("mod_string")))
            p.set_accuracy(100.0 * (m.get("accuracy") or 0.0))
            p.set_combo(m.get("max_combo") or 0)
            p.set_misses(cr.get("miss", 0))
            p.set_lazer(True)
            r = p.calculate(bm)
            d = r.difficulty
            cache[key] = {"pp": round(r.pp, 2), "stars": round(d.stars, 3),
                          "aim": round(d.aim, 2), "speed": round(d.speed, 2),
                          "n": d.n_objects, "mods": pp_mods(m.get("mod_string"))}
        except Exception as e:                                   # noqa: BLE001
            log(f"pp: {m.get('tag') or key[:8]}: {e}")
            skipped += 1
    if skipped:
        log(f"pp: {skipped} plays skipped")
    return cache
