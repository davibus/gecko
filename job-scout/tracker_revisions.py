"""Shared form revision and plain-note semantics; no UI dependency."""
import hashlib
import json

PREFIX = '[Gecko dashboard] '
MANUAL_FIELDS = ['Company', 'Job Title', 'Source', 'Location', 'Salary', 'Work Arrangement',
                 'Employment Type', 'Personal priority', 'Notes', 'Date Posted']


def version(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def notes_parts(value):
    text, meta, history = [], {}, []
    for line in str(value or '').splitlines():
        if line.startswith(PREFIX):
            try:
                item = json.loads(line[len(PREFIX):])
                if not isinstance(item, dict):raise ValueError()
                meta.update({k:item[k] for k in ('follow_up','stage','applied_at','deadline','website') if k in item})
                history.append(item)
                continue
            except (ValueError,TypeError):pass
        text.append(line)
    return '\n'.join(text),meta,history
