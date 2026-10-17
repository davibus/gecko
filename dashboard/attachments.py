"""Local uploaded resumes, separate from generated/validated resume completion."""
import hashlib
import io
import json
from pathlib import Path
import re
import secrets
import zipfile

DIRECTORY = Path(__file__).resolve().parents[1] / 'output' / 'attached-resumes'
MAX_BYTES = 10 * 1024 * 1024

def upload(name, content):
    name = str(name).replace('\\', '/').split('/')[-1]
    extension = Path(name).suffix.lower()
    if not name or len(name)>200 or any(ord(c)<32 for c in name) or extension not in ('.pdf', '.docx'):
        raise ValueError('Choose a PDF or DOCX resume with a filename under 200 characters.')
    if not content or len(content)>MAX_BYTES:
        raise ValueError('Choose a resume no larger than 10 MB.')
    if extension == '.pdf':
        if not content.startswith(b'%PDF-'):
            raise ValueError('This file is not a valid PDF.')
    else:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if not {'[Content_Types].xml','word/document.xml'}.issubset(archive.namelist()) or sum(i.file_size for i in archive.infolist())>50*1024*1024:
                    raise ValueError('Choose a valid DOCX document.')
        except zipfile.BadZipFile as exc:
            raise ValueError('This file is not a valid DOCX document.') from exc
    token = secrets.token_hex(24)
    info = {'token':token, 'name':name, 'size':len(content), 'sha256':hashlib.sha256(content).hexdigest(),
            'mime':'application/pdf' if extension=='.pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    (DIRECTORY / (token+'.bin')).write_bytes(content)
    (DIRECTORY / (token+'.json')).write_text(json.dumps(info),encoding='utf-8')
    return {key:info[key] for key in ('token','name','size')}

def read(token):
    if not isinstance(token,str) or not re.fullmatch('[0-9a-f]{48}',token):
        raise ValueError('Select the resume again before saving.')
    try:
        info=json.loads((DIRECTORY/(token+'.json')).read_text(encoding='utf-8'))
        content=(DIRECTORY/(token+'.bin')).read_bytes()
    except (OSError,ValueError) as exc:
        raise ValueError('The attached resume is unavailable. Select it again.') from exc
    if info['sha256']!=hashlib.sha256(content).hexdigest():
        raise ValueError('The attached resume changed. Select it again.')
    return info,content

def for_job(tracker, job_id):
    with tracker.connection() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='workspace_manual_resumes'").fetchone():
            return None
        row=con.execute('SELECT token FROM workspace_manual_resumes WHERE job_id=?',(job_id,)).fetchone()
    return read(row[0]) if row else None
