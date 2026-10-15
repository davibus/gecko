from native_browser import call
from pathlib import Path
import json
Q=Path('/mnt/c/gecko_main/openclaw/application-queue');j='2252';r=call(['evaluate','--target-id','batch20261014-'+j,'--fn','() => ({url:location.href,title:document.title,text:document.body.innerText,links:Array.from(document.querySelectorAll("a[href]")).map(e=>({text:e.innerText,url:e.href})).filter(e=>/apply|application/i.test(e.text))})']);(Q/j/'after-human-verification-20261014.json').write_text(json.dumps(r,indent=2));print(json.dumps(r['result']))
