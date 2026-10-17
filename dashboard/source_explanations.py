"""Plain-language explanations from saved provider health, without raw request logs."""
import json

def explanation(health):
    status=str(health.get('status') or '').lower()
    detail=str(health.get('detail') or '')
    text=detail.lower()
    if status=='success':
        return 'The source completed successfully; no provider errors were recorded.'
    reasons=[]
    if 'missing credentials' in status:
        reasons.append('The required source credentials are missing or not configured.')
    if any(s in text for s in ('credit_exhausted','insufficient','payment required','http error 402')):
        reasons.append('The search service reported insufficient credits or a billing restriction (HTTP 402).')
    if '404' in text or 'not found' in text:
        companies=[]
        try:
            companies=[str(e['company'])[:100] for e in json.loads(detail) if isinstance(e,dict) and e.get('company')]
        except (ValueError,TypeError):
            pass
        reasons.append('One or more company job boards were not found (HTTP 404)'+(': '+', '.join(companies[:3]) if companies else '')+'.')
    if '429' in text or 'rate limit' in text:
        reasons.append('The source limited request volume; some requests could not complete.')
    if '401' in text or '403' in text:
        reasons.append('Access was refused; credentials or source access may need attention.')
    if 'timeout' in text or 'timed out' in text:
        reasons.append('Some requests timed out before the source responded.')
    if not reasons:
        reasons.append('The source reported '+(status or 'an unknown status')+', but no specific explanation was saved.')
    return ' '.join(reasons)
