from recover_gecko_pending import *
from sources.http import get_json
data=get_json('https://apply.remote.com/api/public/jobs')
save('remote-public-api-index.json',data)
print(json.dumps(data,indent=2)[:7000])
outcomes=[]
for job in data['jobs']:
    if not re.search('marketing|analytics',job['title'],re.I):continue
    if job['location']=='EMEA':
        outcomes.append({'id':job['public_id'],'title':job['title'],'status':'excluded before detail retrieval','reason':'EMEA-only source location'})
        continue
    detail=get_json('https://apply.remote.com/api/public/jobs/'+job['public_id'])
    save('remote-public-job-'+job['public_id']+'.json',detail)
    outcomes.append({'id':job['public_id'],'title':job['title'],'status':'free employer API detail recovered','keys':list(detail)})
save('remote-api-outcomes.json',outcomes)
print(json.dumps(outcomes,indent=2))
from dataclasses import asdict
def plain(node):
    if not isinstance(node,dict):return ''
    if 'text' in node:return node['text']
    text=''.join(plain(child) for child in node.get('content',[]))
    if node.get('type') in ('paragraph','heading','bulleted','numbered'):text+='\n\n'
    return text
raws=[]
for entry in outcomes:
    if entry['status']!='free employer API detail recovered':continue
    job=json.loads((OUT/('remote-public-job-'+entry['id']+'.json')).read_text())['job']
    description='\n\n'.join(plain(section['doc']) for section in job['advert_sections'])+'\n\n'+str(job.get('pay_text') or '')
    # This exact source sentence establishes the country; NORAM alone would not.
    if not re.search(r'Location:\s*United States \(remote\)',description):raise RuntimeError('Explicit U.S. eligibility not found')
    raw=RawListing('remote-careers',job['public_id'],'https://apply.remote.com/jobs/'+job['public_id'],
        job['title'],'Remote','United States (remote)',description,job['employment_type'],
        str((job.get('pay') or {}).get('range_text') or ''),job['opened_at'],job['workplace'],
        metadata={**job,'_query_used_to_find':'Full employer index: remote.com/openings (no search query)',
                  '_retrieved_via':'employer public API','_complete_description':True})
    raws.append(asdict(raw))
save('remote-free-candidates.json',raws)
