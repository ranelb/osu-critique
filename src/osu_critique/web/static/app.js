/* osu-critique web — the only JavaScript: two charts and one lazy table.
   Everything else is server-rendered. No build step, no framework. */
(function () {
  "use strict";

  const COLOR = {
    "300": "#ff66aa", "100": "#ffd166", "50": "#c9a227", "miss": "#ff5f6d",
  };

  function mmss(ms) {
    if (ms == null) return "—";
    const total = Math.max(0, ms) / 1000;
    const m = Math.floor(total / 60);
    const s = total - m * 60;
    return m + ":" + (s < 10 ? "0" : "") + s.toFixed(1);
  }

  function fmt(value, digits) {
    return value == null ? "—" : Number(value).toFixed(digits);
  }

  /* ---------------------------------------------------------- hit error -- */

  function fitCanvas(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth || canvas.parentElement.clientWidth;
    const height = Number(canvas.getAttribute("height")) || 220;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.height = height + "px";
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx: ctx, w: width, h: height };
  }

  function drawHitError(canvas, rows) {
    const { ctx, w, h } = fitCanvas(canvas);
    const pad = { l: 46, r: 12, t: 12, b: 26 };
    const w300 = Number(canvas.dataset.w300) || 25;
    const w100 = Number(canvas.dataset.w100) || 66;
    const w50 = Number(canvas.dataset.w50) || 108;
    const points = rows.filter((r) => r.error_ms != null);
    if (!points.length) return;

    const tMin = Math.min(...points.map((r) => r.t));
    const tMax = Math.max(...points.map((r) => r.t));
    const span = Math.max(1, tMax - tMin);
    const limit = Math.max(w50 * 1.25, ...points.map((r) => Math.abs(r.error_ms)));

    const x = (t) => pad.l + ((t - tMin) / span) * (w - pad.l - pad.r);
    const y = (e) => pad.t + ((limit - e) / (2 * limit)) * (h - pad.t - pad.b);

    ctx.clearRect(0, 0, w, h);
    ctx.font = "11px Poppins, system-ui, sans-serif";
    ctx.textBaseline = "middle";

    // window bands (300 tightest, 50 widest)
    [[w50, "#ff5f6d18"], [w100, "#ffd16618"], [w300, "#4ade8018"]].forEach(([band, fill]) => {
      ctx.fillStyle = fill;
      ctx.fillRect(pad.l, y(band), w - pad.l - pad.r, y(-band) - y(band));
    });
    ctx.strokeStyle = "#3a4560";
    ctx.beginPath();
    ctx.moveTo(pad.l, y(0));
    ctx.lineTo(w - pad.r, y(0));
    ctx.stroke();

    // y labels
    ctx.fillStyle = "#6d778c";
    ctx.textAlign = "right";
    [limit, limit / 2, 0, -limit / 2, -limit].forEach((v) => {
      ctx.fillText(v.toFixed(0), pad.l - 6, y(v));
    });
    // x labels: pin the ends to their edges so the first and last are not
    // half-clipped by the canvas
    [0, 0.5, 1].forEach((f) => {
      ctx.textAlign = f === 0 ? "left" : f === 1 ? "right" : "center";
      ctx.fillText(mmss(tMin + span * f), pad.l + (w - pad.l - pad.r) * f, h - 12);
    });

    points.forEach((r) => {
      ctx.fillStyle = COLOR[r.result] || "#8b95ab";
      ctx.globalAlpha = r.result === "300" ? 0.55 : 0.95;
      ctx.beginPath();
      ctx.arc(x(r.t), y(r.error_ms), r.result === "300" ? 1.8 : 2.8, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.globalAlpha = 1;
  }

  /* ------------------------------------------------------ object table --- */

  const COLUMNS = [
    ["i", "#", 0], ["t", "time", 0], ["kind", "kind", 0],
    ["result", "result", 0], ["error_ms", "error", 1],
    ["aim_r", "aim r", 2], ["spacing_r", "spacing r", 2],
    ["snap", "snap", 0], ["bpm_eff", "bpm", 0],
    ["angle_deg", "angle", 0], ["pattern", "pattern", 0],
    ["key", "key", 0], ["cursor_speed", "speed", 2],
  ];

  function buildTable(host, rows) {
    const table = document.createElement("table");
    table.className = "data tight";
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    COLUMNS.forEach(([, label, numeric]) => {
      const th = document.createElement("th");
      th.textContent = label;
      if (numeric) th.className = "num";
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    const frag = document.createDocumentFragment();
    rows.forEach((r) => {
      const tr = document.createElement("tr");
      tr.className = "res-" + r.result;
      COLUMNS.forEach(([key, , digits]) => {
        const td = document.createElement("td");
        if (digits) td.className = "num";
        let value = r[key];
        if (key === "t") value = mmss(value);
        else if (typeof value === "number") value = fmt(value, digits);
        td.textContent = value == null ? "—" : String(value);
        tr.appendChild(td);
      });
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
    table.appendChild(tbody);
    host.replaceChildren(table);
  }

  async function loadAllObjects(runId, host, button) {
    if (button) { button.disabled = true; button.textContent = "loading…"; }
    host.replaceChildren(Object.assign(document.createElement("p"),
      { className: "muted", textContent: "loading the object table…" }));
    try {
      const res = await fetch("/api/objects/" + encodeURIComponent(runId));
      if (!res.ok) throw new Error(res.status);
      const doc = await res.json();
      buildTable(host, doc.objects || []);
      if (button) button.remove();
    } catch (err) {
      const msg = "could not load the objects (" + err.message + ")";
      if (button) { button.disabled = false; button.textContent = msg; }
      host.replaceChildren(Object.assign(document.createElement("p"),
        { className: "muted", textContent: msg }));
    }
  }

  /* ---------------------------------------------------------------- rail -- */

  /* Highlight the rail entry for the last block that crossed the reading line.
     Deliberately not an IntersectionObserver: a fold that opens or closes moves
     every block below it without scrolling, and reconstructing "what is on
     screen" from enter/leave events gets subtle. Seven bounding rects per frame
     is cheap and cannot desync. */
  function initRail() {
    const rail = document.querySelector(".rail");
    if (!rail) return;
    const links = Array.from(rail.querySelectorAll("a[data-spy]"));
    const targets = links.map((a) => document.getElementById(a.dataset.spy))
      .filter(Boolean);
    if (!targets.length) return;
    let current = null;
    const pick = () => {
      const line = window.innerHeight * 0.28;
      let id = targets[0].id;
      targets.forEach((t) => {
        if (t.getBoundingClientRect().top <= line) id = t.id;
      });
      // a short page cannot scroll its last blocks past the line: the bottom wins
      if (window.innerHeight + window.scrollY
          >= document.documentElement.scrollHeight - 4) {
        id = targets[targets.length - 1].id;
      }
      if (id === current) return;
      current = id;
      links.forEach((a) => a.classList.toggle("active", a.dataset.spy === id));
    };
    let queued = false;
    const schedule = () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => { queued = false; pick(); });
    };
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    document.addEventListener("toggle", schedule, true);
    pick();
  }

  /* -------------------------------------------------------- annotations -- */

  function mapClock(ms, scale) {
    const total = Math.max(0, ms) / 1000 / (scale || 1);
    const m = Math.floor(total / 60);
    const sec = total - m * 60;
    return m + ":" + (sec < 10 ? "0" : "") + sec.toFixed(3);
  }

  function initAnnotations(runEl) {
    const scale = Number(runEl.dataset.rowsScale) || 1;
    const slider = document.getElementById("playhead");
    const label = document.getElementById("playhead-label");
    const hidden = document.getElementById("t-map");
    const stamp = document.getElementById("stamp");
    const clear = document.getElementById("clear-stamp");
    if (!slider || !label || !hidden) return;

    const show = () => {
      label.textContent = mapClock(Number(slider.value), scale);
    };
    slider.addEventListener("input", show);

    if (stamp) {
      stamp.addEventListener("click", () => {
        hidden.value = (Number(slider.value) / 1000 / scale).toFixed(3);
        label.classList.add("stamped");
        show();
      });
    }
    if (clear) {
      clear.addEventListener("click", () => {
        hidden.value = "";
        label.classList.remove("stamped");
      });
    }

    // clicking an object row parks the playhead there (row clock -> slider)
    document.querySelectorAll(".obj-row[data-t]").forEach((row) => {
      row.addEventListener("click", () => {
        slider.value = row.dataset.t;
        show();
      });
    });
    show();
  }

  /* ------------------------------------------------------------ boards -- */

  const BOARD_W = 512;
  const BOARD_H = 384;

  function drawBoard(canvas, board, radius) {
    const ctx = canvas.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#0c0f16";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const chain = board.chain || [];
    if (!chain.length) return;
    const r = Math.max(8, radius || 40);

    // zoom to the five-note window: at full playfield scale the chain is a few
    // tiny dots in a big rectangle, which is not a picture of anything
    const xs = chain.map((c) => c.x);
    const ys = chain.map((c) => c.y);
    const pad = r * 1.15;
    let minX = Math.min(...xs) - r - pad, maxX = Math.max(...xs) + r + pad;
    let minY = Math.min(...ys) - r - pad, maxY = Math.max(...ys) + r + pad;
    const minSpan = r * 9;
    for (const axis of ["x", "y"]) {
      const lo = axis === "x" ? minX : minY;
      const hi = axis === "x" ? maxX : maxY;
      if (hi - lo < minSpan) {
        const mid = (lo + hi) / 2;
        const half = minSpan / 2;
        if (axis === "x") { minX = mid - half; maxX = mid + half; }
        else { minY = mid - half; maxY = mid + half; }
      }
    }
    const sx = canvas.width / (maxX - minX);
    const sy = canvas.height / (maxY - minY);
    const scale = Math.min(sx, sy);
    const offX = (canvas.width - (maxX - minX) * scale) / 2;
    const offY = (canvas.height - (maxY - minY) * scale) / 2;
    ctx.setTransform(scale, 0, 0, scale, offX - minX * scale, offY - minY * scale);

    // the path the hand had to travel
    ctx.strokeStyle = "#ffffff2b";
    ctx.lineWidth = 2 / scale;
    ctx.setLineDash([9 / scale, 7 / scale]);
    ctx.beginPath();
    chain.forEach((c, i) => (i ? ctx.lineTo(c.x, c.y) : ctx.moveTo(c.x, c.y)));
    ctx.stroke();
    ctx.setLineDash([]);

    chain.forEach((c) => {
      const miss = c.i === board.i;
      ctx.beginPath();
      ctx.arc(c.x, c.y, r, 0, Math.PI * 2);
      ctx.fillStyle = miss ? "#ff5f6d3d" : "#ff66aa10";
      ctx.fill();
      ctx.lineWidth = miss ? 3.5 : 2;
      ctx.strokeStyle = miss ? "#ff5f6d" : "#ff66aa77";
      ctx.stroke();
      if (c.kind === "Slider") {
        ctx.beginPath();
        ctx.arc(c.x, c.y, r + 6, 0, Math.PI * 2);
        ctx.strokeStyle = "#ffffff14";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
      if (miss) {
        // a double ring so the miss reads at a glance even in a small card
        ctx.beginPath();
        ctx.arc(c.x, c.y, r * 0.42, 0, Math.PI * 2);
        ctx.strokeStyle = "#ff5f6d";
        ctx.lineWidth = 2.5;
        ctx.stroke();
      }
    });
  }

  function drawHeat(canvas, heat) {
    const ctx = canvas.getContext("2d");
    const s = canvas.width / BOARD_W;
    ctx.setTransform(s, 0, 0, s, 0, 0);
    ctx.clearRect(0, 0, BOARD_W, BOARD_H);
    ctx.fillStyle = "#0c0f16";
    ctx.fillRect(0, 0, BOARD_W, BOARD_H);
    ctx.strokeStyle = "#242c3d";
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, BOARD_W - 2, BOARD_H - 2);
    heat.forEach((p) => {
      const near = p.closest_r != null ? Math.max(0, 1 - p.closest_r / 3) : 0.3;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 7 + near * 9, 0, Math.PI * 2);
      ctx.fillStyle = "rgb(255,95,109," + (0.25 + near * 0.55).toFixed(2) + ")";
      ctx.fill();
    });
  }

  function initBoards() {
    const data = document.getElementById("boards-data");
    if (!data) return;
    let boards;
    try { boards = JSON.parse(data.textContent); } catch (e) { return; }

    const host = document.getElementById("miss-boards");
    if (host) {
      (boards.misses || []).forEach((board, idx) => {
        const fig = document.createElement("figure");
        fig.className = "board-fig";
        const canvas = document.createElement("canvas");
        canvas.className = "board";
        canvas.width = BOARD_W;
        canvas.height = BOARD_H;
        fig.appendChild(canvas);
        const cap = document.createElement("figcaption");
        const when = document.createElement("span");
        when.className = "chip";
        when.textContent = mmss(board.t);
        cap.appendChild(when);
        const detail = document.createElement("span");
        detail.className = "muted";
        detail.textContent =
          " closest " + fmt(board.closest_r, 2) + "r" +
          (board.turn_deg != null ? " · turn " + fmt(board.turn_deg, 0) + "°" : "") +
          (board.press_ms != null ? " · press " + fmt(board.press_ms, 0) + " ms" : "");
        cap.appendChild(detail);
        fig.appendChild(cap);
        host.appendChild(fig);
        drawBoard(canvas, board, boards.radius);
      });
    }

    const heatCanvas = document.getElementById("miss-heat");
    if (heatCanvas && boards.heat && boards.heat.length) {
      drawHeat(heatCanvas, boards.heat);
    }
  }

  /* ---------------------------------------------------------------- copy -- */

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      /* plain-http LAN pages have no clipboard API — fall back to the old way */
    }
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.cssText = "position:fixed;top:-1000px;opacity:0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
    ta.remove();
    return ok;
  }

  function initCopy() {
    const button = document.getElementById("copy-report");
    const holder = document.getElementById("report-text");
    if (!button || !holder) return;
    let text = "";
    try {
      text = JSON.parse(holder.textContent || '""');
    } catch (err) {
      text = holder.textContent || "";
    }
    const label = button.textContent;

    const showText = () => {
      const fold = button.closest("details");
      if (!fold) return;
      let pre = fold.querySelector("#report-copy");
      if (!pre) {
        pre = document.createElement("pre");
        pre.className = "report";
        pre.id = "report-copy";
        pre.textContent = text;
        fold.appendChild(pre);
      }
      fold.open = true;
      pre.scrollIntoView({ block: "nearest" });
    };

    button.addEventListener("click", async (ev) => {
      ev.preventDefault();      // a button inside <summary> would toggle the fold
      ev.stopPropagation();
      if (!text) { showText(); return; }
      const ok = await copyText(text);
      if (ok) {
        button.textContent = "copied";
        setTimeout(() => { button.textContent = label; }, 1600);
      } else {
        /* no clipboard at all: put the text on screen instead of failing quietly */
        button.textContent = "select + ctrl+c";
        setTimeout(() => { button.textContent = label; }, 4000);
        showText();
      }
    });
  }

  /* ------------------------------------------------------- scope critique -- */

  function initScope() {
    const form = document.getElementById("scope-form");
    const body = document.getElementById("scope-body");
    const summary = document.getElementById("copy-summary");
    const text = (document.getElementById("scope-text") || {}).textContent || "";
    if (summary) {
      summary.addEventListener("click", async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const label = summary.textContent;
        const ok = await copyText(text);
        summary.textContent = ok ? "copied" : "select + ctrl+c";
        setTimeout(() => { summary.textContent = label; }, 1600);
      });
    }
    if (!form || !body) return;
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const button = form.querySelector("button[type=submit]");
      const label = button.textContent;
      button.disabled = true;
      button.textContent = "thinking…";
      body.hidden = false;
      body.textContent = "";
      try {
        const res = await fetch(form.action, {
          method: "POST",
          headers: { "Accept": "text/event-stream" },
          body: new URLSearchParams(new FormData(form)),
        });
        if (!res.ok || !res.body) {
          const detail = await res.text();
          body.textContent = "[" + res.status + "] " + detail.slice(0, 400);
          button.disabled = false;
          button.textContent = label;
          return;
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let url = null;
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split("\n\n");
          buffer = frames.pop() || "";
          for (const frame of frames) {
            if (!frame.startsWith("data: ")) continue;
            const payload = frame.slice(6).trim();
            if (payload === "[DONE]") continue;
            let obj;
            try { obj = JSON.parse(payload); } catch (err) { continue; }
            if (obj.delta) body.textContent += obj.delta;
            else if (obj.error) body.textContent += "\n\n[error] " + obj.error;
            else if (obj.done) { url = obj.url; button.textContent = "open"; }
          }
        }
        if (url) window.location.assign(url);
      } catch (err) {
        body.textContent += "\n\n[network error] " + err.message;
      } finally {
        button.disabled = false;
        if (button.textContent === "thinking…") button.textContent = label;
      }
    });
  }

  /* --------------------------------------------------------------- init -- */

  document.addEventListener("DOMContentLoaded", () => {
    initRail();
    initScope();
    const run = document.querySelector("[data-run-id]");
    if (run) {
      const canvas = document.getElementById("hiterror");
      const runId = run.dataset.runId;
      if (canvas) {
        fetch("/api/objects/" + encodeURIComponent(runId))
          .then((r) => (r.ok ? r.json() : null))
          .then((doc) => { if (doc) drawHitError(canvas, doc.objects || []); })
          .catch(() => {});
        let timer = null;
        window.addEventListener("resize", () => {
          clearTimeout(timer);
          timer = setTimeout(() => {
            fetch("/api/objects/" + encodeURIComponent(runId))
              .then((r) => (r.ok ? r.json() : null))
              .then((doc) => { if (doc) drawHitError(canvas, doc.objects || []); })
              .catch(() => {});
          }, 200);
        });
      }
      initAnnotations(run);
      initBoards();
      const digestForm = document.getElementById("digest-form");
      if (digestForm) {
        digestForm.addEventListener("submit", () => {
          const btn = document.getElementById("digest-run");
          if (btn) {
            btn.disabled = true;
            btn.textContent = "digesting… (up to a minute)";
          }
        });
      }
      const critiqueForm = document.getElementById("critique-form");
      if (critiqueForm) {
        critiqueForm.addEventListener("submit", (ev) => {
          ev.preventDefault();
          streamCritique(critiqueForm,
                         document.getElementById("critique-body"),
                         critiqueForm.querySelector("button[type=submit]"));
        });
      }
      initCopy();
      const allDetails = document.getElementById("all-objects-details");
      if (allDetails) {
        allDetails.addEventListener("toggle", () => {
          const host = document.getElementById("object-table");
          if (!allDetails.open || !host || host.dataset.loaded) return;
          host.dataset.loaded = "1";
          loadAllObjects(runId, host, null);
        });
      }
    }
  });
})();
