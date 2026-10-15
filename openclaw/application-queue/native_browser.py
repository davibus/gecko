import json,socket,time
def request(method,path,body=None,query=None):
 q={'profile':'gecko-apply-20261014',**(query or {})}
 p={'method':method,'path':path,'query':q}
 if body is not None:p['body']=body
 with socket.socket(socket.AF_UNIX) as s:
  s.settimeout(75);s.connect('/home/dcall/.openclaw/gecko-browser-bridge.sock');s.sendall((json.dumps(p)+'\n').encode());chunks=[]
  while True:
   b=s.recv(1048576)
   if not b:break
   chunks.append(b)
 r=json.loads(b''.join(chunks))
 if not r['ok']:raise RuntimeError(r['error'])
 return r['result']
def call(args):
 command=args[0];opts={};pos=[];i=1
 while i<len(args):
  x=args[i]
  if x.startswith('--'):
   if x in ['--json','--interactive','--compact','--slowly','--submit']:opts[x[2:]]=True;i+=1
   else:opts[x[2:]]=args[i+1];i+=2
  else:pos.append(x);i+=1
 target=opts.get('target-id');body={'targetId':target} if target else {}
 if command=='open':return request('POST','/tabs/open',{'url':pos[0],**({'label':opts['label']} if 'label' in opts else {})})
 if command=='snapshot':return request('GET','/snapshot',query={'targetId':target,'format':opts.get('format','ai'),'interactive':opts.get('interactive',False),'compact':opts.get('compact',False)})
 if command=='evaluate':body.update(kind='evaluate',fn=opts['fn'])
 elif command=='fill':body.update(kind='fill',fields=json.loads(opts['fields']))
 elif command=='upload':return request('POST','/hooks/file-chooser',{**body,'paths':pos,'element':opts.get('element')})
 elif command=='click':body.update(kind='click',ref=pos[0])
 elif command=='type':body.update(kind='type',ref=pos[0],text=pos[1],slowly=opts.get('slowly',False),submit=opts.get('submit',False))
 elif command=='press':body.update(kind='press',key=pos[0])
 elif command=='batch':body.update(kind='batch',actions=json.loads(opts['actions']))
 elif command=='tabs':return request('GET','/tabs')
 else:raise RuntimeError('Unsupported native browser command '+command)
 return request('POST','/act',body)
if __name__=='__main__':
 r=call(['tabs']);print(json.dumps({'tabs':len(r.get('tabs',[]))}))
