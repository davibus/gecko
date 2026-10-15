from native_browser import call
from pathlib import Path
import json
q=Path('/mnt/c/gecko_main/openclaw/application-queue')
for j in ['1358','1360','1362','1363','1400']:
 s=call(['snapshot','--target-id','retry-'+j,'--format','ai','--interactive','--compact']);(q/j/'snapshot-current.json').write_text(json.dumps(s,indent=2));print(json.dumps({'id':j,'fields':[{'ref':k,'role':v['role'],'name':v.get('name')} for k,v in s['refs'].items() if v['role'] in ['textbox','combobox']]}),flush=True)
