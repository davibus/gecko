from recover_gecko_pending import *
from firecrawl_discovery import identity
def remember_url(url):
    urls.add(posting_identity(url));urls.add(('ats',identity(url)))
baseline=set(json.loads((OUT/'baseline-requests.json').read_text())['ids'])
audit=json.loads((OUT/'audit.json').read_text());urls=set()
for row in audit['pending']+audit['legacy_pending']+audit['cached_postings']:
    for field in ('url','original_url'):
        if row.get(field):remember_url(row[field])
with History().connect() as con:
    rows=con.execute("""SELECT r.id,t.url,json_extract(r.response_json,'$.data.metadata.sourceURL'),
        json_extract(r.response_json,'$.data.metadata.url') FROM requests r LEFT JOIN request_targets t ON t.request_id=r.id
        WHERE r.endpoint='scrape' AND r.status='succeeded'""").fetchall()
for row in rows:
    if row[0] not in baseline:continue
    for url in row[1:]:
        if url:remember_url(url)
for conflict in json.loads((OUT/'identity-blocker-audit.json').read_text()):
    for owner in conflict['owners']:
        raw=owner['raw']
        if (raw.get('metadata',{}).get('_recovery_document') or {}).get('status')=='complete':
            remember_url(raw['url'])
receipts=json.loads((OUT/'verified-jobs.json').read_text())
changes=[{'id':r['id'],'employer':r['employer'],'prior_kind':r['kind'],'corrected_kind':'pending recovered',
          'reason':'Exact posting URL/ID was present in the starting discovery or successful retrieval cache'}
         for r in receipts if r['kind']=='additional new' and (posting_identity(r['url']) in urls or ('ats',identity(r['url'])) in urls)]
save('starting-cache-provenance-audit.json',{'changes':changes,'starting_identities':len(urls)})
print(json.dumps(changes,indent=2))
