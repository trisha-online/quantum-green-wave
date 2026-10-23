"""Hardware-facing analysis: explicit Qiskit circuits for a QAOA window, resource counts on a real IBM
heavy-hex topology, and noisy simulation from a real device's calibration data (no IBM account needed)."""
from __future__ import annotations

import numpy as np
from qiskit import QuantumCircuit, transpile

from .qubo import Qubo, all_bits


def ising_coeffs(q: Qubo):
    h = -q.lin / 2 - q.J.sum(1) / 4
    K = q.J / 4
    return h, K


def window_circuit(q: Qubo, params, measure=False) -> QuantumCircuit:
    """standard QAOA circuit (|+>, rz/rzz cost layer, rx mixer) whose statevector equals qalgos.QAOA.state."""
    n, p = q.n, len(params) // 2
    cost = q.energy(all_bits(n))
    scale = 2 * np.pi / max(cost.max() - cost.min(), 1e-12)
    h, K = ising_coeffs(q)
    qc = QuantumCircuit(n)
    qc.h(range(n))
    for l in range(p):
        g, b = params[l], params[p + l]
        for i in range(n):
            qc.rz(2 * g * scale * h[i], i)
        for i in range(n):
            for j in range(i + 1, n):
                if K[i, j] != 0:
                    qc.rzz(2 * g * scale * K[i, j], i, j)
        for i in range(n):
            qc.rx(2 * b, i)           # RX(2b) == exp(-i b X)
    if measure:
        qc.measure_all()
    return qc


def resources(qc: QuantumCircuit, backend=None, seed=0) -> dict:
    kw = dict(optimization_level=3, seed_transpiler=seed)
    t = transpile(qc, backend, **kw) if backend is not None else \
        transpile(qc, basis_gates=["cx", "rz", "sx", "x"], **kw)
    ops = t.count_ops()
    two = sum(v for k, v in ops.items() if k in ("cx", "ecr", "cz", "rzz"))
    return {"two_qubit": int(two), "depth": int(t.depth()), "qubits": int(qc.num_qubits)}


def noisy_probs(qc: QuantumCircuit, backend, shots=20000, seed=0):
    """noisy sampling on an AerSimulator built from the backend's calibration; returns probability vector."""
    from qiskit_aer import AerSimulator
    c = qc.copy(); c.measure_all()
    t = transpile(c, backend, optimization_level=3, seed_transpiler=seed)
    sim = AerSimulator.from_backend(backend)
    counts = sim.run(t, shots=shots, seed_simulator=seed).result().get_counts()
    pr = np.zeros(2 ** qc.num_qubits)
    for bs, cnt in counts.items():
        pr[int(bs.replace(" ", ""), 2)] += cnt
    return pr / pr.sum()
