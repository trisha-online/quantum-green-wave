"""Regression tests for the bugs fixed in the audit (one test per bug)."""
import numpy as np
import pytest

from qgw.city import AMB_BLOCK_S, City, make_city, make_emergencies
from qgw.classical import exact_milp, simulated_annealing
from qgw.decompose import block_descent, route_windows
from qgw.dispatch import DispatchProblem
from qgw.qalgos import QAOA, interp_params, stats
from qgw.qubo import Qubo, all_bits


def rand_qubo(n, seed):
    rng = np.random.default_rng(seed)
    J = np.triu(rng.normal(size=(n, n)), 1); J = J + J.T
    return Qubo(0.0, rng.normal(size=n), J)


# ---------------------------------------------------------------- ambulance timing
def test_crossing_slots_follow_ambulance_speed():
    city = make_city(4, 4, 6, seed=0)
    assert city.block_s == AMB_BLOCK_S == 9.0
    # crossings at 9, 18, 27, 36, 45, 54 s -> slots 0, 1, 1, 2, 2, 3
    assert [city.crossing_slot(j) for j in range(6)] == [0, 1, 1, 2, 2, 3]
    # with one block per slot the old behaviour (slot j) is recovered
    old = City(4, 4, 6, 15.0, city.q_ew, city.q_ns, block_s=15.0)
    assert [old.crossing_slot(j) for j in range(6)] == list(range(6))


def test_requests_use_crossing_slots_and_conserve_weight():
    city = make_city(4, 4, 6, seed=0)
    route = [(0, 1), (1, 1), (2, 1), (3, 1), (3, 2)]
    reqs = city.requests_for_route(route, severity=2, base_weight=30.0)
    nominal = {(n, t) for n, t, _ in city.route_crossings(route)}
    assert nominal == {(city.node(1, 1), 0), (city.node(2, 1), 1), (city.node(3, 1), 1), (city.node(3, 2), 2)}
    # each crossing inside the horizon carries 60 in total, minus the part of the spread before slot 0
    assert sum(w for *_, w in reqs) == pytest.approx(60 * 4 - 60 * 0.2)
    assert {ax for *_, ax, _ in reqs} == {"ew", "ns"}


def test_bad_route_and_inputs_are_rejected():
    city = make_city(4, 4, 6, seed=0)
    with pytest.raises(ValueError):
        city.requests_for_route([(0, 0), (2, 0)], 1, 30.0)          # jumps two blocks
    with pytest.raises(ValueError):
        city.shortest_path((0, 0), (4, 0))                          # off the grid
    with pytest.raises(ValueError):
        city.requests_for_route([(0, 0), (1, 0)], 1, 30.0, spread={0: 0.5})
    with pytest.raises(ValueError):
        make_emergencies(city, 9)                                    # 18 distinct nodes on a 16-node grid
    with pytest.raises(ValueError):
        City(2, 2, 3, 15.0, np.zeros((4, 2)), np.zeros((4, 3)))


# ---------------------------------------------------------------- classical solvers
def test_sa_never_returns_worse_than_its_start():
    q = rand_qubo(12, 4)
    X = all_bits(12); E = q.energy(X)
    x0 = X[np.argmin(E)]                      # start AT the optimum; zero steps must keep it
    x, e = simulated_annealing(q, steps=0, restarts=1, x0=x0)
    assert e == pytest.approx(E.min()) and (x == x0).all()
    x, e = simulated_annealing(q, steps=200, restarts=3, seed=1, x0=x0)
    assert e == pytest.approx(E.min())
    assert e == pytest.approx(q.energy(x)[0])  # energy is recomputed, no accumulated drift


def test_milp_handles_qubo_without_couplings():
    q = Qubo(1.0, np.array([1.0, -2.0, 0.5]), np.zeros((3, 3)))
    x, e, info = exact_milp(q)
    assert x.tolist() == [0, 1, 0] and e == pytest.approx(-1.0) and info["optimal"]


# ---------------------------------------------------------------- QAOA
def test_cvar_objective_is_robust_to_rounding():
    q = rand_qubo(4, 0)
    cost = q.energy(all_bits(4))
    for a in (1e-6, 0.1, 0.5, 0.999999999):
        v = QAOA(cost, 4, alpha=a).objective(np.array([0.2, 0.3]))
        assert np.isfinite(v) and cost.min() - 1e-9 <= v <= cost.max() + 1e-9
    with pytest.raises(ValueError):
        QAOA(cost, 4, alpha=0.0)


def test_interp_start_is_never_worse_than_shallower_optimum():
    q = rand_qubo(6, 2)
    cost = q.energy(all_bits(6))
    algo = QAOA(cost, 6)
    p1, f1 = algo.optimise(1, restarts=2, maxiter=80, seed=0)
    start = interp_params(p1, 2)
    assert len(start) == 4
    p2, f2 = algo.optimise(2, restarts=1, maxiter=80, seed=0, x0=p1)
    assert f2 <= algo.objective(start) + 1e-9


def test_stats_handles_certain_optimum():
    cost = np.array([0.0, 1.0, 2.0, 3.0])
    s = stats(np.array([1.0, 0, 0, 0]), cost)
    assert s["shots99"] == 1.0 and s["p_opt"] == 1.0


# ---------------------------------------------------------------- decomposition / dispatch
def test_route_windows_cover_the_incident_node():
    city = make_city(4, 4, 6, seed=0)
    route = [(0, 0), (1, 0), (2, 0)]
    wins = route_windows(city, [route])
    covered = {city.unvar(v)[0] for w in wins for v in w}
    assert city.node(2, 0) in covered and city.node(1, 0) in covered


def test_block_descent_never_gets_worse_and_rejects_bad_start():
    q = rand_qubo(10, 7)
    x0 = np.zeros(10, dtype=np.int8)
    x, e, trace = block_descent(q, x0, [[0, 1, 2, 3, 4], [5, 6, 7, 8, 9], [2, 3, 7]], "random", sweeps=2, shots=8)
    assert all(a >= b - 1e-12 for a, b in zip(trace, trace[1:])) and e == pytest.approx(q.energy(x)[0])
    with pytest.raises(ValueError):
        block_descent(q, np.zeros(9), [[0, 1]])


def test_dispatch_requires_square_assignment():
    with pytest.raises(ValueError):
        DispatchProblem(np.ones((3, 2)), np.ones(2), 3, 2)
