-- Run against outputs/planning.sqlite after the Python CLI export.
-- Tables carry one exported scenario. Never append different runs without run_id.
SELECT id, population, assigned, unassigned, priority_unassigned
FROM community_plan ORDER BY unassigned DESC;

SELECT id, available_capacity, assigned,
       available_capacity-assigned AS remaining,
       ROUND(1.0*assigned/NULLIF(available_capacity,0),4) AS utilisation
FROM shelter_plan;

SELECT id, people, capacity FROM road_usage WHERE people > capacity;
-- Must return zero rows.

SELECT asset, COUNT(*) AS assignments
FROM resource_dispatch GROUP BY asset HAVING COUNT(*) > 1;
-- Must return zero rows.

SELECT m.mode, m.as_of, m.horizon_minutes,
       SUM(c.population) AS demand, SUM(c.assigned) AS assigned,
       SUM(c.unassigned) AS unassigned
FROM community_plan c CROSS JOIN scenario_metadata m
GROUP BY m.mode,m.as_of,m.horizon_minutes;
