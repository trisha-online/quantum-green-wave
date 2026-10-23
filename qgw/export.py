"""Merge results/part_*.json into web/data.js (window.QGW = {...}) for the dashboard."""
import json
import os

import numpy as np

from .pipeline import MU, load, scenario, NX, NY, T

WEB = os.path.join(os.path.dirname(__file__), "..", "web")

def agg(runs, key):
    v = [m[key] for m in runs]
    return dict(mean=float(np.mean(v)), sd=float(np.std(v)))


def main():
    S = scenario(0)
    city, p = S["city"], S["prob"]
    sig, dis, win, unc, hw, sumo, trc = (load(k) for k in ("signals", "dispatch", "windows", "uncertainty", "hardware", "sumo", "traces"))
    if abs(p.cost(np.array(sig["plans"]["milp"])) - sig["milp"]["cost"]) > 1e-6 or sig.get("mu", 2.0) != MU:
        raise RuntimeError("results/part_signals.json does not match the current model; rerun `python -m qgw.pipeline`")
    for part in (sumo, ):
        if any("amb_wmean" not in r for sc in part["scenarios"] for v in sc["sim"].values() for r in v):
            raise RuntimeError("results/part_sumo.json was made by the old evaluator; rerun `python -m qgw.pipeline sumo`")
    mu24 = None
    p24 = os.path.join(os.path.dirname(__file__), "..", "results_mu24", "part_sumo.json")
    if os.path.exists(p24):
        with open(p24, encoding="utf-8") as fh:
            m = json.load(fh)
        if all("amb_wmean" in r for sc in m["scenarios"] for v in sc["sim"].values() for r in v):
            am = lambda v, k: float(np.mean([r[k] for r in v]))
            mu24 = [dict(seed=sc["seed"], opt=am(sc["sim"]["optimised (MILP)"], "amb_wmean"), rule=am(sc["sim"]["rule-preempt"], "amb_wmean"),
                         opt_civ=am(sc["sim"]["optimised (MILP)"], "civ_wait_mean"), rule_civ=am(sc["sim"]["rule-preempt"], "civ_wait_mean"))
                    for sc in m["scenarios"]]
        else:
            print("results_mu24/ was made by the old evaluator; skipped (rerun with QGW_MU=24 QGW_RESULTS=results_mu24)")
    plans = dict(sig["plans"])
    plans["hybrid"] = sig["hybrid"]["cvar"][0]["plan"]
    N = city.N
    shape = lambda x: np.array(x).reshape(N, T).tolist()
    data = {
        "meta": dict(nx=NX, ny=NY, T=T, slot_s=city.slot_s, block_s=city.block_s, mu=MU, spacing=150, origin=150, n_qubits=city.nvars,
                     n_windows=sig["n_windows"], window_qubits=sig["window_qubits"]),
        "queues": dict(ew=city.q_ew.tolist(), ns=city.q_ns.tolist()),
        "routes": [dict(amb=a, station=list(S["ambs"][a].station), incident=list(S["incs"][i].node),
                        severity=S["incs"][i].severity, path=[list(q) for q in S["routes"][a]])
                   for a, i in enumerate(S["perm"])],
        "requests": [dict(node=n, slot=t, axis=ax, w=w) for n, t, ax, w in p.requests],
        "plans": {k: shape(v) for k, v in plans.items()},
        "breakdown": dict(sig["baselines"], milp=sig["optimal_breakdown"]),
        "signals": dict(milp=sig["milp"], sa=sig["sa"], start_cost=sig["start_cost"],
                        hybrid={k: dict(cost=[r["cost"] for r in v], trace=v[0]["trace"], seconds=[r["seconds"] for r in v])
                                for k, v in sig["hybrid"].items()}),
        "dispatch": dis,
        "windows": win,
        "uncertainty": unc,
        "hardware": hw,
        "sumo": dict(
            scenarios=[dict(seed=s["seed"], model=s["model"],
                            sim={k: dict(amb=agg(v, "amb_wmean"), civ=agg(v, "civ_wait_mean"),
                                         unfinished=int(sum(m["unfinished"] for m in v))) for k, v in s["sim"].items()})
                       for s in sumo["scenarios"]],
            calibration=sumo["calibration"]
            ),
        "traces": trc,
        "mu24": mu24,
    }
    os.makedirs(WEB, exist_ok=True)
    txt = json.dumps(data, separators=(",", ":"), default=lambda o: o.tolist() if hasattr(o, "tolist") else float(o))
    with open(os.path.join(WEB, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.QGW = " + txt + ";\n")
    print("data.js", len(txt) // 1024, "KB")
    from .site import write as write_site
    n = write_site(os.path.join(WEB, "site", "site-data.js"))
    print("site/site-data.js", n // 1024, "KB")


if __name__ == "__main__":
    main()
