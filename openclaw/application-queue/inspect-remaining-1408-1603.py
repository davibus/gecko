import json,time
from pathlib import Path
from native_browser import call
q=Path('/mnt/c/gecko_main/openclaw/application-queue');rows=json.loads((q/'batch-1408-1603-tracker-snapshot.json').read_text())['rows'];skip=['1431','1441','1447','1477','1499','1506','1509','1524']
for n,row in rows:
 j=str(row['Scout ID'])
 if j in skip:continue
 dest=q/j;dest.mkdir(exist_ok=True)
 try:
  opened=call(['open',row['Job URL'],'--label','inspect-'+j]);target=opened['targetId'];time.sleep(1)
  r=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,title:document.title,text:document.body.innerText.slice(0,24000),links:Array.from(document.querySelectorAll('a')).map(e=>({text:e.innerText,url:e.href})).filter(e=>/apply|greenhouse/i.test(e.text+' '+e.url)),frames:Array.from(document.querySelectorAll('iframe')).map(e=>({id:e.id,src:e.src})),forms:document.forms.length})"]);(dest/'live-page-review.json').write_text(json.dumps(r,indent=2));print(json.dumps({'id':j,'targetId':target,'url':r['result']['url'],'heading':r['result']['text'][:350],'frames':r['result']['frames'],'forms':r['result']['forms'],'links':r['result']['links'][:6]}),flush=True)
 except Exception as e:print(json.dumps({'id':j,'inspection_error':str(e)}),flush=True)
print('REMAINING PAGE INSPECTION DONE',flush=True)
