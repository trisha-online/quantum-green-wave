"""The website must say exactly what the results say, and its interactive grid must compute the model's energy."""
import os
import re
from html.parser import HTMLParser

import numpy as np
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SITE = os.path.join(ROOT, "web", "site", "index.html")
RESULTS = os.path.join(ROOT, "results")

needs_results = pytest.mark.skipif(not os.path.exists(os.path.join(RESULTS, "part_sumo.json")), reason="run the pipeline first")


class Bound(HTMLParser):
    """collects (key, text) for every data-q element and (key, --bar) for every data-qbar element."""
    def __init__(self):
        super().__init__()
        self.stack, self.q, self.bars = [], [], []

    VOID = {"br", "img", "input", "meta", "link", "hr", "source", "area", "base", "col", "embed", "wbr"}

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        a = dict(attrs)
        if "data-qbar" in a:
            m = re.search(r"--bar:\s*([^;]+)", a.get("style", ""))
            self.bars.append((a["data-qbar"], m.group(1).strip() if m else None))
        self.stack.append([a.get("data-q"), ""])

    def handle_endtag(self, tag):
        while self.stack:
            key, text = self.stack.pop()
            if key:
                self.q.append((key, text.strip()))
            if self.stack:
                self.stack[-1][1] += text
            break

    def handle_data(self, data):
        if self.stack:
            self.stack[-1][1] += data


def parse():
    p = Bound()
    with open(SITE, encoding="utf-8") as f:
        p.feed(f.read())
    return p


@needs_results
def test_every_number_on_the_site_matches_the_results():
    from qgw.site import numbers
    t = numbers(RESULTS)
    p = parse()
    assert len(p.q) >= 60
    wrong = [(k, shown, t.get(k)) for k, shown in p.q if t.get(k) != shown]
    assert not wrong, f"site text differs from results (key, shown, expected): {wrong}"
    wrong_bars = [(k, shown, t.get(k)) for k, shown in p.bars if t.get(k) != shown]
    assert not wrong_bars, wrong_bars


@needs_results
def test_site_grid_energy_equals_the_qubo():
    """the page sums const + lin + pairs; that must equal Qubo.energy for the optimum and for flipped plans."""
    from qgw.site import payload
    from qgw.pipeline import scenario
    g = payload(RESULTS)["grid"]
    q = scenario(0)["prob"].to_qubo()

    def page_energy(x):
        return g["const"] + sum(l for l, v in zip(g["lin"], x) if v) + sum(w for i, j, w in g["pairs"] if x[i] and x[j])

    x = list(g["plan"])
    assert page_energy(x) == pytest.approx(g["optimum"]) == pytest.approx(q.energy(np.array(x))[0])
    rng = np.random.default_rng(0)
    for _ in range(20):
        y = list(x)
        for i in rng.choice(len(y), 3, replace=False):
            y[i] = 1 - y[i]
        assert page_energy(y) == pytest.approx(q.energy(np.array(y))[0])
        assert page_energy(y) >= g["optimum"] - 1e-9      # nothing beats the proved optimum


def test_bloch_sphere_uses_the_standard_convention():
    """|0> is the north pole (+Z).  The Manus page had it at the bottom."""
    with open(SITE, encoding="utf-8") as f:
        html = f.read()
    assert ".ket--zero { top:" in html and ".ket--one { bottom:" in html
    assert "north pole is |0⟩" in html


@needs_results
def test_dispatch_matrix_is_the_model_dispatch():
    from qgw.site import payload
    from qgw.pipeline import scenario
    d = payload(RESULTS)["dispatch"]
    disp = scenario(0)["disp"]
    assert np.allclose(d["cost"], disp.tau * disp.w[None, :])
    perm, cost = disp.brute_force()
    assert d["opt_perm"] == perm and d["opt_cost"] == pytest.approx(cost)
    assert sorted(d["opt_perm"]) == list(range(len(perm)))          # one-hot: every incident served once


@needs_results
def test_replay_tracks_are_the_sumo_traces_downsampled():
    """the street replay must show the recorded SUMO run: same vehicles, same start and end points, same arrival times."""
    import json
    from qgw.site import replay
    with open(os.path.join(RESULTS, "part_traces.json"), encoding="utf-8") as f:
        raw = json.load(f)
    r = replay(RESULTS)
    assert len(r["cities"]) == len(raw)
    for c, e in zip(r["cities"], raw):
        for name, run in e["runs"].items():
            got = c["runs"][name]
            assert got["amb_times"] == run["amb_times"] and got["civ_wait"] == pytest.approx(run["civ_wait"])
            assert len(got["tracks"]) == len(run["tracks"])
            assert sum(t[0] for t in got["tracks"]) == len(run["amb_times"])      # every ambulance is drawn
            for tr, src in zip(got["tracks"], run["tracks"].values()):
                p, n = src["p"], len(src["p"]) // 2
                assert tr[:3] == [src["a"], src["t0"], n]
                assert tr[3:5] == p[:2] and tr[-2:] == p[-2:]                       # first and last sample kept
        assert set(c["plans"]) == set(e["runs"])


@needs_results
def test_site_handles_quick_results(tmp_path):
    """Regression: QUICK runs skip the noisy p=2 hardware run and simulate only 2 SUMO cities; the export crashed
    on the first and would have left City 3's old numbers on the page for the second."""
    import json
    import shutil
    from qgw.site import numbers
    for f in os.listdir(RESULTS):
        shutil.copy(os.path.join(RESULTS, f), tmp_path / f)
    hw = json.loads((tmp_path / "part_hardware.json").read_text(encoding="utf-8"))
    for r in hw["rows"]:
        if r["p"] > 1:
            r.pop("noisy_p_opt", None)
    (tmp_path / "part_hardware.json").write_text(json.dumps(hw), encoding="utf-8")
    sumo = json.loads((tmp_path / "part_sumo.json").read_text(encoding="utf-8"))
    sumo["scenarios"] = sumo["scenarios"][:2]
    (tmp_path / "part_sumo.json").write_text(json.dumps(sumo), encoding="utf-8")
    t = numbers(str(tmp_path))
    assert t["hw_p2_noisy"] == "not run noisy" and t["hw_p2_ratio"] == "noisy run skipped"
    assert t["sumo_cities"] == "2" and "sumo3_amb_opt" not in t
    with open(SITE, encoding="utf-8") as f:
        html = f.read()
    assert all(f'<tr data-city="{k}">' in html for k in (1, 2, 3))     # rows the page can hide
