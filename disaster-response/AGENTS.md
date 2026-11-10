# CivicOps Resilience — instructions for Codex

This directory is a standalone disaster decision-support research prototype.
The existing CivicOps app outside this directory is out of scope.

## Commands

- Python: `python -m unittest discover -s tests -v`
- Browser parity and invariants: `node tests/parity.mjs`
- Export: `python -m disaster_response.cli plan --out outputs`
- Stress: `python -m disaster_response.cli stress --runs 100 --out outputs`
- PA baseline: `python -m disaster_response.cli train-demo --out outputs`
- Optional local API: `uvicorn disaster_response.api:app --reload --host 127.0.0.1`

## Model contracts

- Keep Python and browser deterministic planning engines consistent.
- Never present a synthetic asset, shelter or road as real/current/verified.
- Do not turn unavailable feeds into zero observations or safe routes.
- Unknown, stale, closed and hazard-excluded roads must not carry flow.
- Share an undirected road's throughput across both directions.
- Keep people and vehicle units distinct; resource dispatch is independent.
- Validate row-stochastic matrices, timestamps, conservation and capacities.
- Priority is maximum total flow first, priority-group flow second, route cost third.
- This is static flow, NOT an evacuation clearance-time model or a VRP.
- No automatic public warnings or dispatch. No household/person-level data.

## Next bounded tasks

1. Approve a pilot district and obtain historical event labels and official road/PPS observations.
2. Import staged OSM data; implement projected-CRS hazard intersection with provenance.
3. Build event-separated/time-separated training, calibration, Brier and PR-AUC evaluation.
4. Replace independent dispatch with a tested OR-Tools time-expanded multi-vehicle model.
5. Add authority approval, offline/mobile field updates, role access and audit history.
6. Run tabletop exercises with responders before any operational use.

Power BI and RStudio artefacts are supplied as integration files; do not claim they
were executed until tested in the corresponding runtimes. The deployed Site is a
static console using JavaScript, not a remotely running Python backend.
