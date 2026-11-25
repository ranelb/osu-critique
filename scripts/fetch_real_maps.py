#!/usr/bin/env python3
"""Download the .osu files listed in tests/fixtures/patterns/real_maps.json.

Usage:  python scripts/fetch_real_maps.py [OUTDIR]     (default: ./real_maps)

Only ids are committed; the charts belong to their mappers, so each person
fetches their own copy for local analysis. Uses the public osu.ppy.sh/osu/<id>
endpoint (no login).
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIST = ROOT / "tests" / "fixtures" / "patterns" / "real_maps.json"


def main(argv):
    out = Path(argv[0] if argv else "real_maps")
    out.mkdir(parents=True, exist_ok=True)
    for bid, desc in json.loads(LIST.read_text())["maps"].items():
        dest = out / f"{bid}.osu"
        if dest.exists() and dest.stat().st_size > 1000:
            print(f"have {bid}  {desc}")
            continue
        r = subprocess.run(["curl", "-sf", "-m", "60", "-o", str(dest),
                            f"https://osu.ppy.sh/osu/{bid}"])
        ok = r.returncode == 0 and dest.exists() and dest.stat().st_size > 1000
        print(f"{'ok  ' if ok else 'FAIL'} {bid}  {desc}")
        if not ok and dest.exists():
            dest.unlink()


if __name__ == "__main__":
    main(sys.argv[1:])
