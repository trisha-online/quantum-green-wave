"""
Grid city model for emergency-vehicle signal preemption.

The city is an nx-by-ny grid of signalised intersections.  Time is cut into T planning slots
(slot_s seconds each).  At every (intersection n, slot t) the controller picks ONE binary phase

    x[n,t] = 1  ->  East-West (EW) axis is green, North-South (NS) waits
    x[n,t] = 0  ->  North-South axis is green,   EW waits

Demand enters through a *queue forecast* q_ew[n,t], q_ns[n,t] (vehicles that would be waiting on
each axis if it were red in slot t).  Ambulances travel one block per slot along their route and
ask for green on the axis they arrive on ("preemption requests").
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np

TIMING_SPREAD = {-1: 0.2, 0: 0.6, 1: 0.2}      # uncertainty of the ambulance arrival slot

# Seconds an ambulance needs per 150 m block.  Measured in the SUMO network used for validation
# (lane speed 13.89 m/s x speed factor 1.2 -> ~8.5 s per block at free flow, rounded up to 9 s).
# The original model silently assumed one block per 15 s slot, so from the third intersection on
# it asked for green in the wrong slot.
AMB_BLOCK_S = 9.0


@dataclass
class Ambulance:
    id: int
    station: tuple          # (x, y)
    severity: int = 1       # 1..3, weights the preemption request


@dataclass
class Incident:
    id: int
    node: tuple             # (x, y)
    severity: int = 1


@dataclass
class City:
    nx: int
    ny: int
    T: int
    slot_s: float
    q_ew: np.ndarray        # (N, T) forecast queue on the EW approaches of node n in slot t
    q_ns: np.ndarray
    share: float = 0.5      # fraction of a queue released as a platoon toward the next light
    block_s: float = AMB_BLOCK_S   # ambulance travel time per block (s)

    def __post_init__(self):
        self.q_ew = np.asarray(self.q_ew, dtype=float)
        self.q_ns = np.asarray(self.q_ns, dtype=float)
        if self.q_ew.shape != (self.N, self.T) or self.q_ns.shape != (self.N, self.T):
            raise ValueError(f"queue forecasts must have shape (N, T) = {(self.N, self.T)}, "
                             f"got {self.q_ew.shape} and {self.q_ns.shape}")
        if (self.q_ew < 0).any() or (self.q_ns < 0).any() or not np.isfinite(self.q_ew).all() or not np.isfinite(self.q_ns).all():
            raise ValueError("queue forecasts must be finite and non-negative")
        if self.slot_s <= 0 or self.block_s <= 0:
            raise ValueError("slot_s and block_s must be positive")

    @property
    def N(self) -> int:
        return self.nx * self.ny

    @property
    def nvars(self) -> int:
        return self.N * self.T

    def node(self, x: int, y: int) -> int:
        return y * self.nx + x

    def xy(self, n: int) -> tuple:
        return n % self.nx, n // self.nx

    def var(self, n: int, t: int) -> int:
        return n * self.T + t

    def unvar(self, v: int) -> tuple:
        return v // self.T, v % self.T

    def neighbours(self, n: int):
        """yield (m, axis) for each adjacent intersection; axis 'ew' or 'ns'."""
        x, y = self.xy(n)
        if x > 0: yield self.node(x - 1, y), "ew"
        if x < self.nx - 1: yield self.node(x + 1, y), "ew"
        if y > 0: yield self.node(x, y - 1), "ns"
        if y < self.ny - 1: yield self.node(x, y + 1), "ns"

    def congestion(self) -> np.ndarray:
        """mean total queue per node (used to make routing / dispatch avoid jams)."""
        return (self.q_ew + self.q_ns).mean(axis=1)

    def check_xy(self, p) -> tuple:
        x, y = int(p[0]), int(p[1])
        if not (0 <= x < self.nx and 0 <= y < self.ny):
            raise ValueError(f"node {p} is outside the {self.nx}x{self.ny} grid")
        return x, y

    # ------------------------------------------------------------------ routing
    def shortest_path(self, a: tuple, b: tuple, kappa: float = 1.0) -> list:
        """Dijkstra on the grid; each block costs 1 + kappa * (relative congestion of the two ends)."""
        a, b = self.check_xy(a), self.check_xy(b)
        cong = self.congestion()
        cmax = max(cong.max(), 1e-9)
        src, dst = self.node(*a), self.node(*b)
        dist = {src: 0.0}
        prev = {}
        pq = [(0.0, src)]
        while pq:
            d, n = heapq.heappop(pq)
            if n == dst:
                break
            if d > dist.get(n, 1e18):
                continue
            for m, _ in self.neighbours(n):
                w = 1.0 + kappa * 0.5 * (cong[n] + cong[m]) / cmax
                nd = d + w
                if nd < dist.get(m, 1e18) - 1e-12:
                    dist[m] = nd
                    prev[m] = n
                    heapq.heappush(pq, (nd, m))
        path, n = [dst], dst
        while n != src:
            n = prev[n]
            path.append(n)
        return [self.xy(n) for n in reversed(path)]

    def path_cost(self, a: tuple, b: tuple, kappa: float = 1.0) -> float:
        """Estimated travel time in slots (blocks * congestion factor)."""
        path = self.shortest_path(a, b, kappa)
        cong = self.congestion()
        cmax = max(cong.max(), 1e-9)
        c = 0.0
        for p, q in zip(path[:-1], path[1:]):
            c += 1.0 + kappa * 0.5 * (cong[self.node(*p)] + cong[self.node(*q)]) / cmax
        return c

    # ------------------------------------------------------------------ preemption requests
    def crossing_slot(self, j: int) -> int:
        """Slot in which the ambulance crosses the (j+1)-th intersection of its route (j = 0 is the first
        intersection after the station).  It reaches it at (j+1)*block_s seconds; an arrival exactly on a
        slot boundary belongs to the slot that is ending."""
        return int(np.ceil((j + 1) * self.block_s / self.slot_s - 1e-9)) - 1

    def route_crossings(self, route: list) -> list:
        """[(node, nominal slot, axis needed)] for every intersection after the station, incl. the incident node."""
        out = []
        for j in range(len(route) - 1):
            (x0, y0), (x1, y1) = route[j], route[j + 1]
            if abs(x0 - x1) + abs(y0 - y1) != 1:
                raise ValueError(f"route step {route[j]} -> {route[j + 1]} is not one block")
            out.append((self.node(x1, y1), self.crossing_slot(j), "ew" if y0 == y1 else "ns"))
        return out

    def requests_for_route(self, route: list, severity: int, base_weight: float, spread=None) -> list:
        """Green-light requests for one ambulance: it needs green on the axis of the block it travels on,
        at every intersection it crosses.  Returns [(node, slot, axis, weight)] with the arrival-slot
        uncertainty spread over +-1 slot.  Crossings outside the planning horizon are dropped."""
        spread = TIMING_SPREAD if spread is None else spread
        if abs(sum(spread.values()) - 1.0) > 1e-9:
            raise ValueError("timing spread probabilities must sum to 1")
        out = []
        for n, t0, axis in self.route_crossings(route):
            for k, p in spread.items():
                t = t0 + k
                if 0 <= t < self.T:
                    out.append((n, t, axis, base_weight * severity * p))
        return out


def make_city(nx: int = 4, ny: int = 4, T: int = 6, slot_s: float = 15.0, seed: int = 0,
              rush: str = "ew") -> City:
    """Synthetic rush-hour forecast: heavier traffic in the centre, EW (or NS) corridor dominant."""
    rng = np.random.default_rng(seed)
    N = nx * ny
    cx, cy = (nx - 1) / 2, (ny - 1) / 2
    q_ew = np.zeros((N, T))
    q_ns = np.zeros((N, T))
    for y in range(ny):
        for x in range(nx):
            n = y * nx + x
            centre = np.exp(-(((x - cx) / (0.8 * nx)) ** 2 + ((y - cy) / (0.8 * ny)) ** 2))
            base_ew = (14 if rush == "ew" else 8) * centre + rng.uniform(1, 6)
            base_ns = (8 if rush == "ew" else 14) * centre + rng.uniform(1, 6)
            for t in range(T):
                growth = 1.0 + 0.12 * t
                q_ew[n, t] = np.round(base_ew * growth * rng.uniform(0.85, 1.15))
                q_ns[n, t] = np.round(base_ns * growth * rng.uniform(0.85, 1.15))
    return City(nx, ny, T, slot_s, q_ew, q_ns)


def make_emergencies(city: City, n_amb: int = 4, seed: int = 0):
    """Random ambulance stations and incidents (distinct nodes, severity 1-3)."""
    rng = np.random.default_rng(seed + 1000)
    nodes = [(x, y) for y in range(city.ny) for x in range(city.nx)]
    if not 1 <= n_amb or 2 * n_amb > len(nodes):
        raise ValueError(f"need 1 <= n_amb and 2*n_amb <= {len(nodes)} nodes (got n_amb={n_amb})")
    pick = rng.choice(len(nodes), size=2 * n_amb, replace=False)
    ambs = [Ambulance(i, nodes[pick[i]], 1) for i in range(n_amb)]
    incs = [Incident(i, nodes[pick[n_amb + i]], int(rng.integers(1, 4))) for i in range(n_amb)]
    return ambs, incs
