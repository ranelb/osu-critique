# Stored critiques

There are two kinds, and they are not the same artifact:

- **A scope critique** — the critique tab, `osu-critique critique`. It is about a
  *selection*: replays, whole maps, a date range, or any mix. The model reads one
  deterministic text and nothing else. This is the current path (0.23.0).
- **A per-run critique** — `osu-critique coach --save`, written before 0.23.0. It
  was built from a metrics-JSON prompt. The web no longer generates these; it
  still shows the ones that exist, read-only and labelled, because they are
  authored text that was paid for.

The run page's **critique this run** button is gone: it now links into the tab
with the run pre-selected, and shows whatever is stored for that run.

## Scope critiques

A selection is additive and deduplicated: `--runs a,b`, `--maps <md5>,<md5>`
(every attempt of those maps), and a range that reads **`played_at`** — when you
played, not when the replay was exported. Presets: `today`, `session` (since the
last gap longer than three hours), `7d`, `30d`; or `--since YYYY-MM-DD [--until]`.

A **mod filter** (`DT`, `HR`, `HD`, `HT`, `NM`) narrows the map and range
selectors — "this map, DT only", "last week, no-mod plays". It deliberately does
not touch replays you pick by hand: naming a replay is a stronger statement than
a filter, and silently dropping it would be a bug you only notice from the count.
`NM` means *no mods at all*; every other value is a substring of the stored
`mod_string`, so `DT` also catches `HDDT`.

`scope.py` resolves the selection and renders **one text**. That text is the
page's summary section, the model's entire input, and the thing stored in the
artifact — there is no second formatter and no raw metrics in the prompt.

Sizing, because a selection has no natural bound:

| | |
|---|---|
| full per-replay reports | up to 10 runs |
| above that | overview + per-map table (top 40 by plays) + per-run table (newest 120) + the cross-attempt stability block |
| omission | counted in the header, so the model knows what it was not given |
| warning | above 300 KB of text: the page says so and the button reads "generate anyway" — nothing is blocked, because a big selection is the owner's call, not the tool's |

Stored at `out/critiques/scope/<hash>.json`, where the hash covers **the text and
the system prompt**. The same selection over the same corpus is the same artifact,
so a second click opens the stored answer instead of paying again; a re-analysed
replay or a new note changes the text, which is a different artifact by
definition. There is no "stale" state for these — that is the point of hashing.

The sidecar keeps the text as well as the answer, so an artifact can be read years
later next to exactly the input it was given.

```json
{
 "schema_version": 1, "kind": "scope", "hash": "…",
 "created": "…", "model": "deepseek-v4-flash", "prompt_hash": "…", "system": "…",
 "selection": {"runs": [], "maps": ["7f2830e4…"], "since": "7d", "until": null},
 "n_runs": 47, "n_maps": 39, "first_played": "…", "last_played": "…",
 "bytes": 18301, "text": "# Critique selection …", "body": "…"
}
```

`index.sqlite` mirrors the **metadata only** (`scope_critiques`: hash, created,
model, counts, span, size, path — schema v5): the bodies are tens of kilobytes
and are read from the file when a critique is opened. An index from an older
release is rebuilt on the next server start; `osu-critique index --rebuild` does
it by hand.

### From a terminal

```bash
osu-critique critique --since 7d                    # the deterministic text
osu-critique critique --maps <md5> --until 2026-10-20
osu-critique critique --maps <md5> --llm            # call + store + print
```

Same builder, same hash, same sidecar as the tab.

## Per-run critiques (legacy)

Written before 0.23.0 from a `metrics`-JSON prompt by `osu-critique coach --save`.
The web reads them and never regenerates them: the answers exist, they were made
from different input, and pretending otherwise would be a lie.

## What is stored

Canonical: `out/critiques/<run_id>.json` (the run id is the replay md5, or
`tag:<tag>` for pre-schema artifacts; `:` becomes `_` in the filename).

```json
{
 "schema_version": 1,
 "run_id": "5c2aaa86…",
 "replay_md5": "5c2aaa86…",
 "beatmap_md5": "7f2830e4…",
 "model": "deepseek-v4-flash",
 "prompt_hash": "…",
 "run_hash": "…",
 "created": "2026-10-24T17:26:41+00:00",
 "body": "Your timing spread widens noticeably after the first kiai; …"
}
```

Like annotations, this is **authored** data: deleting `out/index.sqlite` loses
nothing, and every sweep re-mirrors the files into the `critiques` table
(primary key `run_id`).

## Staleness

| hash | covers | stale when |
|---|---|---|
| `run_hash` | the metrics document **and the player's annotations** | the play was re-analysed, or you added/changed a note on that map |
| `prompt_hash` | the system prompt (the critique framework) | the framework changed (edits, or a newer release) |
| `model` | — | never: a different model is a different opinion |

The run page shows the model, when it was made, and a **stale** badge with the
reason. A stale critique is not deleted — it is still what the model said about
*that* play at that time, which is often useful to compare against.

## The call

- One chat-completions call, streamed (`stream: true`), same prompt path as
  `coach`: `coach.prepare_critique()` builds system + user + notes,
  `coach.generate_critique()` calls the endpoint.
- In the browser the request is `POST /run/<id>/critique` with
  `Accept: text/event-stream`; the response is SSE —
  `data: {"delta": "…"}` per chunk, then `data: {"done": true, "model", "created"}`,
  then `data: [DONE]`. Errors arrive as `data: {"error": "…"}`.
- Without JavaScript (or with `fetch` unavailable) the same form posts normally,
  the server generates the critique, stores it and redirects to the run page.
- The key is read server-side only (`OSU_LLM_KEY` / `osu-critique setup`); it is
  never sent to the browser. No key → the button is not rendered and the route
  answers 400 with the reason.

## Gating

`web.llm_remote` (default `true`, env `OSU_WEB_LLM_REMOTE`) decides whether a
non-loopback client may spend a call. With it set to `false`, LLM routes answer
403 for anything but `127.0.0.1`/`::1`, while every read-only page stays open.
The default is the owner's explicit choice — the server binds `0.0.0.0` with no
auth, so a device on the same network can use the key unless you turn this off.

## Not stored

The deterministic `report` is free to recompute and is never stored; it is
rendered inline on the run page from the metrics artifact.
