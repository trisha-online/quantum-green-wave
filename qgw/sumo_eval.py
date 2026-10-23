"""
Closed-loop validation in SUMO.  A plan x[n,t] from ANY solver is applied to a 4x4 SUMO grid
(setRedYellowGreenState, one phase per 15 s slot); ambulances follow the planned routes; background traffic
comes from the same forecast.  We report ambulance travel time and civilian waiting time, so the model-vs-simulator
gap is measured instead of assumed.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET

import numpy as np

from .city import City

NET = os.path.join(os.path.dirname(__file__), "..", "sumo_assets", "grid.net.xml")
LETTERS = "ABCD"


def nid(x, y):
    return f"{LETTERS[x]}{y}"


def edge_id(p, q):
    return nid(*p) + nid(*q)


def _axis_of_edges():
    """direction (ew/ns) of every internal edge, from its junction coordinates."""
    root = ET.parse(NET).getroot()
    xy = {j.get("id"): (float(j.get("x")), float(j.get("y"))) for j in root.iter("junction")}
    ax = {}
    for e in root.iter("edge"):
        if e.get("function") == "internal":
            continue
        a, b = xy[e.get("from")], xy[e.get("to")]
        ax[e.get("id")] = "ew" if abs(a[0] - b[0]) > abs(a[1] - b[1]) else "ns"
    return ax


class SumoCity:
    def __init__(self, city: City, seed=0, rate_scale=0.30, warmup=45):
        import traci
        if city.nx != 4 or city.ny != 4 or city.nx > len(LETTERS):
            raise ValueError("the bundled SUMO network is a 4x4 grid; regenerate sumo_assets/grid.net.xml for other sizes")
        self.traci = traci
        self.city, self.seed, self.rate_scale, self.warmup = city, seed, rate_scale, warmup
        self.axis = _axis_of_edges()
        self.tls_links = {}      # node name -> list of (axis) per signal index

    # ----------------------------------------------------------------------- lifecycle
    def start(self, label="qgw"):
        import sumolib
        cmd = [sumolib.checkBinary("sumo"), "-n", NET, "--no-step-log", "--no-warnings", "--seed", str(self.seed),
               "--step-length", "1", "--time-to-teleport", "-1", "--collision.action", "none"]
        self.traci.start(cmd, label=label)
        self.conn = self.traci
        t = self.traci
        t.vehicletype.copy("DEFAULT_VEHTYPE", "civ")
        t.vehicletype.copy("DEFAULT_VEHTYPE", "amb")
        t.vehicletype.setVehicleClass("amb", "emergency")
        t.vehicletype.setMaxSpeed("amb", 22.0)
        t.vehicletype.setSpeedFactor("amb", 1.2)
        t.vehicletype.setColor("amb", (255, 60, 60, 255))
        self.node_axes = {}
        for x in range(self.city.nx):
            for y in range(self.city.ny):
                name = nid(x, y)
                links = t.trafficlight.getControlledLinks(name)
                axes = []
                for group in links:
                    lane = group[0][0]
                    axes.append(self.axis[lane.rsplit("_", 1)[0]])
                self.node_axes[name] = axes
        self._demand_schedule()
        return self

    def close(self):
        self.traci.close()

    # ----------------------------------------------------------------------- demand
    def _demand_schedule(self):
        """pre-compute departures: Bernoulli insertion each second per boundary entry, rate from the forecast."""
        c, rng = self.city, np.random.default_rng(self.seed)
        entries = []   # (edge list, rate)
        for y in range(c.ny):
            rate = c.q_ew[[c.node(x, y) for x in range(c.nx)], :].mean() / c.slot_s * self.rate_scale
            east = ["left%d%s" % (y, nid(0, y))] + [edge_id((x, y), (x + 1, y)) for x in range(c.nx - 1)] + [nid(c.nx - 1, y) + "right%d" % y]
            west = ["right%d%s" % (y, nid(c.nx - 1, y))] + [edge_id((x, y), (x - 1, y)) for x in range(c.nx - 1, 0, -1)] + [nid(0, y) + "left%d" % y]
            entries += [(east, rate), (west, rate)]
        for x in range(c.nx):
            rate = c.q_ns[[c.node(x, y) for y in range(c.ny)], :].mean() / c.slot_s * self.rate_scale
            north = ["bottom%d%s" % (x, nid(x, 0))] + [edge_id((x, y), (x, y + 1)) for y in range(c.ny - 1)] + [nid(x, c.ny - 1) + "top%d" % x]
            south = ["top%d%s" % (x, nid(x, c.ny - 1))] + [edge_id((x, y), (x, y - 1)) for y in range(c.ny - 1, 0, -1)] + [nid(x, 0) + "bottom%d" % x]
            entries += [(north, rate), (south, rate)]
        self.entries = entries
        self.rng = rng
        self.horizon = self.warmup + 160          # every run simulates exactly 160 s after dispatch
        self.dep = [[] for _ in range(self.horizon)]
        for k, (route, rate) in enumerate(entries):
            for s in range(self.horizon):
                if rng.random() < rate:
                    self.dep[s].append(k)

    def _insert(self, step):
        t = self.traci
        for k in self.dep[step] if step < len(self.dep) else []:
            vid = f"v{step}_{k}"
            rid = f"r{k}"
            if rid not in self.routes_added:
                t.route.add(rid, self.entries[k][0]); self.routes_added.add(rid)
            try:
                t.vehicle.add(vid, rid, typeID="civ", departLane="best", departSpeed="max")
            except Exception:
                pass

    # ----------------------------------------------------------------------- signal control
    YELLOW_S = 3

    def _state(self, name, green_axis, yellow=False):
        on = "y" if yellow else "G"
        return "".join(on if a == green_axis else "r" for a in self.node_axes[name])

    def _begin_slot(self, phases):
        """phases: (N,) 1 = EW green.  Nodes that change get YELLOW_S s of yellow on the axis losing green
        (and red on both); unchanged nodes keep green.  Applies to warm-up and plan alike, including the
        hand-over from the warm-up program to slot 0 of the plan."""
        tl = self.traci.trafficlight
        for x in range(self.city.nx):
            for y in range(self.city.ny):
                n, name = self.city.node(x, y), nid(x, y)
                new = "ew" if phases[n] == 1 else "ns"
                if self.cur is not None and self.cur[n] != phases[n]:
                    old = "ew" if self.cur[n] == 1 else "ns"
                    tl.setRedYellowGreenState(name, self._state(name, old, yellow=True))
                else:
                    tl.setRedYellowGreenState(name, self._state(name, new))
        self.pending = np.array(phases).copy()

    def _end_yellow(self):
        tl = self.traci.trafficlight
        for x in range(self.city.nx):
            for y in range(self.city.ny):
                n, name = self.city.node(x, y), nid(x, y)
                tl.setRedYellowGreenState(name, self._state(name, "ew" if self.pending[n] == 1 else "ns"))
        self.cur = self.pending

    # ----------------------------------------------------------------------- run
    def _track_civilians(self, counting):
        """subscribe to the speed of every new civilian vehicle; while `counting`, add one second of waiting
        for each civilian that is (almost) stopped.  Vehicles that leave the network keep their waiting time."""
        t, tc = self.traci, self.traci.constants
        for vid in t.simulation.getDepartedIDList():
            if not vid.startswith("amb"):
                t.vehicle.subscribe(vid, [tc.VAR_SPEED])
        if not counting:
            return
        for vid, res in t.vehicle.getAllSubscriptionResults().items():
            if vid.startswith("amb") or tc.VAR_SPEED not in res:
                continue
            self.civ_seen.add(vid)
            if res[tc.VAR_SPEED] < 0.1:
                self.civ_wait[vid] = self.civ_wait.get(vid, 0.0) + 1.0

    def run(self, X, amb_routes: list, severities: list, record=False):
        """X: (N,T) plan.  amb_routes: list of node paths [(x,y)...].  Returns metrics (+ optional trace).
        Every plan is simulated for the SAME window (horizon - warmup seconds after the ambulances start), so
        civilian waiting is comparable between plans; the plan itself covers the first T*slot_s seconds and the
        network then returns to its default program."""
        t = self.traci
        c = self.city
        X = np.asarray(X).reshape(c.N, c.T)
        if not np.isin(X, (0, 1)).all():
            raise ValueError("plan must be binary")
        if len(amb_routes) != len(severities):
            raise ValueError("one severity per ambulance route is required")
        slot = int(c.slot_s)
        if slot != c.slot_s or slot <= self.YELLOW_S:
            raise ValueError("slot_s must be an integer number of seconds longer than the yellow time")
        self.routes_added, self.cur, self.pending = set(), None, None
        self.civ_wait, self.civ_seen = {}, set()
        # warm-up under the common fixed-time baseline so every method starts from the same queues
        base = np.tile(np.array([(s // 2) % 2 for s in range(c.T)]), (c.N, 1))
        for step in range(self.warmup):
            if step % slot == 0:
                self._begin_slot(base[:, (step // slot) % c.T])
            if step % slot == self.YELLOW_S:
                self._end_yellow()
            self._insert(step); t.simulationStep()
            self._track_civilians(False)
        if self.pending is not None and self.cur is not self.pending:
            self._end_yellow()
        # start ambulances
        amb_ids = []
        for k, r in enumerate(amb_routes):
            for a, b in zip(r[:-1], r[1:]):
                if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
                    raise ValueError(f"ambulance route {k} has a step {a}->{b} that is not one block")
            edges = [edge_id(a, b) for a, b in zip(r[:-1], r[1:])]
            rid = f"amb_route{k}"
            t.route.add(rid, edges)
            vid = f"amb{k}"
            t.vehicle.add(vid, rid, typeID="amb", departLane="best", departSpeed="max")
            amb_ids.append(vid)
        done = {}
        tracks = {}
        plan_end = c.T * slot
        for step in range(self.warmup, self.horizon):
            rel = step - self.warmup
            k = rel // slot
            if k < c.T and rel % slot == 0:
                self._begin_slot(X[:, k])
            elif k < c.T and rel % slot == self.YELLOW_S:
                self._end_yellow()
            elif rel == plan_end:
                for x in range(c.nx):
                    for y in range(c.ny):
                        t.trafficlight.setProgram(nid(x, y), "0")
            self._insert(step)
            t.simulationStep()
            for vid in t.simulation.getArrivedIDList():
                if vid.startswith("amb") and vid not in done:
                    done[vid] = rel + 1          # seconds since the ambulances were dispatched
            self._track_civilians(True)
            if record and rel <= plan_end + 25:
                for vid in t.vehicle.getIDList():
                    px, py = t.vehicle.getPosition(vid)
                    tr = tracks.setdefault(vid, {"t0": rel, "a": int(vid.startswith("amb")), "p": []})
                    tr["p"] += [int(round(px)), int(round(py))]
        cap = self.horizon - self.warmup
        times = [done.get(v, cap) for v in amb_ids]           # unfinished ambulances are censored at the cap
        sev = np.asarray(severities, dtype=float)
        waits = [self.civ_wait.get(v, 0.0) for v in self.civ_seen]
        out = {
            "amb_times": times,
            "amb_weighted": float(np.dot(sev, times)),
            "amb_wmean": float(np.dot(sev, times) / sev.sum()),
            "amb_mean": float(np.mean(times)),
            "civ_wait_mean": float(np.mean(waits)) if waits else 0.0,
            "civ_wait_total": float(np.sum(waits)),
            "n_civ": len(self.civ_seen),
            "unfinished": int(len(amb_ids) - len(done)),
            "window_s": cap,
        }
        if record:
            out["trace"] = tracks
        return out


def evaluate_plans(city, plans: dict, routes, severities, seeds=(0, 1, 2), rate_scale=0.30, record_first=None):
    """run every plan in a fresh simulation for each seed; returns {name: [metrics...]}."""
    res = {k: [] for k in plans}
    for s in seeds:
        for name, X in plans.items():
            sim = SumoCity(city, seed=s, rate_scale=rate_scale).start(label=f"{name}-{s}-{os.getpid()}")
            try:
                res[name].append(sim.run(np.asarray(X).reshape(city.N, city.T), routes, severities,
                                        record=(record_first == name and s == seeds[0])))
            finally:
                sim.close()
    return res
