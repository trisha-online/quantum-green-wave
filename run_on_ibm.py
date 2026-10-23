"""
Run ONE 12-qubit window of the signal problem on real IBM hardware.  NOT TESTED (needs an IBM Quantum account).

    pip install qiskit-ibm-runtime
    export QISKIT_IBM_TOKEN=...      # from quantum.ibm.com
    python run_on_ibm.py --backend ibm_brisbane --shots 4000

The window is solved classically first to get circuit angles (qgw.qalgos), then sampled on the device.
We then compare P(best plan) on hardware to a blind guess (1/4096).
"""
import argparse

import numpy as np

from qgw.classical import rule_preempt
from qgw.decompose import adjacent_windows
from qgw.hardware import window_circuit
from qgw.pipeline import scenario
from qgw.qalgos import QAOA
from qgw.qubo import all_bits

ap = argparse.ArgumentParser()
ap.add_argument("--backend", default=None)
ap.add_argument("--shots", type=int, default=4000)
ap.add_argument("--p", type=int, default=1)
a = ap.parse_args()

from qiskit import transpile
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2

S = scenario(0)
q = S["prob"].to_qubo()
w = adjacent_windows(S["city"])[5]
sub = q.restrict(w, rule_preempt(S["prob"]))
cost = sub.energy(all_bits(sub.n))
params, _ = QAOA(cost, sub.n).optimise(a.p, restarts=3, maxiter=150, seed=3)
qc = window_circuit(sub, params, measure=True)
svc = QiskitRuntimeService()
be = svc.backend(a.backend) if a.backend else svc.least_busy(operational=True, simulator=False, min_num_qubits=sub.n)
tqc = transpile(qc, be, optimization_level=3)
res = SamplerV2(mode=be).run([tqc], shots=a.shots).result()[0]
counts = res.data.meas.get_counts()
pr = np.zeros(2 ** sub.n)
for bs, c in counts.items():
    pr[int(bs, 2)] += c
pr /= pr.sum()
best = np.isclose(cost, cost.min())
print(f"backend {be.name}: P(best plan) = {pr[best].sum():.4f}  (blind guess {best.mean():.4f})")
print(f"mean cost gap = {pr @ cost - cost.min():.1f}")
