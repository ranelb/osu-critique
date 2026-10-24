# Vendored static assets

Everything here ships inside the wheel and is served locally: no CDN at runtime
(except map covers, which are fetched lazily and cached).

| file | version | licence | source |
|---|---|---|---|
| `htmx.min.js` | 2.0.4 | BSD 2-Clause | https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js |
| `fonts/poppins-{400,600,800}.woff2` | Poppins v24 (latin subset) | SIL OFL 1.1 (`fonts/OFL.txt`) | https://fonts.googleapis.com/css2?family=Poppins |

Why Poppins and not Torus (the font osu! uses): `ppy/osu-resources` ships
`osu.Game.Resources/Fonts/Torus/LICENCE`, whose whole text is *"This font
requires a commercial licence for distribution."* The osu!-listing **layout**
is not licensed; the typeface is.
