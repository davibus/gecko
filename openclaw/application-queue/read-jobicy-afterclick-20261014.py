from native_browser import call
import json
r=call(['evaluate','--target-id','A4B334D82CD31BB5E176AA46CAC54061','--fn','() => ({text:document.body.innerText.slice(-6500),dialogs:Array.from(document.querySelectorAll("[role=dialog],dialog")).filter(e=>e.getClientRects().length).map(e=>e.innerText)})']);print(json.dumps(r['result']))
