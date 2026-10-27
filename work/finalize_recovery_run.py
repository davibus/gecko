"""Finish free Remote candidate, retain index leads, independently audit Sheet."""
from recover_gecko_pending import *
from location_evidence import source_location_blocker,location_blocker
from extend_gecko_coverage import Coverage
from query_provenance import remember
from sheet_sync import ensure_frozen_headers

scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
native=sorted((Path(os.environ['LOCALAPPDATA'])/'OpenAI/Codex/bin').glob('*/codex.exe'),key=lambda p:p.stat().st_mtime,reverse=True)
if native:os.environ['PATH']=str(native[0].parent)+os.pathsep+os.environ['PATH']
with run_lock(),JobStore() as store:
    remote=GoogleTracker(config=Config.from_environment());history=History()
    operation=Coverage(remote,history,store)
    operation.coverage=json.loads((OUT/'live.json').read_text()).get('source_health',{})
    operation.coverage.update(json.loads((OUT/'remaining-source-coverage.json').read_text()))
    operation.coverage['remote-careers']['free_detail_recovery']=json.loads((OUT/'remote-api-outcomes.json').read_text())
    operation.stage='remaining free employer API recovery'
    with history.lock():
        with history.connect() as con:outboxes=con.execute('SELECT * FROM daily_candidates WHERE job_json IS NOT NULL AND published=0').fetchall()
        existing_ids={str(v.get('Scout ID',v.get('ID'))) for _,v in remote.scout().rows}
        for outbox in outboxes:
            raw=RawListing(**json.loads(outbox['raw_json']))
            blocker=source_location_blocker(raw) or location_blocker(store.get(outbox['gecko_id']))
            if blocker:
                operation.engine.pending(outbox['key'],blocker,retry=False);continue
            if str(outbox['gecko_id']) in existing_ids:continue
            if raw.source not in ('greenhouse','lever','ashby','workable','remote-careers','jobicy','themuse'):
                operation.engine.pending(outbox['key'],'Accepted cached review retained, but current source availability requires recovery; no repeated access-blocked retrieval or paid retry',retry=False)
                continue
            operation.engine.update(outbox['key'],retry_mode='auto',retry_at=None)
            operation.engine.process(outbox['key'],operation.rejections)
        # Retain the exact underlying identity/availability blocker rather than
        # the supervisor's generic unconfirmed-publication message.
        with history.connect() as con:
            blocked_rows=con.execute("SELECT key FROM daily_candidates WHERE reason LIKE 'Publication remains pending:%'").fetchall()
            for blocked_row in blocked_rows:
                evidence=con.execute("SELECT reason FROM daily_events WHERE candidate=? AND reason IS NOT NULL AND reason NOT LIKE 'Publication remains pending:%' ORDER BY id DESC LIMIT 1",(blocked_row['key'],)).fetchone()
                if evidence:operation.engine.pending(blocked_row['key'],'Publication withheld: '+evidence['reason'],retry=False)
        # Exact URL plus the same Lever UUID verifies these legacy prefixed-ID
        # aliases. The old exclusion was deterministic, not a user rejection;
        # the fresh employer workplaceType supplies the previously missing fact.
        reconciled=[]
        conflicts=json.loads((OUT/'identity-blocker-audit.json').read_text())
        for conflict in conflicts:
            raw=RawListing(**conflict['raw'])
            if raw.source!='lever' or raw.metadata.get('workplaceType','').casefold()!='remote':continue
            if operation.rejections.matches_job(normalize(raw)):continue
            with history.connect() as con:
                for alias_owner in conflict['owners']:
                    old=RawListing(**alias_owner['raw'])
                    if posting_identity(old.url)!=posting_identity(raw.url) or old.title.casefold()!=raw.title.casefold():continue
                    if str(raw.source_job_id) not in str(old.source_job_id):continue
                    owner=con.execute('SELECT candidate FROM daily_aliases WHERE alias=?',(alias_owner['alias'],)).fetchone()
                    if not owner or owner['candidate']==conflict['key']:continue
                    record=con.execute('SELECT state,reason,gecko_id FROM daily_candidates WHERE key=?',(owner['candidate'],)).fetchone()
                    if record['gecko_id'] or record['state']!='rejected' or record['reason']!='non-remote role outside preferred locations':continue
                    if operation.rejections.matches_job(normalize(old)):continue
                    con.execute('UPDATE daily_aliases SET candidate=? WHERE candidate=?',(conflict['key'],owner['candidate']))
                    con.execute('INSERT INTO daily_events(candidate,at,state,reason) VALUES(?,?,?,?)',
                        (owner['candidate'],datetime.now(timezone.utc).isoformat(),'rejected','Historical exclusion retained; exact URL/Lever UUID alias reconciled to '+conflict['key']+' with fresh employer remote evidence'))
                    reconciled.append(conflict['key'])
        save('verified-alias-reconciliation.json',reconciled)
        if reconciled:operation.rounds(operation.prepare(reconciled))
        # An explicit UT, US address is Utah. Retain these complete cached jobs
        # for availability recovery rather than a false location rejection.
        utah_recovered=[]
        for record in json.loads((OUT/'utah-abbreviation-audit.json').read_text()):
            raw=RawListing(**json.loads(record['raw_json']))
            if raw.company not in ('RedRiver Health and Wellness','EcoShield Pest Solutions','PRIME Corporate Services'):continue
            if record['reason']!='non-remote role outside preferred locations' or not re.search(r', UT, US$',raw.location):continue
            if operation.rejections.matches_job(normalize(raw)):continue
            doc=raw.metadata.get('_recovery_document') or {}
            if doc.get('status')!='complete':continue
            raw.metadata['_original_source_location']=raw.location
            raw.location=re.sub(r', UT, US$',', Utah, US',raw.location)
            operation.engine.update(record['key'],raw_json=json.dumps(raw.__dict__),content_json=json.dumps({'description':doc['full_description_markdown'],'url':raw.url,'document':doc}))
            reason='Utah abbreviation resolved; complete cached description retained. Current availability still unverified; Indeed public retrieval is access-blocked and the authorized index is exhausted. No paid retry requested.'
            operation.engine.pending(record['key'],reason,retry=False)
            utah_recovered.append({'key':record['key'],'company':raw.company,'title':raw.title,'reason':reason})
        save('utah-pending-recovery.json',utah_recovered)
        raws=[RawListing(**r) for r in json.loads((OUT/'remote-free-candidates.json').read_text())]
        remember(raws)
        operation.rounds(operation.prepare(operation.engine.ingest(raws,operation.known,operation.rejections)))
        leads=json.loads((OUT/'remaining-index-candidates.json').read_text())
        raws=[RawListing(r['source'],str(r.get('source_job_id') or r['url']),r['url'],str(r.get('title_from_index') or ''),'',
            description=str(r.get('description_snippet') or ''),metadata={'_snippet':True,'_incomplete':True,
            '_query_used_to_find':r['actual_query'],'_pending_reason':r['reason']}) for r in leads]
        remember(raws);keys=operation.engine.ingest(raws,operation.known,operation.rejections)
        for key in keys:
            with history.connect() as con:row=con.execute('SELECT state,published FROM daily_candidates WHERE key=?',(key,)).fetchone()
            if not row['published'] and row['state'] in ('seen','pending'):
                operation.engine.pending(key,'Index-only lead: exact employer, complete posting, availability and eligibility required; shared authorized index exhausted',retry=False)
    # Audit accepted receipts against the same persistent source guards.
    remote.fill_blanks_only=False
    remote.discovery_writes=False
    blocked=json.loads((OUT/'blocked-location-jobs.json').read_text())
    with history.connect() as con:source_rows={r['gecko_id']:r for r in con.execute('SELECT * FROM daily_candidates WHERE gecko_id IS NOT NULL')}
    for receipt in list(operation.receipts):
        source=source_rows[receipt['id']];raw=RawListing(**json.loads(source['raw_json']))
        reason=source_location_blocker(raw) or location_blocker(store.get(receipt['id']))
        if not reason:continue
        tab=remote.scout();number,row=next((n,v) for n,v in tab.rows if str(v.get('Scout ID',v.get('ID')))==str(receipt['id']))
        if row['Job URL']!=receipt['url']:raise RuntimeError('Eligibility hold identity mismatch')
        remote._write(tab,number,{'Apply?':'No','Notes':str(row.get('Notes') or '')+'\nLocation review: '+reason})
        saved=next(v for _,v in remote.scout().rows if str(v.get('Scout ID',v.get('ID')))==str(receipt['id']))
        if saved['Apply?']!='No':raise RuntimeError('Eligibility hold readback failed')
        operation.engine.pending(source['key'],reason,retry=False);operation.engine.update(source['key'],published=0)
        blocked.append(receipt);operation.receipts.remove(receipt)
    save('blocked-location-jobs.json',blocked)
    # Replace tenant fallbacks only from verified first-party posting evidence.
    corrections=[]
    brands={r['saved_employer']:r for r in json.loads((OUT/'employer-name-audit.json').read_text()) if r.get('resolved_employer_name')}
    for receipt in operation.receipts:
        proof=brands.get(receipt['employer'])
        if not proof:continue
        name=proof['resolved_employer_name']
        if name==receipt['employer']:continue
        tab=remote.scout();number,row=next((n,v) for n,v in tab.rows if str(v.get('Scout ID',v.get('ID')))==str(receipt['id']))
        if row['Company']!=receipt['employer'] or row['Job URL']!=receipt['url']:raise RuntimeError('Employer correction identity mismatch')
        remote._write(tab,number,{'Company':name})
        saved=next(v for _,v in remote.scout().rows if str(v.get('Scout ID',v.get('ID')))==str(receipt['id']))
        if saved['Company']!=name:raise RuntimeError('Employer correction readback failed')
        store.connection.execute('UPDATE jobs SET company=? WHERE id=?',(name,receipt['id']));store.connection.commit()
        with history.connect() as con:
            record=con.execute('SELECT key,job_json FROM daily_candidates WHERE gecko_id=?',(receipt['id'],)).fetchone()
            if record and record['job_json']:
                saved_job=json.loads(record['job_json']);saved_job['company']=name
                con.execute('UPDATE daily_candidates SET job_json=? WHERE key=?',(json.dumps(saved_job),record['key']))
        receipt['employer']=name;corrections.append({'id':receipt['id'],'company':name,'evidence':proof})
    save('employer-name-corrections.json',corrections);save('verified-jobs.json',operation.receipts)
    operation.finalize()
    after=snapshot(remote)
    before_freeze={s['sheetId']:s.get('gridProperties',{}).get('frozenRowCount',0) for s in operation.baseline['properties']}
    freeze={s['title']:s.get('gridProperties',{}).get('frozenRowCount',0) for s in after['properties']}
    if any(s.get('gridProperties',{}).get('frozenRowCount',0)<max(1,before_freeze.get(s['sheetId'],1)) for s in after['properties']):raise RuntimeError('Frozen header preservation failed')
    receipts=json.loads((OUT/'verified-jobs.json').read_text())
    ids=[r['id'] for r in receipts]
    if len(ids)!=len(set(ids)):raise RuntimeError('Duplicate receipt IDs')
    with history.connect() as con:
        source_rows={r['gecko_id']:r for r in con.execute('SELECT gecko_id,raw_json,review_json FROM daily_candidates WHERE gecko_id IS NOT NULL')}
    for receipt in receipts:
        row=after['rows'][str(receipt['id'])]
        for key,field in [('employer','Company'),('title','Job Title'),('url','Job URL'),('query','Query Used to Find')]:
            if str(row.get(field) or '')!=str(receipt[key] or ''):raise RuntimeError('Independent readback mismatch '+str(receipt['id'])+' '+field)
        for key,field,floor in [('score','Match Score',60),('responsibilities','Responsibilities Match',50),('required_skills','Required Skills Match',50)]:
            if float(row[field])<floor or abs(float(row[field])-float(receipt[key]))>.001:raise RuntimeError('Score mismatch')
        if row.get('Qualifies to Apply?',row.get('Apply?'))!='Yes':raise RuntimeError('Qualification mismatch '+str(receipt['id']))
        job=store.get(receipt['id'])
        evidence=source_rows[receipt['id']]
        if source_location_blocker(RawListing(**json.loads(evidence['raw_json']))):raise RuntimeError('Structured source country conflict '+str(receipt['id']))
        if operation.rejections.matches_job(job):raise RuntimeError('Rejected posting admitted')
        if location_blocker(job):raise RuntimeError('Location restriction unresolved '+str(receipt['id']))
    prior=set(json.loads((OUT/'baseline-requests.json').read_text())['ids'])
    run_start=datetime.fromtimestamp((OUT/'tracker-before.json').stat().st_mtime,timezone.utc).isoformat()
    with history.connect() as con:
        requests=[dict(r) for r in con.execute('SELECT id,status,endpoint,confirmed,reserved FROM requests') if r['id'] not in prior]
        pending_reasons=dict(con.execute("SELECT reason,COUNT(*) FROM daily_candidates WHERE state='pending' GROUP BY reason"))
        states=dict(con.execute('SELECT state,COUNT(*) FROM daily_candidates GROUP BY state'))
        run_states=dict(con.execute('SELECT state,COUNT(*) FROM daily_candidates WHERE first_at>=? GROUP BY state',(run_start,)))
        retained=con.execute("SELECT gecko_id,raw_json FROM daily_candidates WHERE last_at>=? AND published=1 AND state<>'duplicate'",(run_start,)).fetchall()
        known_skipped=len({('id',r['gecko_id']) if r['gecko_id'] else posting_identity(json.loads(r['raw_json'])['url']) for r in retained if r['gecko_id'] not in ids})
    audit=json.loads((OUT/'audit.json').read_text())
    unchanged_roles=operation.preferences['target_roles']==audit['target_roles']
    if not unchanged_roles:raise RuntimeError('Shared roles changed')
    boards=json.loads((OUT/'additional-boards.json').read_text())
    try:
        from sources.http import get_json
        balance=get_json('https://api.firecrawl.dev/v2/team/credit-usage',{'Authorization':'Bearer '+os.environ['FIRECRAWL_API_KEY']})
        save('firecrawl-balance-final.json',balance)
    except Exception as exc:balance={'status':'unavailable','reason':str(exc)}
    result={'pending_recovered':sum(r['kind']=='pending recovered' for r in receipts),'additional_new':sum(r['kind']=='additional new' for r in receipts),
        'tracker_verified_job_ids':ids,'held_ineligible_ids':[r['id'] for r in json.loads((OUT/'blocked-location-jobs.json').read_text())],
        'duplicate_tracker_rows_retained':[r['id'] for r in json.loads((OUT/'duplicate-history-rows.json').read_text())],
        'new_firecrawl_requests':requests,'new_provider_confirmed_requests':sum(r['status']=='succeeded' for r in requests),
        'new_unresolved_requests':sum(r['status'] in ('reserved','unknown') for r in requests),
        'existing_rows_changed':[k for k,v in operation.baseline['rows'].items() if after['rows'].get(k)!=v],
        'headers_preserved':after['headers']==operation.baseline['headers'],'shared_target_roles_unchanged':unchanged_roles,
        'frozen_rows_by_tab':freeze,'firecrawl_balance':balance,
        'candidate_states':states,'pending_reasons':pending_reasons,'coverage':operation.coverage,
        'new_candidate_states_this_run':run_states,'known_postings_skipped_before_retrieval':known_skipped,
        'additional_board_results':dict(Counter(r['status'] for r in boards)),
        'index_only_pending_leads':len(leads),'checked_at':datetime.now(timezone.utc).isoformat()}
    save('final-verification.json',result)
    operation.panel('Verified recovery and source coverage finished; blocked leads retained',force=True,status='complete')
    print(json.dumps(result,indent=2))
