# Stars and pp (optional extra)

The core package measures the play; it does not run osu!'s difficulty/pp
algorithm. That lives behind the optional extra:

```sh
pip install 'osu-critique[stars]'      # adds rosu-pp-py (Rust wheel, ~600 KB)
osu-critique stars out/                # out/stars_by_md5.json
osu-critique pp    out/                # out/pp_by_replay.json
```

`rosu-pp-py` is imported lazily, so a core install never needs it; the mod
canonicalisation and the md5 -> map index are testable without it.

## Stars (`metrics/difficulty.build_stars`)

For every map in the stored runs it resolves the map path in lazer's store, then
computes the base NM rating and each SR-changing mod family:

- only **DT / NC -> DT, HT / DC -> HT, HR** change star rating; HD/NF/RX reuse
  the NM value by definition;
- **NM is always computed**, even for maps only ever played modded, because the
  base rating is what the modded one is read against.

`out/stars_by_md5.json` is `{beatmap_md5: {"NM": stars, "DT": stars, ...}}`.

## pp (`metrics/difficulty.build_pp`)

For each unique replay it sets accuracy, combo and miss count on the map with
the play's mods and ``set_lazer(True)``:

- **RX/AP are unranked and stripped** (rosu-pp rejects them); NF/EZ/HD/HR/DT/
  NC/HT/FL/SD/PF/SO/TD are kept;
- the difficulty attributes (`aim`, `speed`, `n`) come back beside the pp.

`out/pp_by_replay.json` is
`{replay_md5: {pp, stars, aim, speed, n, mods}}`.

## The gotcha that cost real time

**lazer's `files/` store is content-addressed by SHA-256; a replay's
`beatmap_md5` is MD5.** The path cannot be derived from the hash — every blob's
`.osu` bytes must be hashed to build md5 -> path. This reuses
`io.pairing.build_lazer_index` and caches the result at
`out/lazer_md5_index.json` (a few thousand blobs; build once).

## Environment note

The author's rosu-pp lives in its own venv
(`~/.local/share/osu-sr/venv`), kept out of the repo venv. If the extra is not
installed, the commands exit with the exact `pip install` line instead of
silently skipping.
