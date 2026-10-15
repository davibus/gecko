from pathlib import Path
p=Path('/home/dcall/.openclaw/tools/node-v24.21.0/lib/node_modules/openclaw/dist')
for f in p.glob('*browser*.mjs'):
 lines=f.read_text().splitlines()
 for i,line in enumerate(lines):
  if any(s in line for s in ['file-chooser','browser.command("evaluate")','browser.command("batch")','browser.command("upload")','kind: "evaluate"','kind: "batch"','/tabs/open','/tabs/close','/hooks/','/snapshot','path: "/act"']):
   print(f.name+':'+str(i+1));print('\n'.join(lines[max(0,i-5):i+18]))
