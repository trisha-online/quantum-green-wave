"""
Numbers and data for the public website (web/site/).

Every figure the site shows is computed here from results/part_*.json, so the page can never drift from the
model: `python -m qgw.export` writes web/site/site-data.js, the page fills each `data-q="key"` element from
it, and tests/test_site.py checks that the text written into the HTML (shown when JavaScript is off) equals
what this module computes.
"""
from __future__ import annotations

import json
import os

import numpy as np

from .pipeline import RES, scenario

LETTERS = "ABCDEFGHIJKLMNOP"

MINUS = "−"


def _load(res, name):
    with open(os.path.join(res, f"part_{name}.json"), encoding="utf-8") as f:
        return json.load(f)


def _pct0(p):
    return f"{round(p * 100):d}%"


def _pct1(p):
    return f"{p * 100:.1f}%"


def _gain(g):
    return f"×{int(round(g, -1)):d}"


def numbers(res: str = RES) -> dict:
    """{key: display text}.  Keys are the data-q attributes used in web/site/index.html."""
    sig, dis, win, hw, sumo, unc = (_load(res, k) for k in ("signals", "dispatch", "windows", "hardware", "sumo", "uncertainty"))
    t = {}
    # problem size and hybrid loop
    nq = len(sig["plans"]["milp"])
    wq = int(sig["window_qubits"])
    t["n_qubits"] = str(nq)
    t["window_qubits"] = str(wq)
    t["frozen"] = str(nq - wq)
    t["window_plans"] = f"{2 ** wq:d}"
    t["n_windows"] = str(sig["n_windows"])
    t["sweeps"] = str((len(sig["hybrid"]["qaoa"][0]["trace"]) - 1) // sig["n_windows"])
    # dispatch: 4 ambulances, p = 2, mean over the random cities
    m4 = [r for r in dis["multi"] if r["A"] == 4]
    t["disp_xy_feasible"] = _pct0(np.mean([r["p_feasible"] for r in m4 if r["mixer"] == "xy"]))
    t["disp_x_feasible"] = _pct0(np.mean([r["p_feasible"] for r in m4 if r["mixer"] == "x"]))
    t["disp_cities"] = str(len([r for r in m4 if r["mixer"] == "xy"]))
    t["disp_qubits"] = str(m4[0]["n"])
    t["disp_valid"] = str(m4[0]["space"])
    t["disp_states"] = f"{2 ** m4[0]['n']:,}"
    t["disp_ratio"] = f"{np.mean([r['p_feasible'] for r in m4 if r['mixer'] == 'xy']) / np.mean([r['p_feasible'] for r in m4 if r['mixer'] == 'x']):.1f}×"
    # 12-qubit windows (ideal statevector)
    u = float(np.mean([w["uniform"] for w in win]))
    t["win_blind"] = f"{u * 100:.3f}%"
    t["win_count"] = str(len(win))
    for key, name in (("p1", "qaoa p1"), ("p2", "qaoa p2"), ("p3", "qaoa p3"), ("warm2", "warm p2"), ("cvar3", "cvar p3")):
        p = float(np.mean([w[name]["p_opt"] for w in win]))
        t[f"win_{key}"] = _pct0(p)
        t[f"win_{key}_gain"] = _gain(float(np.mean([w[name]["gain"] for w in win])))
        t[f"win_{key}_bar"] = f"{p * 100:.1f}%"
    t["win_start_rank"] = _pct1(float(np.mean([w["rank_of_start"] for w in win])))
    # city-wide result
    t["opt_cost"] = f"{sig['milp']['cost']:.0f}"
    for k in ("qaoa", "cvar", "warm"):
        t[f"cost_{k}"] = f"{sig['hybrid'][k][0]['cost']:.0f}"
    rc = [r["cost"] for r in sig["hybrid"]["random"]]
    t["cost_random"] = f"{min(rc):.0f}–{max(rc):.0f}"
    t["cost_rule"] = f"{sig['baselines']['rule-preempt']['total']:.0f}"
    t["cost_actuated"] = f"{sig['baselines']['actuated']['total']:.0f}"
    t["cost_fixed"] = f"{sig['baselines']['fixed']['total']:.0f}"
    t["milp_time"] = "under a second" if sig["milp"]["seconds"] < 1 else f"{sig['milp']['seconds']:.0f} s"
    # hardware
    for r in hw["rows"]:
        p = r["p"]
        t[f"hw_p{p}_gates"] = str(r["sherbrooke"]["two_qubit"])
        t[f"hw_p{p}_ideal"] = _pct1(r["ideal_p_opt"])
        t[f"hw_p{p}_noisy"] = _pct1(r["noisy_p_opt"]) if r.get("noisy_p_opt") is not None else "not run noisy"
    r2 = next(r for r in hw["rows"] if r["p"] == 2)
    noisy2 = r2.get("noisy_p_opt")             # QUICK runs skip the noisy p=2 simulation
    t["hw_p2_ratio"] = f"≈{int(round(noisy2 / r2['uniform'], -1)):d}× blind guess" if noisy2 is not None else "noisy run skipped"
    # SUMO
    wins = ties = losses = civ_less = 0
    for k, sc in enumerate(sumo["scenarios"], 1):
        mean = lambda name, m: float(np.mean([r[m] for r in sc["sim"][name]]))
        ao, ar = mean("optimised (MILP)", "amb_wmean"), mean("rule-preempt", "amb_wmean")
        co, cr = mean("optimised (MILP)", "civ_wait_mean"), mean("rule-preempt", "civ_wait_mean")
        t[f"sumo{k}_amb_opt"], t[f"sumo{k}_amb_rule"] = f"{ao:.1f}", f"{ar:.1f}"
        t[f"sumo{k}_civ_opt"], t[f"sumo{k}_civ_rule"] = f"{co:.1f}", f"{cr:.1f}"
        if f"{ao:.1f}" == f"{ar:.1f}":
            t[f"sumo{k}_outcome"] = "tie"; ties += 1
        elif ao < ar:
            t[f"sumo{k}_outcome"] = "win"; wins += 1
        else:
            t[f"sumo{k}_outcome"] = "loss"; losses += 1
        civ_less += co < cr
    n = len(sumo["scenarios"])
    plural = lambda c, w: f"{c} {w}" + ("" if c == 1 else ("es" if w.endswith("s") else "s"))
    t["sumo_summary"] = ", ".join([plural(wins, "win"), plural(ties, "tie"), plural(losses, "loss")])
    t["sumo_civ"] = "in all three" if civ_less == n == 3 else f"in {civ_less} of {n}"
    t["sumo_cities"] = str(n)                 # the page hides table rows for cities this run did not simulate
    # robustness (model only)
    a = float(np.mean([r["point"] for r in unc])); b = float(np.mean([r["robust"] for r in unc]))
    t["rob_point"], t["rob_robust"] = f"{a:.2f}", f"{b:.2f}"
    d = round((b / a - 1) * 100) if a > 0 else 0
    t["rob_drop"] = (MINUS if d < 0 else "+") + f"{abs(d)}%"
    t["rob_cities"] = str(len(unc))
    return t


def payload(res: str = RES) -> dict:
    """Everything the site's script needs: the display text plus, for the interactive grid, the proved-optimal
    plan of City 1 and its exact QUBO (constant, linear terms, couplings), so the page computes real energies."""
    sig = _load(res, "signals")
    S = scenario(0)
    city, prob = S["city"], S["prob"]
    q = prob.to_qubo()
    plan = [int(v) for v in sig["plans"]["milp"]]
    if abs(float(q.energy(np.array(plan))[0]) - sig["milp"]["cost"]) > 1e-6:
        raise RuntimeError("results/part_signals.json does not match the current model; rerun the pipeline")
    iu, ju = np.nonzero(np.triu(q.J, 1))
    reqs = {}                                     # nominal crossing slot of every ambulance (the +-1 spread is not drawn)
    for route, sev in zip(S["routes"], S["sev"]):
        for n, t, axis in city.route_crossings(route):
            if 0 <= t < city.T:
                reqs.setdefault(f"{n},{t}", []).append([axis, int(sev)])
    dis = _load(res, "dispatch")
    dispatch = {"cost": [[float(dis["tau"][a][i] * dis["w"][i]) for i in range(len(dis["w"]))] for a in range(len(dis["tau"]))],
                "severity": [int(v) for v in dis["w"]], "opt_perm": [int(v) for v in dis["opt_perm"]],
                "opt_cost": float(dis["opt_cost"]), "greedy_cost": float(dis["greedy_cost"])}
    return {
        "text": numbers(res),
        "dispatch": dispatch,
        "replay": replay(res),
        "grid": {"nx": city.nx, "ny": city.ny, "T": city.T, "slot_s": city.slot_s,
                 "names": [LETTERS[x] + str(y) for y in range(city.ny) for x in range(city.nx)],
                 "plan": plan, "const": float(q.const), "lin": [float(v) for v in q.lin],
                 "pairs": [[int(i), int(j), float(q.J[i, j])] for i, j in zip(iu, ju)],
                 "requests": reqs, "optimum": float(sig["milp"]["cost"])},
    }


REPLAY_DT = 2      # keep every 2nd one-second SUMO sample; the page interpolates between them


def replay(res: str = RES, dt: int = REPLAY_DT) -> dict:
    """SUMO vehicle tracks for the street replay (part_traces): per city, the routes, the two plans and, per plan,
    every vehicle's positions sampled every `dt` seconds, plus the ambulance arrival times measured by SUMO."""
    if dt < 1:
        raise ValueError("dt must be >= 1")
    cities = []
    for e in _load(res, "traces"):
        runs = {}
        for name, r in e["runs"].items():
            tracks = []
            for vid, tr in r["tracks"].items():
                pts = tr["p"]
                n = len(pts) // 2
                keep = list(range(0, n, dt))
                if keep[-1] != n - 1:
                    keep.append(n - 1)              # always keep the last sample (where the vehicle left the record)
                xy = [c for k in keep for c in (pts[2 * k], pts[2 * k + 1])]
                # [is_ambulance, first second, seconds recorded, x0, y0, x1, y1, ...]; sample k is at second
                # min(k*dt, n-1) after t0, so the page can rebuild the times without storing them
                tracks.append([int(tr["a"]), int(tr["t0"]), n] + xy)
            runs[name] = {"amb_times": [int(v) for v in r["amb_times"]], "civ_wait": float(r["civ_wait"]), "tracks": tracks}
        cities.append({"seed": int(e["seed"]),
                       "routes": [{"station": rt["station"], "incident": rt["incident"], "severity": int(rt["severity"]), "path": rt["path"]}
                                  for rt in e["routes"]],
                       "plans": {k: [[int(v) for v in row] for row in rows] for k, rows in e["plans"].items()},
                       "runs": runs})
    return {"dt": dt, "cities": cities}


def write(path: str, res: str = RES) -> int:
    txt = json.dumps(payload(res), separators=(",", ":"), ensure_ascii=False)
    with open(path, "w", encoding="utf-8") as f:
        f.write("window.QGW_SITE = " + txt + ";\n")
    return len(txt)
