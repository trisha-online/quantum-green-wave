"""
Ambulance -> incident assignment as a constrained QUBO (A ambulances x I incidents -> A*I qubits).

  cost    = sum_{a,i} w_i * tau[a,i] * x[a,i]          (severity-weighted, congestion-aware travel time)
  rows    each ambulance serves exactly one incident   -> enforced EXACTLY by an XY mixer + Dicke start
  columns each incident gets exactly one ambulance     -> penalty  P * (sum_a x[a,i] - 1)^2
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np

from .city import City
from .qalgos import QAOA, dicke_state
from .qubo import Qubo, all_bits


@dataclass
class DispatchProblem:
    tau: np.ndarray        # (A, I) estimated travel time in slots
    w: np.ndarray          # (I,) severity weights
    A: int
    I: int
    P: float = 0.0

    @classmethod
    def from_city(cls, city: City, ambs, incs, kappa=1.0):
        tau = np.array([[city.path_cost(a.station, i.node, kappa) for i in incs] for a in ambs])
        w = np.array([float(i.severity) for i in incs])
        return cls(tau, w, len(ambs), len(incs))

    def __post_init__(self):
        self.tau = np.asarray(self.tau, dtype=float)
        self.w = np.asarray(self.w, dtype=float)
        if self.A != self.I:
            raise ValueError(f"the assignment model needs as many ambulances as incidents (got {self.A} and {self.I})")
        if self.tau.shape != (self.A, self.I) or self.w.shape != (self.I,):
            raise ValueError("tau must be (A, I) and w must be (I,)")

    def var(self, a, i):
        return a * self.I + i

    def base_cost(self):
        return (self.tau * self.w[None, :]).reshape(-1)

    def to_qubo(self, P=None) -> Qubo:
        """penalty form: rows AND columns both penalised (used for the penalty-QAOA baseline)."""
        P = self.default_penalty() if P is None else P
        n = self.A * self.I
        lin = self.base_cost().copy()
        J = np.zeros((n, n))
        const = 0.0
        groups = [[self.var(a, i) for i in range(self.I)] for a in range(self.A)] + \
                 [[self.var(a, i) for a in range(self.A)] for i in range(self.I)]
        for g in groups:
            const += P
            for u in g:
                lin[u] += -2 * P + P          # (sum x -1)^2 = sum x^2 + 2 sum_{u<v} x x - 2 sum x + 1, x^2 = x
            for u, v in itertools.combinations(g, 2):
                J[u, v] += 2 * P; J[v, u] += 2 * P
        return Qubo(const, lin, J)

    def column_qubo(self, P=None) -> Qubo:
        """only the column constraints are penalised; rows are handled by the mixer."""
        P = self.default_penalty() if P is None else P
        n = self.A * self.I
        lin = self.base_cost().copy()
        J = np.zeros((n, n))
        const = 0.0
        for i in range(self.I):
            g = [self.var(a, i) for a in range(self.A)]
            const += P
            for u in g:
                lin[u] += -P
            for u, v in itertools.combinations(g, 2):
                J[u, v] += 2 * P; J[v, u] += 2 * P
        return Qubo(const, lin, J)

    def default_penalty(self):
        return float(1.5 * (self.base_cost().max()))

    def feasible(self, X):
        M = X.reshape(len(X), self.A, self.I)
        return (M.sum(2) == 1).all(1) & (M.sum(1) == 1).all(1)

    def cost_of(self, perm):
        """perm[a] = incident index"""
        return float(sum(self.w[perm[a]] * self.tau[a, perm[a]] for a in range(self.A)))

    def brute_force(self):
        best = min(itertools.permutations(range(self.I)), key=self.cost_of)
        return list(best), self.cost_of(best)

    def greedy_nearest(self):
        """each incident, in order of severity, takes the nearest still-free ambulance (what a dispatcher does)."""
        free, perm = set(range(self.A)), [None] * self.A
        for i in np.argsort(-self.w):
            a = min(free, key=lambda a: self.tau[a, i])
            perm[a] = int(i); free.remove(a)
        return perm, self.cost_of(perm)

    def xy_qaoa(self, p=3, restarts=5, maxiter=300, seed=0, mixer="xy", P=None):
        """returns dict with probability of the optimum, etc.  mixer: 'xy' (rows exact) or 'x' (all penalties)."""
        n = self.A * self.I
        X = all_bits(n)
        feas = self.feasible(X)
        if mixer == "xy":
            q = self.column_qubo(P)
            cost = q.energy(X)
            rows = [[self.var(a, i) for i in range(self.I)] for a in range(self.A)]
            init = dicke_state(n, rows, 1)
            pairs = []
            for r in rows:                               # even/odd ring on each row
                m = len(r)
                for k in range(0, m - 1, 2): pairs.append((r[k], r[k + 1]))
                for k in range(1, m - 1, 2): pairs.append((r[k], r[k + 1]))
                if m > 2: pairs.append((r[-1], r[0]))
            algo = QAOA(cost, n, "xy", init, xy_pairs=pairs)
        else:
            q = self.to_qubo(P)
            cost = q.energy(X)
            algo = QAOA(cost, n, "x", None)
        params, val = algo.optimise(p, restarts, maxiter, seed)
        pr = algo.probs(params)
        c0 = self.base_cost() @ X.T
        opt = c0[feas].min()
        is_opt = feas & np.isclose(c0, opt)
        out = {"p_feasible": float(pr[feas].sum()), "p_opt": float(pr[is_opt].sum()),
               "e_cost_feasible": float((pr[feas] @ c0[feas]) / max(pr[feas].sum(), 1e-12)),
               "uniform_p_opt": float(is_opt.mean()), "feasible_space": int(feas.sum()),
               "optimum": float(opt), "params": params.tolist(), "n": n}
        # best feasible bitstring by probability mass
        k = np.argmax(np.where(feas, pr, -1))
        out["best_assignment"] = [int(np.argmax(X[k].reshape(self.A, self.I)[a])) for a in range(self.A)]
        return out
