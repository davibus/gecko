from native_browser import call
from pathlib import Path
import json,time
Q=Path('/mnt/c/gecko_main/openclaw/application-queue');j='2231';row=next(r for n,r in json.loads((Q/'batch-rows2-100-20261014-snapshot.json').read_text())['rows'] if str(r['Scout ID'])==j);t=call(['open',row['Job URL'],'--label','route20261014-'+j])['targetId'];time.sleep(1);s=call(['snapshot','--target-id',t,'--format','ai','--interactive','--compact']);(Q/j/'route-snapshot-20261014.json').write_text(json.dumps({'targetId':t,'snapshot':s},indent=2));print(s['snapshot'][-15000:])
