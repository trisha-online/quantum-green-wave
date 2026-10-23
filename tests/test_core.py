import numpy as np
import pytest

from qgw.city import make_city, make_emergencies
from qgw.classical import actuated, exact_milp, fixed_time, rule_preempt, simulated_annealing
from qgw.signals import SignalProblem


def problem(seed=0, nx=3, ny=3, T=4):
    city = make_city(nx, ny, T, seed=seed)
    ambs, incs = make_emergencies(city, 2, seed)
    reqs = []
    for a, i in zip(ambs, incs):
        route = city.shortest_path(a.station, i.node)
        reqs += city.requests_for_route(route, i.severity, 30.0)
    return SignalProblem(city, reqs)


@pytest.mark.parametrize("seed", range(5))
def test_qubo_equals_direct_cost(seed):
    p = problem(seed)
    q = p.to_qubo()
    rng = np.random.default_rng(seed)
    for _ in range(30):
        x = rng.integers(0, 2, q.n)
        assert q.energy(x)[0] == pytest.approx(p.cost(x))


def test_restrict_matches_full():
    p = problem(1)
    q = p.to_qubo()
    rng = np.random.default_rng(0)
    x = rng.integers(0, 2, q.n)
    block = [3, 4, 9, 10, 11]
    sub = q.restrict(block, x)
    for _ in range(10):
        y = x.copy()
        y[block] = rng.integers(0, 2, len(block))
        assert sub.energy(y[block])[0] == pytest.approx(q.energy(y)[0])


def test_milp_is_exact_on_small_instance():
    city = make_city(2, 2, 3, seed=2)
    p = SignalProblem(city, [])
    q = p.to_qubo()
    from qgw.qubo import all_bits
    X = all_bits(q.n)
    best = q.energy(X).min()
    x, e, info = exact_milp(q)
    assert e == pytest.approx(best) and info["optimal"]


def test_heuristics_are_worse_or_equal_than_exact():
    p = problem(3)
    q = p.to_qubo()
    x, e, info = exact_milp(q, time_limit=60)
    assert info["optimal"]
    for h in (fixed_time, actuated, rule_preempt):
        assert p.cost(h(p)) >= e - 1e-6
    xs, es = simulated_annealing(q, steps=8000, restarts=2)
    assert es >= e - 1e-6
