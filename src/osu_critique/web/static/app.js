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
    // x labels
    ctx.textAlign = "center";
    [0, 0.5, 1].forEach((f) => {
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
    button.disabled = true;
    button.textContent = "loading…";
    try {
      const res = await fetch("/api/objects/" + encodeURIComponent(runId));
      if (!res.ok) throw new Error(res.status);
      const doc = await res.json();
      buildTable(host, doc.objects || []);
      const details = host.closest("details");
      if (details) details.open = true;
      button.remove();
    } catch (err) {
      button.disabled = false;
      button.textContent = "could not load the objects (" + err.message + ")";
    }
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

  /* ---------------------------------------------------------- critiques -- */

  async function streamCritique(form, body, button) {
    const empty = document.getElementById("critique-empty");
    if (empty) empty.hidden = true;
    body.hidden = false;
    if (!body.dataset.kept) body.textContent = "";
    body.dataset.kept = "1";
    button.disabled = true;
    const label = button.textContent;
    button.textContent = "thinking…";
    try {
      const res = await fetch(form.action, {
        method: "POST",
        headers: { Accept: "text/event-stream" },
      });
      if (!res.ok || !res.body) {
        const detail = await res.text();
        if (empty) { empty.hidden = false; empty.textContent = "the critique failed:"; }
        body.textContent = detail || String(res.status);
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let cut;
        while ((cut = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, cut);
          buf = buf.slice(cut + 2);
          if (!frame.startsWith("data: ")) continue;
          const payload = frame.slice(6).trim();
          if (payload === "[DONE]") continue;
          let obj;
          try { obj = JSON.parse(payload); } catch (e) { continue; }
          if (obj.delta) body.textContent += obj.delta;
          else if (obj.error) body.textContent += "\n\n[error] " + obj.error;
          else if (obj.done) button.textContent = "regenerate";
        }
      }
    } catch (err) {
      body.textContent += "\n\n[network error] " + err.message;
    } finally {
      button.disabled = false;
      if (button.textContent === "thinking…") button.textContent = label;
    }
  }

  /* --------------------------------------------------------------- init -- */

  document.addEventListener("DOMContentLoaded", () => {
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
      const critiqueForm = document.getElementById("critique-form");
      if (critiqueForm) {
        critiqueForm.addEventListener("submit", (ev) => {
          ev.preventDefault();
          streamCritique(critiqueForm,
                         document.getElementById("critique-body"),
                         critiqueForm.querySelector("button[type=submit]"));
        });
      }
      const button = document.getElementById("all-objects");
      if (button) {
        button.addEventListener("click", () =>
          loadAllObjects(runId, document.getElementById("object-table"), button));
      }
    }
  });
})();
