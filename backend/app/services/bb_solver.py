"""Branch-and-Bound solver ported from algo-docs/bb_demo.py.
Finds the optimal subset of applicable attacks for a single AP
within a given time budget."""
from __future__ import annotations

import time as time_mod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AttackDef:
    """Attack definition with weight and estimated time."""
    index: int
    name: str
    weight: float
    time_s: float

    @property
    def rho(self) -> float:
        return self.weight / self.time_s if self.time_s > 0 else 0.0


DEFAULT_ATTACKS: list[tuple[str, float, float]] = [
    ("recon",              0.0,   300),   # v0
    ("handshake_capture",  0.6,  1800),   # v1
    ("pmkid_capture",      0.7,  3600),   # v2
    ("wps_pixie",          0.9,  1200),   # v3
    ("dragonshift",        0.8,  5400),   # v4
    ("psk_crack",          0.5,  2700),   # v5
    ("krack",              0.85, 3600),   # v6  (deferred - kept for index compat)
    ("dos",                0.5,  1800),   # v7
]

CONJ_DEPS: list[tuple[int, int]] = [
    (0, 1), (0, 2), (0, 3), (0, 4), (0, 6), (0, 7),
]
DISJ_DEPS: dict[int, list[int]] = {5: [1, 2]}

EXECUTION_ORDER = [0, 1, 2, 3, 4, 6, 7, 5]

ACTIVE_ATTACK_INDICES = {1, 2, 3, 4, 5, 7}


@dataclass
class APParams:
    """Access point parameters extracted from recon data."""
    x1: str = "WPA2"   # encryption protocol
    x2: int = 0        # WPS enabled
    x3: int = 0        # PMF: 0=none, 1=capable, 2=required
    x4: int = 0        # client count
    x5: int = 0        # 802.11r
    x9: int = 0        # HT capabilities

    def as_tuple(self) -> tuple:
        return (self.x1, self.x2, self.x3, self.x4, self.x5, self.x9)


def ap_params_from_recon(ap_data: dict) -> APParams:
    """Map ReconAP dict to APParams for the B&B solver."""
    sec = ap_data.get("security_info") or {}
    wps = ap_data.get("wps") or {}
    tagged = ap_data.get("tagged_params") or {}

    display_sec = (sec.get("display_security") or "Open").upper()
    x1_map = {
        "OPEN": "OPEN", "WEP": "WEP", "WPA": "WPA",
        "WPA2": "WPA2", "WPA3": "WPA3",
    }
    x1 = x1_map.get(display_sec, "WPA2")
    if "WPA2/WPA3" in display_sec or "WPA2 / WPA3" in display_sec:
        x1 = "WPA2/WPA3-TM"

    x2 = 1 if wps.get("enabled") else 0

    pmf_str = (sec.get("pmf") or "none").lower()
    x3 = {"none": 0, "capable": 1, "required": 2}.get(pmf_str, 0)

    x4 = ap_data.get("client_count", 0)

    akm = sec.get("akm") or ""
    x5 = 1 if "FT-" in akm.upper() else 0

    x9 = 1 if tagged.get("ht_capabilities") else 0

    return APParams(x1=x1, x2=x2, x3=x3, x4=x4, x5=x5, x9=x9)


def phi(j: int, params: tuple) -> bool:
    """Applicability predicate phi_j for attack j given AP params."""
    x1, x2, x3, x4, x5, x9 = params
    wpa2_like = x1 in ("WPA2", "WPA2/WPA3-TM")

    if j == 0:
        return True
    if j == 1:  # handshake: WPA2 + client
        return wpa2_like and x4 > 0
    if j == 2:  # PMKID: WPA2 (works on any PSK/SAE network, not just FT)
        return wpa2_like
    if j == 3:  # WPS Pixie-Dust
        return x2 == 1
    if j == 4:  # DragonShift: transition mode + client (PMF irrelevant - rogue AP bypasses it)
        return x1 == "WPA2/WPA3-TM" and x4 > 0
    if j == 5:  # PSK crack: WPA2
        return wpa2_like
    if j == 6:  # KRACK (deferred)
        return False
    if j == 7:  # DoS (Bl0ck): HT + client
        return x9 == 1 and x4 > 0
    return False


def _dep_feasible(
    assignment: dict[int, int],
    vuln_j: int,
) -> bool:
    """Check conjunctive and disjunctive dependencies for a single AP."""
    for l, s in CONJ_DEPS:
        if s == vuln_j and assignment.get(l, 0) != 1:
            return False
    if vuln_j in DISJ_DEPS:
        if not any(assignment.get(l, 0) == 1 for l in DISJ_DEPS[vuln_j]):
            return False
    return True


@dataclass
class BBResult:
    """Result of B&B optimization for one AP."""
    selected_attacks: list[dict[str, Any]] = field(default_factory=list)
    f_star: float = 0.0
    total_time_s: float = 0.0
    nodes_visited: int = 0
    execution_order: list[str] = field(default_factory=list)


def solve(
    ap_params: APParams,
    attacks: list[tuple[str, float, float]] | None = None,
    time_budget_s: float = 28800.0,
    solver_timeout_s: float = 10.0,
) -> BBResult:
    """Run B&B for a single AP, return selected attacks in execution order."""
    items = attacks or DEFAULT_ATTACKS
    m = len(items) - 1
    weights = [w for _, w, _ in items]
    times = [t for _, _, t in items]
    names = [n for n, _, _ in items]
    params = ap_params.as_tuple()

    applicable = [j for j in range(m + 1) if phi(j, params)]
    p = len(applicable)

    best_F = 0.0
    best_Z: dict[int, int] = {}
    nodes = [0]
    start = time_mod.perf_counter()

    def bb(idx: int, a: dict[int, int], T_rem: float, F_cur: float) -> None:
        nonlocal best_F, best_Z
        nodes[0] += 1
        if time_mod.perf_counter() - start > solver_timeout_s:
            return
        ub = F_cur + sum(weights[j] for j in applicable[idx:] if j not in a and j != 0)
        if ub <= best_F:
            return
        if idx == p:
            if F_cur > best_F:
                best_F, best_Z = F_cur, dict(a)
            return
        vj = applicable[idx]
        if T_rem >= times[vj] and _dep_feasible(a, vj):
            a[vj] = 1
            bb(idx + 1, a, T_rem - times[vj], F_cur + (weights[vj] if vj >= 1 else 0.0))
            del a[vj]
        a[vj] = 0
        bb(idx + 1, a, T_rem, F_cur)
        del a[vj]

    bb(0, {}, time_budget_s, 0.0)

    selected = [j for j in range(m + 1) if best_Z.get(j, 0) == 1 and j in ACTIVE_ATTACK_INDICES]
    ordered = [j for j in EXECUTION_ORDER if j in selected]

    result = BBResult(
        f_star=best_F,
        nodes_visited=nodes[0],
        total_time_s=sum(times[j] for j in ordered),
    )
    for j in ordered:
        result.selected_attacks.append({
            "index": j,
            "name": names[j],
            "weight": weights[j],
            "time_s": times[j],
            "applicable": True,
        })
        result.execution_order.append(names[j])

    return result
