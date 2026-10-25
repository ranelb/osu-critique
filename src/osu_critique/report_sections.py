"""The deterministic report as data, with the CLI text as one renderer of it.

``render_report`` used to build a big list of strings. The web needs the same
content as sections, tables and verdicts, so the *content* lives here once and
both front ends serialize it: :func:`to_text` for the terminal,
``web/templates/run.html`` for the page.

Nothing in this module computes a new metric — it phrases what the analysis
already produced, keeping the thresholds that ``render_report`` always had
(UR verdicts, aim verdicts, the primary-target rule, the trust/time-base
warnings that stop a broken judgement reading as fact).
"""
from __future__ import annotations


# ------------------------------------------------------------------ verdicts --

def ur_verdict(value) -> str:
    if value is None:
        return "n/a"
    if value < 120:
        return "excellent"
    if value < 180:
        return "good"
    if value < 250:
        return "inconsistent"
    return "timing breakdown"


def aim_verdict(value) -> str:
    if value is None:
        return "n/a"
    if value < 0.30:
        return "strong"
    if value < 0.45:
        return "good"
    if value < 0.60:
        return "acceptable"
    return "aim struggling"


# -------------------------------------------------------------------- items --

def kv(label, value, note=None):
    return {"kind": "kv", "label": label, "value": value, "note": note}


def note(text, tone="info"):
    """A callout: the trust warning, a time-base notice, the primary target."""
    return {"kind": "note", "text": text, "tone": tone}


def table(columns, rows, caption=None):
    return {"kind": "table", "columns": columns, "caption": caption,
            "rows": [[("" if c is None else c) for c in row] for row in rows]}


def _section(section_id, title, *items):
    kept = [i for i in items if i is not None]
    # a wide table needs the full row: squeezing six numeric columns into a
    # third of the page is how "0.42r" becomes "0." with a cut-off remainder
    wide = any(i["kind"] == "table" and len(i["columns"]) > 5 for i in kept)
    return {"id": section_id, "title": title, "items": kept, "wide": wide}


# ------------------------------------------------------------------ builder --

def sections(metrics: dict, baseline: dict | None = None) -> list[dict]:
    """All report sections, in reading order."""
    out: list[dict] = []
    h = metrics.get("hit_error_ms") or {}
    aim = metrics.get("aim_px") or {}
    tb = metrics.get("time_base") or {}
    trust = metrics.get("trust") or {}
    b = baseline or {}
    b_ur = b.get("ur")
    b_aim = (b.get("aim_px") or {}).get("mean_norm") if isinstance(b.get("aim_px"), dict) else None
    recorded = metrics.get("counts_recorded") or {}

    # -- headline ------------------------------------------------------------
    ur = metrics.get("ur")
    ur_text = f"{ur:.1f} ({ur_verdict(ur)})" if ur is not None else "n/a"
    headline = [
        note(f"Accuracy {metrics['accuracy'] * 100:.1f}% | UR {ur_text} | "
             f"{recorded.get('300', 0)}x300 / {recorded.get('100', 0)}x100 / "
             f"{recorded.get('50', 0)}x50 / {recorded.get('miss', 0)}x miss | "
             f"max combo {metrics.get('max_combo')}", "headline"),
    ]
    if tb.get("note"):
        headline.append(note(f"TIME BASE: {tb['note']}", "warn"))
    if trust and not trust.get("trustworthy", True):
        headline.append(note(
            f"TRUST: judgement differs from the game on {trust.get('abs_delta_total')} "
            f"of {trust.get('judged')} objects "
            f"(miss {(trust.get('count_deltas') or {}).get('miss', 0):+d}, "
            f"{trust.get('abs_delta_pct', 0):.1f}%) — treat per-pattern numbers as "
            f"approximate.", "bad"))
    if metrics.get("failed_play"):
        headline.append(note("NOTE: this was a failed play (ended before the map "
                             "finished).", "warn"))
    if metrics.get("map_version_mismatch"):
        headline.append(note("NOTE: replay/map timing mismatch detected; analysis "
                             "unreliable past the replay end.", "warn"))
    out.append(_section("summary", "Summary", *headline))

    # -- map profile ---------------------------------------------------------
    prof = metrics.get("profile") or {}
    if prof:
        items = []
        rate = prof.get("rate") or {}
        bpm, gap = rate.get("effective_bpm") or {}, rate.get("note_gap_ms") or {}
        win = rate.get("gap_vs_300_window") or {}
        if bpm.get("median"):
            player = " (player time)" if tb.get("overridden") else ""
            detail = ""
            if {"p10", "median", "p90"} <= set(gap):
                detail = (f"note gaps p10 {gap['p10']:.0f} / median {gap['median']:.0f}"
                          f" / p90 {gap['p90']:.0f} ms")
            elif gap.get("median") is not None:
                detail = f"note gap median {gap['median']:.0f} ms"
            if win.get("p10_ratio"):
                detail += f" · the tightest notes sit {win['p10_ratio']:.1f}x the 300-window"
            items.append(kv(
                "rate",
                f"{bpm['median']:.0f} bpm effective "
                f"({(bpm.get('min') or bpm['median']):.0f}-"
                f"{(bpm.get('max') or bpm['median']):.0f})",
                (detail + player).strip() or None))
        comp = [f for f in prof.get("composition", []) if f.get("reported")]
        if comp:
            items.append(table(
                ["family", "share", "non-300", "mean err", "aim"],
                [[f["family"], f"{f['share'] * 100:.1f}% (n={f['n']})",
                  f"{f['non300_rate'] * 100:.1f}%",
                  f"{f['mean_err_ms']:+.1f} ms" if f.get("mean_err_ms") is not None else "—",
                  f"{f['mean_aim_r']:.2f}r" if f.get("mean_aim_r") is not None else "—"]
                 for f in sorted(comp, key=lambda f: -f["n"])[:8]],
                caption="composition"))
        stam = prof.get("stamina") or {}
        if stam.get("peak_notes_per_second"):
            run = stam.get("longest_sustained") or {}
            items.append(kv(
                "stamina", f"peak {stam['peak_notes_per_second']:.1f} n/s",
                f"{(stam.get('seconds_above_6nps') or 0):.0f}s above 6 n/s"
                + (f" · longest run {run['notes']} notes (~{run['seconds']:.0f}s)" if run else "")
                + (f" · {len(stam['breaks'])} break(s)" if stam.get("breaks") else "")))
        ch = prof.get("chains") or {}
        if ch.get("n_chains"):
            by_pos = ch.get("by_position") or []
            items.append(kv(
                "chains", f"{ch['n_chains']} runs ({ch.get('notes', 0)} notes) with a "
                          "steady gap",
                ("non-300 by position — " + ", ".join(
                    f"{p['notes']} notes {p['non300_rate'] * 100:.0f}%"
                    for p in by_pos)) if by_pos else None))
        timing = prof.get("timing_by_family") or []
        if timing:
            items.append(table(
                ["family", "bias", "p10", "p90", "n"],
                [[tf["family"], f"{tf['bias_ms']:+.1f} ms", f"{tf['p10']:+.0f}",
                  f"{tf['p90']:+.0f}", tf["n"]] for tf in timing[:4]]))
        sl = prof.get("sliders") or {}
        if sl.get("n"):
            speed = sl.get("cursor_speed_px_ms") or {}
            detail = None
            if speed.get("median") is not None:
                detail = (f"cursor speed needed p10 {speed.get('p10', 0):.2f} / "
                          f"median {speed['median']:.2f} / p90 {speed.get('p90', 0):.2f} px/ms")
            share = sl.get("long_path_share")
            items.append(kv(
                "sliders",
                f"{sl['n']}" + (f" ({share * 100:.0f}% with a real path ≥100px)"
                                if share is not None else ""),
                detail))
        for ctx in prof.get("context") or []:
            items.append(kv(f"context · {ctx['after']}",
                            f"{ctx['non300_rate'] * 100:.1f}%", f"n={ctx['n']}"))
        out.append(_section("profile", "Map profile", *items))

    # -- timing --------------------------------------------------------------
    timing_items = []
    if h.get("mean") is not None and h.get("std") is not None:
        timing_items.append(kv("mean hit error", f"{h['mean']:+.1f} ms",
                               f"std {h['std']:.1f} ms · "
                               f"{metrics.get('early_pct', 0) * 100:.0f}% early"))
    else:
        timing_items.append(note("no taps were assigned to an object "
                                 "(Relax play, or all misses)."))
    timing_items.append(kv("vs baseline",
                           ur_verdict(metrics.get("ur")),
                           f"baseline UR {b_ur:.0f}" if b_ur else None))
    if h.get("mean") is not None and abs(h["mean"]) > 6:
        timing_items.append(note("|bias| > 6 ms with a consistent sign — consider "
                                 "an offset test.", "warn"))
    out.append(_section("timing", "Timing", *timing_items))

    # -- aim -----------------------------------------------------------------
    aim_items = [kv("mean aim error at press time",
                    f"{aim['mean_norm']:.2f}r ({aim_verdict(aim['mean_norm'])})"
                    if aim.get("mean_norm") is not None else "n/a",
                    f"baseline {b_aim:.2f}r" if b_aim else None)]
    am = metrics.get("aim_mode") or {}
    d = am.get("distance_at_note_r") or {}
    ca = am.get("closest_approach_r") or {}
    pk = am.get("peak_offset_ms") or {}
    rn = am.get("reached_not_on_time") or {}
    es = am.get("error_shape") or {}
    if am.get("n") and d.get("mean") is not None:
        bits = [f"window ±{am.get('window_ms', 0):.0f} ms"]
        if ca.get("median") is not None:
            bits.append(f"closest approach {ca['median']:.2f}r")
        if pk.get("median") is not None:
            bits.append(f"peak {pk['median']:+.0f} ms")
        if pk.get("late_pct") is not None:
            bits.append(f"{pk['late_pct']:.0f}% late")
        bits.append(f"n={am['n']}")
        aim_items.append(kv(
            "cursor arrival",
            f"{d['mean']:.2f}r at the note"
            + (f" ({d['inside_pct']:.0f}% inside)" if d.get("inside_pct") is not None else ""),
            " · ".join(bits)))
    if rn.get("pct") is not None:
        details = []
        if es.get("short_pct") is not None:
            details.append(f"{es['short_pct']:.0f}% of arrivals stopped short")
        if es.get("past_pct") is not None:
            details.append(f"{es['past_pct']:.0f}% went past")
        aim_items.append(kv(
            "there but not then",
            f"{rn['pct']:.1f}% of notes" + (f" ({rn['n']})" if rn.get("n") is not None else ""),
            " · ".join(details) or None))
        if am.get("ceiling"):
            aim_items.append(table(
                ["required px/ms", "mean r at note"],
                [[f"{c['v_lo']:.1f}-{c['v_hi']:.1f}", f"{c['mean_r']:.2f}r"]
                 for c in am["ceiling"]],
                caption="aim ceiling (required speed → distance at the note)"))
    avs = metrics.get("aim_vs_speed") or {}
    if avs.get("slope_r_per_px_ms") is not None:
        bins = " ".join(f"{b['mean_aim_r']:.2f}r" for b in avs.get("bins") or []
                        if b.get("mean_aim_r") is not None)
        aim_items.append(kv(
            "aim error vs cursor speed",
            f"{avs['slope_r_per_px_ms']:+.3f}r per px/ms",
            f"r² {avs['r2']:.2f}" + (f" · slowest→fastest quartile {bins}" if bins else "")))
    out.append(_section("aim", "Aim", *aim_items))

    # -- miss autopsy --------------------------------------------------------
    au = metrics.get("autopsy") or {}
    classes = [c for c in (au.get("shapes") or {}).get("classes", []) if c.get("reported")]
    if (classes or au.get("arrival_margin_r") or (au.get("misses") or {}).get("n")):
        items = []
        if classes:
            items.append(table(
                ["shape (5-note windows)", "off 300", "n", "share", "at the note"],
                [[c["class"], f"{c['non300_rate'] * 100:.1f}%", c["n"],
                  f"{c['share'] * 100:.0f}%",
                  f"{c['mean_d_r']:.2f}r" if c.get("mean_d_r") is not None else "—"]
                 for c in classes],
                caption="shapes (5-note windows)"))
        if (au.get("arrival_margin_r") or {}).get("median") is not None:
            m = au["arrival_margin_r"]
            bits = [f"p90 {m['p90']:.2f}r"] if m.get("p90") is not None else []
            if m.get("max") is not None:
                bits.append(f"max {m['max']:.2f}r")
            if m.get("beyond_rim_pct") is not None:
                bits.append(f"{m['beyond_rim_pct']:.1f}% pressed beyond 0.8r")
            if m.get("n") is not None:
                bits.append(f"n={m['n']}")
            items.append(kv("arrival margin at press", f"median {m['median']:.2f}r",
                            " · ".join(bits) or None))
        if (au.get("press_vs_arrival_ms") or {}).get("median") is not None:
            p = au["press_vs_arrival_ms"]
            bits = []
            if p.get("p10") is not None and p.get("p90") is not None:
                bits.append(f"p10 {p['p10']:+.0f} / p90 {p['p90']:+.0f}")
            if p.get("pressed_before_arrival_pct") is not None:
                bits.append(f"{p['pressed_before_arrival_pct']:.0f}% of presses land "
                            f"before the closest approach")
            if p.get("n") is not None:
                bits.append(f"n={p['n']}")
            items.append(kv("press vs arrival", f"median {p['median']:+.0f} ms",
                            " · ".join(bits) or None))
        if au.get("legs"):
            g = au["legs"]
            hh = g["heading_err_deg"]
            detail = (f"heading error median {hh['median']:.0f}° · p90 {hh['p90']:.0f}° · "
                      f"max {hh['max']:.0f}°")
            eff = g.get("path_efficiency")
            if eff:
                detail += (f" · path efficiency median {eff['median']:.2f} "
                           f"(<0.7 in {eff['below_70pct_pct']:.1f}% of legs)")
            items.append(kv("legs", f"n={g['n']}", detail))
        if au.get("stutter"):
            s = au["stutter"]
            items.append(kv("mid-travel presses", f"{s['n']} of {s['presses']} "
                                                  f"({s['pct']:.1f}%)",
                            f"pressed >{s['min_early_ms']:.0f} ms early while the "
                            f"cursor was still >{s['threshold_r']:.1f}r away"))
        rows = (au.get("misses") or {}).get("rows") or []
        if rows:
            items.append(table(
                ["#", "kind", "at", "note r", "press", "aim r", "gap r", "turn"],
                [[f"#{m['i']}", (m.get("kind") or "").lower(),
                  f"{m['t'] / 1000:.1f}s",
                  f"{m['d_r']:.2f}" if m.get("d_r") is not None else "—",
                  f"{m['press_ms']:+.0f} ms" if m.get("press_ms") is not None else "no press",
                  f"{m['aim_at_press_r']:.2f}" if m.get("aim_at_press_r") is not None else "—",
                  f"{m['gap_r']:.1f}" if m.get("gap_r") is not None else "—",
                  f"{m['turn_deg']:.0f}°" if m.get("turn_deg") is not None else "—"]
                 for m in rows[:8]]))
        out.append(_section("autopsy", "Miss autopsy", *items))

    # -- patterns ------------------------------------------------------------
    pat = metrics.get("patterns") or {}
    if pat:
        items = [table(
            ["pattern", "n", "miss rate", "mean err", "std"],
            [[p, d["n"], f"{d['miss_rate'] * 100:.1f}% ({d['miss']})",
              f"{d['mean_err']:+.1f} ms" if d.get("mean_err") is not None else "—",
              f"{d['std_err']:.1f} ms" if d.get("std_err") is not None else "—"]
             for p, d in sorted(pat.items(), key=lambda kv_: -kv_[1]["n"])])]
        from .metrics.profile import primary_target
        best = primary_target(prof, metrics.get("n_objects", 0)) if prof else None
        if best:
            items.append(note(
                f"Primary target: {best['family']} — {best['non300']} of {best['n']} "
                f"objects off 300 ({best['non300_rate'] * 100:.1f}%, "
                f"{best['share'] * 100:.0f}% of the map).", "target"))
        else:
            items.append(note("No pattern stands out as a weakness — clean run.",
                              "good"))
        out.append(_section("patterns", "Patterns", *items))

    # -- streams -------------------------------------------------------------
    st = metrics.get("streams") or {}
    segs = st.get("segments") or []
    if segs:
        detail = (f"{st.get('notes', sum(s['n'] for s in segs))} notes · "
                  f"{st.get('misses', sum(s['miss'] for s in segs))} miss")
        if st.get("gap_ms_median") is not None:
            material = f"median run {st['gap_ms_median']:.0f} ms"
            if st.get("notes_per_s_p50") is not None:
                material += f" = {st['notes_per_s_p50']:.1f} notes/s"
            if st.get("velocity_r_ms_p50") is not None:
                material += f" at {st['velocity_r_ms_p50']:.3f} r/ms"
            kinds = st.get("kinds") or {}
            if kinds:
                material += " · kinds " + ", ".join(f"{k} {v}" for k, v in kinds.items())
            detail += " · " + material
        st_items = [kv("runs", f"{len(segs)} of sustained notes", detail)]
        st_items.append(table(
            ["when", "n / miss", "alt", "material", "std err"],
            [[f"{s['t_start'] / 1000:.0f}s-{s['t_end'] / 1000:.0f}s",
              f"{s['n']} / {s['miss']}", f"{s['alt_ratio'] * 100:.0f}%",
              (f"{round(s['gap_ms'])} ms, {round(s['notes_per_s'], 1) if s.get('notes_per_s') else '-'} n/s"
               + (", " + "+".join(f"{k[0]}{v}" for k, v in (s.get("kinds") or {}).items())
                  if s.get("kinds") else ""))
              if s.get("gap_ms") else "—",
              f"{s['std_err']:.1f} ms" if s.get("std_err") is not None else "—"]
             for s in sorted(segs, key=lambda s: -(s["std_err"] or 0))[:4]]))
        out.append(_section("streams", "Streams", *st_items))

    # -- breakdown -----------------------------------------------------------
    bd = metrics.get("breakdown") or {}
    if bd:
        trustworthy = (metrics.get("trust") or {}).get("trustworthy")
        items = []
        if trustworthy is False:
            items.append(note("trust=false: these numbers are approximate — critique "
                              "only what is populated.", "bad"))
        bins = bd.get("speed_bins") or []
        if bins:
            items.append(table(
                ["required px/ms", "n", "miss", "rate"],
                [[b.get("label") or f"{b['lo']:.1f}-{b['hi']:.1f}", b["n"], b["miss"],
                  f"{b['rate'] * 100:.1f}%"] for b in bins]))
        if bd.get("cliff") is not None:
            items.append(kv("speed cliff", f"{bd['cliff']:.1f} px/ms",
                            f"knee {(bd.get('knee') or 0):.1f}"))
        rev = bd.get("reversal") or {}
        if rev:
            items.append(table(
                ["reversal × spacing", "n", "miss", "rate"],
                [[k, v["n"], v["miss"], f"{v['rate'] * 100:.1f}%"]
                 for k, v in rev.items()]))
        ramp = bd.get("ramp") or {}
        if ramp.get("n"):
            items.append(kv("worst ramp",
                            f"{ramp['n']} notes, {ramp['miss']} miss",
                            f"t={ramp['t0'] / 1000:.0f}s→{ramp['t1'] / 1000:.0f}s"))
        casc = bd.get("cascades") or []
        if casc:
            items.append(kv("miss cascades", f"{len(casc)}",
                            " · ".join(f"{c['t0'] / 1000:.0f}s ({c['n']})"
                                       for c in casc[:4])))
        out.append(_section("breakdown", "How it breaks down", *items))

    # -- tapping -------------------------------------------------------------
    tap = metrics.get("tapping") or {}
    items = []
    if tap:
        items.append(kv("alternation", f"{tap['alt_ratio'] * 100:.0f}%",
                        f"same-key adjacencies {tap['same_key_pct'] * 100:.1f}% "
                        f"(good > 90%)"))
    keys = metrics.get("key_usage") or {}
    if keys:
        items.append(kv("keys", " / ".join(f"{k} {v}" for k, v in keys.items()),
                        f"whiffed presses {metrics.get('whiffed_presses', 0)}"
                        f" (rate {metrics.get('whiffed_presses', 0) / max(1, tap.get('n') or 1):.1%})"))
    w = metrics.get("whiffs") or {}
    if w.get("n"):
        items.append(kv(
            "whiff causes",
            f"{w['mash']} mash · {w['off_target']} off-target · "
            f"{w['slider_head']} beside a slider head",
            f"mean off-target {(w.get('off_target_mean_r') or 0):.2f}r · "
            f"{w['lost']} duplicate · {w['after_end']} after the map — only the "
            f"off-target share is 'rushing'"))
    if items:
        out.append(_section("tapping", "Tapping", *items))

    return out


# ---------------------------------------------------------------- text form --

def to_text(metrics: dict, sections_: list[dict]) -> str:
    """The terminal rendering: same content, one line per item."""
    lines = [f"# Report: {metrics['map']}", ""]
    for section in sections_:
        lines.append(f"## {section['title']}")
        for item in section["items"]:
            if item["kind"] == "kv":
                text = f"- {item['label']}: {item['value']}"
                if item.get("note"):
                    text += f" — {item['note']}"
                lines.append(text)
            elif item["kind"] == "note":
                lines.append(f"- {item['text']}")
            elif item["kind"] == "table":
                if item.get("caption"):
                    lines.append(f"- {item['caption']}")
                header = " | ".join(str(c) for c in item["columns"])
                lines.append(f"- {header}")
                for row in item["rows"]:
                    lines.append("  " + " | ".join(str(c) for c in row))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
