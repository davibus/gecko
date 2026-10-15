from current_batch_ui import UI
from pathlib import Path
import json
Q=Path('/mnt/c/gecko_main/openclaw/application-queue');j='2241';e=json.loads((Q/j/'submission-result.json').read_text());u=UI(e['targetId']);s=u.call(['snapshot','--format','ai']);(Q/j/'full-form-snapshot-20261014.json').write_text(json.dumps(s,indent=2));print('\n'.join(x for x in s['snapshot'].splitlines() if 'option ' not in x)[-13000:]);r=u.call(['evaluate','--fn','() => Array.from(document.querySelectorAll("select")).map(e=>({name:e.name,question:e.closest("li")?.innerText,options:Array.from(e.options).map(o=>({text:o.text,value:o.value})).filter(o=>["Yes","United States"].includes(o.text))}))']);print(json.dumps(r['result']))
