"""Portable CSV, GeoJSON and SQLite outputs for QGIS/Power BI/R."""
import csv
import json
import sqlite3
from pathlib import Path


def export_plan(data, result, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plan.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    tables = {
        "community_plan": result["communities"], "shelter_plan": result["shelters"],
        "road_usage": result["road_usage"], "resource_dispatch": [{**r,"roads":"|".join(r["roads"])} for r in result["dispatch"]["assignments"]],
        "route_plan": [{**r,"priority":int(r["priority"]),"roads":"|".join(r["roads"])} for r in result["routes"]],
        "scenario_metadata": [{"mode": result["mode"], "as_of":result["as_of"],"model_version":result["model_version"],
                               "horizon_minutes":result["options"]["horizon_minutes"],"pressure":result["options"]["pressure"]}],
    }
    keys = {
        "community_plan":["id","population","assigned","unassigned","priority_served","priority_unassigned"],
        "shelter_plan":["id","available_capacity","assigned"], "road_usage":["id","people","capacity"],
        "resource_dispatch":["asset","community","type","minutes","roads"],
        "route_plan":["community","shelter","priority","people","roads","minutes"],
        "scenario_metadata":["mode","as_of","model_version","horizon_minutes","pressure"],
    }
    with sqlite3.connect(folder / "planning.sqlite") as db:
        for name, rows in tables.items():
            columns = keys[name]
            with (folder / (name + ".csv")).open("w", newline="",encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f,fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
            db.execute(f'DROP TABLE IF EXISTS "{name}"')
            types = {c: "TEXT" if c in {"id","asset","community","type","roads","shelter","mode","as_of","model_version"} else "REAL" for c in columns}
            db.execute(f'CREATE TABLE "{name}" ('+", ".join(f'"{c}" {types[c]}' for c in columns)+")")
            db.executemany(f'INSERT INTO "{name}" VALUES ('+",".join("?" for _ in columns)+")",[[r[c] for c in columns] for r in rows])
    nodes = {n["id"]:n for n in data["nodes"]}
    features = []
    for r in data["roads"]:
        coords = [[nodes[k]["lon"], nodes[k]["lat"]] for k in [r["u"],r["v"]]]
        features.append({"type":"Feature","geometry":{"type":"LineString","coordinates":coords},
                         "properties":{**r,"data_mode":"synthetic_exercise"}})
    for kind in ["communities","shelters"]:
        for item in data[kind]:
            node = nodes[item["node"]]
            features.append({"type":"Feature","geometry":{"type":"Point","coordinates":[node["lon"],node["lat"]]},
                             "properties":{**item,"kind":kind,"data_mode":"synthetic_exercise"}})
    (folder / "exercise.geojson").write_text(json.dumps({"type":"FeatureCollection","features":features},ensure_ascii=False),encoding="utf-8")
    return folder
