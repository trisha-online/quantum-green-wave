"""QUBO container + helpers (dense, symmetric, zero diagonal):  cost = const + lin.x + sum_{i<j} J_ij x_i x_j"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from qiskit_optimization import QuadraticProgram


def all_bits(n: int) -> np.ndarray:
    """All 2^n bit strings, bit i of the row index = variable i (Qiskit little-endian convention)."""
    k = np.arange(2 ** n)[:, None]
    return ((k >> np.arange(n)) & 1).astype(np.int8)


@dataclass
class Qubo:
    const: float
    lin: np.ndarray
    J: np.ndarray

    @property
    def n(self) -> int:
        return len(self.lin)

    def energy(self, X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(np.asarray(X, dtype=float))
        return self.const + X @ self.lin + 0.5 * np.einsum("bi,ij,bj->b", X, self.J, X)

    def delta_flip(self, x: np.ndarray, i: int) -> float:
        d = 1.0 - 2.0 * x[i]
        return d * (self.lin[i] + self.J[i] @ x)

    def restrict(self, block, x_full) -> "Qubo":
        """Freeze every variable outside `block` at x_full -> smaller QUBO over `block`."""
        block = list(block)
        inb = np.zeros(self.n, dtype=bool)
        inb[block] = True
        out = np.where(~inb)[0]
        x_out = np.asarray(x_full, dtype=float)[out]
        const = self.const + self.lin[out] @ x_out + 0.5 * x_out @ self.J[np.ix_(out, out)] @ x_out
        lin = self.lin[block] + self.J[np.ix_(block, out)] @ x_out
        return Qubo(float(const), lin, self.J[np.ix_(block, block)].copy())

    def to_quadratic_program(self, name: str = "qubo") -> QuadraticProgram:
        qp = QuadraticProgram(name)
        for i in range(self.n):
            qp.binary_var(f"x{i}")
        quad = {(i, j): float(self.J[i, j]) for i in range(self.n) for j in range(i + 1, self.n) if self.J[i, j] != 0}
        qp.minimize(constant=float(self.const), linear=[float(v) for v in self.lin], quadratic=quad)
        return qp

    def interaction_graph(self) -> list:
        return [np.nonzero(self.J[i])[0].tolist() for i in range(self.n)]
