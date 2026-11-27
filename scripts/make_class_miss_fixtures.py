"""Synthetic per-object rows with a planted miss structure: ``tests/fixtures/class_miss/maps.json``.

Ground truth, by construction (miss probability per object):

    base 2 %, +9 pp in the top aim-strain tercile of the map, +10 pp on ``walk:star`` objects.

* ``walk:star``     a real effect: contrast stays ~ +10 pp after matching on strain.
* ``dist:wide``     *confounded*: wide legs sit in the high-strain sections, so the raw contrast
                    is large and positive, but the strain-matched one is ~ 0.
* ``walk:hexagon``  no effect, an ordinary class to check the intervals span 0.
* ``curve:arc``     present on 4 objects of a map only: must be held back by the gate.

Row layout (lists, to keep the fixture small): see ``COLUMNS``. Deterministic: ``python
scripts/make_class_miss_fixtures.py`` rewrites the file byte for byte.
"""
import json
import random
from pathlib import Path

COLUMNS = ["kind", "result", "shape", "walk", "curve", "leg_dist", "leg_flow", "leg_tempo",
           "sec_aim", "sec_speed"]
MAPS, PER_MAP = 60, 200


def make():
    rng = random.Random(20260528)
    maps = {}
    for m in range(MAPS):
        rows = []
        sections = [rng.uniform(20, 200) for _ in range(PER_MAP // 5 + 1)]
        speeds = [rng.uniform(20, 150) for _ in sections]
        cut = sorted(sections)[2 * len(sections) // 3]       # top tercile of aim strain
        i = 0
        while i < PER_MAP:
            sec = i // 5
            high = sections[sec] > cut
            wide = rng.random() < (0.55 if high else 0.08)
            dist = "wide" if wide else rng.choice(["touching", "close", "medium"])
            walk = None
            run = 1
            roll = rng.random()
            if roll < 0.02:
                walk, run = "star", 4
            elif roll < 0.05:
                walk, run = "hexagon", 4
            curve = "arc" if (m == 0 and i in (10, 11, 12, 13)) else None
            for _ in range(run):
                if i >= PER_MAP:
                    break
                p = 0.02 + (0.09 if high else 0.0) + (0.10 if walk == "star" else 0.0)
                rows.append(["Circle", "miss" if rng.random() < p else "300", None, walk, curve,
                             dist, rng.choice(["flow", "angle", "snap", "none"]),
                             rng.choice(["fast", "mid", "slow"]),
                             round(sections[sec], 2), round(speeds[sec], 2)])
                i += 1
        rows[0][5] = rows[0][6] = rows[0][7] = None            # the first object has no leg
        maps[f"map{m:02d}"] = rows
    return {"columns": COLUMNS, "maps": maps}


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "tests/fixtures/class_miss/maps.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(make(), separators=(",", ":")) + "\n")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
