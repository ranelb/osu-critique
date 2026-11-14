# Vendored static assets

Everything here ships inside the wheel and is served locally: no CDN at runtime
(except map covers, which are fetched lazily and cached).

| file | version | licence | source |
|---|---|---|---|
| `htmx.min.js` | 2.0.4 | BSD 2-Clause | https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js |
| `fonts/poppins-{400,600,800}.woff2` | Poppins v24 (latin subset) | SIL OFL 1.1 (`fonts/OFL.txt`) | https://fonts.googleapis.com/css2?family=Poppins |
| `fonts/jetbrains-mono.woff2` | JetBrains Mono v24 (latin subset, variable 400–800) | SIL OFL 1.1 | https://fonts.googleapis.com/css2?family=JetBrains+Mono |

Why Poppins and not Torus (the font osu! uses): `ppy/osu-resources` ships
`osu.Game.Resources/Fonts/Torus/LICENCE`, whose whole text is *"This font
requires a commercial licence for distribution."* The osu!-listing **layout**
is not licensed; the typeface is.

Why a second face: every number on these pages (accuracy, UR, star rating,
per-object ms) sits in a column or a figure and has to line up. Poppins is
proportional, so `172.1` and `1119` in two stacked rows drift. JetBrains Mono
carries the digits, the table heads and the bar keys; Poppins keeps the prose.
One variable file covers the whole weight axis, so it costs 31 KB once.
