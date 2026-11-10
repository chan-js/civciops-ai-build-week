"""All geographic entities below are fictional exercise assets on a schematic graph."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
coords={
 'C1':(3.05,101.43),'C2':(3.09,101.47),'C3':(3.02,101.48),'C4':(3.07,101.53),'C5':(3.00,101.54),
 'J1':(3.07,101.46),'J2':(3.045,101.49),'J3':(3.085,101.52),'J4':(3.035,101.55),'J5':(3.105,101.56),
 'S1':(3.12,101.49),'S2':(3.105,101.59),'S3':(3.025,101.60),'S4':(2.985,101.58),'D1':(3.135,101.55)}
communities=[]
for i,(pop,priority,score,needs) in enumerate([
 (320,90,.98,{'rescue_team':2,'medical_team':1,'bus':2}),
 (260,65,.80,{'rescue_team':1,'medical_team':1,'bus':1}),
 (380,110,.95,{'rescue_team':2,'medical_team':2,'bus':2}),
 (210,50,.70,{'rescue_team':1,'medical_team':1,'bus':1}),
 (290,85,.90,{'rescue_team':2,'medical_team':1,'bus':2})],1):
 communities.append({'id':f'Z{i}','name':f'社区 {chr(64+i)}','label_en':f'Exercise community {chr(64+i)}','node':f'C{i}', 'population':pop,'priority_population':priority,'priority_score':score,'needs':needs})
spec=[('C1','J1',6,240,.30),('C1','J2',9,180,.56),('C2','J1',4,260,.24),('C2','J3',7,230,.22),
 ('C3','J2',5,300,.39),('C3','J4',10,160,.62),('C4','J3',4,260,.15),('C4','J4',5,240,.32),
 ('C5','J4',5,280,.40),('C5','S4',7,220,.49),('J1','J2',5,280,.46),('J1','S1',9,380,.18),
 ('J2','J3',6,260,.27),('J2','J4',7,220,.35),('J3','S1',7,320,.12),('J3','J5',4,340,.10),
 ('J4','S3',8,420,.20),('J4','S4',8,230,.37),('J5','S2',5,420,.08),('J5','D1',6,420,.08),
 ('D1','S1',7,300,.09),('S2','S3',12,280,.17),('J4','J5',10,240,.31)]
roads=[{'id':f'R{i:02}','u':u,'v':v,'name':f'模拟走廊 R{i:02}','minutes':t,'capacity_per_hour':cap,'risk':risk,
 'status':'verified_exercise','observed_at':'2026-11-10T08:45:00+08:00','oneway':False} for i,(u,v,t,cap,risk) in enumerate(spec,1)]
# Two examples deliberately fail data quality checks.
roads[1]['status']='closed'
roads[9]['observed_at']='2026-11-10T04:00:00+08:00'
shelters=[{'id':f'P{i}','node':f'S{i}','name':f'演练 PPS {chr(64+i)}','capacity':cap,'occupied':occ,'accessible':access,'status':'open_exercise','observed_at':'2026-11-10T08:40:00+08:00'} for i,(cap,occ,access) in enumerate([(500,80,True),(600,120,True),(480,100,True),(360,40,False)],1)]
resources=[{'id':f'{kind[:3].upper()}-{j:02}','name':f'{label} {j}','type':kind,'node':node,'available':True,'status':'verified_exercise','observed_at':'2026-11-10T08:45:00+08:00'} for kind,label,count,node in [('rescue_team','救援队',5,'D1'),('medical_team','医疗队',3,'S1'),('bus','巴士',4,'S2')] for j in range(1,count+1)]
data={'schema_version':'1.0','mode':'synthetic_exercise','title':'Klang–Shah Alam fictional flood exercise','hazard':'flood','crs':'EPSG:4326','as_of':'2026-11-10T09:00:00+08:00',
 'notice':'ALL communities, roads, capacities, resources and PPS are invented. Coordinates are illustrative; these are NOT real evacuation routes or open PPS.',
 'nodes':[{'id':k,'lat':lat,'lon':lon} for k,(lat,lon) in coords.items()], 'communities':communities,'roads':roads,'shelters':shelters,'resources':resources}
(root/'data/demo/scenario.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
(root/'dist/scenario.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
print('Wrote fictional scenario:',len(roads),'roads,',sum(c['population'] for c in communities),'people')
