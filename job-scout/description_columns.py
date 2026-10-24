"""Separate search-tool descriptions while keeping legacy readers compatible."""
GECKO_DESCRIPTION = 'Gecko Job Description'
FIRECRAWL_DESCRIPTION = 'Firecrawl Job Description'
DESCRIPTION_COLUMNS = (GECKO_DESCRIPTION, FIRECRAWL_DESCRIPTION)


def description_word_count_formula(row):
    def cell(header):
        return f'INDEX({row}:{row},1,MATCH("{header}",$1:$1,0))'
    gecko, firecrawl = cell(GECKO_DESCRIPTION), cell(FIRECRAWL_DESCRIPTION)
    selected = f'IF(LEN({gecko})>=LEN({firecrawl}),{gecko},{firecrawl})'
    return f'=IF(TRIM({selected})="",0,COUNTA(SPLIT(TRIM(REGEXREPLACE({selected},"\\s+"," "))," ")))'


def description_column(headers, backend):
    names = {str(h).casefold(): h for h in headers}
    target = FIRECRAWL_DESCRIPTION if str(backend).casefold() == 'firecrawl' else GECKO_DESCRIPTION
    if target.casefold() in names:
        return target if target in headers else names[target.casefold()]
    if not any(h.casefold() in names for h in DESCRIPTION_COLUMNS) and 'Job Description' in headers:
        return 'Job Description'
    raise RuntimeError('Missing description column for ' + str(backend) + ': ' + target)


def description_value(data):
    legacy = str(data.get('Job Description') or '').strip()
    if legacy:
        return legacy
    candidates = [str(v or '').strip() for h,v in data.items()
                  if str(h).casefold() in {c.casefold() for c in DESCRIPTION_COLUMNS}]
    return max(candidates, key=len, default='')


def add_read_alias(data, headers):
    if 'Job Description' not in headers:
        value = description_value(data)
        if value:
            data['Job Description'] = value
    return data


def adopt_split_schema(base, local_rows, remote_rows, local_headers, remote_headers):
    """Adopt Dave's renamed columns without recreating the retired heading.

    Sheet edits are authoritative. Unsynchronized legacy local edits must either
    already match a new column or stop for review; never discard them silently.
    """
    if 'Job Description' in remote_headers or 'Job Description' not in local_headers:
        return base, local_rows, local_headers
    split = [h for h in remote_headers if h.casefold() in {c.casefold() for c in DESCRIPTION_COLUMNS}]
    if len(split) != 2:
        return base, local_rows, local_headers
    base = {k:dict(v) for k,v in base.items()}
    local_rows = {k:dict(v) for k,v in local_rows.items()}
    for key, local in local_rows.items():
        previous = base.get(key, {})
        old = str(local.get('Job Description') or '')
        prior = str(previous.get('Job Description') or '')
        remote = remote_rows.get(key, {})
        if key in remote_rows:
            if old != prior and old and not any(old == str(remote.get(h) or '') for h in split):
                raise ValueError('Job ' + key + ' has an unsynchronized legacy description; both versions are preserved for review')
            for field in split:
                local.setdefault(field, remote.get(field,''))
                if key in base:
                    base[key][field] = remote.get(field,'')
        elif old:
            field = description_column(split, local.get('Found Using') or 'Gecko')
            local.setdefault(field, old)
        local.pop('Job Description', None)
    for previous in base.values():
        previous.pop('Job Description',None)
    return base, local_rows, [h for h in local_headers if h != 'Job Description']
