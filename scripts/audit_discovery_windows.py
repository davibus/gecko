"""Independent GET-only diagnostic queries for supported posting-age windows."""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'job-scout'))
import scout
from sources.base import SearchRequest
from sources.acquisition import search_pages
from audit_job_discovery import safe_error

def check(name, days, location):
    provider=scout.providers()[name]
    result={'source':name,'days':days,'query':'Paid Search Manager','location':location,
            'parsed_results':0,'status':'missing credentials','tracker_writes':0}
    if not provider.configured(): return result
    try:
        rows=list(search_pages(provider,SearchRequest('Paid Search Manager',location,1,50,days)))
        result.update(parsed_results=len(rows),status='success' if rows else 'zero results')
    except Exception as exc:
        result.update(status='error',error=safe_error(exc))
    result['detail_errors']=[safe_error(e) for e in getattr(provider,'errors',[])]
    result['raw_search_hits']=getattr(provider,'search_results_returned',None)
    return result

if __name__=='__main__':
    scout.load_local_environment()
    tasks=[(name,days,location) for name in ['adzuna','usajobs','indeed','linkedin','glassdoor','ziprecruiter']
           for days in [1,7,30] for location in ['Utah','Remote']]
    results=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for f in as_completed([pool.submit(check,*task) for task in tasks]):
            r=f.result();results.append(r);print(r['source'],r['days'],r['location'],r['status'],r['parsed_results'],flush=True)
            (ROOT/'reports/discovery-audit/20261013/server-windows.json').write_text(json.dumps(results,indent=2))
