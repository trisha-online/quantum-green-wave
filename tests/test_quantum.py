import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.circuit.library import XXPlusYYGate
from qiskit.quantum_info import Statevector

from qgw.city import make_city, make_emergencies
from qgw.dispatch import DispatchProblem
from qgw.qalgos import QAOA, _apply_xy, warm_init
from qgw.qubo import Qubo, all_bits


def rand_qubo(n, seed):
    rng = np.random.default_rng(seed)
    J = np.triu(rng.normal(size=(n, n)), 1); J = J + J.T
    return Qubo(0.0, rng.normal(size=n), J)


def test_x_qaoa_matches_qiskit():
    q = rand_qubo(4, 0)
    X = all_bits(4); cost = q.energy(X)
    algo = QAOA(cost, 4)
    params = np.array([0.3, -0.2, 0.5, 0.4])
    psi = algo.state(params)
    qc = QuantumCircuit(4); qc.h(range(4))
    cn = algo.cn
    for l in range(2):
        # diagonal phase exp(-i g cn[x]) as a global diagonal gate
        from qiskit.circuit.library import DiagonalGate
        qc.append(DiagonalGate(np.exp(-1j * params[l] * cn)), range(4))
        for k in range(4):
            qc.rx(2 * params[2 + l], k)
    ref = Statevector(qc).data
    assert abs(np.vdot(ref, psi)) == pytest.approx(1.0, abs=1e-9)


def test_xy_gate_matches_qiskit_and_conserves_hamming():
    n = 3
    psi = np.zeros(8, complex); psi[0b001] = 0.6; psi[0b010] = 0.8
    out = _apply_xy(psi, n, 0, 1, 0.37)
    qc = QuantumCircuit(3); qc.initialize(psi, range(3)); qc.append(XXPlusYYGate(2 * 0.37), [0, 1])
    ref = Statevector(qc).data
    assert abs(np.vdot(ref, out)) == pytest.approx(1.0, abs=1e-9)
    assert np.abs(out[[0b000, 0b011, 0b100, 0b101, 0b110, 0b111]]).sum() == pytest.approx(0)


def test_warm_start_state_is_biased_to_solution():
    psi, th = warm_init(np.array([1, 0, 1]), eps=0.1)
    pr = np.abs(psi) ** 2
    assert np.argmax(pr) == 0b101 and pr.sum() == pytest.approx(1)


def test_dispatch_xy_stays_feasible_in_rows():
    city = make_city(4, 4, 6, seed=0)
    ambs, incs = make_emergencies(city, 3, 0)
    d = DispatchProblem.from_city(city, ambs, incs)
    out = d.xy_qaoa(p=2, restarts=2, maxiter=60)
    # rows are exact => infeasibility can only come from columns
    assert 0 < out["p_feasible"] <= 1 and out["p_opt"] >= out["uniform_p_opt"]
    perm, c = d.brute_force()
    assert out["optimum"] == pytest.approx(c)


def test_window_circuit_matches_numpy_state():
    from qgw.hardware import window_circuit
    q = rand_qubo(5, 3)
    cost = q.energy(all_bits(5))
    algo = QAOA(cost, 5)
    params = np.array([0.4, 0.15, 0.35, 0.2])
    ref = Statevector(window_circuit(q, params)).data
    assert abs(np.vdot(ref, algo.state(params))) == pytest.approx(1.0, abs=1e-9)
