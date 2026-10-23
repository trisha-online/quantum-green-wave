"""
Window decomposition ("block-coordinate descent"): the 96-variable city QUBO is far beyond a statevector
(or a NISQ chip), so we repeatedly freeze everything except a <=12-qubit window, solve that sub-QUBO, and
write the answer back only if it does not make the plan worse.  The window solver is pluggable:

    exact        brute-force the window (upper bound on what any window solver can do)
    random       best of S random samples (control: is the quantum solver better than luck?)
    qaoa         plain QAOA, X mixer, |+> start
    cvar         CVaR-QAOA (alpha)
    warm         warm-started QAOA from the current plan (eps-regularised)
Samples drawn from the final QAOA distribution (shots) pick the window's candidate.
"""
from __future__ import annotations

import numpy as np

from .city import City
from .qalgos import QAOA, warm_init
from .qubo import Qubo, all_bits


def adjacent_windows(city: City) -> list:
    """windows of variables: all time slots of two adjacent intersections (<=12 qubits for T<=6)."""
    wins = []
    for n in range(city.N):
        for m, _ in city.neighbours(n):
            if m > n:
                wins.append([city.var(n, t) for t in range(city.T)] + [city.var(m, t) for t in range(city.T)])
    return wins


def route_windows(city: City, routes: list, max_q: int = 12) -> list:
    """windows following each ambulance route: consecutive intersections on the route, same slots.
    Every intersection the ambulance crosses is covered, including the incident node (it carries requests too)."""
    if city.T > max_q:
        raise ValueError(f"a window holds all {city.T} slots of a node, which exceeds max_q={max_q}")
    wins = []
    for route in routes:
        nodes = [city.node(*p) for p in route[1:]]
        per = max(1, max_q // city.T)
        for k in range(0, len(nodes), per):
            chunk = nodes[k:k + per]
            wins.append([city.var(n, t) for n in chunk for t in range(city.T)])
    return wins


MAX_WINDOW = 16      # 2^16 statevector entries; beyond this brute force / statevector QAOA is impractical


def solve_window(sub: Qubo, solver: str, x_cur, rng, shots=256, p=2, alpha=0.2, eps=0.15, restarts=3, maxiter=120):
    n = sub.n
    if n > MAX_WINDOW:
        raise ValueError(f"window of {n} qubits is larger than MAX_WINDOW={MAX_WINDOW}")
    X = all_bits(n)
    cost = sub.energy(X)
    if solver == "exact":
        return X[np.argmin(cost)].copy(), {}
    if solver == "random":
        idx = rng.integers(0, 2 ** n, shots)
        k = idx[np.argmin(cost[idx])]
        return X[k].copy(), {}
    if solver in ("qaoa", "cvar"):
        algo = QAOA(cost, n, "x", None, alpha=(alpha if solver == "cvar" else 1.0))
    elif solver == "warm":
        init, th = warm_init(np.asarray(x_cur), eps)
        algo = QAOA(cost, n, "warm", init, warm_theta=th)
    else:
        raise ValueError(solver)
    params, _ = algo.optimise(p, restarts, maxiter, int(rng.integers(1 << 30)))
    pr = algo.probs(params)
    idx = rng.choice(2 ** n, size=shots, p=pr)
    k = idx[np.argmin(cost[idx])]
    info = {"p_best": float(pr[np.argmin(cost)]), "mean": float(pr @ cost), "ground": float(cost.min())}
    return X[k].copy(), info


def block_descent(q: Qubo, x0, windows, solver="exact", sweeps=2, seed=0, shots=256, **kw):
    rng = np.random.default_rng(seed)
    x = np.array(x0, dtype=np.int8).copy()
    if x.shape != (q.n,):
        raise ValueError(f"start plan has shape {x.shape}, expected ({q.n},)")
    windows = [sorted(set(w)) for w in windows if len(w)]
    e = float(q.energy(x)[0])
    trace = [e]
    for s in range(sweeps):
        order = rng.permutation(len(windows))
        for wi in order:
            w = windows[wi]
            sub = q.restrict(w, x)
            xw, _ = solve_window(sub, solver, x[w], rng, shots=shots, **kw)
            y = x.copy(); y[w] = xw
            ey = float(q.energy(y)[0])
            if ey <= e + 1e-12:
                x, e = y, ey
            trace.append(e)
    return x, e, trace
