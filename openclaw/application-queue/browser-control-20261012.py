import subprocess,json,socket,time,sys
cli='/home/dcall/.openclaw/bin/openclaw'
for attempt in range(16):
 try:
  with socket.create_connection(('127.0.0.1',18789),timeout=2):pass
  break
 except OSError:
  if attempt==15: raise SystemExit('Gateway startup failed')
  if attempt%4==0:print('Waiting for OpenClaw browser gateway...',flush=True)
  time.sleep(4)
print('BROWSER_CONTROL_READY',flush=True)
for line in sys.stdin:
 try:
  args=json.loads(line)
  if args==['exit']:break
  if not isinstance(args,list) or not all(isinstance(x,str) for x in args):raise ValueError('Expected string arguments')
  r=subprocess.run([cli]+args,capture_output=True,text=True,timeout=90)
  print(json.dumps({'exit':r.returncode,'stdout':r.stdout,'stderr':r.stderr}),flush=True)
 except Exception as e:print(json.dumps({'error':str(e)}),flush=True)
