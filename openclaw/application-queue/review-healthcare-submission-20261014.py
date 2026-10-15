from current_batch_ui import UI
from pathlib import Path
import json
Q=Path('/mnt/c/gecko_main/openclaw/application-queue');j='2242';e=json.loads((Q/j/'submission-result.json').read_text());u=UI(e['targetId']);r=u.call(['evaluate','--fn','() => ({url:location.href,title:document.title,text:document.body.innerText,iframes:Array.from(document.querySelectorAll("iframe")).map(e=>({title:e.title,src:e.src})),errors:Array.from(document.querySelectorAll(".error,.error-message,[role=alert]")).map(e=>e.innerText)})']);(Q/j/'after-submit-review-20261014.json').write_text(json.dumps(r,indent=2));print(json.dumps(r['result']));s=u.snap();print(s['snapshot'][-7000:])
