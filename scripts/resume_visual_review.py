"""Fresh, artifact-bound visual review for the canonical resume queue.

The reviewing operator/agent opens both PNGs and writes the requested JSON
decision. An earlier approval is never reused for another review request.
"""
import hashlib
import json
from pathlib import Path
import time
from uuid import uuid4

import fitz
from resume_performance import phase


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_decision(request, decision, docx, pdf):
    if (decision.get('request_id') != request['request_id']
            or decision.get('sha256') != request['sha256']
            or decision.get('pdf_sha256') != request['pdf_sha256']):
        raise ValueError('Visual approval does not match this fresh review request.')
    if decision.get('approved') is not True:
        raise ValueError('Visual review needs attention: ' + str(decision.get('reason', 'not approved')))
    if digest(docx) != request['sha256'] or digest(pdf) != request['pdf_sha256']:
        raise ValueError('Resume artifacts changed after visual review.')


def review(docx, pdf, scratch, qa, *, timeout=3600):
    if qa.get('status') != 'pass' or qa.get('word_pages') != 2 or qa.get('pdf_pages') != 2:
        raise ValueError('Visual review requires passing native Word/PDF QA.')
    scratch = Path(scratch)
    request_id = uuid4().hex
    images = []
    with fitz.open(pdf) as rendered:
        if len(rendered) != 2:
            raise ValueError('Visual review requires exactly two PDF pages.')
        for number, page in enumerate(rendered, 1):
            path = scratch / f'visual-{request_id}-page-{number}.png'
            page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4)).save(path)
            images.append(str(path.resolve()))
    request_path = scratch / 'visual-review-request.json'
    decision_path = scratch / f'visual-review-{request_id}.json'
    request = {'request_id': request_id, 'resume': str(Path(docx).resolve()),
               'pdf': str(Path(pdf).resolve()), 'sha256': digest(docx), 'pdf_sha256': digest(pdf),
               'images': images, 'decision_path': str(decision_path.resolve()),
               'required_checks': ['Both pages readable; no clipping or overlap',
                   'Employment headings and dates align', 'Complete sections and appropriate page-two density',
                   'Established PDF layout preserved'],
               'decision_example': {'request_id': request_id, 'sha256': digest(docx),
                   'pdf_sha256': digest(pdf), 'approved': True, 'reason': 'Describe checks performed'}}
    request_path.write_text(json.dumps(request, indent=2), encoding='utf-8')
    print('Fresh visual review required: ' + str(request_path.resolve()), flush=True)
    deadline = time.monotonic() + timeout
    with phase('review_wait'):
        while not decision_path.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError('Visual review remains pending: ' + str(request_path))
            time.sleep(.5)
    decision = json.loads(decision_path.read_text(encoding='utf-8'))
    check_decision(request, decision, docx, pdf)
    return decision_path
