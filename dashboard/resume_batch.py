"""Bounded selected resume jobs; publication remains in the canonical generator."""

def select_jobs(tracker, jobs):
    from dashboard import server as s
    from rejected_jobs import PermanentlyRejectedError
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 100:
        raise ValueError('Select between 1 and 100 jobs.')
    tab = tracker.scout()
    ids, items, seen = [], [], set()
    for selected in jobs:
        if not isinstance(selected, dict):
            raise ValueError('Invalid job selection.')
        job_id = str(selected.get('id', ''))
        if not job_id.isdigit() or int(job_id) <= 0 or int(job_id) in seen:
            raise ValueError('Select each valid job only once.')
        seen.add(int(job_id))
        row, data = s.find_job(tab, job_id)
        if s.version(data) != selected.get('version'):
            raise ValueError('A selected job changed. Refresh and select it again.')
        item = dict(id=job_id, company=data.get('Company', ''), title=data.get('Job Title', ''), status='queued', reason='Waiting to create resume')
        try:
            tracker._assert_scout_row_not_rejected(data)
            if not s.present(row, data)['can_generate']:
                raise ValueError('Skipped: already applied, existing resume, or not approved and eligible.')
        except (ValueError, PermanentlyRejectedError) as exc:
            item.update(status='skipped', reason=str(exc))
        else:
            ids.append(int(job_id))
        items.append(item)
    if not ids:
        raise ValueError('No selected jobs need an eligible new resume. Existing resumes, applied jobs, and Do not apply jobs are skipped.')
    return ids, items


def verify_results(app):
    from dashboard import server as s
    for item in app.operation['items']:
        if item['status'] == 'skipped':
            continue
        job = app.detail(item['id'])
        if job['resume_available'] and s.marked(job['fields'].get('Resume Created')):
            item.update(status='created', reason='Resume saved, verified, and linked to this job.')
        else:
            item.update(status='needs_attention', reason='Resume was not completed. Review this job and the run log; its Created field was not set by this batch.')
