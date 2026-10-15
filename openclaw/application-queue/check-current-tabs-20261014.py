from native_browser import call
import json
r=call(['tabs']);print(json.dumps([{'targetId':t['targetId'],'url':t['url'],'title':t['title']} for t in r.get('tabs',[]) if 'podium' in t['url'] or 'app20261014-2242'==t.get('label')]))
