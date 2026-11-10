"""Integer min-cost maximum-flow planning; no remote services required.

Road throughput is shared in both directions. All capacities refer to one static
planning horizon. This is NOT a time-expanded traffic or transport simulation.
"""
from __future__ import annotations
from collections import deque
from copy import deepcopy
from datetime import datetime
import math


def timestamp(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timestamps must include a timezone")
    return dt


def integer(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or int(value) != value:
        raise ValueError(f"{name} must be a nonnegative integer")


def validate(data):
    if data.get("mode") != "synthetic_exercise":
        raise ValueError("v0.1 accepts synthetic_exercise only; operational inputs need an approved adapter")
    timestamp(data["as_of"])
    nodes = data["nodes"]
    ids = [n["id"] for n in nodes]
    if len(set(ids)) != len(ids) or not ids:
        raise ValueError("Node IDs must be unique")
    for n in nodes:
        if not (-90 <= n["lat"] <= 90 and -180 <= n["lon"] <= 180):
            raise ValueError("Invalid WGS84 coordinate")
    for key in ["roads", "communities", "shelters", "resources"]:
        entries = data[key]
        if len({e["id"] for e in entries}) != len(entries):
            raise ValueError(f"Duplicate {key} ID")
    for e in data["roads"]:
        if e["u"] not in ids or e["v"] not in ids or e["u"] == e["v"]:
            raise ValueError("Road endpoints must reference different nodes")
        integer(e["capacity_per_hour"], "road capacity")
        if not math.isfinite(e["minutes"]) or e["minutes"] <= 0 or not 0 <= e["risk"] <= 1:
            raise ValueError("Invalid road cost/risk")
        timestamp(e["observed_at"])
    for c in data["communities"]:
        integer(c["population"], "population")
        integer(c["priority_population"], "priority population")
        if not isinstance(c["priority_score"], (int,float)) or not 0 <= c["priority_score"] <= 1:
            raise ValueError("Invalid community priority score")
        if c["node"] not in ids or c["priority_population"] > c["population"]:
            raise ValueError("Invalid community node or priority population")
        for v in c["needs"].values():
            integer(v, "resource need")
    for s in data["shelters"]:
        integer(s["capacity"], "shelter capacity")
        integer(s["occupied"], "occupied")
        if s["occupied"] > s["capacity"] or s["node"] not in ids:
            raise ValueError("Invalid shelter capacity/node")
        timestamp(s["observed_at"])
    for r in data["resources"]:
        if r["node"] not in ids:
            raise ValueError("Invalid resource node")
        timestamp(r["observed_at"])
    return data


class Flow:
    def __init__(self):
        self.graph = {}
        self.forward = []

    def add(self, u, v, capacity, cost=0, meta=None):
        self.graph.setdefault(u, [])
        self.graph.setdefault(v, [])
        a = {"u": u, "v": v, "cap": int(capacity), "initial": int(capacity), "cost": cost, "rev": len(self.graph[v]), "meta": meta}
        b = {"u": v, "v": u, "cap": 0, "initial": 0, "cost": -cost, "rev": len(self.graph[u]), "meta": None}
        self.graph[u].append(a)
        self.graph[v].append(b)
        self.forward.append(a)
        return a

    def solve(self, source, sink):
        total = 0
        while True:
            dist = {k: math.inf for k in self.graph}
            prev = {}
            dist[source] = 0
            for _ in range(len(self.graph) - 1):
                changed = False
                for u, edges in self.graph.items():
                    if not math.isfinite(dist[u]):
                        continue
                    for e in edges:
                        if e["cap"] > 0 and dist[e["v"]] > dist[u] + e["cost"]:
                            dist[e["v"]] = dist[u] + e["cost"]
                            prev[e["v"]] = e
                            changed = True
                if not changed:
                    break
            if sink not in prev:
                break
            path, v = [], sink
            while v != source:
                e = prev[v]
                path.append(e)
                v = e["u"]
            amount = min(e["cap"] for e in path)
            for e in path:
                e["cap"] -= amount
                self.graph[e["v"]][e["rev"]]["cap"] += amount
            total += amount
        return total

    def paths(self, source, sink):
        remaining = {id(e): e["initial"] - e["cap"] for e in self.forward}
        outgoing = {}
        for e in self.forward:
            outgoing.setdefault(e["u"], []).append(e)
        results = []
        while True:
            q, seen, prev = deque([source]), {source}, {}
            while q and sink not in seen:
                u = q.popleft()
                for e in outgoing.get(u, []):
                    if remaining[id(e)] > 0 and e["v"] not in seen:
                        seen.add(e["v"])
                        prev[e["v"]] = e
                        q.append(e["v"])
            if sink not in seen:
                break
            path, v = [], sink
            while v != source:
                e = prev[v]
                path.append(e)
                v = e["u"]
            path.reverse()
            amount = min(remaining[id(e)] for e in path)
            for e in path:
                remaining[id(e)] -= amount
            results.append((amount, path))
        return results


DEFAULTS = {"pressure": 1.0, "horizon_minutes": 60, "risk_limit": 0.72,
            "congestion": 1.0, "shelter_scale": 1.0, "closed_roads": [],
            "closed_shelters": [], "accessible_only": True, "max_age_minutes": 120}


def settings(options):
    p = {**DEFAULTS, **(options or {})}
    for key in ["pressure", "horizon_minutes", "risk_limit", "congestion", "shelter_scale", "max_age_minutes"]:
        if isinstance(p[key], bool) or not isinstance(p[key], (int, float)) or not math.isfinite(p[key]):
            raise ValueError(f"Invalid {key}")
    if not (0 <= p["pressure"] <= 3 and 1 <= p["horizon_minutes"] <= 240 and 0 < p["risk_limit"] <= 1 and 1 <= p["congestion"] <= 4 and 0 <= p["shelter_scale"] <= 2 and 0 <= p["max_age_minutes"] <= 1440):
        raise ValueError("Scenario options outside supported bounds")
    return p


def fresh(item, data, p):
    age = (timestamp(data["as_of"]) - timestamp(item["observed_at"])).total_seconds() / 60
    return 0 <= age <= p["max_age_minutes"]


def road_state(road, data, p):
    if road["id"] in p["closed_roads"] or road["status"] == "closed":
        return "closed"
    if road["status"] != "verified_exercise":
        return "unverified"
    if not fresh(road, data, p):
        return "stale"
    if road["risk"] * p["pressure"] >= p["risk_limit"]:
        return "hazard_excluded"
    return "available_exercise"


def shortest(data, p, start, end):
    """Positive-cost shortest route on eligible roads, for arrival estimates only."""
    dist = {n["id"]: math.inf for n in data["nodes"]}
    dist[start] = 0
    prev = {}
    available = [r for r in data["roads"] if road_state(r, data, p) == "available_exercise"]
    for _ in range(len(dist)-1):
        changed = False
        for r in available:
            for a, b in [(r["u"], r["v"])] + ([] if r.get("oneway") else [(r["v"], r["u"])]):
                cost = r["minutes"] * p["congestion"]
                if dist[b] > dist[a] + cost:
                    dist[b], prev[b], changed = dist[a] + cost, (a, r["id"]), True
        if not changed:
            break
    if not math.isfinite(dist[end]):
        return None
    roads, node = [], end
    while node != start:
        node, rid = prev[node]
        roads.append(rid)
    return {"minutes": round(dist[end], 2), "roads": roads[::-1]}


def dispatch(data, p):
    """Independent first-wave team recommendations; not evacuation fleet scheduling."""
    f, src, dst = Flow(), "__dispatch_source", "__dispatch_sink"
    f.graph[src], f.graph[dst] = [], []
    for r in data["resources"]:
        if r.get("available", False) and r.get("status") == "verified_exercise" and fresh(r, data, p):
            f.add(src, "asset:" + r["id"], 1)
            for c in data["communities"]:
                if c["needs"].get(r["type"], 0) == 0:
                    continue
                route = shortest(data, p, r["node"], c["node"])
                if route and route["minutes"] <= p["horizon_minutes"]:
                    f.add("asset:" + r["id"], "need:" + c["id"] + ":" + r["type"], 1,
                          round(route["minutes"] * 10) - round(c["priority_score"] * 100000),
                          {"asset": r["id"], "community": c["id"], "type": r["type"], **route})
    for c in data["communities"]:
        for kind, count in c["needs"].items():
            f.add("need:" + c["id"] + ":" + kind, dst, count)
    f.solve(src, dst)
    assignments = [deepcopy(e["meta"]) for e in f.forward if e["meta"] and e["initial"] > e["cap"]]
    return {"assignments": assignments,
            "requested_units": sum(sum(c["needs"].values()) for c in data["communities"]),
            "assigned_units": len(assignments),
            "scope": "Independent one-way first-wave arrivals; no seats, return trips, service times or shared road usage with evacuation flow."}


def plan(data, options=None):
    validate(data)
    p = settings(options)
    total = sum(c["population"] for c in data["communities"])
    f, src, dst = Flow(), "__source", "__sink"
    f.graph[src], f.graph[dst] = [], []
    available, excluded = [], []
    for r in data["roads"]:
        state = road_state(r, data, p)
        if state == "available_exercise":
            available.append(r)
        else:
            excluded.append({"id": r["id"], "reason": state})
    # All route costs are nonnegative. This bound dominates total route cost,
    # giving priority_people lexicographic precedence AFTER maximum total flow.
    weights = {r["id"]: math.floor(r["minutes"] * p["congestion"] * 10 + .5) + math.floor(r["risk"] * p["pressure"] * 100 + .5) for r in available}
    priority_bonus = (sum(weights.values()) + 1) * (total + 1)
    supply_edges = []
    for c in data["communities"]:
        for count, priority in [(c["priority_population"], True), (c["population"]-c["priority_population"], False)]:
            e = f.add(src, c["node"], count, -priority_bonus if priority else 0,
                      {"origin": c["id"], "priority": priority})
            supply_edges.append(e)
    road_edges = {}
    for r in available:
        cap = math.floor(r["capacity_per_hour"] * p["horizon_minutes"] / 60)
        a, b = "road_in:"+r["id"], "road_out:"+r["id"]
        f.add(r["u"], a, total)
        f.add(b, r["v"], total)
        if not r.get("oneway"):
            f.add(r["v"], a, total)
            f.add(b, r["u"], total)
        road_edges[r["id"]] = f.add(a, b, cap, weights[r["id"]], {"road": r["id"]})
    shelter_edges, capacities, unavailable_shelters = {}, {}, []
    for s in data["shelters"]:
        reason = None
        if s["id"] in p["closed_shelters"] or s["status"] != "open_exercise":
            reason = "closed_or_unverified"
        elif not fresh(s, data, p):
            reason = "stale"
        elif p["accessible_only"] and not s["accessible"]:
            reason = "accessibility_filter"
        cap = max(0, math.floor(s["capacity"] * p["shelter_scale"]) - s["occupied"]) if reason is None else 0
        capacities[s["id"]] = cap
        if reason:
            unavailable_shelters.append({"id": s["id"], "reason": reason})
        shelter_edges[s["id"]] = f.add(s["node"], dst, cap, 0, {"shelter": s["id"]})
    served = f.solve(src, dst)
    lookup = {r["id"]: r for r in data["roads"]}
    routes = []
    for count, path in f.paths(src, dst):
        metas = [e["meta"] for e in path if e["meta"]]
        origin = next(m for m in metas if "origin" in m)
        target = next(m["shelter"] for m in metas if "shelter" in m)
        roads = [m["road"] for m in metas if "road" in m]
        routes.append({"community": origin["origin"], "shelter": target, "priority": origin["priority"],
                       "people": count, "roads": roads,
                       "minutes": round(sum(lookup[r]["minutes"] for r in roads) * p["congestion"], 2)})
    communities = []
    for c in data["communities"]:
        own = [e for e in supply_edges if e["meta"]["origin"] == c["id"]]
        assigned = sum(e["initial"]-e["cap"] for e in own)
        priority_served = sum(e["initial"]-e["cap"] for e in own if e["meta"]["priority"])
        communities.append({"id": c["id"], "population": c["population"], "assigned": assigned,
                            "unassigned": c["population"]-assigned, "priority_served": priority_served,
                            "priority_unassigned": c["priority_population"]-priority_served})
    return {"model_version": "0.1.0", "mode": data["mode"], "as_of": data["as_of"], "options": p,
            "objective": "maximize total assigned, then priority assigned, then minimize assumed travel+risk cost",
            "total_demand": total, "assigned": served, "unassigned": total-served,
            "priority_assigned": sum(c["priority_served"] for c in communities),
            "routes": routes, "communities": communities,
            "shelters": [{"id": s["id"], "available_capacity": capacities[s["id"]],
                          "assigned": shelter_edges[s["id"]]["initial"]-shelter_edges[s["id"]]["cap"]} for s in data["shelters"]],
            "road_usage": [{"id": rid, "people": e["initial"]-e["cap"], "capacity": e["initial"]} for rid,e in road_edges.items()],
            "excluded_roads": excluded, "excluded_shelters": unavailable_shelters,
            "dispatch": dispatch(data, p),
            "limitations": ["Synthetic schematic graph, populations and shelters; not real navigation.",
                            "Static throughput flow; not a time-expanded evacuation clearance model.",
                            "Priority people are an aggregate planning group, not medical triage.",
                            "Resource dispatch is independent; evacuation seats and assistance are not guaranteed.",
                            "Travel minutes exclude queues, boarding, service and return trips."]}
