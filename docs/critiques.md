# Stored critiques

The LLM critique of a run is **stored with that run**, not regenerated every
time you open the page. One call, one artifact, and a clear mark when the
artifact no longer describes the data.

`osu-critique coach --save out/<tag>_metrics.json` stores it from the CLI; the
run page's **critique this run** button stores it from the browser.

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
