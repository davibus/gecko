from native_browser import call
from pathlib import Path
import json
from concurrent.futures import ThreadPoolExecutor
q=Path('/mnt/c/gecko_main/openclaw/application-queue')
def one(j):
 s=call(['snapshot','--target-id','retry-'+j,'--format','ai','--interactive','--compact']);(q/j/'snapshot-current.json').write_text(json.dumps(s,indent=2))
 r=call(['evaluate','--target-id','retry-'+j,'--fn','() => ({url:location.href,title:document.title,body:document.body.innerText.slice(0,14000),form:document.querySelector("form").innerText,inputs:Array.from(document.querySelectorAll("input,textarea")).map(e=>({id:e.id,type:e.type,value:e.value,placeholder:e.placeholder,required:e.required}))})']);(q/j/'form-current.json').write_text(json.dumps(r,indent=2));return {'id':j,'refs':[{ 'ref':k,'role':v['role'],'name':v.get('name','')} for k,v in s['refs'].items() if v['role'] in ['checkbox','combobox','textbox']]}
with ThreadPoolExecutor(max_workers=3) as pool:
 for r in pool.map(one,['1376','1380','1381','1384','1399']):print(json.dumps(r),flush=True)
