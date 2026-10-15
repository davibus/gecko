import json,re,time
from native_browser import call
class UI:
 def __init__(self,target):self.t=target;self.last_snapshot=None
 def call(self,args):return call(args+['--target-id',self.t])
 def snap(self):
  for attempt in range(3):
   try:
    self.last_snapshot=self.call(['snapshot','--format','ai','--interactive','--compact']);return self.last_snapshot
   except RuntimeError as e:
    if 'snapshot capture timed out' not in str(e) or attempt==2:raise
    print('Retrying browser read',flush=True);time.sleep(1)
 def ref(self,s,role,name):
  hits=[k for k,v in s['refs'].items() if v['role']==role and v.get('name','').strip()==name];assert len(hits)==1,(role,name);return hits[0]
 def choose(self,name,value,search=False):
  s=self.last_snapshot or self.snap();k=self.ref(s,'combobox',name)
  if search or name=='Country':self.call(['type',k,('United States' if name=='Country' else value.split(' - ')[0]),'--slowly']);time.sleep(1)
  else:
   lines=s['snapshot'].splitlines();i=next(i for i,x in enumerate(lines) if f'[ref={k}]' in x);b=re.search(r'ref=(e\d+)',next(x for x in lines[i+1:] if 'button "Toggle flyout"' in x)).group(1);self.call(['click',b])
  s=self.snap();hits=[k for k,v in s['refs'].items() if v['role']=='option' and v.get('name','').strip()==value];assert len(hits)==1,{'field':name,'wanted':value,'options':[v['name'] for v in s['refs'].values() if v['role']=='option']};self.call(['click',hits[0]])
 def options(self,name):
  self.call(['press','Escape']);s=self.snap();k=self.ref(s,'combobox',name);lines=s['snapshot'].splitlines();i=next(i for i,x in enumerate(lines) if f'[ref={k}]' in x);b=re.search(r'ref=(e\d+)',next(x for x in lines[i+1:] if 'button "Toggle flyout"' in x)).group(1);self.call(['click',b]);s=self.snap();o=[v['name'] for v in s['refs'].values() if v['role']=='option'];self.call(['press','Escape']);return o
 def fill(self,answers):
  s=self.snap();f=[{'ref':self.ref(s,'textbox',n),'value':v} for n,v in answers.items()];self.call(['fill','--fields',json.dumps(f)])
 def form(self):return self.call(['evaluate','--fn',"() => ({url:location.href,title:document.title,text:document.querySelector('form')?.innerText,inputs:Array.from(document.querySelectorAll('input,textarea')).map(e=>({id:e.id,value:e.value,checked:e.checked,required:e.required})),invalid:Array.from(document.querySelectorAll('input,textarea,select')).filter(e=>!e.checkValidity()).map(e=>({id:e.id,message:e.validationMessage}))})"])
