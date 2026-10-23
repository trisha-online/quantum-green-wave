"""
Fast numpy statevector QAOA family (cross-checked against Qiskit circuits in the tests).

  * standard QAOA (X mixer, |+> start)
  * CVaR-QAOA  (optimise the mean of the best alpha-fraction of outcomes, Barkoutsos et al.)
  * warm-start QAOA (Egger et al.): start from a classical solution, eps-regularised, with the
    matching rotated mixer
  * XY-mixer QAOA with Dicke/W-state start for one-hot (assignment) constraints
Bit i of a basis-state index is variable i (Qiskit little-endian).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from .qubo import Qubo, all_bits


# ------------------------------------------------------------------ gates on a flat statevector
def _apply_1q(psi, n, q, U):
    psi = psi.reshape(2 ** (n - 1 - q), 2, 2 ** q)
    return np.einsum("ab,xbz->xaz", U, psi).reshape(-1)


_XY_CACHE = {}


def _xy_idx(n, a, b):
    key = (n, a, b)
    if key not in _XY_CACHE:
        idx = np.arange(2 ** n)
        ba, bb = (idx >> a) & 1, (idx >> b) & 1
        i01 = idx[(ba == 1) & (bb == 0)]
        _XY_CACHE[key] = (i01, i01 ^ ((1 << a) | (1 << b)))
    return _XY_CACHE[key]


def _apply_xy(psi, n, a, b, beta):
    """exp(-i beta (XX+YY)/2) on qubits a,b: rotates the {|01>,|10>} subspace, leaves |00>,|11>."""
    i01, i10 = _xy_idx(n, a, b)
    out = psi.copy()
    c, s = np.cos(beta), -1j * np.sin(beta)
    out[i01] = c * psi[i01] + s * psi[i10]
    out[i10] = c * psi[i10] + s * psi[i01]
    return out


def rx(beta):
    return np.array([[np.cos(beta), -1j * np.sin(beta)], [-1j * np.sin(beta), np.cos(beta)]])


def ry(th):
    return np.array([[np.cos(th / 2), -np.sin(th / 2)], [np.sin(th / 2), np.cos(th / 2)]], dtype=complex)


def rz(th):
    return np.diag([np.exp(-1j * th / 2), np.exp(1j * th / 2)])


def dicke_state(n, groups, k=1):
    """equal superposition over bitstrings with exactly k ones in each group (list of qubit lists)."""
    X = all_bits(n)
    ok = np.ones(len(X), bool)
    for g in groups:
        ok &= X[:, g].sum(1) == k
    psi = ok.astype(complex)
    return psi / np.linalg.norm(psi)


@dataclass
class QAOA:
    cost: np.ndarray                 # diagonal over all 2^n basis states
    n: int
    mixer: str = "x"                 # "x" | "warm" | "xy"
    init: np.ndarray | None = None   # starting statevector (default |+>)
    xy_pairs: list | None = None     # list of (a,b) pairs for the XY mixer
    warm_theta: np.ndarray | None = None
    alpha: float = 1.0               # CVaR level (1.0 = ordinary expectation)

    def __post_init__(self):
        self.cost = np.asarray(self.cost, dtype=float)
        if self.cost.shape != (2 ** self.n,):
            raise ValueError(f"cost must have 2^n = {2 ** self.n} entries, got {self.cost.shape}")
        if not 0.0 < self.alpha <= 1.0:
            raise ValueError("CVaR alpha must be in (0, 1]")
        if self.mixer not in ("x", "warm", "xy"):
            raise ValueError(f"unknown mixer {self.mixer!r}")
        if self.mixer == "xy" and not self.xy_pairs:
            raise ValueError("the XY mixer needs xy_pairs")
        if self.mixer == "warm" and (self.warm_theta is None or len(self.warm_theta) != self.n):
            raise ValueError("the warm-start mixer needs one angle per qubit")
        self.cmin, self.cmax = float(self.cost.min()), float(self.cost.max())
        self.cn = (self.cost - self.cmin) / max(self.cmax - self.cmin, 1e-12) * 2 * np.pi   # phase scale
        if self.init is None:
            self.init = np.full(2 ** self.n, 2 ** (-self.n / 2), dtype=complex)
        self._order = np.argsort(self.cost, kind="stable")

    def state(self, params):
        p = len(params) // 2
        g, b = params[:p], params[p:]
        psi = self.init.copy()
        for l in range(p):
            psi = psi * np.exp(-1j * g[l] * self.cn)
            if self.mixer == "xy":
                for a, bq in self.xy_pairs:
                    psi = _apply_xy(psi, self.n, a, bq, b[l])
            elif self.mixer == "warm":
                for q in range(self.n):
                    th = self.warm_theta[q]
                    M = ry(th) @ rz(-2 * b[l]) @ ry(-th)
                    psi = _apply_1q(psi, self.n, q, M)
            else:
                U = rx(b[l])
                for q in range(self.n):
                    psi = _apply_1q(psi, self.n, q, U)
        return psi

    def probs(self, params):
        pr = np.abs(self.state(params)) ** 2
        return pr / pr.sum()

    def objective(self, params):
        pr = self.probs(params)
        if self.alpha >= 1.0:
            return float(pr @ self.cost)
        order = self._order
        cs, ps = self.cost[order], pr[order]
        cum = np.cumsum(ps)
        k = min(int(np.searchsorted(cum, self.alpha)), len(cum) - 1)   # float rounding can leave cum[-1] < alpha
        w = ps.copy()
        w[k + 1:] = 0
        w[k] = self.alpha - (cum[k - 1] if k > 0 else 0.0)
        return float(w @ cs / self.alpha)

    def optimise(self, p, restarts=4, maxiter=200, seed=0, x0=None):
        """COBYLA with `restarts` starts.  x0 may be a good start for depth p, or the optimum of depth p-1
        (it is then interpolated to depth p, the INTERP strategy of Zhou et al.), so deeper circuits never
        start worse than the shallower optimum."""
        if p < 1 or restarts < 1:
            raise ValueError("p and restarts must be >= 1")
        rng = np.random.default_rng(seed)
        if x0 is not None and len(x0) == 2 * (p - 1) and p > 1:
            x0 = interp_params(x0, p)
        best = None
        for r in range(restarts):
            if x0 is not None and r == 0 and len(x0) == 2 * p:
                start = np.array(x0, dtype=float)
            else:
                # linear-ramp (annealing-like) initial guess + noise: far better than random for QAOA
                ramp = (np.arange(p) + 0.5) / p
                start = np.concatenate([0.6 * ramp, 0.6 * (1 - ramp)]) * rng.uniform(0.6, 1.4) + rng.normal(0, 0.05, 2 * p)
            res = minimize(self.objective, start, method="COBYLA", options={"maxiter": maxiter, "rhobeg": 0.3})
            if best is None or res.fun < best.fun:
                best = res
        return best.x, float(best.fun)


def interp_params(params, p_new):
    """INTERP: linearly interpolate (gamma, beta) of a depth-p QAOA to depth p_new."""
    params = np.asarray(params, dtype=float)
    p = len(params) // 2
    g, b = params[:p], params[p:]
    if p == p_new:
        return params.copy()
    xs_old = (np.arange(p) + 0.5) / p
    xs_new = (np.arange(p_new) + 0.5) / p_new
    return np.concatenate([np.interp(xs_new, xs_old, g), np.interp(xs_new, xs_old, b)])


# ------------------------------------------------------------------ metrics
def stats(pr, cost, feasible=None, ground=None):
    """P(optimal), mean cost, P(better than median), expected shots to see the optimum (99 %)."""
    g = cost.min() if ground is None else ground
    p_opt = float(pr[np.isclose(cost, g)].sum())
    shots = float(np.log(0.01) / np.log1p(-p_opt)) if 0 < p_opt < 1 - 1e-12 else (1.0 if p_opt > 0 else float("inf"))
    return {"p_opt": p_opt, "mean": float(pr @ cost), "best_sampled_gap": float(cost[pr > 1e-9].min() - g),
            "shots99": shots}


def uniform_baseline(cost, ground=None):
    g = cost.min() if ground is None else ground
    return float(np.isclose(cost, g).mean())


def warm_params(x_star, eps=0.15):
    if not 0.0 <= eps <= 0.5:
        raise ValueError("warm-start eps must be in [0, 0.5]")
    c = np.clip(np.asarray(x_star, dtype=float), eps, 1 - eps)
    return 2 * np.arcsin(np.sqrt(c))


def warm_init(x_star, eps=0.15):
    th = warm_params(x_star, eps)
    psi = np.array([1.0 + 0j])
    for q in range(len(th)):                         # qubit q is least significant for q=0 -> kron order reversed
        v = ry(th[q]) @ np.array([1, 0])
        psi = np.kron(v, psi)
    return psi, th


def solve_qubo(q: Qubo, p=2, mode="qaoa", alpha=1.0, warm_x=None, eps=0.15, restarts=4, maxiter=200, seed=0):
    """Run one flavour of QAOA on a (small) QUBO; returns best sampled bitstring, probs, details."""
    X = all_bits(q.n)
    cost = q.energy(X)
    if mode == "warm":
        init, th = warm_init(warm_x, eps)
        algo = QAOA(cost, q.n, "warm", init, warm_theta=th, alpha=alpha)
    else:
        algo = QAOA(cost, q.n, "x", None, alpha=alpha)
    params, val = algo.optimise(p, restarts, maxiter, seed)
    pr = algo.probs(params)
    return X, cost, pr, params, algo
