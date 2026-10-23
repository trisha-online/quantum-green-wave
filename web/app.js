(function(){
const D = window.QGW, M = D.meta, NS = "http://www.w3.org/2000/svg";
const $ = id => document.getElementById(id);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const L = "ABCD", name = n => L[n % M.nx] + Math.floor(n / M.nx);
const px = (x, y) => [M.origin + M.spacing * x, 750 - (M.origin + M.spacing * y)];
const f0 = v => Math.round(v).toLocaleString("en-US");
const f1 = v => v.toFixed(1);
const secs = v => v < 1 ? "under a second" : v < 10 ? v.toFixed(1) + " s" : f0(v) + " s";
const pct = v => v >= .1 ? (v * 100).toFixed(0) + "%" : v >= .001 ? (v * 100).toFixed(1) + "%" : (v * 100).toFixed(3) + "%";
const mean = a => a.reduce((s, v) => s + v, 0) / a.length;
const S = (tag, attrs, inner) => { let s = "<" + tag; for (const k in attrs) s += " " + k + '="' + attrs[k] + '"'; return s + ">" + (inner || "") + "</" + tag + ">"; };

/* theme */
try { const t = localStorage.getItem("qgw-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
$("themebtn").onclick = () => {
  const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme:dark)").matches;
  const t = dark ? "light" : "dark"; document.documentElement.dataset.theme = t;
  try { localStorage.setItem("qgw-theme", t); } catch (e) {}
};

/* chips */
const hy = D.signals.hybrid;
$("chips").innerHTML = [
  M.n_qubits + " binary variables", M.n_windows + " windows of ≤" + M.window_qubits + " qubits",
  D.routes.length + " ambulances", M.nx + "×" + M.ny + " intersections, " + M.T + " slots of " + M.slot_s + " s",
  "validated in SUMO"].map(t => '<span class="chip">' + t + "</span>").join("");

/* ------------------------------------------------------------------ live map */
let sc = 0, SC = D.traces[0], planName = "optimised", t = 0, playing = false, last = 0;
const TMAX = M.T * M.slot_s + 25;
const svg = $("map");
function drawStatic() {
  let s = "";
  for (let y = 0; y < M.ny; y++) { const [, py] = px(0, y); s += S("line", { x1: 0, x2: 750, y1: py, y2: py, stroke: "var(--road)", "stroke-width": 16 }); }
  for (let x = 0; x < M.nx; x++) { const [pxx] = px(x, 0); s += S("line", { y1: 0, y2: 750, x1: pxx, x2: pxx, stroke: "var(--road)", "stroke-width": 16 }); }
  SC.routes.forEach((r, i) => {
    const pts = r.path.map(p => px(p[0], p[1]).join(",")).join(" ");
    s += S("polyline", { points: pts, fill: "none", stroke: "var(--amb)", "stroke-width": 3, "stroke-dasharray": "2 7", "stroke-linecap": "round", opacity: .75 });
    const [sx, sy] = px(r.station[0], r.station[1]); const [ix, iy] = px(r.incident[0], r.incident[1]);
    s += S("rect", { x: sx - 11, y: sy - 36, width: 22, height: 16, rx: 3, fill: "var(--amb)" }) + S("text", { x: sx, y: sy - 24, "text-anchor": "middle", style: "fill:#fff;font-weight:600" }, "S" + (i + 1));
    s += S("circle", { cx: ix, cy: iy, r: 27, fill: "none", stroke: "var(--amb)", "stroke-width": 3 }) + S("text", { x: ix + 30, y: iy + 4 }, "I" + (i + 1) + " ×" + r.severity);
  });
  svg.innerHTML = s + '<g id="sig"></g><g id="veh"></g>';
}
function slotPlan() { return SC.plans[planName]; }
function drawSignals() {
  const slot = Math.floor(t / M.slot_s), plan = slotPlan(); let s = "";
  for (let y = 0; y < M.ny; y++) for (let x = 0; x < M.nx; x++) {
    const [cx, cy] = px(x, y), n = y * M.nx + x, fb = slot >= M.T, ew = !fb && plan[n][slot] === 1;
    const cEW = fb ? "var(--ink3)" : ew ? "var(--go)" : "var(--bad)", cNS = fb ? "var(--ink3)" : ew ? "var(--bad)" : "var(--go)";
    s += S("rect", { x: cx - 13, y: cy - 13, width: 26, height: 26, rx: 4, fill: "var(--surface)", stroke: "var(--line)" });
    s += S("rect", { x: cx - 10, y: cy - 2.5, width: 20, height: 5, rx: 2, fill: cEW }) + S("rect", { x: cx - 2.5, y: cy - 10, width: 5, height: 20, rx: 2, fill: cNS });
  }
  $("sig").innerHTML = s;
}
function drawVeh() {
  const tracks = SC.runs[planName].tracks; let civ = "", amb = "";
  for (const id in tracks) {
    const k = tracks[id], i = t - k.t0, n = k.p.length / 2;
    if (i < 0 || i > n - 1) continue;
    const a = Math.floor(i), b = Math.min(a + 1, n - 1), f = i - a;
    const x = k.p[2 * a] + (k.p[2 * b] - k.p[2 * a]) * f, y = 750 - (k.p[2 * a + 1] + (k.p[2 * b + 1] - k.p[2 * a + 1]) * f);
    if (k.a) amb += '<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="15" fill="var(--amb)" opacity=".22"/><circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="7" fill="var(--amb)"/>';
    else civ += '<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="3.2"/>';
  }
  $("veh").innerHTML = '<g fill="var(--ink3)">' + civ + "</g>" + amb;
}
function readout() {
  const T0 = SC.runs[planName], times = T0.amb_times, w = SC.routes.map(r => r.severity);
  const arrived = times.filter(v => v <= t).length;   // from SUMO arrival times, not from where the recorded track ends
  const wm = times.reduce((s, v, i) => s + v * w[i], 0) / w.reduce((s, v) => s + v, 0);
  $("readout").innerHTML = [
    [arrived + " of " + times.length, "ambulances have arrived now"],
    [f0(Math.max.apply(null, times)) + " s", "slowest ambulance"],
    [f1(wm) + " s", "mean ambulance time, weighted by severity"],
    [f1(T0.civ_wait) + " s", "average wait of other vehicles"]].map(r => '<div class="kpi"><b>' + r[0] + "</b><span>" + r[1] + "</span></div>").join("");
}
function frame() {
  $("clock").textContent = f0(t) + " s";
  $("scrub").value = t; drawSignals(); drawVeh(); readout();
}
function note() {
  const a = SC.runs["fixed-time"], b = SC.runs["optimised"], w = SC.routes.map(r => r.severity), sw = w.reduce((s, v) => s + v, 0);
  const wf = a.amb_times.reduce((s, v, i) => s + v * w[i], 0) / sw, wo = b.amb_times.reduce((s, v, i) => s + v * w[i], 0) / sw;
  $("livenote").innerHTML = "Severity-weighted ambulance time: <b>" + f1(wf) + " s</b> fixed-time against <b>" + f1(wo) + " s</b> optimised. " +
    "Other vehicles wait <b>" + f1(a.civ_wait) + " s</b> on average under fixed-time and <b>" + f1(b.civ_wait) + " s</b> under the optimised plan (same 160 s window for both). After " + f0(M.T * M.slot_s) + " s the simulator returns to its own default program, shown in grey.";
}
function setPlan(p) { planName = p; $("p-fixed").setAttribute("aria-pressed", p === "fixed-time"); $("p-opt").setAttribute("aria-pressed", p === "optimised"); frame(); }
$("scseg").innerHTML = D.traces.map((x, i) => '<button type="button" data-i="' + i + '" aria-pressed="' + (i === 0) + '">City ' + (i + 1) + "</button>").join("");
$("scseg").onclick = e => { const i = e.target.dataset && e.target.dataset.i; if (i == null) return; sc = +i; SC = D.traces[sc]; [...$("scseg").children].forEach(b => b.setAttribute("aria-pressed", b.dataset.i === i)); drawStatic(); note(); t = Math.min(t, 100); frame(); };
$("p-fixed").onclick = () => setPlan("fixed-time"); $("p-opt").onclick = () => setPlan("optimised");
$("scrub").max = TMAX; $("scrub").oninput = e => { t = +e.target.value; frame(); };
$("play").onclick = () => { playing = !playing; $("play").textContent = playing ? "Pause" : "Play"; if (playing) { if (t >= TMAX) t = 0; last = performance.now(); requestAnimationFrame(tick); } };
function tick(now) {
  if (!playing) return;
  t = Math.min(TMAX, t + (now - last) / 1000 * 3); last = now; frame();
  if (t >= TMAX) { playing = false; $("play").textContent = "Replay"; return; }
  requestAnimationFrame(tick);
}
drawStatic(); note(); t = 28; frame();

/* ------------------------------------------------------------------ plan heatmap */
const PL = [["fixed", "Fixed-time"], ["actuated", "Queue-actuated"], ["rule", "Rule preemption"], ["milp", "Exact optimum"], ["hybrid", "Quantum windows"]];
let curPlan = "hybrid";
function planFig() {
  const P = D.plans[curPlan === "rule" ? "rule-preempt" : curPlan], cw = 52, ch = 21, ox = 38, oy = 22, W = ox + cw * M.T + 8, H = oy + ch * M.nx * M.ny + 8;
  let s = "";
  for (let t0 = 0; t0 < M.T; t0++) s += S("text", { x: ox + cw * t0 + cw / 2, y: 13, "text-anchor": "middle" }, f0(t0 * M.slot_s) + "s");
  const req = {}; D.requests.forEach(r => { const k = r.node + "_" + r.slot; (req[k] = req[k] || []).push(r); });
  for (let n = 0; n < M.nx * M.ny; n++) {
    s += S("text", { x: 0, y: oy + ch * n + 15 }, name(n));
    for (let t0 = 0; t0 < M.T; t0++) {
      const ew = P[n][t0] === 1, x = ox + cw * t0, y = oy + ch * n;
      s += S("rect", { x: x + 1, y: y + 1, width: cw - 2, height: ch - 2, rx: 3, fill: ew ? "var(--q)" : "var(--road)", opacity: ew ? .85 : 1 },
        "<title>" + name(n) + " slot " + t0 + ": " + (ew ? "east-west green" : "north-south green") + "</title>");
      (req[n + "_" + t0] || []).forEach((r, j) => {
        const ok = (r.axis === "ew") === ew;
        s += S("circle", { cx: x + 10 + j * 9, cy: y + ch / 2, r: 2 + r.w / 8, fill: ok ? "var(--amb)" : "var(--bad)", stroke: ok ? "none" : "var(--ink)", "stroke-width": 1.2 },
          "<title>ambulance wants " + (r.axis === "ew" ? "east-west" : "north-south") + " (weight " + r.w.toFixed(1) + ")</title>");
      });
    }
  }
  $("planfig").innerHTML = '<div class="scroll">' + S("svg", { viewBox: "0 0 " + W + " " + H, style: "min-width:340px" }, s) + "</div>";
  const key = curPlan === "rule" ? "rule-preempt" : curPlan, b = D.breakdown[key];
  $("plancap").innerHTML = (b ? "Model cost <b>" + f0(b.total) + "</b> (delay " + f0(b.delay) + ", platoon stops " + f0(b.platoon) + ", switching " + f0(b.switch) + ", ambulance misses " + f0(b.emergency) + ", fairness " + f0(b.fairness) + ")."
    : "Model cost <b>" + f0(hy.cvar.cost[0]) + "</b>, " + (Math.abs(hy.cvar.cost[0] - D.signals.milp.cost) < 1e-6 ? "the same as the exact optimum." : f0(hy.cvar.cost[0] - D.signals.milp.cost) + " above the exact optimum (" + f0(D.signals.milp.cost) + ").")) + " Blue cells give east-west green, grey cells north-south. Orange dots are ambulance requests the plan meets; red dots with a dark ring are missed.";
}
$("planseg").innerHTML = PL.map(p => '<button type="button" data-k="' + p[0] + '" aria-pressed="' + (p[0] === curPlan) + '">' + p[1] + "</button>").join("");
$("planseg").onclick = e => { const k = e.target.dataset && e.target.dataset.k; if (!k) return; curPlan = k; [...$("planseg").children].forEach(b => b.setAttribute("aria-pressed", b.dataset.k === k)); planFig(); };
planFig();

/* dispatch matrix */
(function(){
  const d = D.dispatch, A = d.tau.length, cw = 78, ch = 46, ox = 56, oy = 34, W = ox + cw * A + 6, H = oy + ch * A + 6;
  let mx = 0; d.tau.forEach((r, a) => r.forEach((v, i) => mx = Math.max(mx, v * d.w[i])));
  let s = "";
  for (let i = 0; i < A; i++) s += S("text", { x: ox + cw * i + cw / 2, y: 16, "text-anchor": "middle" }, "I" + (i + 1)) + S("text", { x: ox + cw * i + cw / 2, y: 29, "text-anchor": "middle", style: "fill:var(--ink3)" }, "severity " + d.w[i]);
  for (let a = 0; a < A; a++) {
    s += S("text", { x: 0, y: oy + ch * a + 27 }, "Amb " + (a + 1));
    for (let i = 0; i < A; i++) {
      const v = d.tau[a][i] * d.w[i], on = d.opt_perm[a] === i;
      s += S("rect", { x: ox + cw * i + 2, y: oy + ch * a + 2, width: cw - 4, height: ch - 4, rx: 4, fill: "var(--q)", opacity: .1 + .5 * (1 - v / mx), stroke: on ? "var(--amb)" : "none", "stroke-width": 3 });
      s += S("text", { x: ox + cw * i + cw / 2, y: oy + ch * a + 28, "text-anchor": "middle", style: "fill:var(--ink);font-weight:" + (on ? 700 : 400) }, f1(v));
    }
  }
  $("dispfig").innerHTML = '<div class="scroll">' + S("svg", { viewBox: "0 0 " + W + " " + H, style: "min-width:340px" }, s) + "</div>";
  const same = Math.abs(d.opt_cost - d.greedy_cost) < 1e-6;
  $("dispcap").innerHTML = "Cells show severity-weighted travel time in slots, with congestion on the route included. The outlined cells are the best assignment, total <b>" + f1(d.opt_cost) + "</b>. " +
    (same ? "On this draw the nearest-ambulance rule finds the same assignment, so the comparison on the right matters more than this one example." : "The nearest-ambulance rule costs <b>" + f1(d.greedy_cost) + "</b>.");
})();

/* ------------------------------------------------------------------ bar chart helper (log scale) */
function logBars(el, rows, opt) {
  const W = 560, lh = 30, top = 24, left = opt.left || 150, right = 70, H = top + rows.length * lh + 26, lo = Math.log10(opt.min), hi = Math.log10(opt.max);
  const X = v => left + (Math.log10(Math.max(v, opt.min)) - lo) / (hi - lo) * (W - left - right);
  let s = "";
  for (let e = Math.ceil(lo); e <= hi; e++) { const x = X(Math.pow(10, e)); s += S("line", { x1: x, x2: x, y1: top - 6, y2: H - 24, class: "axis" }) + S("text", { x: x, y: H - 8, "text-anchor": "middle" }, e === 0 ? "1×" : "10" + String(e).replace("-", "−").replace(/(\d)/g, d => "⁰¹²³⁴⁵⁶⁷⁸⁹"[d]).replace("−", "⁻")); }
  rows.forEach((r, i) => {
    const y = top + i * lh;
    s += S("text", { x: left - 10, y: y + 17, "text-anchor": "end", style: "fill:var(--ink)" }, r.label);
    s += S("rect", { x: left, y: y + 4, width: Math.max(2, X(r.v) - left), height: 18, rx: 3, fill: r.color }, "<title>" + r.tip + "</title>");
    if (r.ref) s += S("line", { x1: X(r.ref), x2: X(r.ref), y1: y + 1, y2: y + 25, stroke: "var(--ink)", "stroke-width": 2 });
    s += S("text", { x: X(r.v) + 8, y: y + 17, style: "fill:var(--ink)" }, r.txt);
  });
  el.innerHTML = '<div class="scroll">' + S("svg", { viewBox: "0 0 " + W + " " + H, style: "min-width:460px" }, s) + "</div>";
}

/* window study */
(function(){
  const ms = ["qaoa p1", "qaoa p2", "qaoa p3", "cvar p2", "cvar p3", "warm p1", "warm p2"], nm = { qaoa: "QAOA", cvar: "CVaR-QAOA", warm: "Warm-start QAOA" }, col = { qaoa: "var(--q)", cvar: "var(--go)", warm: "var(--warn)" };
  const W = D.windows, rows = ms.map(m => { const g = mean(W.map(r => r[m].gain)), p = mean(W.map(r => r[m].p_opt)), sh = mean(W.map(r => r[m].shots99)), fam = m.split(" ")[0];
    return { label: nm[fam] + " p=" + m.split(" ")[1].slice(1), v: g, color: col[fam], txt: f0(g) + "×  (" + pct(p) + ")", tip: "mean chance of measuring the optimum " + pct(p) + ", about " + f0(sh) + " shots for 99% confidence" }; });
  logBars($("winfig"), rows, { min: 1, max: 1e4, left: 150 });
  const u = mean(W.map(r => r.uniform)), best = rows.reduce((a, b) => b.v > a.v ? b : a);
  const ps = mean(W.map(r => r["warm p1"].p_start));
  $("wincap").innerHTML = "Average over " + W.length + " windows of " + W[0].qubits + " qubits (4096 possible plans each). Bar length is how many times more likely than a blind guess (" + pct(u) + ") the circuit is to return the best plan; the figure in brackets is that probability. " +
    "Best average: <b>" + best.label + "</b>. The warm-start circuits begin from the rule-based plan, which already sits in the top " + pct(mean(W.map(r => r.rank_of_start))) + " of each window, so part of their lift is inherited from that start (they put " + pct(ps) + " of the probability back on the start itself at p=1).";
})();

/* dispatch multi */
(function(){
  const m = D.dispatch.multi, rows = [];
  [2, 3, 4].forEach(A => {
    const xy = m.filter(r => r.A === A && r.mixer === "xy"), px_ = m.filter(r => r.A === A && r.mixer === "x");
    if (!xy.length) return;
    const n = xy[0].n, u = mean(xy.map(r => r.uniform));
    rows.push({ label: A + " ambulances, XY mixer", v: mean(xy.map(r => r.p_opt)), color: "var(--q)", ref: u, txt: pct(mean(xy.map(r => r.p_opt))), tip: n + " qubits; feasible " + pct(mean(xy.map(r => r.p_feasible))) });
    rows.push({ label: A + " ambulances, penalties", v: mean(px_.map(r => r.p_opt)), color: "var(--ink3)", ref: u, txt: pct(mean(px_.map(r => r.p_opt))), tip: n + " qubits; feasible " + pct(mean(px_.map(r => r.p_feasible))) });
  });
  logBars($("dmfig"), rows, { min: 1e-5, max: 1, left: 170 });
  const r4 = m.filter(r => r.A === 4), f = (mx) => mean(r4.filter(r => r.mixer === mx).map(r => r.p_feasible));
  $("dmcap").innerHTML = "Chance of measuring the best assignment, averaged over " + r4.filter(r => r.mixer === "xy").length + " random cities per size, depth p=2. The black tick is a blind guess. With 4 ambulances (16 qubits) the XY mixer keeps every ambulance on exactly one incident by construction and returns a fully valid assignment " + pct(f("xy")) + " of the time; with penalties only, " + pct(f("x")) + ".";
})();

/* convergence */
(function(){
  const sol = [["exact", "exact window", "var(--ink)"], ["qaoa", "QAOA", "var(--q)"], ["cvar", "CVaR-QAOA", "var(--go)"], ["random", "random best-of-256", "var(--ink3)"], ["warm", "warm-start", "var(--warn)"]];
  const W = 1000, H = 300, l = 54, r = 190, tp = 14, bt = 34; let lo = 1e9, hi = 0, nmax = 0;
  sol.forEach(s => { const tr = hy[s[0]].trace; nmax = Math.max(nmax, tr.length); tr.forEach(v => { lo = Math.min(lo, v); hi = Math.max(hi, v); }); });
  lo = Math.min(lo, D.signals.milp.cost) - 20; hi = Math.min(hi, D.signals.start_cost + 40);
  const X = i => l + i / (nmax - 1) * (W - l - r), Y = v => tp + (1 - (Math.min(v, hi) - lo) / (hi - lo)) * (H - tp - bt);
  let s = "";
  for (let k = 0; k <= 4; k++) { const v = lo + (hi - lo) * k / 4, y = Y(v); s += S("line", { x1: l, x2: W - r, y1: y, y2: y, class: "axis" }) + S("text", { x: l - 8, y: y + 4, "text-anchor": "end" }, f0(v)); }
  s += S("text", { x: (l + W - r) / 2, y: H - 6, "text-anchor": "middle" }, "windows solved (each is one sub-problem of up to 12 qubits)");
  const my = Y(D.signals.milp.cost);
  s += S("line", { x1: l, x2: W - r, y1: my, y2: my, stroke: "var(--ink)", "stroke-dasharray": "6 5" }) + S("text", { x: l + 8, y: my - 7, style: "fill:var(--ink)" }, "exact optimum " + f0(D.signals.milp.cost));
  const ends = [];
  sol.forEach(se => { const tr = hy[se[0]].trace; s += S("polyline", { points: tr.map((v, i) => X(i).toFixed(1) + "," + Y(v).toFixed(1)).join(" "), fill: "none", stroke: se[2], "stroke-width": 2.4, "stroke-linejoin": "round" });
    ends.push([Y(tr[tr.length - 1]), se, tr[tr.length - 1]]); });
  ends.sort((a, b) => a[0] - b[0]); let prev = -99;
  ends.forEach(e => { let y = Math.max(e[0], prev + 14); prev = y; s += S("circle", { cx: X(hy[e[1][0]].trace.length - 1), cy: e[0], r: 4, fill: e[1][2] }) + S("text", { x: W - r + 8, y: y + 4 , style: "fill:" + e[1][2] }, e[1][1] + " " + f0(e[2])); });
  $("convfig").innerHTML = '<div class="scroll">' + S("svg", { viewBox: "0 0 " + W + " " + H, style: "min-width:640px" }, s) + "</div>";
  const fin = k => hy[k].cost[0], sa = D.signals.sa.cost;
  $("convcap").innerHTML = "All solvers except warm-start start from the same random plan (cost " + f0(D.signals.start_cost) + "); warm-start starts from the rule-based plan. A window answer is kept only if it does not make the plan worse. " +
    "Final costs: QAOA <b>" + f0(fin("qaoa")) + "</b>, CVaR-QAOA <b>" + f0(fin("cvar")) + "</b>, warm-start <b>" + f0(fin("warm")) + "</b>, random sampling <b>" + f0(mean(hy.random.cost)) + "</b> (mean of " + hy.random.cost.length + " runs), exact window search <b>" + f0(fin("exact")) + "</b>. " +
    "Simulated annealing on all " + M.n_qubits + " variables reaches " + f0(sa) + ". The exact solver (HiGHS) proves the optimum in " + secs(D.signals.milp.seconds) + ", so this is a method demonstration, not a speed claim.";
})();

/* ------------------------------------------------------------------ SUMO table */
(function(){
  let h = "", beats = 0, tot = 0;
  D.sumo.scenarios.forEach(sc => {
    const names = Object.keys(sc.sim), best = names.reduce((a, b) => sc.sim[b].amb.mean < sc.sim[a].amb.mean ? b : a);
    const rule = sc.sim["rule-preempt"].amb.mean, opt = sc.sim["optimised (MILP)"].amb.mean; tot++; if (opt <= rule) beats++;
    h += '<table><thead><tr><th>Scenario ' + (sc.seed + 1) + '</th><th>QUBO cost</th><th>Ambulance time, severity-weighted mean (s)</th><th>Other vehicles, mean wait (s)</th><th>Ambulances unfinished</th></tr></thead><tbody>';
    names.forEach(k => { const r = sc.sim[k]; h += '<tr class="' + (k === best ? "best" : "") + '"><td>' + k + '</td><td class="m">' + f0(sc.model[k]) + '</td><td class="m">' + f1(r.amb.mean) + " ± " + f1(r.amb.sd) + '</td><td class="m">' + f1(r.civ.mean) + " ± " + f1(r.civ.sd) + '</td><td class="m">' + r.unfinished + "</td></tr>"; });
    h += "</tbody></table><div style='height:18px'></div>";
  });
  $("simtable").innerHTML = h;
  const c = D.sumo.calibration;
  const bestAmb = c.reduce((a, b) => b.amb < a.amb ? b : a), bestCiv = c.reduce((a, b) => b.civ < a.civ ? b : a);
  const calTxt = bestAmb.mu === bestCiv.mu
    ? "weight " + bestAmb.mu + " was best on both counts there"
    : "weight " + bestAmb.mu + " was best for ambulances and weight " + bestCiv.mu + " for other traffic, so there is no single winner";
  let m24 = "";
  if (D.mu24) {
    const slower = D.mu24.filter(x => x.opt > x.rule + 1e-9).length;
    m24 = " Stress test with the fairness weight at 24 on the reported cities: the optimised plan was slower for ambulances than rule-based preemption in " + slower + " of " + D.mu24.length +
      " (" + D.mu24.map(x => f1(x.opt) + " s against " + f1(x.rule) + " s").join(", ") + ").";
  }
  $("simnote").innerHTML = "Shaded rows are the fastest for ambulances in that scenario. The optimised plan matches or beats the rule-based preemption on <b>" + beats + " of " + tot + "</b> scenarios for ambulance time. A lower QUBO cost does not always mean a lower simulated delay, because the model approximates queues and lost time. " +
    "The fairness weight " + M.mu + " was fixed before the experiments. A sweep on three other cities (seeds 10 to 12): " + c.map(x => "weight " + x.mu + " gave " + f1(x.amb) + " s ambulance / " + f1(x.civ) + " s other").join("; ") + "; " + calTxt + " (three cities, so treat this as a hint, not a calibration)." +
    " Ambulances that have not arrived after 160 s are counted at 160 s and listed as unfinished." + m24;
})();

/* uncertainty */
(function(){
  const u = D.uncertainty, W = 560, lh = 34, tp = 22, left = 80, H = tp + u.length * lh + 20, mx = Math.max.apply(null, u.map(r => Math.max(r.point, r.robust))) * 1.15 || 1;
  const X = v => left + v / mx * (W - left - 60); let s = "";
  [0, .25, .5, .75, 1].forEach(k => { const x = X(mx * k); s += S("line", { x1: x, x2: x, y1: tp - 6, y2: H - 18, class: "axis" }) + S("text", { x: x, y: H - 4, "text-anchor": "middle" }, f1(mx * k)); });
  u.forEach((r, i) => { const y = tp + i * lh; s += S("text", { x: left - 10, y: y + 18, "text-anchor": "end", style: "fill:var(--ink)" }, "city " + (i + 1));
    s += S("rect", { x: left, y: y + 3, width: Math.max(2, X(r.point) - left), height: 10, rx: 2, fill: "var(--ink3)" }, "<title>plan for the expected arrival slot only</title>") + S("text", { x: X(r.point) + 6, y: y + 12 }, f1(r.point));
    s += S("rect", { x: left, y: y + 16, width: Math.max(2, X(r.robust) - left), height: 10, rx: 2, fill: "var(--q)" }, "<title>plan that accounts for ±1 slot</title>") + S("text", { x: X(r.robust) + 6, y: y + 25 }, f1(r.robust)); });
  $("uncfig").innerHTML = '<div class="scroll">' + S("svg", { viewBox: "0 0 " + W + " " + H, style: "min-width:420px" }, s) + "</div>";
  const a = mean(u.map(r => r.point)), b = mean(u.map(r => r.robust));
  $("unccap").innerHTML = "Severity-weighted intersections where an ambulance finds the wrong axis green, averaged over sampled arrival delays (grey: plan built for the expected arrival slot only; blue: plan that spreads its request over the slot before and after). Across " + u.length + " cities the mean " + (b < a ? "falls" : b > a ? "rises" : "stays") + " from <b>" + f1(a) + "</b> to <b>" + f1(b) + "</b>. Evaluated in the model only, not in SUMO.";
})();

/* hardware */
(function(){
  const h = D.hardware; let t = "<table><thead><tr><th>p</th><th>2q gates (line)</th><th>2q gates (IBM)</th><th>Depth (IBM)</th><th>Ideal P(best)</th><th>Noisy P(best)</th></tr></thead><tbody>";
  h.rows.forEach(r => { t += "<tr><td>" + r.p + '</td><td class="m">' + r.line.two_qubit + '</td><td class="m">' + r.sherbrooke.two_qubit + '</td><td class="m">' + r.sherbrooke.depth + '</td><td class="m">' + pct(r.ideal_p_opt) + '</td><td class="m">' + (r.noisy_p_opt != null ? pct(r.noisy_p_opt) : "not run") + "</td></tr>"; });
  $("hwtable").innerHTML = t + "</tbody></table>";
  const r2 = h.rows.find(r => r.noisy_p_opt != null && r.p === 2) || h.rows[0], u = h.rows[0].uniform;
  $("hwcap").innerHTML = "Noisy runs use the calibration snapshot of " + h.device + ". A blind guess finds the best of 4096 plans " + pct(u) + " of the time; with noise the p=" + r2.p + " circuit reaches " + (r2.noisy_p_opt != null ? pct(r2.noisy_p_opt) + ", about " + f0(r2.noisy_p_opt / u) + "× a blind guess" : "(not run)") + " (ideal " + pct(r2.ideal_p_opt) + "). Noise shrinks the signal as depth grows, so today the hybrid loop runs on a simulator and the repository includes a script for running one window on IBM hardware.";
})();

/* limits */
$("limitlist").innerHTML = [
  ["No quantum speed-up is claimed", "A classical exact solver proves the optimum for the full problem in " + secs(D.signals.milp.seconds) + ". The quantum circuits solve pieces of it" + (["qaoa", "cvar", "warm"].every(k => Math.abs(hy[k].cost[0] - D.signals.milp.cost) < 1e-6) ? " and reach the same answer" : "; not every variant reaches the optimum") + ", which tests the formulation and the hybrid loop."],
  ["The city is synthetic", "The 4×4 grid and its queue forecast are generated. Map downloads were not reachable from the build environment, so no real street data is used."],
  ["Windows are simulated, not run on a chip", "All circuits ran on a statevector or a noisy simulator. Hardware results would need an IBM account and queue time."],
  ["Model and simulator disagree sometimes", "The QUBO approximates queues, so a better QUBO cost can still give a slower simulated trip. The table above reports those cases instead of hiding them."],
  ["Small samples", "Three scenarios, three simulator seeds each. Differences of a few seconds are within the spread."],
  ["Planning is open-loop", "Plans cover one 90-second horizon. A rolling re-plan as ambulances move is the natural next step and is not built."]
].map(x => "<div><h3>" + x[0] + "</h3><p>" + x[1] + "</p></div>").join("");
})();
