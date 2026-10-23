# Audit: data check and bug fixes

## 1. Data check (before any fix)

Every stored number in `results/` was recomputed from the code as shipped:

| check | result |
|---|---|
| MILP optimum, scenario 0 | 1593, proved optimal, same as stored |
| model cost of fixed / actuated / rule / MILP plans | 2423 / 1679 / 1734 / 1593, same as stored |
| stored baseline plans equal what the code generates | yes, all three |
| each hybrid run's stored cost equals the cost of its stored plan | yes, every run |
| hybrid traces never go up | yes |
| dispatch optimum and greedy assignment | same as stored |
| SUMO-table model costs and MILP costs for all 3 cities | same as stored |
| README figures (23% / 830x, 41% / 1500x, 40% vs 4%, ~90x noisy) | match the stored data |

So the stored files really did come from the code. The problems were in the code itself, and in two claims that
the data did not support:

* **The civilian-wait numbers in the SUMO table were measurement artefacts** (bug 1). Example: City 2,
  optimised plan, **10.4 s** in the table, but **44.6 s** when the same plan ran for the full window in `part_traces`.
* **The README said the fairness sweep "showed no clear winner".** The stored sweep had weight 24 best on *both*
  ambulance time and civilian wait.

## 2. Bugs fixed

| # | where | bug | effect | fix |
|---|---|---|---|---|
| 1 | `sumo_eval.run` | The simulation **stopped as soon as the ambulances arrived**, and civilian wait was read only from vehicles still in the network | Each plan was measured over a different window, and vehicles that had left were dropped, so plans with fast ambulances looked better for civilians | Every plan runs the same 160 s; waiting is counted every second for every civilian vehicle, including ones that have left |
| 2 | `sumo_eval.run` | Used `getAccumulatedWaitingTime`, which SUMO caps at a 100 s memory | Long waits under-counted | Replaced by per-second counting through speed subscriptions |
| 3 | `city.requests_for_route` | Assumed the ambulance covers **one block per 15 s slot**. In SUMO it takes ~8.5 s (measured) | From the 3rd intersection on, the plan put green in the wrong slot | `City.block_s = 9 s` (measured; checked by a test against SUMO); crossing slot = ceil((j+1)·9/15) − 1 |
| 4 | `sumo_eval._yellow` | No yellow phase on the switch from the warm-up program to slot 0 of the plan | Unrealistic instant switch, depending on the plan | One signal controller handles every switch, warm-up included |
| 5 | SUMO table / README | "Ambulance time (s)" was a **severity-weighted sum** (e.g. 299 s) shown as a time | Read like single trips of 3–5 minutes | New `amb_wmean` (weighted mean, in seconds) used for the table, sweep and README |
| 6 | `pipeline.part_uncertainty` | Monte-Carlo clamped out-of-horizon arrivals to slot 0 / T−1, while the QUBO drops them | Robustness test scored the plans on requests they were never given | Same rule as the QUBO: skip arrivals outside the horizon |
| 7 | `classical.simulated_annealing` | Best plan only updated on accepted moves; the start plan was never counted; `steps=0` crashed | Could return a plan worse than its own start; energy drift | Start counted as a candidate; energy recomputed exactly at the end |
| 8 | `classical.exact_milp` | Crashed (`res.x is None`) if HiGHS found no solution in the time limit; crashed on a QUBO with no couplings | Pipeline abort | Falls back to `x_start` or SA; `optimal` flag stays honest |
| 9 | `qalgos.QAOA.objective` (CVaR) | `searchsorted` could return an index past the end when float rounding left the cumulative sum just below alpha | IndexError | Index clipped |
| 10 | `qalgos.QAOA.optimise` | Each depth was optimised from scratch | p=3 ended **worse** than p=2 (19.7% vs 26.7% ideal) | INTERP start: depth p starts from the interpolated depth p−1 optimum |
| 11 | `decompose.route_windows` | Skipped the incident node, which also carries ambulance requests | Those requests were never in a route window | Window covers `route[1:]` |
| 12 | `pipeline.part_sumo` | Re-simulated and stored animation traces that nothing reads (~1 MB, duplicate of `part_traces`) | Wasted time and space | Removed |
| 13 | `pipeline.part_sumo` / `export` | Silently used `part_signals.json` even if it came from other settings | Stale plans could reach the dashboard | Checks that stored costs match the current model, otherwise asks for a rerun |
| 14 | `dispatch`, `city`, `decompose`, `qalgos` | No input checks: A≠I assignments, `2·n_amb > N`, off-grid nodes, routes that jump blocks, spreads that do not sum to 1, wrong plan shapes, bad CVaR alpha | Silent wrong answers or deep crashes | Clear `ValueError`s |
| 15 | `web/index.html` | No `<!doctype>`, `<meta charset>` or viewport | Opened from disk, `×`, `±`, `≤` came out garbled; page was not mobile-scaled | Proper document head |
| 16 | `web/app.js` | "Ambulances arrived" counted a track as arrived when the recorded track ended (recording stops at 115 s) | Unfinished ambulances shown as arrived | Uses SUMO arrival times |
| 17 | `web/app.js` | Hard-coded conclusions: hybrid "same as the exact optimum", "no clear winner", mu=24 "slower in all", uncertainty "falls" | Text could contradict the data | All computed from the data |
| 18 | `web/build_single.py` | `</script` inside inlined code would end the tag; no encoding set | Broken single page | Escaped; UTF-8 everywhere |
| 19 | `pipeline` CLI | Unknown part name gave a KeyError; `traces` ran first | Confusing errors | Fixed order (signals before sumo), clear message |

## 3. Tests

14 original tests + 13 new regression tests (one per fixable bug, including a SUMO free-flow check that the
model's 9 s/block matches the simulator and a check that every plan is measured over the same window). All pass.

## 4. Re-run

All experiments were re-run with the fixed code (`python -m qgw.pipeline`), and the mu=24 stress test with
`QGW_MU=24 QGW_RESULTS=results_mu24 python -m qgw.pipeline signals sumo`. Old results are not kept: they were
made by the buggy evaluator. Updated numbers are in `README.md`.

## 5. What changed in the results

| claim | before (buggy) | after (fixed) |
|---|---|---|
| City 1 ambulance time, optimised vs rule | "299 s vs 190 s" (a weighted *sum*) | 51.9 s vs 41.7 s (weighted mean): still worse |
| City 2 ambulance time | "122 s vs 139 s" | 22.2 s vs 26.3 s: still better |
| City 3 ambulance time | "191 s vs 191 s" | 18.5 s vs 18.5 s: still equal |
| City 1 other vehicles, optimised vs fixed-time | 45.6 s vs 26.2 s (optimised looked much worse) | 34.8 s vs 36.1 s: optimised is slightly *better* |
| Other vehicles, optimised vs rule preemption | mixed | optimised better in all 3 cities |
| QAOA p=2 / p=3 on 12-qubit windows | 23% / 24% | 32% / 40% (INTERP starts) |
| Hardware window, ideal p=3 | 19.7% (worse than p=2) | 38.4% (better than p=2) |
| Fairness sweep | "no clear winner" (data said 24 won both) | 24 wins both on held-out cities but loses on 2 of 3 reported cities; kept at 2 and said so |
| Uncertainty test (model only) | 1.35 -> 0.58 (clamped arrivals) | 1.35 -> 0.58 (same rule as the QUBO) |

Unchanged: the QUBO, its optimum (1593), dispatch results, the hybrid loop reaching the optimum, and the
"no quantum advantage" conclusion.

Note on the timing fix: the reported cities have short routes (1 to 3 blocks), so it moved only one request
(City 3, node B1, slot 2 -> 1), and that city's optimum cost stayed at 1495. Most of the change in the SUMO
table comes from the measurement fixes (bugs 1, 2, 5). The timing fix matters for longer routes and larger grids.

## 6. Website integration (Manus site)

The Manus page arrived as a static mock-up: every number typed in by hand, a 4×4 grid of random lights not
connected to the model, and decorative dispatch circles. It is now `web/site/` and is driven by the model.

**Integration.** `qgw/site.py` computes, from `results/`, every number the page shows (`data-q` keys), the
proved-optimal City 1 plan with its exact QUBO (constant, linear terms, couplings), the dispatch cost matrix and
the SUMO vehicle traces. `python -m qgw.export` writes `web/site/site-data.js`; `web/build_single.py` inlines
it into `web/site/dist/index.html`.

* Plan explorer: the real 16 × 6 plan, one slot at a time, ambulance requests marked met or missed; flipping
  a qubit recomputes E(x) from the QUBO (e.g. 1593 → 1602), and nothing goes below the proved optimum.
* Dispatch: the real severity-weighted cost matrix with the optimal one-hot assignment outlined.
* Street replay: the recorded SUMO runs for all three cities, fixed-time vs optimised, with arrival
  counts and times taken from SUMO, not from where a recorded track ends.

**Bugs fixed in the Manus page.**

| bug | fix |
|---|---|
| Bloch sphere had \|1⟩ at the north pole and \|0⟩ at the south (the standard convention is \|0⟩ = +Z); the same slip was on the deck cover | \|0⟩ north / north-south green, \|1⟩ south / east-west green, on the site and the deck; the vector now precesses about Z |
| Window bars labelled "measured probability" | they are ideal statevector probabilities; label says so and gives the window count |
| Blind-guess bar said 0.024% (1/4096), but some windows have tied optima | uses the measured mean of the windows, 0.027%, explained in the caption |
| Light grid was a random pattern with no relation to the model | the real plan and exact energy |
| Decorative dispatch nodes "A C D XY" | real dispatch matrix |
| All content stayed invisible (opacity 0) if JavaScript failed | reveal animation only applies when JS runs |
| Particle background went blank after a resize with reduced motion on; animation ran forever off-screen | redraws on resize; pauses when the hero is not visible |
| Wide tables widened the whole page on phones | grid children may shrink; tables scroll inside their panel |
| "Ising Hamilton" | "Ising Hamiltonian" |
| `server.js` served files outside its folder (prefix check), crashed on a directory URL, broke on URL-encoded names, served JS/CSS as binary | fixed; serves its own folder on `PORT` (default 3000) |

**Checks.** `tests/test_site.py`: every `data-q` number in the HTML equals what `qgw.site` computes; the page's
energy equals `Qubo.energy` for the optimum and for flipped plans; the dispatch matrix is the model's; the replay
tracks are the SUMO traces (same vehicles, first and last points, arrival times); the Bloch convention. Rendered
in headless Chromium at 1440 px and 390 px: no console errors, no horizontal scroll, content visible with
JavaScript off. 32 tests pass.

## 7. Final pass before publishing

| area | finding | fix |
|---|---|---|
| website replay | pressing Pause then Play quickly could leave two animation loops running (double speed) | one loop at a time (`cancelAnimationFrame`); checked at 2.95 simulated s per real s after rapid clicks |
| website, dashboard | browsers requested `/favicon.ico` and got a 404 | inline SVG favicon; share tags (`og:title`, `og:description`) for the deployed link |
| presentation | cover still had \|1⟩ at the north pole; blind guess "0.024%"; "10× more valid dispatches"; "27 tests" on a slide and in two speaker notes | \|0⟩ at the north pole; 0.027%; 9.5× (40.0% vs 4.2%); 33 tests. File validated, member names kept |
| Windows | result files were read and written in the system default encoding | every file is opened as UTF-8 |
| code | unused imports and one unused variable (pyflakes) | removed; pyflakes is clean |
| dependencies | no version bounds; `playwright` installed but unused | ranges around the tested versions; `playwright` dropped |
| repository | no CI and no deployment config | `.github/workflows/tests.yml` (tests and page rebuild on every push), `.github/workflows/pages.yml` (GitHub Pages), `netlify.toml` |
| clean checkout | running the whole pipeline from scratch in a fresh copy (`QUICK=1`) crashed the website export (`KeyError: 'noisy_p_opt'`: quick runs skip the noisy p=2 simulation), and with only 2 SUMO cities the page would have kept City 3's hand-typed numbers | the export handles missing runs; the page hides rows for cities not in the results; regression test added; the fresh copy now runs pipeline, export and build end to end |

All 33 tests pass; both pages render at 1440 px and 390 px with no console errors and no horizontal scroll.
