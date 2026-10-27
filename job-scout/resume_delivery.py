"""Private Drive delivery receipts, preserving local application attachments."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'job-scout/preferences/resume-delivery.json'
MANIFEST = ROOT / 'reports/resume-delivery/manifest.json'
MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


def settings():
    return json.loads(CONFIG.read_text(encoding='utf-8')) if CONFIG.exists() else {}


def entries():
    return json.loads(MANIFEST.read_text(encoding='utf-8')).get('files', {}) if MANIFEST.exists() else {}


def checked_local(path):
    path = Path(path).resolve()
    if path.parent != (ROOT / 'output/resumes').resolve() or path.suffix.lower() != '.docx' or not path.is_file() or not path.stat().st_size:
        raise ValueError('A nonempty DOCX directly under output/resumes is required.')
    return path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def register(path, metadata, downloaded_sha256):
    """Register an observed connector upload only after private byte readback."""
    path = checked_local(path)
    cfg = settings()
    file_id, url = metadata.get('id', ''), metadata.get('url', '')
    parsed = urlsplit(url)
    if (not file_id or parsed.scheme != 'https' or parsed.netloc not in ('drive.google.com', 'docs.google.com')
            or not re.search(r'/d/' + re.escape(file_id) + r'(?:/|$)', parsed.path)):
        raise ValueError('An observed Google Drive HTTPS URL matching its file ID is required.')
    if (metadata.get('shared') is not False or not metadata.get('permissions')
            or any(p.get('type') != 'user' or p.get('role') != 'owner' for p in metadata['permissions'])):
        raise ValueError('Resume delivery must remain private to its owner.')
    if (metadata.get('title') != path.name or metadata.get('mime_type') != MIME
            or int(metadata.get('size', -1)) != path.stat().st_size
            or cfg.get('folder_id') not in metadata.get('parent_ids', [])):
        raise ValueError('Drive filename, type, size or approved folder differs from the local resume.')
    sha = digest(path)
    if downloaded_sha256 != sha:
        raise ValueError('Downloaded Drive bytes differ from the completed local resume.')
    files = entries()
    files[str(path)] = {'path': str(path), 'sha256': sha, 'downloaded_sha256': sha,
                       'file_id': file_id, 'url': url, 'private': True,
                       'verified_at': datetime.now(timezone.utc).isoformat()}
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    temporary = MANIFEST.with_suffix('.tmp')
    temporary.write_text(json.dumps({'files': files}, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(MANIFEST)
    return url


def publish(path):
    path = checked_local(path)
    if settings().get('mode') != 'private_google_drive':
        return path.as_uri()  # Legacy checkouts/tests; live Gecko explicitly selects Drive.
    entry = entries().get(str(path), {})
    if (entry.get('private') is True and entry.get('sha256') == digest(path)
            and entry.get('downloaded_sha256') == entry.get('sha256')):
        return entry['url']
    raise RuntimeError('Private Drive publication pending: upload this final DOCX with the Google Drive '
                       'connector, verify private metadata and downloaded bytes, then register its receipt '
                       'with scripts/register_resume_drive_link.py before completing the tracker. '
                       f'Local resume preserved: {path}')


def local_path(url):
    """Resolve registered HTTPS links without downloading or guessing filenames."""
    parsed = urlsplit(str(url))
    if parsed.scheme == 'file' and parsed.netloc in ('', 'localhost'):
        raw = unquote(parsed.path)
        if re.match(r'^/[A-Za-z]:/', raw):
            raw = raw[1:]
        try:
            return checked_local(raw)
        except (OSError, ValueError):
            return None
    for entry in entries().values():
        if entry.get('url') == url and entry.get('private') is True:
            try:
                path = checked_local(entry['path'])
                if digest(path) == entry['sha256'] == entry['downloaded_sha256']:
                    return path
            except (OSError, ValueError, KeyError):
                pass
    return None


def verified_target(url):
    path = local_path(url)
    if path is None or publish(path) != url:
        raise ValueError('Resume Link needs a verified private Drive delivery receipt for this exact DOCX.')
    return url


def ensure_sheet_hyperlinks(tracker, tab, targets):
    """Set the hyperlink property explicitly; RAW text alone is not proof."""
    from google_tracker import _col
    requests, ranges = [], []
    for row, url in targets:
        if not str(url).startswith('https://'):
            continue
        if settings().get('mode') == 'private_google_drive':
            verified_target(url)
        column = tab.headers['Resume Link']
        requests.append({'repeatCell': {
            'range': {'sheetId': tab.sheet_id, 'startRowIndex': row-1, 'endRowIndex': row,
                      'startColumnIndex': column-1, 'endColumnIndex': column},
            'cell': {'userEnteredFormat': {'textFormat': {'link': {'uri': url}}}},
            'fields': 'userEnteredFormat.textFormat.link'}})
        title = tab.title.replace("'", "''")
        ranges.append(f"'{title}'!{_col(column)}{row}")
    if not requests:
        return
    tracker.api.batchUpdate(spreadsheetId=tracker.config.spreadsheet_id,
                            body={'requests': requests}).execute()
    observed = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id, ranges=ranges,
        includeGridData=True, fields='sheets(data(rowData(values(hyperlink))))').execute()
    links = [cell.get('hyperlink') for sheet in observed.get('sheets', [])
             for grid in sheet.get('data', []) for row in grid.get('rowData', [])
             for cell in row.get('values', [])]
    expected = [url for _, url in targets if str(url).startswith('https://')]
    if sorted(links) != sorted(expected):
        raise RuntimeError('Resume hyperlink readback failed; link publication remains incomplete.')
