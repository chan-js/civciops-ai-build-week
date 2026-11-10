import io
import json
import math
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from urllib.error import URLError
from disaster_response.engine import plan,validate,Flow
from disaster_response.export import export_plan
from disaster_response.predictive import train_demo
from disaster_response.stochastic import stress,TRANSITION
from scripts.fetch_public import fetch,population_to_people

ROOT=Path(__file__).resolve().parents[1]
DATA=json.loads((ROOT/'data/demo/scenario.json').read_text())

class PlannerTests(unittest.TestCase):
    def test_baseline_conservation_and_capacities(self):
        r=plan(DATA)
        self.assertEqual(r['assigned'],1260)
        self.assertEqual(r['total_demand'],r['assigned']+r['unassigned'])
        self.assertEqual(sum(x['people'] for x in r['routes']),r['assigned'])
        self.assertEqual(sum(x['assigned'] for x in r['shelters']),r['assigned'])
        for c in r['communities']:
            self.assertEqual(c['assigned']+c['unassigned'],c['population'])
            self.assertGreaterEqual(c['priority_unassigned'],0)
        for s in r['shelters']:
            self.assertLessEqual(s['assigned'],s['available_capacity'])
        for road in r['road_usage']:
            self.assertLessEqual(road['people'],road['capacity'])
            self.assertEqual(road['people'],sum(p['people']*p['roads'].count(road['id']) for p in r['routes']))

    def test_no_excluded_road_in_any_plan_or_dispatch(self):
        r=plan(DATA,{'closed_roads':['R12','R19']})
        excluded={x['id'] for x in r['excluded_roads']}
        self.assertTrue({'R02','R10','R12','R19'}.issubset(excluded))
        for p in r['routes']+r['dispatch']['assignments']:
            self.assertTrue(excluded.isdisjoint(p['roads']))

    def test_route_continuity_and_direction(self):
        r=plan(DATA)
        roads={e['id']:e for e in DATA['roads']}
        communities={c['id']:c for c in DATA['communities']}
        shelters={s['id']:s for s in DATA['shelters']}
        for route in r['routes']:
            current=communities[route['community']]['node']
            for rid in route['roads']:
                edge=roads[rid]
                if current==edge['u']:
                    current=edge['v']
                else:
                    self.assertFalse(edge['oneway'])
                    self.assertEqual(current,edge['v'])
                    current=edge['u']
            self.assertEqual(current,shelters[route['shelter']]['node'])

    def test_all_roads_closed_has_no_allocation(self):
        r=plan(DATA,{'closed_roads':[x['id'] for x in DATA['roads']]})
        self.assertEqual(r['assigned'],0)
        self.assertEqual(r['dispatch']['assigned_units'],0)

    def test_all_shelters_closed_returns_explicit_gap(self):
        r=plan(DATA,{'closed_shelters':[s['id'] for s in DATA['shelters']]})
        self.assertEqual(r['unassigned'],r['total_demand'])
        self.assertEqual(r['routes'],[])

    def test_expired_or_future_road_is_not_passable(self):
        for timestamp in ['2026-11-09T09:00:00+08:00','2026-11-11T09:00:00+08:00']:
            d=deepcopy(DATA)
            d['roads'][0]['observed_at']=timestamp
            r=plan(d)
            self.assertIn({'id':'R01','reason':'stale'},r['excluded_roads'])

    def test_unknown_road_excluded(self):
        d=deepcopy(DATA)
        d['roads'][0]['status']='unknown'
        self.assertIn({'id':'R01','reason':'unverified'},plan(d)['excluded_roads'])

    def test_stale_shelter_excluded(self):
        d=deepcopy(DATA)
        d['shelters'][0]['observed_at']='2026-11-09T09:00:00+08:00'
        s=next(s for s in plan(d)['shelters'] if s['id']=='P1')
        self.assertEqual(s['available_capacity'],0)

    def test_stale_resources_not_dispatched(self):
        d=deepcopy(DATA)
        for x in d['resources']:
            x['observed_at']='2026-11-09T09:00:00+08:00'
        self.assertEqual(plan(d)['dispatch']['assigned_units'],0)

    def test_unique_assets_and_matching_capability(self):
        r=plan(DATA)
        rows=r['dispatch']['assignments']
        self.assertEqual(len(rows),len({x['asset'] for x in rows}))
        resources={x['id']:x for x in DATA['resources']}
        for x in rows:
            self.assertEqual(x['type'],resources[x['asset']]['type'])
            self.assertLessEqual(x['minutes'],60)
        for c in DATA['communities']:
            for kind,count in c['needs'].items():
                self.assertLessEqual(sum(x['community']==c['id'] and x['type']==kind for x in rows),count)

    def test_priority_people_before_general_when_capacity_scarce(self):
        d=deepcopy(DATA)
        d['communities']=d['communities'][:1]
        d['communities'][0].update(population=10,priority_population=6)
        d['shelters']=d['shelters'][:1]
        d['shelters'][0].update(capacity=3,occupied=0)
        r=plan(d)
        self.assertEqual(r['assigned'],3)
        self.assertEqual(r['priority_assigned'],3)

    def test_residual_rerouting_finds_maximum_flow(self):
        f=Flow()
        for u,v,cost in [('s','a',0),('s','b',0),('a','x',0),('a','y',2),('b','x',1),('x','t',0),('y','t',0)]:
            f.add(u,v,1,cost)
        self.assertEqual(f.solve('s','t'),2)
        self.assertEqual(sum(amount for amount,_ in f.paths('s','t')),2)

    def test_oneway_is_respected(self):
        d=deepcopy(DATA)
        d['communities']=d['communities'][:1]
        d['shelters']=d['shelters'][:1]
        d['roads']=d['roads'][:1]
        d['roads'][0].update(u='S1',v='C1',oneway=True)
        self.assertEqual(plan(d)['assigned'],0)
        d['roads'][0]['oneway']=False
        self.assertGreater(plan(d)['assigned'],0)

    def test_bad_inputs_rejected(self):
        for value in [-1,math.nan,1.5]:
            d=deepcopy(DATA)
            d['roads'][0]['capacity_per_hour']=value
            with self.assertRaises(ValueError):
                plan(d)
        for opts in [{'pressure':math.nan},{'congestion':0},{'risk_limit':2},{'horizon_minutes':0}]:
            with self.assertRaises(ValueError):
                plan(DATA,opts)
        d=deepcopy(DATA)
        d['mode']='live'
        with self.assertRaises(ValueError):
            plan(d)

    def test_timezone_required(self):
        d=deepcopy(DATA)
        d['as_of']='2026-11-10T09:00:00'
        with self.assertRaises(ValueError):
            validate(d)

    def test_empty_demand_and_empty_fleet(self):
        d=deepcopy(DATA)
        for c in d['communities']:
            c['population']=c['priority_population']=0
            c['needs']={}
        d['resources']=[]
        r=plan(d)
        self.assertEqual(r['assigned'],0)
        self.assertEqual(r['unassigned'],0)
        self.assertEqual(r['dispatch']['assigned_units'],0)

    def test_export_and_sql_including_empty_routes(self):
        for options in [{},{'closed_shelters':[s['id'] for s in DATA['shelters']]}]:
            with tempfile.TemporaryDirectory() as folder:
                r=plan(DATA,options)
                export_plan(DATA,r,folder)
                with sqlite3.connect(Path(folder)/'planning.sqlite') as db:
                    self.assertEqual(db.execute('SELECT SUM(assigned) FROM community_plan').fetchone()[0],r['assigned'])
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM road_usage WHERE people>capacity').fetchone()[0],0)
                    for query in (ROOT/'sql/analysis.sql').read_text().split(';'):
                        if query.strip():
                            db.execute(query).fetchall()
                gj=json.loads((Path(folder)/'exercise.geojson').read_text())
                self.assertEqual(gj['features'][0]['geometry']['coordinates'][0], [101.43,3.05])
                self.assertTrue((Path(folder)/'route_plan.csv').exists())

    def test_stochastic_reproducible_and_valid_transition(self):
        self.assertTrue(all(abs(TRANSITION.sum(axis=1)-1)<1e-12))
        a=stress(DATA,runs=8,seed=19)
        b=stress(DATA,runs=8,seed=19)
        self.assertEqual(a,b)
        self.assertGreaterEqual(a['unassigned_p95'],a['unassigned_p50'])

    def test_predictive_holdout_is_explicitly_synthetic(self):
        p=train_demo()
        self.assertEqual(p['mode'],'synthetic_training_only')
        self.assertEqual(p['train_n'],335)
        self.assertEqual(p['test_n'],144)
        self.assertTrue(0<=p['holdout_brier']<=1)
        self.assertIn('lag1',p['features'][0])

    def test_feed_failure_never_becomes_zero(self):
        def unavailable(*args,**kwargs):
            raise URLError('offline fixture')
        r=fetch('weather',opener=unavailable)
        self.assertEqual(r['status'],'unavailable')
        self.assertIsNone(r['records'])

    def test_population_units_and_overlapping_totals(self):
        row={'sex':'both','age':'overall','ethnicity':'overall','population':20.5}
        self.assertEqual(population_to_people(row),20500)
        with self.assertRaises(ValueError):
            population_to_people({**row,'age':'0-4'})

if __name__=='__main__':
    unittest.main()
