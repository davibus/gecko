import sys,json
from pathlib import Path
sys.path[:0]=['C:/gecko_main/job-scout']
sys.stdout.reconfigure(encoding='utf-8')
import scout
scout.load_local_environment();scout.load_local_environment(Path('C:/gecko_main/.env.google-sheets.local'))
from google_tracker import GoogleTracker,Config
from description_columns import description_value
from description_readiness import assess
p=Path(__file__).resolve().parent
tab=GoogleTracker(config=Config.from_environment()).scout()
records=[{'id':str(r['Scout ID']),'company':r['Company'],'title':r['Job Title'],
          'description':description_value(r)} for _,r in tab.rows
         if not str(r.get('Enough Data') or '').strip() and str(r.get('Scout ID') or '').isdigit()]
(p/'readiness-input.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
print('Content review starting for '+str(len(records))+' blank Enough Data cells',flush=True)
reviews=assess(records)
(p/'readiness-results.json').write_text(json.dumps(reviews,indent=2),encoding='utf-8')
print(json.dumps(reviews,indent=2),flush=True)
