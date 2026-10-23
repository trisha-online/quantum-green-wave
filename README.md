# Quantum Green Wave

Quantum optimisation for emergency vehicles in a smart city (Qiskit hackathon track *Quantum Optimization for Smart Cities*).

**Problem.** Choose which ambulance serves which incident, then set the phase (east-west or north-south green) of every traffic light on a 4x4 grid for six 15-second slots so ambulances meet green lights, without making ordinary traffic worse.

**Formulation.**
* Signal timing: 16 intersections x 6 slots = **96 binary variables**, one unconstrained QUBO with five terms: queue delay, platoon stops between neighbours, lost time when a light switches, ambulance preemption requests (weighted by severity, spread over +-1 slot of arrival uncertainty), and a fairness term.
* Dispatch: ambulances x incidents = up to 16 qubits, a constrained assignment problem.

**Quantum / hybrid methods** (`qgw/`)
| file | what |
|---|---|
| `signals.py` | the 96-variable QUBO and a direct cost function used to test it |
| `dispatch.py` | assignment QUBO; XY-mixer QAOA from a Dicke start (each ambulance gets exactly one incident by construction) vs penalty-only QAOA |
| `qalgos.py` | fast statevector QAOA, CVaR-QAOA, warm-start QAOA (eps-regularised) |
| `decompose.py` | window decomposition: freeze everything except a <=12-qubit window, solve it, write back only if the plan does not get worse |
| `classical.py` | fixed-time, queue-actuated, rule-based preemption, exact MILP (HiGHS), simulated annealing |
| `sumo_eval.py` | closed-loop check in the SUMO traffic simulator |
| `hardware.py`, `run_on_ibm.py` | circuits, transpiled 2-qubit gate counts on a real IBM heavy-hex layout, noisy simulation; `run_on_ibm.py` is untested |
| `pipeline.py`, `export.py` | all experiments, and the data files for the dashboard and the website |
| `site.py` | every number the website shows, the exact QUBO for its plan explorer, the dispatch matrix and the SUMO replay tracks |

**Team Voyager.**

## Run it
Python 3.10 or newer. `pip install` also installs the SUMO traffic simulator (`eclipse-sumo`).
```
pip install -r requirements.txt
python -m pytest -q                 # 33 tests, about a minute (3 run SUMO)
python -m qgw.pipeline              # all experiments (~25 min); parts: dispatch signals windows uncertainty hardware sumo traces
python -m qgw.export                # results -> web/data.js and web/site/site-data.js
python web/build_single.py          # -> web/site/dist/index.html (website) and web/dist/index.html (dashboard)
```
Options are environment variables: `QUICK=1` runs a small version of every part (a few minutes),
`QGW_RESULTS=<folder>` writes results elsewhere, `QGW_MU=<w>` changes the fairness weight. The fairness stress test is
`QGW_MU=24 QGW_RESULTS=results_mu24 python -m qgw.pipeline signals sumo`. In Windows PowerShell set them first,
for example `$env:QUICK=1` then `python -m qgw.pipeline` (and `Remove-Item Env:QUICK` afterwards).

`results/` holds the committed results, so the pages can be rebuilt without re-running the experiments.
See `AUDIT.md` for every bug fixed in the audits.

## The pages
Both are single self-contained files (they need internet only for the fonts):
* **`web/site/dist/index.html`**: the website. Every number on it is filled from the model's results (a test checks the page text against them), the plan explorer computes the exact QUBO energy as you flip qubits, the dispatch matrix is the model's, and the street replay plays the recorded SUMO runs.
* **`web/dist/index.html`**: the full evidence dashboard.

Open either file directly, or preview the website with `node web/site/server.js` (http://localhost:3000).
Edit `web/site/index.html` (website) or `web/index.html` + `web/app.js` (dashboard), never the files in `dist/`,
which `build_single.py` overwrites. After changing the model, re-run the pipeline, then export and build.

## Deploy
* **GitHub Pages:** push to `main`, then in the repository go to Settings → Pages → Build and deployment →
  Source: **GitHub Actions**. `.github/workflows/pages.yml` publishes the website at the site root and the
  dashboard at `/dashboard/`.
* **Netlify:** "Add new site" → import the repository; `netlify.toml` already points it at `web/site/dist`.
  Or drag the `web/site/dist` folder onto app.netlify.com/drop.
* `.github/workflows/tests.yml` runs the test suite and rebuilds the pages on every push.

## Repository layout
| path | what |
|---|---|
| `qgw/` | the model, solvers, SUMO evaluation, experiments and export |
| `tests/` | correctness, regression, SUMO and website tests |
| `results/`, `results_mu24/` | experiment results (main run, fairness stress test) |
| `sumo_assets/` | the SUMO network (4x4 grid, 150 m blocks) |
| `web/site/` | the website source; `web/site/dist/` the built page |
| `web/` | the dashboard source; `web/dist/` the built page |
| `run_on_ibm.py` | runs one window on IBM hardware (needs an IBM Quantum account; untested) |
| `docs/` | the presentation (`Quantum_Green_Wave_Final.pptx`) and the website's design notes |
| `AUDIT.md` | every bug found and fixed, and how the results changed |

## Results (and what they do not show)
* The QUBO is checked against a direct cost function on random plans (`tests/test_core.py`); the numpy QAOA is checked against Qiskit circuits (`tests/test_quantum.py`); the model's ambulance speed (9 s per 150 m block) is checked against SUMO (`tests/test_sumo.py`).
* 12-qubit windows (4096 plans each, 10 windows): QAOA p=2 measures the best plan ~32% of the time (~1190x a blind guess) and p=3 ~40% (~1500x); each depth starts from the previous depth's angles (INTERP). Warm-start p=2 ~41% (~1570x), but it starts from the rule-based plan, which is already in the top ~1% of each window, so part of that is inherited. CVaR-QAOA (alpha=0.1) optimises a different target and lands lower (11-14%).
* Dispatch (16 qubits, 4 ambulances): the XY mixer returns a valid assignment 40% of the time against 4% for penalties only.
* Hybrid loop: exact window search, QAOA, CVaR-QAOA and warm-start all reach the exact optimum (1593) on the main city; random sampling of the same windows stops short (1606 to 1627).
* **No quantum advantage is claimed.** HiGHS proves the optimum of the full 96-variable problem in well under a second. The point is a correct formulation and a working hybrid loop that the same code can run on hardware.
* SUMO check (3 cities x 3 simulator seeds, every plan simulated for the same 160 s). Severity-weighted mean ambulance time, optimised vs rule-based preemption: City 1 **51.9 s vs 41.7 s** (worse), City 2 **22.2 s vs 26.3 s** (better), City 3 **18.5 s vs 18.5 s** (equal). Mean wait of other vehicles is lower under the optimised plan than under rule-based preemption in all three cities (34.8 vs 41.2 s, 39.1 vs 49.1 s, 36.0 vs 39.1 s), and lower than fixed-time in Cities 1 and 2 (City 3: 36.0 vs 35.1 s). A lower QUBO cost does not guarantee a lower simulated delay.
* Fairness weight: fixed at 2 before the experiments. A sweep on separate cities (seeds 10 to 12) favoured weight 24 on both ambulance time (18.3 vs 23.2 s) and other traffic (37.6 vs 38.0 s), but on the three reported cities weight 24 made the optimised plan slower than rule-based preemption in 2 of 3 (results in `results_mu24/`). Three cities are too few to pick a weight, so it stays at 2.
* Arrival uncertainty (model only, 6 cities x 1000 draws): planning for +-1 slot cuts severity-weighted missed greens from 1.35 to 0.58 per draw on average.
* Noisy simulation of one 12-qubit window on the Sherbrooke calibration: P(best plan) drops from ~27% to ~2% at p=2, still ~90x a blind guess; p=3 (ideal ~38%) was not run noisy.
* The city is synthetic; map download was blocked in the build environment, so no OpenStreetMap data is used. Planning is open-loop over one 90 s horizon.

SUMO runs of the "MILP" plan use a 60 s solver limit; at the default weights the optimum is proved in well under a second. With weight 24 the problem is harder and HiGHS does not always finish in the limit, so in `results_mu24/` the "MILP" plan is the best found, not a proved optimum.
