from native_browser import call
from pathlib import Path
import json
Q=Path('/mnt/c/gecko_main/openclaw/application-queue');j='2241';s=call(['snapshot','--target-id','541699D3D305B492A6283326F59549BE','--format','ai','--interactive','--compact']);r=call(['evaluate','--target-id','541699D3D305B492A6283326F59549BE','--fn','() => ({url:location.href,title:document.title,text:document.body.innerText,files:Array.from(document.querySelectorAll("input[type=file]")).map(e=>({id:e.id,name:e.name}))})']);(Q/j/'application-form-20261014.json').write_text(json.dumps({'snapshot':s,'page':r},indent=2));print(s['snapshot']);print(json.dumps(r['result']))
