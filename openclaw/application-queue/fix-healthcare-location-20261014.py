from pathlib import Path
from current_batch_ui import UI
import json,time
Q=Path('/mnt/c/gecko_main/openclaw/application-queue');j='2242';e=json.loads((Q/j/'submission-result.json').read_text());u=UI(e['targetId']);s=u.snap();print(s['snapshot']);k=next(k for k,v in s['refs'].items() if v['role']=='textbox' and v.get('name','').startswith('Current location'));u.call(['type',k,'American Fork','--slowly']);time.sleep(2);s=u.snap();print(s['snapshot']);(Q/j/'location-options-20261014.json').write_text(json.dumps(s,indent=2))
