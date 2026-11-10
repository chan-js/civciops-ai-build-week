"""Optional GIS preparation, deliberately NOT a ready-to-route operational graph.
Install `pip install '.[gis]'` first. OSMnx API verified against official v2 docs;
network retrieval has not been executed in this restricted environment.
"""
import argparse
import json
from pathlib import Path


def main():
    import osmnx as ox
    p=argparse.ArgumentParser()
    p.add_argument('--place',default='Klang, Selangor, Malaysia')
    p.add_argument('--out',default='outputs/osm')
    a=p.parse_args()
    folder=Path(a.out)
    folder.mkdir(parents=True,exist_ok=True)
    graph=ox.graph.graph_from_place(a.place,network_type='drive',simplify=True)
    graph=ox.routing.add_edge_speeds(graph)
    graph=ox.routing.add_edge_travel_times(graph)
    ox.io.save_graphml(graph,filepath=folder/'roads.graphml')
    nodes,edges=ox.convert.graph_to_gdfs(graph)
    # No disaster passage permission is inferred from OSM tags or speed estimates.
    edges['passability_status']='unverified'
    edges['observed_at']=None
    edges['capacity_per_hour']=None
    edges.to_file(folder/'roads.geojson',driver='GeoJSON')
    nodes.to_file(folder/'nodes.geojson',driver='GeoJSON')
    (folder/'provenance.json').write_text(json.dumps({'source':'OpenStreetMap contributors via OSMnx',
        'licence':'ODbL 1.0 — verify attribution/database reuse obligations', 'place':a.place,
        'model_ready':False,'needs':['confirmed closures','observed_at','flow capacity calibration','facility linking','spatial hazard intersection','vehicle access rules']},indent=2))
    print('GIS staging output only; not accepted by the exercise planner.')


if __name__=='__main__':
    main()
