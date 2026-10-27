"""Reuse verified, unchanged application blockers without retrying employers."""
import json
import hashlib
from pathlib import Path
from application_runtime import ROOT


def workflow_fingerprint():
    """Do not carry an automation failure across a repair of its implementation."""
    digest = hashlib.sha256()
    for name in ('application_forms.py','playwright_batch.py','playwright_fast.py'):
        digest.update((ROOT/'scripts'/name).read_bytes())
    return digest.hexdigest()


def previous_blocker(item, sources, base, audit_root=None):
    root = Path(audit_root or ROOT/'reports/playwright-pilot')
    candidates = []
    for path in root.glob(f'*/{item["id"]}/state.json'):
        if path.parent.parent.resolve() == Path(base).resolve():
            continue
        old = json.loads(path.read_text(encoding='utf-8'))
        if (old.get('category') != 'blocked' or not old.get('outcome_tracker', {}).get('verified') or
                old.get('company') != item['company'] or old.get('title') != item['title']):
            continue
        packet_path = path.parent/'packet.json'
        if packet_path.exists():
            original = json.loads(packet_path.read_text(encoding='utf-8'))['row']
        else:
            selected = path.parent.parent/'selected.json'
            if not selected.exists():
                continue
            found = [p['row'] for p in json.loads(selected.read_text(encoding='utf-8')) if p['id'] == item['id']]
            if len(found) != 1:
                continue
            original = found[0]
        if any(original.get(k, '') != item['row'].get(k, '') for k in
               ('Company', 'Job Title', 'Job URL', 'Resume Link', 'Gecko Job Description', 'Firecrawl Job Description')):
            continue
        if not old.get('blocker') or old['blocker'] not in str(item['row'].get('Notes', '')):
            continue
        if old.get('blocker') == 'Required answers need confirmation' and old.get('source_hashes') != sources.hashes:
            continue
        semantic_blocker = old['blocker'] in ('Required answers need confirmation', 'Duplicate job flagged',
                                              'Employer page states this position is no longer available')
        if not semantic_blocker and old.get('workflow_fingerprint') != workflow_fingerprint():
            continue
        candidates.append((old.get('checkpoint_at', ''), path, old))
    if not candidates:
        return None
    _, path, old = max(candidates, key=lambda p: p[0])
    return dict(status='Blocked - prior blocker unchanged', blocker=old['blocker'],
        url=old.get('recovery_url') or old.get('url') or item['row']['Job URL'],
        missing_required=old.get('missing_required', []), unverified_required=old.get('unverified_required', []),
        recovery_file=old.get('recovery_file'), prior_blocker_checkpoint=str(path),
        prior_blocker_not_retried=True, source_hashes=dict(sources.hashes))
