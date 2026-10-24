# Third-party components

## Shipped in the wheel

| component | licence | source |
|---|---|---|
| `slider==0.8.4` | MIT | PyPI — the beatmap/replay parser, pinned because the judgement is validated against this exact release |
| `numpy` | BSD-3-Clause | PyPI |
| `matplotlib` (optional `[charts]`) | PSF-based | PyPI |
| `rosu-pp-py` (optional `[stars]`) | MIT | PyPI |
| `fastapi`, `uvicorn`, `jinja2`, `python-multipart` (optional `[web]`) | MIT / BSD / BSD / Apache-2.0 | PyPI |
| `htmx` 2.0.4 (vendored static) | BSD-2-Clause | https://unpkg.com/htmx.org |
| Poppins (vendored woff2, latin subset) | SIL OFL 1.1 | https://fonts.google.com/specimen/Poppins — see `web/static/fonts/OFL.txt` |

## Downloaded at runtime, never bundled in the wheel

**BeatmapExporter** — https://github.com/kabiiQ/BeatmapExporter, MIT,
version `v2.8.0`, by kabiiQ. It is the osu!lazer Realm reader that makes the
opt-in `osu-critique export` possible; osu!lazer itself has no export interface
and reading the Realm from Python was investigated and rejected
(`docs/ROADMAP.md`, item 7a).

`osu-critique export --install` downloads one binary for the current platform,
verifies it against the pinned SHA-256 in `src/osu_critique/export_assets.json`,
and drops it in `~/.local/share/osu-critique/bin/`. The release workflow
attaches the same binaries to this project's GitHub releases (fetched from
upstream and hash-verified at build time), so the download works even if the
upstream release disappears. It is executed only when `export.enabled` is true.

No osu! assets are redistributed: beatmap covers are fetched at runtime from
`assets.ppy.sh` and cached locally.
