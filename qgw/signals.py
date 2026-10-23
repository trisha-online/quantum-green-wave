"""
The signal-timing problem as a QUBO (this is the main 'quantum' problem).

Cost of a plan x[n,t] (x=1: EW green, x=0: NS green)

  1. delay      q_ns[n,t]*x + q_ew[n,t]*(1-x)             vehicles stuck on red
  2. platoon    EW: f*x[n,t]*(1-x[m,t+1])  NS: f*(1-x[n,t])*x[m,t+1]
                a platoon released at n in slot t reaches neighbour m in slot t+1 and is stopped if m is red
  3. switching  s*(x[n,t] XOR x[n,t+1])                    lost time when a light changes
  4. emergency  W*severity*p*[phase != axis needed]        ambulance preemption requests (expected
                                                            over +-1 slot arrival uncertainty)
  5. fairness   mu*(sum_t x[n,t] - T/2)^2                  stops one axis being starved over the horizon

All five terms are linear or quadratic in the binary variables, so the whole problem is an
UNCONSTRAINED QUBO on N*T qubits.  breakdown() evaluates the same cost directly (no QUBO algebra),
which the tests use to prove that the QUBO is correct.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .city import City
from .qubo import Qubo


@dataclass
class SignalProblem:
    city: City
    requests: list = field(default_factory=list)   # [(node, slot, axis, weight)]
    s_switch: float = 3.0
    mu_fair: float = 2.0

    # ----------------------------------------------------------------- derived quantities
    def platoon(self, n: int, t: int, axis: str) -> float:
        q = self.city.q_ew if axis == "ew" else self.city.q_ns
        return float(np.round(self.city.share * q[n, t]))

    def links(self):
        """ordered neighbour pairs (n, m, axis)."""
        for n in range(self.city.N):
            for m, axis in self.city.neighbours(n):
                yield n, m, axis

    # ----------------------------------------------------------------- QUBO
    def to_qubo(self) -> Qubo:
        c, T = self.city, self.city.T
        nv = c.nvars
        lin = np.zeros(nv)
        J = np.zeros((nv, nv))
        const = 0.0

        def add_pair(i, j, w):
            J[i, j] += w
            J[j, i] += w

        for n in range(c.N):
            for t in range(T):
                v = c.var(n, t)
                const += c.q_ew[n, t]
                lin[v] += c.q_ns[n, t] - c.q_ew[n, t]
        for n, m, axis in self.links():
            for t in range(T - 1):
                f = self.platoon(n, t, axis)
                if f == 0:
                    continue
                if axis == "ew":                      # f * x[n,t] * (1 - x[m,t+1])
                    lin[c.var(n, t)] += f
                    add_pair(c.var(n, t), c.var(m, t + 1), -f)
                else:                                 # f * (1 - x[n,t]) * x[m,t+1]
                    lin[c.var(m, t + 1)] += f
                    add_pair(c.var(n, t), c.var(m, t + 1), -f)
        for n in range(c.N):
            for t in range(T - 1):
                a, b = c.var(n, t), c.var(n, t + 1)
                lin[a] += self.s_switch
                lin[b] += self.s_switch
                add_pair(a, b, -2 * self.s_switch)
        for n, t, axis, w in self.requests:
            v = c.var(n, t)
            if axis == "ew":                          # need x=1: penalty w*(1-x)
                const += w
                lin[v] -= w
            else:                                     # need x=0: penalty w*x
                lin[v] += w
        mu = self.mu_fair
        for n in range(c.N):
            const += mu * T * T / 4.0
            for t in range(T):
                lin[c.var(n, t)] += mu * (1 - T)
                for u in range(t + 1, T):
                    add_pair(c.var(n, t), c.var(n, u), 2 * mu)
        return Qubo(float(const), lin, J)

    # ----------------------------------------------------------------- direct evaluation
    def grid(self, x) -> np.ndarray:
        return np.asarray(x).reshape(self.city.N, self.city.T)

    def breakdown(self, x) -> dict:
        c, T = self.city, self.city.T
        X = self.grid(x).astype(float)
        delay = float(np.sum(c.q_ns * X + c.q_ew * (1 - X)))
        platoon = 0.0
        for n, m, axis in self.links():
            for t in range(T - 1):
                f = self.platoon(n, t, axis)
                if axis == "ew":
                    platoon += f * X[n, t] * (1 - X[m, t + 1])
                else:
                    platoon += f * (1 - X[n, t]) * X[m, t + 1]
        switch = float(self.s_switch * np.sum(np.abs(np.diff(X, axis=1))))
        emergency = 0.0
        for n, t, axis, w in self.requests:
            emergency += w * ((1 - X[n, t]) if axis == "ew" else X[n, t])
        fairness = float(self.mu_fair * np.sum((X.sum(axis=1) - T / 2.0) ** 2))
        total = delay + platoon + switch + emergency + fairness
        return {"delay": delay, "platoon": float(platoon), "switch": switch, "emergency": float(emergency),
                "fairness": fairness, "total": float(total)}

    def cost(self, x) -> float:
        return self.breakdown(x)["total"]
