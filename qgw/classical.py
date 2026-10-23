"""Classical solvers / baselines for the signal QUBO."""
from __future__ import annotations

import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from .qubo import Qubo
from .signals import SignalProblem


# ------------------------------------------------------------------------------ heuristics
def fixed_time(p: SignalProblem) -> np.ndarray:
    """Uncoordinated fixed-time plan: every light does NS,NS,EW,EW,NS,NS ... in sync."""
    T, N = p.city.T, p.city.N
    row = np.array([(t // 2) % 2 for t in range(T)])
    return np.tile(row, N).astype(np.int8)


def actuated(p: SignalProblem) -> np.ndarray:
    """Queue-actuated rule: serve the axis with the longer queue in every slot (ignores everything else)."""
    return (p.city.q_ew > p.city.q_ns).astype(np.int8).reshape(-1)


def rule_preempt(p: SignalProblem) -> np.ndarray:
    """Actuated + rule-based emergency preemption: where an ambulance is expected, force the axis it needs
    (the highest total request weight wins).  This is what a simple classical preemption system does."""
    x = actuated(p).reshape(p.city.N, p.city.T).copy()
    need = {}
    for n, t, axis, w in p.requests:
        need.setdefault((n, t), {"ew": 0.0, "ns": 0.0})[axis] += w
    for (n, t), d in need.items():
        x[n, t] = 1 if d["ew"] >= d["ns"] else 0
    return x.reshape(-1)


# ------------------------------------------------------------------------------ exact (MILP)
def exact_milp(q: Qubo, time_limit: float = 60.0, x_start=None):
    """Exact optimum of the QUBO via linearisation + HiGHS (scipy.optimize.milp).
    y_ij <= x_i, y_ij <= x_j (for J_ij < 0) and y_ij >= x_i + x_j - 1 (for J_ij > 0) are the standard tight
    linearisations of the products.  If HiGHS stops on the time limit the best incumbent is returned and
    info["optimal"] is False; if it found nothing at all, x_start (or a greedy SA run) is used instead."""
    n = q.n
    iu, ju = np.nonzero(np.triu(q.J, 1))
    pairs = list(zip(iu.tolist(), ju.tolist()))
    m = len(pairs)
    c = np.concatenate([q.lin, q.J[iu, ju]])
    lb, ub = [], []
    A = lil_matrix((2 * m, n + m))
    r = 0
    for k, (i, j) in enumerate(pairs):
        w = q.J[i, j]
        if w < 0:       # want y large -> y <= x_i, y <= x_j
            A[r, n + k] = 1; A[r, i] = -1; lb.append(-np.inf); ub.append(0); r += 1
            A[r, n + k] = 1; A[r, j] = -1; lb.append(-np.inf); ub.append(0); r += 1
        else:           # want y small -> y >= x_i + x_j - 1
            A[r, n + k] = 1; A[r, i] = -1; A[r, j] = -1; lb.append(-1); ub.append(np.inf); r += 1
    integrality = np.concatenate([np.ones(n), np.zeros(m)])
    cons = [LinearConstraint(A[:r].tocsr(), lb, ub)] if r else []
    t0 = time.time()
    res = milp(c, constraints=cons, integrality=integrality,
               bounds=Bounds(np.zeros(n + m), np.ones(n + m)), options={"time_limit": time_limit, "mip_rel_gap": 0.0})
    seconds = time.time() - t0
    if res.x is not None:
        x = np.round(res.x[:n]).astype(np.int8)
    elif x_start is not None:
        x = np.asarray(x_start, dtype=np.int8).copy()
    else:
        x, _ = simulated_annealing(q, steps=20000, restarts=2, seed=0)
    bound = getattr(res, "mip_dual_bound", None)
    return x, float(q.energy(x)[0]), {"status": res.message, "optimal": bool(res.status == 0 and res.x is not None),
                                       "seconds": seconds, "bound": float(bound + q.const) if bound is not None else None}


# ------------------------------------------------------------------------------ simulated annealing
def simulated_annealing(q: Qubo, steps: int = 40000, restarts: int = 4, seed: int = 0, x0=None):
    """Single-flip Metropolis annealing.  Restart 0 starts from x0 when given.  Always returns the best plan
    actually visited (including each starting plan), with its energy recomputed exactly (no drift)."""
    if restarts < 1:
        raise ValueError("restarts must be >= 1")
    rng = np.random.default_rng(seed)
    n = q.n
    scale = max(np.abs(q.lin).max(initial=0.0), np.abs(q.J).max(initial=0.0), 1.0)
    best_x, best_e = None, np.inf
    for r in range(restarts):
        x = (rng.integers(0, 2, n) if (x0 is None or r > 0) else np.array(x0)).astype(float)
        e = float(q.energy(x)[0])
        if e < best_e:
            best_e, best_x = e, x.copy()
        for s in range(steps):
            temp = scale * 2.0 * (0.001 / 2.0) ** (s / steps)
            i = rng.integers(n)
            d = 1.0 - 2.0 * x[i]
            de = d * (q.lin[i] + q.J[i] @ x)
            if de <= 0 or rng.random() < np.exp(-de / temp):
                x[i] += d
                e += de
                if e < best_e - 1e-9:
                    best_e, best_x = e, x.copy()
    best_x = best_x.astype(np.int8)
    return best_x, float(q.energy(best_x)[0])
