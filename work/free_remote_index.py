from recover_gecko_pending import *
from html.parser import HTMLParser
from sources.http import get_document
class Links(HTMLParser):
    def __init__(self):super().__init__();self.rows=[];self.active=None
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if tag=='a' and 'apply.remote.com/jobs/' in values.get('href',''):
            self.active={'url':values['href'],'text':''}
    def handle_data(self,text):
        if self.active is not None:self.active['text']+=text+' '
    def handle_endtag(self,tag):
        if tag=='a' and self.active is not None:self.rows.append(self.active);self.active=None
page=get_document('https://remote.com/openings').body.decode('utf-8')
(OUT/'remote-openings.html').write_text(page,encoding='utf-8')
parser=Links();parser.feed(page);save('remote-index-roles.json',parser.rows)
print(json.dumps(parser.rows,indent=2))
from sources.remote_careers import RemoteCareersProvider
from dataclasses import asdict
provider=RemoteCareersProvider();candidates=[];outcomes=[]
with History().connect() as con:known={r[0] for r in con.execute('SELECT alias FROM daily_aliases')}
for row in parser.rows:
    if not re.search(r'marketing|growth|paid|analytics|\bSEO\b|\bSEM\b',row['text'],re.I):continue
    if 'url:'+repr(posting_identity(row['url'])) in known:
        outcomes.append({**row,'status':'known skipped before retrieval'});continue
    try:
        document=get_document(row['url'])
        (OUT/('remote-page-'+row['url'].rsplit('/',1)[-1]+'.html')).write_text(document.body.decode('utf-8',errors='replace'),encoding='utf-8')
        listings=list(provider.extract(document,row['url']))
        for raw in listings:
            raw.metadata['_query_used_to_find']='Full employer index: remote.com/openings (no search query)'
            candidates.append(asdict(raw))
        outcomes.append({**row,'status':'free public page checked','complete_records':len(listings)})
    except Exception as exc:outcomes.append({**row,'status':'free page blocked','reason':str(exc)})
save('remote-free-candidates.json',candidates);save('remote-free-outcomes.json',outcomes)
print(json.dumps(outcomes,indent=2))
