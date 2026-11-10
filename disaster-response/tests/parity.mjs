import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import assert from 'node:assert/strict';
import {plan,defaults,simulate} from '../dist/engine.js';
const d=JSON.parse(readFileSync('data/demo/scenario.json','utf8'));
const scenarios=[{}, {pressure:1.8},{horizon_minutes:30},{horizon_minutes:120},{shelter_scale:.65},{accessible_only:false},{congestion:1.8},{closed_roads:['R12','R19']},{closed_shelters:['P1','P2','P3','P4']},{closed_roads:d.roads.map(r=>r.id)},{max_age_minutes:0},{risk_limit:.2},{pressure:1.3,congestion:1.5,shelter_scale:.8}];
const python=JSON.parse(execFileSync('python',['-c',`import json;from disaster_response.engine import plan;d=json.load(open('data/demo/scenario.json'));print(json.dumps([plan(d,p) for p in json.loads(${JSON.stringify(JSON.stringify(scenarios))})]))`],{encoding:'utf8',maxBuffer:8*1024*1024}));
for(let i=0;i<scenarios.length;i++){
 const r=plan(d,scenarios[i]),p=python[i];
 for(let field of ['assigned','unassigned','priority_assigned','communities','shelters','road_usage','routes','excluded_roads','excluded_shelters'])assert.deepEqual(r[field],p[field],`scenario ${i}: ${field}`);
 assert.deepEqual(r.dispatch.assignments,p.dispatch.assignments,`scenario ${i}: dispatch`);
 assert.equal(r.assigned+r.unassigned,r.total_demand);
 for(let road of r.road_usage)assert(road.people<=road.capacity);
 const excluded=new Set(r.excluded_roads.map(e=>e.id));
 for(let path of [...r.routes,...r.dispatch.assignments])for(let rid of path.roads)assert(!excluded.has(rid));
}
const a=simulate(d,defaults,10,42),b=simulate(d,defaults,10,42);assert.deepEqual(a,b);assert(a.unassigned_p95>=a.unassigned_p50);
console.log(`PASS: ${scenarios.length} Python/browser parity scenarios; conservation, closures, capacities, dispatch and seeded stress.`);
