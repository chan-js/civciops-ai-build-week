"""Assumption-driven Markov + common-shock Monte Carlo stress exercise."""
from copy import deepcopy
import numpy as np
from .engine import plan

TRANSITION = np.array([[.82,.16,.02],[.18,.63,.19],[.05,.25,.70]])


def stress(data, options=None, runs=120, seed=42, steps=3):
    if not 1 <= runs <= 2000 or not 1 <= steps <= 24:
        raise ValueError("Use 1..2000 runs and 1..24 hourly steps")
    if not np.allclose(TRANSITION.sum(axis=1), 1):
        raise ValueError("Transition rows must sum to one")
    rng = np.random.default_rng(seed)
    unmet, hazard_states = [], []
    for _ in range(runs):
        state = 1
        for _ in range(steps):
            state = int(rng.choice(3, p=TRANSITION[state]))
        d = deepcopy(data)
        # A shared hazard state and a common closure shock induce road dependence.
        common = rng.random()
        for r in d["roads"]:
            if r["risk"] > .3 and common < [.01,.15,.45][state]:
                r["status"] = "closed"
        demand_factor = float(rng.lognormal(-.5*.12**2, .12))
        for c in d["communities"]:
            ratio = c["priority_population"]/max(1,c["population"])
            c["population"] = int(rng.poisson(c["population"]*demand_factor))
            c["priority_population"] = min(c["population"], round(c["population"]*ratio))
        p = {**(options or {}), "pressure": (options or {}).get("pressure",1)*[.8,1.05,1.4][state]}
        p["pressure"] = min(3, p["pressure"])
        result = plan(d, p)
        unmet.append(result["unassigned"])
        hazard_states.append(state)
    return {"mode":"synthetic_assumptions", "seed":seed, "runs":runs, "steps_hours":steps,
            "transition_matrix":TRANSITION.tolist(), "unassigned_samples":unmet,
            "unassigned_p50":float(np.quantile(unmet,.5)), "unassigned_p95":float(np.quantile(unmet,.95)),
            "probability_any_unassigned":float(np.mean(np.array(unmet)>0)),
            "state_counts":[hazard_states.count(i) for i in range(3)],
            "interpretation":"Sensitivity to invented assumptions, NOT an estimated Malaysian disaster probability."}
