"""Read-only, bounded official API sample acquisition. Never supplies routing inputs.
Usage: python scripts/fetch_public.py weather --out outputs/weather.json
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ENDPOINTS={
 'weather':'https://api.data.gov.my/weather/warning?limit=20',
 'forecast':'https://api.data.gov.my/weather/forecast?contains=Selangor%40location__location_name&limit=20',
 'population_sample':'https://api.data.gov.my/data-catalogue?id=population_district&limit=20',
}


def fetch(source,opener=urlopen):
    url=ENDPOINTS[source]
    fetched_at=datetime.now(timezone.utc).isoformat()
    meta={'source_url':url,'fetched_at':fetched_at,'licence':'CC BY 4.0','sample_limit':20,
          'not_operational':True,'provider':'MET Malaysia / data.gov.my' if source!='population_sample' else 'DOSM / data.gov.my'}
    try:
        req=Request(url,headers={'User-Agent':'CivicOps-Resilience-Research/0.1','Accept':'application/json'})
        with opener(req,timeout=15) as response:
            raw=response.read(2_000_001)
            if len(raw)>2_000_000:
                raise ValueError('Bounded response size exceeded')
            records=json.loads(raw)
        if not isinstance(records,list):
            raise ValueError('Expected JSON list; schema changed')
        for row in records:
            if not isinstance(row,dict):
                raise ValueError('Expected record objects')
            if source=='weather':
                for key in ['valid_from','valid_to','warning_issue']:
                    if key not in row:
                        raise ValueError('Weather schema missing '+key)
            if source=='population_sample' and 'population' not in row:
                raise ValueError('Population schema missing population')
        return {**meta,'status':'retrieved_sample','possibly_truncated':len(records)>=20,'records':records,
                'caveat':'A bounded sample is not a complete warning list or a population total.'}
    except (HTTPError,URLError,TimeoutError,ValueError,OSError) as e:
        return {**meta,'status':'unavailable','records':None,'error':str(e),
                'caveat':'Unavailable is not zero warnings, zero population or safe roads. No retries; respect rate limits.'}


def population_to_people(row):
    """Only a single selected aggregate; caller must avoid mixing overlapping totals."""
    if any(row.get(k) != v for k,v in {'sex':'both','age':'overall','ethnicity':'overall'}.items()):
        raise ValueError('Select an aggregate row; do not add overlapping breakdowns')
    value=float(row['population'])
    if not 0 <= value < 1e9:
        raise ValueError('Invalid population')
    return value*1000


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('source',choices=ENDPOINTS)
    p.add_argument('--out',default='outputs/official_sample.json')
    a=p.parse_args()
    result=fetch(a.source)
    out=Path(a.out)
    out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_suffix(out.suffix+'.tmp')
    tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(out)
    print(json.dumps({'status':result['status'],'source':a.source,'records':len(result['records'] or [])}))
    sys.exit(0 if result['status']=='retrieved_sample' else 2)
