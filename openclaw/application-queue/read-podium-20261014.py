from native_browser import call
import json
s=call(['snapshot','--target-id','batch20261014-2240','--format','ai','--interactive','--compact']);print(s['snapshot']);r=call(['evaluate','--target-id','batch20261014-2240','--fn','() => ({url:location.href,title:document.title,text:document.querySelector("form")?.innerText})']);print(json.dumps(r['result']))
