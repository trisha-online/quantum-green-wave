import numpy as np
import pytest

pytest.importorskip("traci")


def test_sumo_runs_and_ambulances_arrive():
    from qgw.classical import fixed_time
    from qgw.pipeline import scenario
    from qgw.sumo_eval import evaluate_plans
    S = scenario(1)
    r = evaluate_plans(S["city"], {"f": fixed_time(S["prob"])}, S["routes"], S["sev"], seeds=(0,))["f"][0]
    assert r["unfinished"] == 0 and all(t > 0 for t in r["amb_times"])
    assert r["n_civ"] > 0 and r["civ_wait_mean"] >= 0 and r["window_s"] == 160
    w = np.array(S["sev"], float)
    assert r["amb_wmean"] == pytest.approx(np.dot(w, r["amb_times"]) / w.sum())


def test_sumo_measures_every_plan_over_the_same_window():
    """Regression: the old loop stopped as soon as the ambulances arrived, so a plan whose ambulances were
    fast was measured over a shorter window and looked better for civilians.  Now the window is fixed, the
    run is deterministic for a given seed, and ending early is impossible."""
    from qgw.classical import fixed_time, rule_preempt
    from qgw.pipeline import scenario
    from qgw.sumo_eval import evaluate_plans
    S = scenario(1)
    plans = {"fixed": fixed_time(S["prob"]), "rule": rule_preempt(S["prob"]), "fixed2": fixed_time(S["prob"])}
    r = evaluate_plans(S["city"], plans, S["routes"], S["sev"], seeds=(0,))
    assert r["fixed"][0]["civ_wait_total"] == r["fixed2"][0]["civ_wait_total"]   # deterministic
    assert {m[0]["window_s"] for m in r.values()} == {160}


def test_free_flow_ambulance_matches_model_block_time():
    """The model assumes AMB_BLOCK_S seconds per block; check that against SUMO with no traffic and green lights."""
    from qgw.city import AMB_BLOCK_S
    from qgw.pipeline import scenario
    from qgw.sumo_eval import SumoCity
    S = scenario(0)
    city = S["city"]
    route = [(0, 1), (1, 1), (2, 1), (3, 1)]
    X = np.ones((city.N, city.T), dtype=np.int8)        # every light EW green
    sim = SumoCity(city, seed=0, rate_scale=0.0).start(label="freeflow")
    try:
        r = sim.run(X, [route], [1])
    finally:
        sim.close()
    per_block = r["amb_times"][0] / 3
    assert per_block <= AMB_BLOCK_S and per_block >= AMB_BLOCK_S - 2.0
