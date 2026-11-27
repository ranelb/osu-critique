#!/usr/bin/env python3
"""Build a blind labelling page: one self-contained HTML file, no server.

    python scripts/label_sheet.py OUT.html MAP.osu [MAP.osu ...] [--per-map 14] [--seed 1]

Each map contributes windows of 6-14 consecutive objects, drawn three ways so the
page cannot be gamed: windows the classifier labelled (clipped to 14 objects),
windows it left unlabelled, and windows picked at random. Which is which is stored
in the data (``src``) for scoring but never shown. The page draws circles at their
true radius with numbered objects, travel arrows and slider curves; the owner
clicks a shape (or "none"), optionally marks where the pattern starts and ends,
and exports JSON. Progress is kept in localStorage, so closing the tab loses
nothing.

The export is ``[{map, i0, i1, from, to, t0, t1, shape, note, src}]`` -- global
object indices, so ``scripts/labels_to_eval.py`` can turn it into the
``{shape, dir, t0, t1}`` blocks ``eval_patterns.py`` scores.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from osu_critique.io.beatmap import build_objects, circle_radius, load_beatmap  # noqa: E402
from osu_critique.metrics import geometry  # noqa: E402

MIN_W, MAX_W, CTX = 6, 14, 2


def slider_paths(bm):
    objs = sorted(bm.hit_objects(), key=lambda o: o.time.total_seconds())
    out = []
    for o in objs:
        pts = None
        if type(o).__name__ == "Slider":
            try:
                pts = [[round(float(o.curve(k / 24).x), 1), round(float(o.curve(k / 24).y), 1)]
                       for k in range(25)]
            except Exception:
                pts = None
        out.append(pts)
    return out


def pick_windows(objs, segs, per_map, rng):
    n = len(objs)
    ok = [o["kind"] != "Spinner" for o in objs]
    covered = set()
    for s in segs:
        covered.update(range(s["start"], s["end"] + 1))
    used = set()

    def free(a, b):
        return a >= 0 and b < n and all(ok[a:b + 1]) and not any(k in used for k in range(a, b + 1))

    out = []

    def take(a, b, src):
        if free(a, b):
            used.update(range(a, b + 1))
            out.append({"i0": a, "i1": b, "src": src})

    third = max(1, per_map // 3)
    segs = sorted(segs, key=lambda s: s["start"])
    if segs:
        step = max(1, len(segs) / third)
        for k in range(min(third, len(segs))):
            s = segs[int(k * step)]
            a, b = s["start"], min(s["end"], s["start"] + MAX_W - 1)
            if b - a + 1 < MIN_W:
                b = min(n - 1, a + MIN_W - 1)
            take(a, b, "classified")
    tries = 0
    while sum(w["src"] == "unlabelled" for w in out) < third and tries < 4000:
        tries += 1
        L = rng.randint(MIN_W, 12)
        a = rng.randrange(0, max(1, n - L))
        if not any(k in covered for k in range(a, a + L)):
            take(a, a + L - 1, "unlabelled")
    tries = 0
    while len(out) < per_map and tries < 4000:
        tries += 1
        L = rng.randint(MIN_W, 12)
        a = rng.randrange(0, max(1, n - L))
        take(a, a + L - 1, "random")
    return out


def build(maps, per_map, seed):
    rng = random.Random(seed)
    wins = []
    for path in maps:
        bm = load_beatmap(path)
        objs = build_objects(bm, 1.0)
        r = circle_radius(bm.cs())
        segs = geometry.classify(objs, r, None)
        paths = slider_paths(bm)
        name = Path(path).stem
        for w in pick_windows(objs, segs, per_map, rng):
            lo, hi = max(0, w["i0"] - CTX), min(len(objs) - 1, w["i1"] + CTX)
            rows = []
            for i in range(lo, hi + 1):
                o = objs[i]
                rows.append({"i": i, "x": round(o["x"], 1), "y": round(o["y"], 1),
                             "ex": round(o.get("end_x", o["x"]), 1),
                             "ey": round(o.get("end_y", o["y"]), 1),
                             "t": round(o["t"]), "k": o["kind"][0], "p": paths[i]})
            wins.append({"map": name, "i0": w["i0"], "i1": w["i1"], "r": round(r, 2),
                         "src": w["src"], "rows": rows})
    rng.shuffle(wins)
    for k, w in enumerate(wins):
        w["id"] = k
    return wins


PAGE = r"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pattern labelling</title>
<style>
body{font:14px system-ui,sans-serif;margin:0;background:#fafafa;color:#222}
#wrap{display:flex;gap:16px;padding:12px;flex-wrap:wrap}
canvas{background:#fff;border:1px solid #ccc;cursor:crosshair}
#side{flex:1;min-width:300px;max-width:520px}
button{font:inherit;padding:6px 10px;margin:2px;border:1px solid #888;border-radius:5px;background:#fff;cursor:pointer}
button.on{background:#2a6df4;color:#fff;border-color:#2a6df4}
button.none{border-style:dashed}
small{color:#666}kbd{background:#eee;border:1px solid #bbb;border-radius:3px;padding:0 4px;font-size:11px}
#bar{height:6px;background:#ddd}#bar i{display:block;height:6px;background:#2a6df4}
input[type=text]{width:95%;padding:5px}input[type=number]{width:56px}
</style>
<div id="bar"><i></i></div>
<div id="wrap">
 <canvas id="c" width="640" height="640"></canvas>
 <div id="side">
  <h3 id="h" style="margin:4px 0"></h3>
  <div id="meta"><small></small></div>
  <p><small>Pick what this window is. Numbered objects are the window; grey ones are context.
  Click an object to mark where the pattern <b>starts</b>, click another for where it <b>ends</b>
  (a third click resets). Default is the whole window.</small></p>
  <div id="opts"></div>
  <p>pattern from <input type="number" id="from" min="1"> to <input type="number" id="to" min="1">
     <button id="reset">whole window</button></p>
  <p><input type="text" id="note" placeholder="note (what would you call it, what is off)"></p>
  <p><button id="prev">&larr; back</button> <button id="next">next &rarr; (Enter)</button>
     <button id="skip">skip</button></p>
  <p><button id="export">Download labels.json</button> <button id="copy">Copy JSON</button>
     <button id="clear">clear all</button><br><small id="stat"></small></p>
 </div>
</div>
<script>
const W=__DATA__;
const SHAPES=["triangle","square","rectangle","pentagon","hexagon","star","back_and_forth","zigzag","circle","arc","line","stack",
 "wide_jumps","curvy_stream","drifting_polygon","other","none","unsure"];
const KEYS="1234567890qwertyuiop";
const KEY="pattern-labels-v1";
let S=JSON.parse(localStorage.getItem(KEY)||"{}");
let cur=0;
const cv=document.getElementById("c"),g=cv.getContext("2d");
let hit=[];
const save=()=>localStorage.setItem(KEY,JSON.stringify(S));
function ent(){return S[W[cur].id]||(S[W[cur].id]={shape:null,from:null,to:null,note:""})}
function inside(w){return w.rows.filter(o=>o.i>=w.i0&&o.i<=w.i1)}
function draw(){
 const w=W[cur],e=ent(),n=inside(w).length;
 const from=e.from||1,to=e.to||n;
 let xs=[],ys=[];
 w.rows.forEach(o=>{xs.push(o.x,o.ex);ys.push(o.y,o.ey);(o.p||[]).forEach(p=>{xs.push(p[0]);ys.push(p[1])})});
 const pad=w.r*1.6,x0=Math.min(...xs)-pad,x1=Math.max(...xs)+pad,y0=Math.min(...ys)-pad,y1=Math.max(...ys)+pad;
 const sc=Math.min(cv.width/(x1-x0),cv.height/(y1-y0)),ox=(cv.width-sc*(x1-x0))/2-x0*sc,oy=(cv.height-sc*(y1-y0))/2-y0*sc;
 const X=x=>x*sc+ox,Y=y=>y*sc+oy;
 g.clearRect(0,0,cv.width,cv.height);hit=[];
 const pos=o=>o.i-w.i0+1;
 w.rows.forEach(o=>{
  const ins=o.i>=w.i0&&o.i<=w.i1,p=pos(o),sel=ins&&p>=from&&p<=to;
  const col=!ins?"#aaa":sel?"#2a6df4":"#9ab";
  if(o.p){g.strokeStyle=col;g.globalAlpha=.35;g.lineWidth=w.r*sc*1.4;g.lineCap="round";g.beginPath();
   o.p.forEach((q,k)=>k?g.lineTo(X(q[0]),Y(q[1])):g.moveTo(X(q[0]),Y(q[1])));g.stroke();g.globalAlpha=1}
  g.beginPath();g.arc(X(o.x),Y(o.y),w.r*sc,0,7);g.fillStyle=sel?"rgba(42,109,244,.13)":"rgba(0,0,0,.03)";g.fill();
  g.lineWidth=1.5;g.strokeStyle=col;g.stroke();
  if(ins)hit.push({p,x:X(o.x),y:Y(o.y)});
 });
 for(let k=0;k<w.rows.length-1;k++){
  const a=w.rows[k],b=w.rows[k+1],ax=X(a.ex),ay=Y(a.ey),bx=X(b.x),by=Y(b.y),d=Math.hypot(bx-ax,by-ay);
  if(d<4)continue;const ins=a.i>=w.i0&&b.i<=w.i1,sel=ins&&pos(a)>=from&&pos(b)<=to;
  const sh=w.r*sc*.62,ux=(bx-ax)/d,uy=(by-ay)/d,sx=ax+ux*sh,sy=ay+uy*sh,tx=bx-ux*sh,ty=by-uy*sh;
  if(Math.hypot(tx-sx,ty-sy)<6)continue;
  g.strokeStyle=!ins?"#bbb":sel?"#2a6df4":"#9ab";g.lineWidth=1.4;g.beginPath();g.moveTo(sx,sy);g.lineTo(tx,ty);
  g.lineTo(tx-ux*9+uy*5,ty-uy*9-ux*5);g.moveTo(tx,ty);g.lineTo(tx-ux*9-uy*5,ty-uy*9+ux*5);g.stroke();
 }
 const lab={};
 w.rows.forEach(o=>{if(o.i<w.i0||o.i>w.i1)return;const k=Math.round(X(o.x)/10)+","+Math.round(Y(o.y)/10);(lab[k]=lab[k]||{x:X(o.x),y:Y(o.y),n:[]}).n.push(pos(o))});
 g.font="bold 15px system-ui";g.textAlign="center";g.textBaseline="middle";g.fillStyle="#123";
 Object.values(lab).forEach(l=>g.fillText(l.n.join(","),l.x,l.y));
}
function ui(){
 const w=W[cur],e=ent(),n=inside(w).length;
 document.getElementById("h").textContent=`window ${cur+1} / ${W.length}`;
 const gaps=[];for(let k=1;k<w.rows.length;k++)gaps.push(w.rows[k].t-w.rows[k-1].t);
 const med=gaps.sort((a,b)=>a-b)[Math.floor(gaps.length/2)];
 const t=inside(w)[0].t/1000;
 document.getElementById("meta").innerHTML=`<small>${w.map.replace(/^.*\) /,"").slice(-34)} &middot; ${Math.floor(t/60)}:${(t%60).toFixed(1).padStart(4,"0")} &middot; ${n} objects &middot; median gap ${med} ms &middot; radius ${w.r}</small>`;
 const o=document.getElementById("opts");o.innerHTML="";
 SHAPES.forEach((s,k)=>{const b=document.createElement("button");b.textContent=s.replace("_"," ")+(KEYS[k]?"  ["+KEYS[k]+"]":"");
  if(s==="none"||s==="unsure")b.className="none";if(e.shape===s)b.classList.add("on");
  b.onclick=()=>{e.shape=s;save();ui();};o.appendChild(b)});
 const f=document.getElementById("from"),t2=document.getElementById("to");
 f.max=t2.max=n;f.value=e.from||"";t2.value=e.to||"";f.placeholder="1";t2.placeholder=n;
 document.getElementById("note").value=e.note||"";
 const done=Object.values(S).filter(x=>x.shape).length;
 document.getElementById("stat").textContent=`${done} / ${W.length} labelled`;
 document.querySelector("#bar i").style.width=(100*done/W.length)+"%";
 draw();
}
cv.onclick=ev=>{const r=cv.getBoundingClientRect(),x=(ev.clientX-r.left)*cv.width/r.width,y=(ev.clientY-r.top)*cv.height/r.height;
 let best=null,bd=1e9;hit.forEach(h=>{const d=Math.hypot(h.x-x,h.y-y);if(d<bd){bd=d;best=h}});
 if(!best||bd>60)return;const e=ent();
 if(e.from&&!e.to&&best.p>=e.from){e.to=best.p}else{e.from=best.p;e.to=null}
 save();ui();};
const go=d=>{cur=Math.max(0,Math.min(W.length-1,cur+d));ui()};
document.getElementById("next").onclick=()=>go(1);
document.getElementById("prev").onclick=()=>go(-1);
document.getElementById("skip").onclick=()=>go(1);
document.getElementById("reset").onclick=()=>{const e=ent();e.from=e.to=null;save();ui()};
document.getElementById("from").onchange=ev=>{ent().from=+ev.target.value||null;save();ui()};
document.getElementById("to").onchange=ev=>{ent().to=+ev.target.value||null;save();ui()};
document.getElementById("note").oninput=ev=>{ent().note=ev.target.value;save()};
addEventListener("keydown",ev=>{if(ev.target.tagName==="INPUT")return;
 if(ev.key==="Enter"||ev.key==="ArrowRight")go(1);else if(ev.key==="ArrowLeft")go(-1);
 else{const k=KEYS.indexOf(ev.key.toLowerCase());if(k>=0&&k<SHAPES.length){ent().shape=SHAPES[k];save();ui()}}});
function out(){return W.filter(w=>S[w.id]&&S[w.id].shape).map(w=>{const e=S[w.id],ins=inside(w),a=ins[(e.from||1)-1],b=ins[(e.to||ins.length)-1];
 return{map:w.map,i0:w.i0+(e.from||1)-1,i1:w.i0+(e.to||ins.length)-1,window:[w.i0,w.i1],t0:a.t,t1:b.t,shape:e.shape,note:e.note,src:w.src}})}
document.getElementById("export").onclick=()=>{const a=document.createElement("a");
 a.href=URL.createObjectURL(new Blob([JSON.stringify(out(),null,1)],{type:"application/json"}));a.download="labels.json";a.click()};
document.getElementById("copy").onclick=()=>navigator.clipboard.writeText(JSON.stringify(out(),null,1));
document.getElementById("clear").onclick=()=>{if(confirm("Delete all labels?")){S={};save();ui()}};
ui();
</script>
"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("maps", nargs="+")
    ap.add_argument("--per-map", type=int, default=14)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    wins = build(a.maps, a.per_map, a.seed)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(PAGE.replace("__DATA__", json.dumps(wins, separators=(",", ":"))),
                           encoding="utf-8")
    by = {}
    for w in wins:
        by[w["src"]] = by.get(w["src"], 0) + 1
    print(f"{a.out}: {len(wins)} windows {by}")


if __name__ == "__main__":
    main()
