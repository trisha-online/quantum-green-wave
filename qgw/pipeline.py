"""
End-to-end experiments.  Usage:  python -m qgw.pipeline [part ...]   (no args = all parts)
Each part writes results/part_<name>.json; `python -m qgw.export` merges them into web/data.js.
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

from .city import make_city, make_emergencies, TIMING_SPREAD
from .classical import actuated, exact_milp, fixed_time, rule_preempt, simulated_annealing
from .decompose import adjacent_windows, block_descent, route_windows
from .dispatch import DispatchProblem
from .qalgos import QAOA, stats, uniform_baseline, warm_init
from .qubo import all_bits
from .signals import SignalProblem

RES = os.environ.get("QGW_RESULTS") or os.path.join(os.path.dirname(__file__), "..", "results")
QUICK = bool(os.environ.get("QUICK"))
NX = NY = 4
T = 6
W_AMB = 30.0
MU = float(os.environ.get("QGW_MU", 2.0))     # fairness weight; fixed before the experiments


def save(name, obj):
    os.makedirs(RES, exist_ok=True)
    with open(os.path.join(RES, f"part_{name}.json"), "w", encoding="utf-8") as f:
        json.dump(obj, f, default=lambda o: o.tolist() if hasattr(o, "tolist") else float(o))


def load(name):
    with open(os.path.join(RES, f"part_{name}.json"), encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------------------- scenario
def scenario(seed=0, n_amb=4, rush="ew", s_switch=3.0, mu=None, spread=None, perm=None):
    """city + ambulance/incident draw + (optimal) dispatch + signal problem."""
    mu = MU if mu is None else mu
    city = make_city(NX, NY, T, seed=seed, rush=rush)
    ambs, incs = make_emergencies(city, n_amb, seed)
    disp = DispatchProblem.from_city(city, ambs, incs)
    if perm is None:
        perm, _ = disp.brute_force()
    routes, reqs, sev = [], [], []
    for a, i in enumerate(perm):
        r = city.shortest_path(ambs[a].station, incs[i].node)
        routes.append(r); sev.append(incs[i].severity)
        reqs += city.requests_for_route(r, incs[i].severity, W_AMB, spread)
    prob = SignalProblem(city, reqs, s_switch=s_switch, mu_fair=mu)
    return dict(city=city, ambs=ambs, incs=incs, disp=disp, perm=perm, routes=routes, sev=sev, prob=prob)


# ---------------------------------------------------------------------------------------- A: dispatch
def part_dispatch():
    S = scenario(0)
    d = S["disp"]
    opt_perm, opt_cost = d.brute_force()
    gr_perm, gr_cost = d.greedy_nearest()
    rows = []
    for mixer in ("xy", "x"):
        for p in (1, 2, 3):
            t = time.time()
            r = d.xy_qaoa(p=p, restarts=4, maxiter=250, seed=1, mixer=mixer)
            r.update(mixer=mixer, p=p, seconds=time.time() - t)
            rows.append(r)
            print("dispatch", mixer, p, round(r["p_opt"], 4), round(r["p_feasible"], 3), flush=True)
    # multi-scenario scaling (3 and 4 ambulances)
    multi = []
    for A in (2, 3, 4):
        for sd in range(2 if QUICK else 5):
            Sx = scenario(100 + sd, n_amb=A)
            dx = Sx["disp"]
            o = dx.brute_force()[1]
            g = dx.greedy_nearest()[1]
            for mixer in ("xy", "x"):
                r = dx.xy_qaoa(p=2, restarts=3, maxiter=150, seed=sd, mixer=mixer)
                multi.append(dict(A=A, seed=sd, mixer=mixer, p_opt=r["p_opt"], p_feasible=r["p_feasible"],
                                  uniform=r["uniform_p_opt"], greedy_gap=(g - o) / o, e_gap=(r["e_cost_feasible"] - o) / o,
                                  n=r["n"], space=r["feasible_space"]))
            print("dispatch multi", A, sd, flush=True)
    save("dispatch", dict(tau=d.tau, w=d.w, opt_perm=opt_perm, opt_cost=opt_cost, greedy_perm=gr_perm,
                         greedy_cost=gr_cost, runs=rows, multi=multi,
                         stations=[a.station for a in S["ambs"]], incidents=[(i.node, i.severity) for i in S["incs"]]))


# ---------------------------------------------------------------------------------------- B: signals
def part_signals():
    S = scenario(0)
    p, city = S["prob"], S["city"]
    q = p.to_qubo()
    xe, ee, info = exact_milp(q, 120)
    xs, es = simulated_annealing(q, steps=40000, restarts=4, seed=0)
    base = {"fixed": fixed_time(p), "actuated": actuated(p), "rule-preempt": rule_preempt(p)}
    out = {"milp": dict(cost=ee, seconds=info["seconds"], optimal=info["optimal"]),
           "sa": dict(cost=es), "baselines": {k: p.breakdown(v) for k, v in base.items()},
           "optimal_breakdown": p.breakdown(xe), "plans": {k: v.tolist() for k, v in base.items()}}
    out["plans"]["milp"] = xe.tolist()
    wins = adjacent_windows(city) + route_windows(city, S["routes"])
    out["n_windows"] = len(wins); out["window_qubits"] = max(len(w) for w in wins)
    rng = np.random.default_rng(0)
    x0 = rng.integers(0, 2, q.n).astype(np.int8)
    out["start_cost"] = float(q.energy(x0)[0])
    sweeps = 2 if QUICK else 3
    for solver, seeds in (("exact", 3), ("random", 3), ("qaoa", 1), ("cvar", 1), ("warm", 1)):
        runs = []
        for sd in range(1 if QUICK else seeds):
            t = time.time()
            # warm-start needs a decent start: use the rule-based plan; others start from the same random plan
            start = base["rule-preempt"] if solver == "warm" else x0
            x, e, tr = block_descent(q, start, wins, solver, sweeps=sweeps, seed=sd, shots=256, p=2)
            runs.append(dict(cost=e, trace=tr, seconds=time.time() - t, plan=x.tolist()))
            print("signals", solver, sd, round(e, 1), round(time.time() - t, 1), "s", flush=True)
        out.setdefault("hybrid", {})[solver] = runs
    out["warm_start_from"] = "rule-preempt"
    out["mu"] = MU
    save("signals", out)


# ---------------------------------------------------------------------------------------- C: window study
def part_windows():
    S = scenario(0)
    p, city = S["prob"], S["city"]
    q = p.to_qubo()
    x_ref = rule_preempt(p)
    wins = adjacent_windows(city)
    rng = np.random.default_rng(1)
    pick = rng.choice(len(wins), size=4 if QUICK else 10, replace=False)
    rows = []
    for wi in pick:
        w = wins[wi]
        sub = q.restrict(w, x_ref)
        X = all_bits(sub.n)
        cost = sub.energy(X)
        ground = cost.min()
        base_row = dict(window=int(wi), qubits=sub.n, uniform=uniform_baseline(cost),
                        start_gap=float(sub.energy(x_ref[w])[0] - ground),
                        rank_of_start=float((cost < sub.energy(x_ref[w])[0] - 1e-9).mean()))
        prev = {}
        for name, kw in [("qaoa p1", dict(mode="x", p=1)), ("qaoa p2", dict(mode="x", p=2)), ("qaoa p3", dict(mode="x", p=3)),
                         ("cvar p2", dict(mode="x", p=2, alpha=0.1)), ("cvar p3", dict(mode="x", p=3, alpha=0.1)),
                         ("warm p1", dict(mode="warm", p=1)), ("warm p2", dict(mode="warm", p=2))]:
            if kw["mode"] == "warm":
                init, th = warm_init(x_ref[w], 0.15)
                algo = QAOA(cost, sub.n, "warm", init, warm_theta=th)
            else:
                algo = QAOA(cost, sub.n, "x", None, alpha=kw.get("alpha", 1.0))
            fam = name.split()[0]
            params, _ = algo.optimise(kw["p"], restarts=3, maxiter=150, seed=int(wi), x0=prev.get(fam))
            prev[fam] = params                     # next depth of the same family starts from INTERP(this)
            pr = algo.probs(params)
            s = stats(pr, cost)
            s.update(method=name, uniform=base_row["uniform"], gain=s["p_opt"] / base_row["uniform"],
                     gap_mean=float(pr @ cost - ground))
            if kw["mode"] == "warm":
                k = int(np.dot(x_ref[w], 1 << np.arange(sub.n)))
                s["p_start"] = float(pr[k])
            base_row[name] = s
        rows.append(base_row)
        print("window", wi, flush=True)
    save("windows", rows)


# ---------------------------------------------------------------------------------------- D: robustness
def part_uncertainty(n_mc=1000):
    out = []
    for sd in range(2 if QUICK else 6):
        S_pt = scenario(sd, spread={0: 1.0})
        S_sp = scenario(sd)
        plans = {}
        for name, S in (("point", S_pt), ("robust", S_sp)):
            q = S["prob"].to_qubo()
            plans[name] = exact_milp(q, 60)[0]
        city = S_sp["city"]
        rng = np.random.default_rng(sd)
        res = {k: [] for k in plans}
        for _ in range(n_mc):
            shifts = rng.choice([-1, 0, 1], size=len(S_sp["routes"]), p=[TIMING_SPREAD[-1], TIMING_SPREAD[0], TIMING_SPREAD[1]])
            for name, x in plans.items():
                X = x.reshape(city.N, city.T)
                miss = 0.0
                for r, sv, sh in zip(S_sp["routes"], S_sp["sev"], shifts):
                    for node, t0, axis in city.route_crossings(r):
                        t = t0 + sh
                        if not 0 <= t < city.T:          # outside the plan: same rule as the QUBO requests
                            continue
                        need = 1 if axis == "ew" else 0
                        miss += sv * (X[node, t] != need)
                res[name].append(miss)
        out.append(dict(seed=sd, point=float(np.mean(res["point"])), robust=float(np.mean(res["robust"])),
                        point_p90=float(np.percentile(res["point"], 90)), robust_p90=float(np.percentile(res["robust"], 90))))
        print("uncertainty", sd, out[-1], flush=True)
    save("uncertainty", out)


# ---------------------------------------------------------------------------------------- E: hardware
def part_hardware():
    from qiskit_ibm_runtime.fake_provider import FakeSherbrooke
    from .hardware import noisy_probs, resources, window_circuit
    S = scenario(0)
    p, city = S["prob"], S["city"]
    q = p.to_qubo()
    x_ref = rule_preempt(p)
    wins = adjacent_windows(city)
    w = wins[5]
    sub = q.restrict(w, x_ref)
    X = all_bits(sub.n); cost = sub.energy(X)
    be = FakeSherbrooke()
    rows = []
    prev = None
    for pp in (1, 2, 3):
        algo = QAOA(cost, sub.n, "x", None)
        params, val = algo.optimise(pp, restarts=3, maxiter=150, seed=3, x0=prev)   # p>1 starts from INTERP(p-1)
        prev = params
        qc = window_circuit(sub, params)
        ideal = algo.probs(params)
        row = dict(p=pp, qubits=sub.n, ideal_p_opt=float(ideal[np.isclose(cost, cost.min())].sum()),
                   line=resources(qc), sherbrooke=resources(qc, be), uniform=uniform_baseline(cost))
        if pp <= (1 if QUICK else 2):
            t = time.time()
            pr = noisy_probs(qc, be, shots=20000 if not QUICK else 4000)
            row["noisy_p_opt"] = float(pr[np.isclose(cost, cost.min())].sum())
            row["noisy_mean_gap"] = float(pr @ cost - cost.min()); row["ideal_mean_gap"] = float(ideal @ cost - cost.min())
            row["noisy_seconds"] = time.time() - t
        rows.append(row)
        print("hardware", row, flush=True)
    # dispatch circuit size (16 qubits, XY mixer decomposed into 2 CX per XX+YY)
    save("hardware", dict(device="FakeSherbrooke (127q heavy-hex, Eagle r3 calibration snapshot)", rows=rows))


# ---------------------------------------------------------------------------------------- F: SUMO
def part_sumo():
    from .sumo_eval import evaluate_plans
    sig = load("signals")
    out = {"scenarios": [], "calibration": []}
    for sd in range(2 if QUICK else 3):
        S = scenario(sd)
        p, city = S["prob"], S["city"]
        q = p.to_qubo()
        xe, ee, _ = exact_milp(q, 60)
        plans = {"fixed-time": fixed_time(p), "actuated": actuated(p), "rule-preempt": rule_preempt(p), "optimised (MILP)": xe}
        if sd == 0:
            if abs(p.cost(np.array(sig["hybrid"]["cvar"][0]["plan"])) - sig["hybrid"]["cvar"][0]["cost"]) > 1e-6:
                raise RuntimeError("results/part_signals.json is stale (made with other settings); rerun the signals part")
            hy = sig["hybrid"]["cvar"][0]["plan"]
            plans["hybrid (CVaR-QAOA windows)"] = np.array(hy, dtype=np.int8)
        res = evaluate_plans(city, plans, S["routes"], S["sev"], seeds=(0,) if QUICK else (0, 1, 2),
                             record_first=None)
        out["scenarios"].append(dict(seed=sd, model={k: float(p.cost(v)) for k, v in plans.items()},
                                     sim={k: v for k, v in res.items()}))
        print("sumo", sd, flush=True)
    # (per-vehicle animation traces are produced by part_traces)
    # calibration of the fairness weight, done on HELD-OUT scenarios (seeds 10-12), not on the reported ones
    for mu in (2, 6, 12, 24):
        am, cv = [], []
        for sd in (10, 11, 12):
            Sm = scenario(sd, mu=mu)
            x, e, _ = exact_milp(Sm["prob"].to_qubo(), 60)
            r = evaluate_plans(Sm["city"], {"o": x}, Sm["routes"], Sm["sev"], seeds=(0, 1))["o"]
            am.append(np.mean([m["amb_wmean"] for m in r])); cv.append(np.mean([m["civ_wait_mean"] for m in r]))
        out["calibration"].append(dict(mu=mu, amb=float(np.mean(am)), civ=float(np.mean(cv))))
        print("calib", out["calibration"][-1], flush=True)
    save("sumo", out)


def part_traces():
    """per-vehicle second-by-second tracks for the dashboard animation, all three reported scenarios."""
    from .sumo_eval import evaluate_plans
    out = []
    for sd in range(3):
        S = scenario(sd)
        p, city = S["prob"], S["city"]
        xo = exact_milp(p.to_qubo(), 60)[0]
        entry = dict(seed=sd, routes=[dict(station=list(S["ambs"][a].station), incident=list(S["incs"][i].node),
                                           severity=S["incs"][i].severity, path=[list(q) for q in S["routes"][a]])
                                      for a, i in enumerate(S["perm"])],
                     plans={"fixed-time": fixed_time(p).reshape(city.N, city.T), "optimised": xo.reshape(city.N, city.T)}, runs={})
        for name, X in (("fixed-time", fixed_time(p)), ("optimised", xo)):
            r = evaluate_plans(city, {name: X}, S["routes"], S["sev"], seeds=(0,), record_first=name)[name][0]
            entry["runs"][name] = dict(tracks=r["trace"], amb_times=r["amb_times"], civ_wait=r["civ_wait_mean"])
            print("traces", sd, name, r["amb_times"], flush=True)
        out.append(entry)
    save("traces", out)


PARTS = dict(traces=part_traces, dispatch=part_dispatch, signals=part_signals, windows=part_windows, uncertainty=part_uncertainty,
             hardware=part_hardware, sumo=part_sumo)

# signals must run before sumo (sumo re-uses the hybrid plan); traces last because it is slow
ORDER = ["dispatch", "signals", "windows", "uncertainty", "hardware", "sumo", "traces"]
PARTS = {k: PARTS[k] for k in ORDER}

if __name__ == "__main__":
    which = sys.argv[1:] or list(PARTS)
    bad = [k for k in which if k not in PARTS]
    if bad:
        sys.exit(f"unknown part(s) {bad}; choose from {list(PARTS)}")
    for k in which:
        t = time.time()
        PARTS[k]()
        print(f"== {k} done in {time.time() - t:.0f}s", flush=True)
