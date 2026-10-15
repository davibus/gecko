from native_browser import call
import json
r=call(['tabs']);print(json.dumps([{'targetId':t['targetId'],'title':t['title'],'url':t['url'],'label':t.get('label')} for t in r.get('tabs',[]) if 'filevine' in t['url']]))
