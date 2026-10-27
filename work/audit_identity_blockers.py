from recover_gecko_pending import *
history=History();results=[]
with history.connect() as con:
    rows=con.execute("SELECT * FROM daily_candidates WHERE reason LIKE '%identity reconciliation%' OR reason LIKE 'Publication remains pending:%'").fetchall()
    for row in rows:
        raw=RawListing(**json.loads(row['raw_json']));job=normalize(raw)
        content=json.loads(row['content_json'] or '{}');job.authoritative_url=content.get('url') or job.url
        owners={}
        for alias in aliases(job):
            for match in con.execute('SELECT candidate FROM daily_aliases WHERE alias=?',(alias,)):
                if match['candidate']==row['key']:continue
                owner=con.execute('SELECT key,state,gecko_id,published,raw_json FROM daily_candidates WHERE key=?',(match['candidate'],)).fetchone()
                owners[owner['key']]={'alias':alias,'state':owner['state'],'gecko_id':owner['gecko_id'],'published':owner['published'],'raw':json.loads(owner['raw_json'])}
        results.append({'key':row['key'],'raw':json.loads(row['raw_json']),'reason':row['reason'],'owners':list(owners.values())})
save('identity-blocker-audit.json',results)
print(json.dumps([{'key':r['key'],'title':r['raw']['title'],'url':r['raw']['url'],'owners':[{'alias':o['alias'],'state':o['state'],'gecko_id':o['gecko_id'],'title':o['raw']['title'],'url':o['raw']['url']} for o in r['owners']]} for r in results],indent=2))
