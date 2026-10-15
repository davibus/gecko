from native_browser import call
import json,time
t=time.monotonic();r=call(['evaluate','--target-id','retry-1311','--fn','() => ({url:location.href,title:document.title})']);print(json.dumps(r));print('Elapsed '+str(round(time.monotonic()-t,2)))
