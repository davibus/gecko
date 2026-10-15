from native_browser import call
import json
from pathlib import Path
q=Path('/mnt/c/gecko_main/openclaw/application-queue/2234');e=json.loads((q/'submission-result.json').read_text());t=e['targetId']
r=call(['evaluate','--target-id',t,'--fn',"() => ({url:location.href,title:document.title,text:document.querySelector('form')?.innerText,files:Array.from(document.querySelectorAll('input[type=file]')).map(e=>({id:e.id,names:Array.from(e.files||[]).map(f=>f.name)})),fields:Array.from(document.querySelectorAll('input,textarea')).filter(e=>e.type!=='hidden' && e.type!=='file').map(e=>({id:e.id,name:e.name,value:e.value})),invalid:Array.from(document.querySelectorAll('input,textarea,select')).filter(e=>!e.checkValidity()).map(e=>({id:e.id,name:e.name,message:e.validationMessage}))})"])
(q/'current-form-20261014.json').write_text(json.dumps(r,indent=2));print(json.dumps(r['result'],indent=2))
